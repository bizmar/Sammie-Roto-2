# sammie/exr_ingest.py
"""
OpenEXR ingest.

EXR plates are scene-linear and usually far larger than the models can hold -
a 6.7K ACES plate is around eight times what matting fits on a 12GB card - so
they are converted to 8-bit proxy frames here, at ingest. Everything
downstream keeps reading ordinary 8-bit images from the frame cache.

Two details matter and are easy to get wrong:

  * The float data has no meaning as 8-bit pixels until a colour transform is
    applied. Applying an sRGB curve without a gamut conversion produces flat,
    desaturated frames, so the transform goes through OpenColorIO rather than
    a hand-rolled matrix.

  * Enabling OpenCV's EXR codec is what makes a bare cv2.imread() on an EXR
    dangerous. With the codec disabled imread raises; once enabled it returns
    the float data cast to uint8 with no scaling, which is a near-black image
    that cv2.imwrite will save quite happily. Every EXR read must come through
    ExrConverter.convert() below.
"""
import os
import re

import cv2
import numpy as np

# A missing PyOpenColorIO must not stop the rest of the application from
# starting, so the error is raised when an EXR is actually loaded rather than
# at import time.
try:
    import PyOpenColorIO as ocio
except ImportError:
    ocio = None

EXR_EXTENSIONS = ['.exr']

DEFAULT_PROXY_LONG_EDGE = 1920
PROXY_LONG_EDGE_MIN = 512
PROXY_LONG_EDGE_MAX = 4096

DEFAULT_SOURCE_COLORSPACE = "ACES2065-1"
DEFAULT_DISPLAY = "sRGB - Display"

# The tone-mapped ACES output transform is the default rather than a plain
# colourspace conversion. On real plates the plain conversion clips both ends
# of the range - around 18% near-black and 2% near-white on our test footage -
# and matte edges live exactly in the detail that clipping destroys.
DEFAULT_VIEW = "ACES 2.0 - SDR 100 nits (Rec.709)"

# Selecting this view reproduces `oiiotool --colorconvert` for anyone who
# needs to match an existing pipeline.
UNTONEMAPPED_VIEW = "Un-tone-mapped"

# Half-float maximum, used to bring infinities back into a sane range instead
# of letting them turn into black pixels.
_HALF_MAX = 65504.0


class ExrIngestError(Exception):
    """Raised when an EXR cannot be read or colour-managed."""
    pass


def is_exr(path):
    """True if the path looks like an OpenEXR file."""
    return os.path.splitext(path)[1].lower() in EXR_EXTENSIONS


def is_available():
    """True if EXR ingest can actually run (PyOpenColorIO present)."""
    return ocio is not None


def get_config():
    """
    The OCIO config to convert with.

    Honours $OCIO if the show sets one, otherwise falls back to the built-in
    ACES config, which knows ACES2065-1 and sRGB - Display out of the box.
    """
    if ocio is None:
        raise ExrIngestError(
            "OpenEXR support requires PyOpenColorIO.\n\n"
            "Install it into the Sammie environment with:\n"
            "    pip install opencolorio"
        )
    if os.environ.get("OCIO"):
        return ocio.GetCurrentConfig()
    return ocio.Config.CreateFromBuiltinConfig("ocio://default")


def available_displays():
    """Display names offered by the active config, for the settings UI."""
    try:
        return list(get_config().getDisplays())
    except Exception:
        return []


def available_views(display=DEFAULT_DISPLAY):
    """View names for a display, for the settings UI."""
    try:
        return list(get_config().getViews(display))
    except Exception:
        return []


def available_colorspaces():
    """Colourspace names offered by the active config, for the settings UI."""
    try:
        return [cs.getName() for cs in get_config().getColorSpaces()]
    except Exception:
        return []


def source_frame_number(path):
    """
    The frame number embedded in a filename, or None.

    Kept so exported mattes can be named back to the real frame numbers of the
    source plates rather than to the cache's own 0-based index.
    """
    name = os.path.splitext(os.path.basename(path))[0]
    match = re.search(r'(\d+)$', name)
    return int(match.group(1)) if match else None


class ExrConverter:
    """
    Converts EXR frames to 8-bit BGR images at the proxy resolution.

    The downscale runs before the colour transform. That order is both more
    correct - averaging belongs in scene-linear light - and around ten times
    faster, since the transform then runs on 2.5MP instead of 30MP.
    """

    def __init__(self, long_edge=DEFAULT_PROXY_LONG_EDGE,
                 source_colorspace=DEFAULT_SOURCE_COLORSPACE,
                 display=DEFAULT_DISPLAY, view=DEFAULT_VIEW):
        self.long_edge = int(long_edge) if long_edge else 0
        self.source_colorspace = source_colorspace
        self.display = display
        self.view = view

        # Filled in by the first conversion, and recorded in the session so the
        # exporter can map proxy mattes back onto the untouched originals.
        self.scale = 1.0
        self.source_width = 0
        self.source_height = 0

        config = get_config()
        try:
            transform = ocio.DisplayViewTransform(src=source_colorspace,
                                                  display=display, view=view)
            self.processor = config.getProcessor(transform).getDefaultCPUProcessor()
        except Exception as e:
            raise ExrIngestError(
                f"Could not build the colour transform "
                f"{source_colorspace} -> {display} / {view}:\n{e}"
            )

    def describe(self):
        """One-line summary for the console log."""
        target = f"{self.long_edge}px long edge" if self.long_edge else "full resolution"
        return f"{self.source_colorspace} -> {self.display} / {self.view}, {target}"

    def convert(self, path):
        """Read one EXR and return an 8-bit BGR image at the proxy resolution."""
        image = cv2.imread(path, cv2.IMREAD_UNCHANGED)
        if image is None:
            raise ExrIngestError(f"Could not read EXR: {path}")

        # The frame cache is 3-channel BGR; drop any alpha, expand mono.
        if image.ndim == 2:
            image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        elif image.shape[2] > 3:
            image = image[:, :, :3]
        elif image.shape[2] != 3:
            raise ExrIngestError(
                f"Unsupported channel count {image.shape[2]} in {os.path.basename(path)}"
            )

        rgb = np.ascontiguousarray(image[:, :, ::-1], dtype=np.float32)
        # Lossy compression and extreme scene values can leave NaN or Inf,
        # which would otherwise propagate through the transform as holes.
        rgb = np.nan_to_num(rgb, nan=0.0, posinf=_HALF_MAX, neginf=0.0)

        height, width = rgb.shape[:2]
        self.source_width, self.source_height = width, height

        source_long_edge = max(width, height)
        if self.long_edge and source_long_edge > self.long_edge:
            self.scale = self.long_edge / source_long_edge
            new_size = (max(1, int(round(width * self.scale))),
                        max(1, int(round(height * self.scale))))
            # INTER_AREA is the right filter for a large reduction, and this
            # runs while the data is still scene-linear.
            rgb = np.ascontiguousarray(cv2.resize(rgb, new_size,
                                                  interpolation=cv2.INTER_AREA))
        else:
            self.scale = 1.0

        out_height, out_width = rgb.shape[:2]
        self.processor.apply(ocio.PackedImageDesc(rgb, out_width, out_height, 3))

        eight_bit = (np.clip(rgb, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
        return np.ascontiguousarray(eight_bit[:, :, ::-1])
