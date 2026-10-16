import os

# OpenCV reads its codec switches once, when cv2 is first imported anywhere in
# the process, so this has to be set before any Sammie module pulls cv2 in.
# Without it, reading an EXR raises; see sammie/exr_ingest.py for why enabling
# it also means EXRs must never reach a bare cv2.imread().
os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")

from PySide6.QtWidgets import QApplication, QSplashScreen, QMessageBox
from PySide6.QtGui import QPixmap, QIcon
from PySide6.QtCore import Qt, QLockFile, QDir, QTimer
import sys
import argparse
import os
import traceback
from sammie.resources import resources
from sammie import theme

def show_splash(app):
    # Just the title band of the original splash, without the figures. The
    # original stays in the compiled resources as the fallback.
    splash_pix = QPixmap(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                      "sammie", "resources", "splash_text.png"))
    if splash_pix.isNull():
        splash_pix = QPixmap(":/splash.webp")
    splash = QSplashScreen(splash_pix, Qt.SplashScreen)
    splash.showMessage("Loading Sammie-Roto...", Qt.AlignCenter | Qt.AlignBottom, Qt.white)
    splash.setWindowFlags(Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
    splash.show()
    app.processEvents()
    return splash

def foreground_window():
    """The window that has the keyboard focus right now, or None (Windows only)."""
    if os.name != 'nt':
        return None
    try:
        import ctypes
        return ctypes.windll.user32.GetForegroundWindow() or None
    except Exception:
        return None

def bring_to_front(window, focus_at_launch):
    """
    Bring the main window to the front, unless the user has moved on.

    Windows only lets the program a user just started come to the front, and
    the desktop shortcut starts Sammie through uvw.exe, uv.exe and the venv's
    python.exe, so that permission stays with uvw.exe and the main window
    opens behind whatever had focus. If the focus is still on the window that
    had it at launch, or on Sammie's own splash, the user hasn't gone on to
    something else, so the window is brought forward. Otherwise it is left
    where it is and Windows flashes its taskbar button, as it normally would.

    Any failure leaves the window exactly as Qt showed it.
    """
    if os.name != 'nt':
        return
    try:
        import ctypes
        from ctypes import wintypes
        user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
        hwnd = int(window.winId())
        focus = user32.GetForegroundWindow()
        if focus == hwnd:
            return
        focus_pid = wintypes.DWORD()
        focus_thread = user32.GetWindowThreadProcessId(focus, ctypes.byref(focus_pid))
        if focus != focus_at_launch and focus_pid.value != os.getpid():
            return
        # SetForegroundWindow is refused to a process that wasn't just
        # started by the user. Sharing the focused window's input state for
        # the call is the usual way round that (Qt's own AlwaysActivateWindow
        # option does the same, but PySide6 doesn't expose it).
        own_thread = kernel32.GetCurrentThreadId()
        attached = bool(focus_thread) and focus_thread != own_thread and \
            bool(user32.AttachThreadInput(own_thread, focus_thread, True))
        try:
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
        finally:
            if attached:
                user32.AttachThreadInput(own_thread, focus_thread, False)
    except Exception:
        pass

def check_single_instance():
    """
    Check if another instance is already running.
    Returns (lock_file, is_first_instance)
    """
    # Use a lock file in the temp directory
    lock_file_path = QDir.tempPath() + "/sammie-roto.lock"
    lock_file = QLockFile(lock_file_path)
    
    # Try to lock - returns True if successful (first instance)
    if lock_file.tryLock(100):  # 100ms timeout
        return lock_file, True
    else:
        return lock_file, False
    
def show_error_dialog(app, error_message, detailed_error=""):
    """Show an error dialog with the crash information"""
    msg_box = QMessageBox()
    msg_box.setIcon(QMessageBox.Critical)
    msg_box.setWindowTitle("Sammie-Roto Startup Error")
    msg_box.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    msg_box.setText("Sammie-Roto encountered an error during startup and cannot continue.")
    msg_box.setInformativeText(error_message)
    
    if detailed_error:
        msg_box.setDetailedText(detailed_error)
    
    msg_box.setStandardButtons(QMessageBox.Ok)
    msg_box.setDefaultButton(QMessageBox.Ok)
    
    # Make sure the dialog appears on top
    msg_box.setWindowFlags(msg_box.windowFlags() | Qt.WindowStaysOnTopHint)
    
    try:
        with open("sammie_debug.log", "w", encoding="utf-8") as f:
            f.write(error_message + '\n' + detailed_error)
    except PermissionError:
        # Show a more specific permission error
        app_dir = os.path.dirname(os.path.abspath(__file__))
        perm_msg_box = QMessageBox()
        perm_msg_box.setIcon(QMessageBox.Critical)
        perm_msg_box.setWindowTitle("Permission Error")
        perm_msg_box.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        perm_msg_box.setText("Sammie-Roto does not have write permission in its installation directory.")
        perm_msg_box.setInformativeText(
            f"Current location:\n{app_dir}\n\n"
            f"Please move Sammie-Roto to a location where you have write access.\n\n"
            f"Avoid running from Program Files or system directories."
        )
        perm_msg_box.setWindowFlags(perm_msg_box.windowFlags() | Qt.WindowStaysOnTopHint)
        perm_msg_box.exec()
    except:
        pass

    return msg_box.exec()

def parse_arguments():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description="Sammie-Roto: Video Segmentation and Matting Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
    Examples:
    python launcher.py                          # Start with GUI file picker
    python launcher.py video.mp4               # Load specific video file
    python launcher.py image.jpg               # Load specific image file
    python launcher.py --file path/to/video.mp4 # Load using --file flag
            """
    )
    
    # Positional argument for file path (most common usage)
    parser.add_argument(
        'file', 
        nargs='?', 
        help='Path to video or image file to load'
    )
    
    # Alternative --file flag (for explicit usage)
    parser.add_argument(
        '--file', '-f',
        dest='file_flag',
        help='Path to video or image file to load'
    )
    
    args = parser.parse_args()
    
    # Use either positional argument or --file flag
    file_path = args.file or args.file_flag
    
    # Validate file exists if provided
    if file_path:
        if not os.path.exists(file_path):
            print(f"Error: File not found: {file_path}")
            sys.exit(1)
    
    return file_path

if __name__ == "__main__":
    # Before anything is shown: where the focus was when the user launched us
    focus_at_launch = foreground_window()

    # Parse command line arguments first
    file_to_load = parse_arguments()

    try:
        if os.name == 'nt':
            import ctypes
            myappid = 'Sammie-Roto.2'
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
    except:
        pass

    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(":/icon.ico"))
    
    # Check for single instance
    lock_file, is_first = check_single_instance()
    if not is_first:
        # Nothing else has been shown, so this is the only window the user sees
        theme.apply_theme(app)
        msg_box = QMessageBox()
        msg_box.setIcon(QMessageBox.Warning)
        msg_box.setWindowTitle("Already Running")
        msg_box.setText("Sammie-Roto is already running.\nOnly one instance can run at a time.")
        msg_box.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        msg_box.exec()
        sys.exit(0)
    # Keep lock_file alive so it isn't garbage collected
    app.lock_file = lock_file
    app.aboutToQuit.connect(lambda: lock_file.unlock())
    # The splash is the first thing on screen, so it goes up before any other setup
    splash = show_splash(app)
    # The app is always dark, whatever the operating system's light/dark setting.
    # Everything shown after the splash, including error boxes, uses it.
    theme.apply_theme(app)

    def load():
        try:
            from sammie_main import MainWindow
            window = MainWindow(initial_file=file_to_load)
            window.show()
            splash.finish(window)
            bring_to_front(window, focus_at_launch)
            window.setWindowIcon(QIcon(":/icon.ico"))
        except ImportError as e:
            splash.close()
            error_msg = f"Failed to import required modules: {str(e)}"
            detailed_error = traceback.format_exc()
            show_error_dialog(app, error_msg, detailed_error)
            sys.exit(1)
        except Exception as e:
            splash.close()
            error_msg = f"Unexpected error during startup: {str(e)}"
            detailed_error = traceback.format_exc()
            show_error_dialog(app, error_msg, detailed_error)
            sys.exit(1)

    QTimer.singleShot(100, load)
    sys.exit(app.exec())