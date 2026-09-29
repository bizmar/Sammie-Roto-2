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
import threading

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

# Peak working set per concurrent frame, as a multiple of the source plate's
# float32 size. Measured at about 3.7x on 6.7K ACES plates: the decoded float
# image, the resize destination, and OpenCV's own scratch all coexist briefly.
# Used only to keep the worker count from exhausting memory.
_MEMORY_FACTOR = 3.7

# Beyond this, more workers stop paying for themselves and only cost memory.
_MAX_WORKERS = 16


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


def _available_memory_bytes():
    """
    Free physical memory, or 0 if it cannot be determined.

    Deliberately 'available' rather than 'total': on a workstation the plates
    are often being ingested while Nuke or a browser is holding several
    gigabytes, and sizing the worker pool against total RAM would then push
    the machine into swap.
    """
    try:  # Windows
        import ctypes
        from ctypes import wintypes

        class MemoryStatusEx(ctypes.Structure):
            _fields_ = [("dwLength", wintypes.DWORD),
                        ("dwMemoryLoad", wintypes.DWORD),
                        ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

        status = MemoryStatusEx()
        status.dwLength = ctypes.sizeof(MemoryStatusEx)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return int(status.ullAvailPhys)
    except Exception:
        pass

    try:  # Linux, and macOS for SC_PHYS_PAGES
        return os.sysconf('SC_PAGE_SIZE') * os.sysconf('SC_AVPHYS_PAGES')
    except Exception:
        pass

    return 0


def suggested_workers(width, height, requested=0):
    """
    How many frames to convert at once.

    A 6.7K plate needs well over a gigabyte of working set while it is being
    decoded and resized, so the limit here is usually memory rather than
    cores. Returns at least 1, and never more than there are cores to run on.
    """
    if requested and requested > 0:
        return max(1, min(int(requested), _MAX_WORKERS))

    cores = os.cpu_count() or 4
    workers = max(2, cores // 2)

    per_frame = width * height * 3 * 4 * _MEMORY_FACTOR
    available = _available_memory_bytes()
    if per_frame > 0 and available > 0:
        # Leave most of memory alone; this is a background step, not the point
        # of the application, and matting will want the machine shortly.
        affordable = int((available * 0.5) // per_frame)
        workers = min(workers, max(1, affordable))

    return max(1, min(workers, _MAX_WORKERS, cores))


class ExrConverter:
    """
    Converts EXR frames to 8-bit BGR images at the proxy resolution.

    The downscale runs before the colour transform. That order is both more
    correct - averaging belongs in scene-linear light - and around ten times
    faster, since the transform then runs on 2.5MP instead of 30MP.

    convert() is safe to call from several threads at once: the OCIO CPU
    processor is immutable once built, and the only shared state written here
    is the source geometry, which is recorded once under a lock.
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
        # Written once, under a lock, because frames convert concurrently.
        self.scale = 1.0
        self.source_width = 0
        self.source_height = 0
        self._geometry_lock = threading.Lock()

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

        height, width = image.shape[:2]

        # Lossy compression and extreme scene values can leave NaN or Inf,
        # which would otherwise propagate through the resize and the transform
        # as holes. This has to happen at source resolution, before any
        # averaging, or a single bad pixel poisons a whole neighbourhood - but
        # clean plates are the normal case, so only pay for it when needed.
        if not np.isfinite(image).all():
            image = np.nan_to_num(image, copy=False, nan=0.0,
                                  posinf=_HALF_MAX, neginf=0.0)

        source_long_edge = max(width, height)
        if self.long_edge and source_long_edge > self.long_edge:
            scale = self.long_edge / source_long_edge
            new_size = (max(1, int(round(width * scale))),
                        max(1, int(round(height * scale))))
            # INTER_AREA is the right filter for a large reduction, and this
            # runs while the data is still scene-linear. Channel order does not
            # affect the result, so the BGR to RGB swap waits until afterwards,
            # where it costs a few megabytes instead of a few hundred.
            image = cv2.resize(image, new_size, interpolation=cv2.INTER_AREA)
        else:
            scale = 1.0

        with self._geometry_lock:
            if not self.source_width:
                self.scale = scale
                self.source_width, self.source_height = width, height

        rgb = np.ascontiguousarray(image[:, :, ::-1], dtype=np.float32)

        out_height, out_width = rgb.shape[:2]
        self.processor.apply(ocio.PackedImageDesc(rgb, out_width, out_height, 3))

        eight_bit = (np.clip(rgb, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
        return np.ascontiguousarray(eight_bit[:, :, ::-1])
