"""
Render Sammie-Roto windows offscreen and save them as PNGs.

Used to compare the UI before and after styling changes without needing a
display, a GPU or the models. torch and SAM2 are replaced with stubs, so this
only ever shows the interface, never real segmentation.

    pip install PySide6-essentials numpy opencv-python-headless requests packaging pillow tqdm av OpenEXR
    python tools/ui_preview.py --out ui-preview

On a bare Linux box Qt also needs libEGL/libGL (apt: libegl1 libgl1 libxkbcommon0 libfontconfig1).
"""
import argparse
import os
import shutil
import sys
import tempfile
import types
from pathlib import Path
from unittest import mock

from PySide6.QtCore import QCoreApplication, QEvent

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

# Packages that are too heavy to import just to draw the UI.
HEAVY_MODULES = (
    "torch", "torch.cuda", "torch.cuda.amp", "torch.nn", "torch.nn.functional",
    "torchvision", "sam2", "sam2.build_sam", "diffusers", "einops", "accelerate",
)


class _Stub(types.ModuleType):
    __path__ = []

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return mock.MagicMock(name=f"{self.__name__}.{name}")


def say(text=""):
    """Print to the real stdout; the app redirects sys.stdout into its console widget."""
    sys.__stdout__.write(text + "\n")
    sys.__stdout__.flush()


def _install_stubs():
    for name in HEAVY_MODULES:
        sys.modules.setdefault(name, _Stub(name))


def _example_pixmap(frame_index):
    """A real video frame from examples/, so the viewer isn't empty."""
    import cv2
    from PySide6.QtGui import QImage, QPixmap

    cap = cv2.VideoCapture(str(REPO / "examples" / "example_bunny.mp4"))
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        return None
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    h, w, _ = rgb.shape
    image = QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888).copy()
    return QPixmap.fromImage(image)


def _populate(window, app):
    """Put the main window in a state that looks like real use."""
    total_frames, current = 240, 40

    pixmap = _example_pixmap(current)
    if pixmap is not None:
        window.viewer.load_image_reset_zoom(pixmap)

    slider = window.frame_slider
    slider.blockSignals(True)
    slider.setRange(0, total_frames - 1)
    slider.setValue(current)
    slider.blockSignals(False)
    slider.set_in_point(20)
    slider.set_out_point(150)
    window.frame_value.setText(str(current))

    window.point_manager.add_point(current, 0, True, 310, 220)
    window.point_manager.add_point(current, 0, False, 120, 80)
    window.point_manager.add_point(current, 1, True, 480, 260)
    app.processEvents()


def _grab(widget, app, path, size=None):
    if size:
        widget.resize(*size)
    widget.show()
    app.processEvents()
    # Widgets removed with deleteLater() are only destroyed on request here
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()
    if not widget.grab().save(str(path)):
        raise RuntimeError(f"could not write {path}")
    say(f"  {path.name}")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", default="ui-preview", help="directory for the PNGs")
    parser.add_argument("--width", type=int, default=1400)
    parser.add_argument("--height", type=int, default=900)
    args = parser.parse_args()

    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)

    # The app reads and writes its settings relative to the working directory.
    workdir = tempfile.mkdtemp(prefix="sammie-ui-preview-")
    os.chdir(workdir)

    _install_stubs()
    import sammie_main
    from PySide6.QtWidgets import QApplication
    from sammie import gui_widgets

    # No network, no model loading, no session restore.
    gui_widgets.UpdateChecker.check_for_updates = lambda self: None
    sammie_main.MainWindow._deferred_init = lambda self: None

    app = QApplication(sys.argv)
    try:
        from sammie import theme
        theme.apply_theme(app)
        say("theme applied")
    except ImportError:
        say("no theme module yet - rendering the stock look")

    window = sammie_main.MainWindow()
    console_text = []
    size = (args.width, args.height)
    try:
        _populate(window, app)

        say("main window:")
        for index, name in enumerate(("segmentation", "matting", "removal")):
            window.sidebar.tab_widget.setCurrentIndex(index)
            _grab(window, app, out / f"main-{name}.png", size)

        window.sidebar.tab_widget.setCurrentIndex(0)
        window.view_combo.setCurrentText("Segmentation-BGcolor")
        _grab(window, app, out / "main-bgcolor-view.png", size)
        window.view_combo.setCurrentText("Segmentation-Edit")

        say("dialogs:")
        from sammie.export_dialog import ExportDialog
        from sammie.export_image_dialog import ImageExportDialog
        from sammie.settings_dialog import SettingsDialog

        dialogs = {
            "settings": lambda: SettingsDialog(window.settings_mgr, window),
            "export": lambda: ExportDialog(window),
            "export-image": lambda: ImageExportDialog(window, 40),
            "hotkeys": lambda: gui_widgets.HotkeysHelpDialog(window._shortcuts_list, window),
        }
        for name, make in dialogs.items():
            try:
                dialog = make()
                _grab(dialog, app, out / f"dialog-{name}.png")
                dialog.close()
            except Exception as exc:  # a dialog that needs real state shouldn't stop the rest
                say(f"  {name}: skipped ({exc!r})")

        console_text.append(window.console.toPlainText())
    finally:
        window.close()
        sys.stdout, sys.stderr = sys.__stdout__, sys.__stderr__
        shutil.rmtree(workdir, ignore_errors=True)

    say(f"done: {out}")
    if console_text and console_text[0].strip():
        say("app console output:\n" + console_text[0].strip()[-800:])


if __name__ == "__main__":
    main()
