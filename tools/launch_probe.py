"""
Runs the real launcher.py headlessly and prints the order in which top-level
windows are first shown, one class name per line. Used by ui_checks.py to
confirm that the splash screen is the first thing on screen.

Not meant to be run by hand, but it works: python tools/launch_probe.py
"""
import os
import runpy
import sys
import tempfile

import ui_preview  # offscreen platform, repo on sys.path

os.chdir(tempfile.mkdtemp(prefix="sammie-launch-probe-"))
ui_preview.install_stubs()

from PySide6 import QtWidgets
from PySide6.QtCore import QEvent, QObject, QTimer

shown = []


class Recorder(QObject):
    def eventFilter(self, obj, event):
        if event.type() == QEvent.Show and isinstance(obj, QtWidgets.QWidget) and obj.isWindow():
            name = type(obj).__name__
            if name not in shown:
                shown.append(name)
        return False


class RecordingApp(QtWidgets.QApplication):
    """The launcher builds its own QApplication; this one records from the start."""
    def __init__(self, *args):
        super().__init__(*args)
        self._recorder = Recorder(self)
        self.installEventFilter(self._recorder)


QtWidgets.QApplication = RecordingApp

# No network, no model loading, no session restore
from sammie import gui_widgets
gui_widgets.UpdateChecker.check_for_updates = lambda self: None
import sammie_main
sammie_main.MainWindow._deferred_init = lambda self: None

original_exec = QtWidgets.QApplication.exec  # a static method in PySide6


def exec_then_quit(*_):
    QTimer.singleShot(1500, QtWidgets.QApplication.quit)
    return original_exec()


RecordingApp.exec = exec_then_quit

sys.argv = ["launcher.py"]
try:
    runpy.run_path(str(ui_preview.REPO / "launcher.py"), run_name="__main__")
except SystemExit:
    pass
sys.__stdout__.write("\n".join(shown) + "\n")
