# Brief: window "shadow" flashes before the splash screen (Windows 11)

For the Claude thread that runs on the Windows machine. The thread that wrote this could not run Windows, so everything under "Hypotheses" is untested. Please test it, fix it, and report back.

Branch: `claude/bold-brown-no64ko` (pull it first). Files involved: `launcher.py`, `manage.py`.

## Symptom

On launch, a split second before the splash screen appears, a window-shaped **shadow** shows up. Its interior is transparent (you can see the desktop through it). It is not a console window and not a window with content.

## What is already known

- **From Python's side, nothing else is shown before the splash.** `tools/launch_probe.py` runs the real `launcher.py` headlessly and records the first time each top-level window is shown: `QSplashScreen`, then `MainWindow`. `python tools/ui_checks.py` fails if anything else comes first. (Offscreen only: it cannot see native or DWM behaviour.)
- **The splash image is opaque.** `:/splash.webp` is 640x400 with no alpha channel, so the transparency is not in the picture.
- **`show_splash()` changes the splash's window type.** `QSplashScreen(pix, Qt.SplashScreen)` is built, then `setWindowFlags(Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)` replaces the flags. That drops `Qt.SplashScreen`, so Windows sees an ordinary frameless top-level window. Measured offscreen: type goes from `SplashScreen` to `Window`.
- **A console window was suspected first and may still contribute.** The desktop shortcut used to run `run_sammie.bat`, which opens an empty console. `manage.py` now creates the shortcut to run `.uv\uvw.exe run --no-sync launcher.py` directly (existing shortcuts are only rewritten when `manage.py` next creates them). The user reports the flash is a shadow, not a console, so this is probably not the cause. It is harmless; keep it unless it causes trouble.
- The theme is applied after the splash is shown (`theme.apply_theme(app)` in `launcher.py`), so it is unlikely to be involved. `apply_theme` calls `styleHints().setColorScheme(Dark)`; if nothing else works, test with that line disabled.

## Hypotheses, most likely first

1. **The splash's own native window is composed by DWM before its first paint.** A top-level window can be shown for a few milliseconds with its frame and shadow but no content, and the frameless-`Window` type probably makes the shadow more visible than a `SplashScreen` type would.
2. **Something that is not Qt:** `uvw.exe` or the Python start-up showing a window, or Windows' own start-up feedback. This would have nothing to do with the splash code.
3. A second hidden Qt window (for example the one Qt creates for the tray or colour scheme) briefly becoming visible. The headless probe would not show this, because it only sees widgets.

## Step 1: find out which window it is (do this before changing code)

Add a temporary poller as the first lines of `launcher.py`'s `__main__` block, before `QApplication` is created, that logs every top-level window this process owns with a timestamp, class name, title, rectangle and visibility, every few milliseconds until the splash has been up for a second. Sketch:

```python
import ctypes, threading, time
from ctypes import wintypes
def _poll():
    user32 = ctypes.windll.user32
    pid = ctypes.windll.kernel32.GetCurrentProcessId()
    seen = {}
    t0 = time.perf_counter()
    cb_t = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        p = wintypes.DWORD(); user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
        if p.value == pid:
            cls = ctypes.create_unicode_buffer(256); user32.GetClassNameW(hwnd, cls, 256)
            r = wintypes.RECT(); user32.GetWindowRect(hwnd, ctypes.byref(r))
            key = (hwnd, user32.IsWindowVisible(hwnd), r.left, r.top, r.right, r.bottom)
            if seen.get(hwnd) != key:
                seen[hwnd] = key
                print(f"{time.perf_counter()-t0:7.3f}s hwnd={hwnd:#x} class={cls.value} visible={bool(key[1])} rect={key[2:]}", flush=True)
        return True
    while time.perf_counter() - t0 < 6:
        user32.EnumWindows(cb_t(cb), 0); time.sleep(0.002)
threading.Thread(target=_poll, daemon=True).start()
```

Run it from a terminal with `.venv\Scripts\python.exe launcher.py` so the output is visible. Note the class name and rectangle of the first window that becomes visible, and whether it is the splash (640x400, centred).

Also run the app these ways and note which show the flash, to separate the launch chain from Qt:

- the desktop shortcut,
- `.uv\uvw.exe run --no-sync launcher.py`,
- `.venv\Scripts\python.exe launcher.py` from a terminal.

If a screen recording is easier (Xbox Game Bar, Win+Alt+R, 60 fps), step through the frames around the first appearance instead.

## Step 2: candidate fixes, test each one

A. **Keep the splash window type.** In `show_splash()`, use `Qt.SplashScreen | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint` instead of `Qt.Window | ...` (or drop the override, since the constructor already sets frameless and splash). Check the splash still stays on top and does not get a taskbar button.

B. **Never show an unpainted window.** Show the splash at zero opacity, force a paint, then reveal it:

```python
splash.setWindowOpacity(0.0)
splash.show()
splash.repaint()
app.processEvents()
splash.setWindowOpacity(1.0)
```

C. **Turn off the DWM shadow on the splash.** Before `show()`, call `splash.winId()` to create the native window, then:

```python
hwnd = int(splash.winId())
policy = ctypes.c_int(1)  # DWMNCRP_DISABLED
ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 2, ctypes.byref(policy), 4)  # DWMWA_NCRENDERING_POLICY
```

D. If Step 1 shows the window is **not** the splash, fix whatever it is instead (for example a second Qt window), and say so in your report.

Combining A and B is the likely end result, but let the evidence from Step 1 decide.

## Constraints

- Keep `python tools/ui_checks.py` passing (89 checks). It includes the splash-is-first probe; do not weaken it.
- Keep the theme applied after the splash is shown and before any error or "already running" box. Keep the single-instance check.
- Do not touch the README.
- Remove the temporary poller before committing. Commit to `claude/bold-brown-no64ko`.
- Add what you find to the "Gotchas" section of `docs/UI_HANDOFF.md`.

## Report back

1. The class name, size and timing of the window that flashes (from Step 1).
2. Which launch method(s) show it.
3. Which fix removed it, and whether the splash still behaves (on top, no taskbar button, not stealing focus).
4. Whether the `.bat` to `uvw.exe` shortcut change turned out to matter.

## Result (tested on the Windows machine, 2026-10-02)

Measured with an external watcher instead of an in-process poller: a separate script took a snapshot of every top-level window on the desktop, launched Sammie, and logged every window from any process that appeared or changed, every millisecond. That also sees windows owned by `uvw.exe`, `cmd.exe` or Windows Terminal, which a poller inside `launcher.py` cannot. No temporary code went into `launcher.py`.

1. **The window that flashes is Windows Terminal hosting the console of `run_sammie.bat`.** Class `CASCADIA_HOSTING_WINDOW_CLASS`, process `WindowsTerminal.exe`, 1008x524 at a cascaded position (not centred), visible from 0.38 s to 0.50 s after launch - about 0.12 s, gone before it draws anything, which is why it reads as a shadow with a see-through middle. The splash followed at 1.75 s.
2. **Only the old desktop shortcut shows it** (Target `run_sammie.bat`). Launching `.uv\uvw.exe run --no-sync launcher.py` directly, or through a shortcut that does, shows no window at all before the splash: the first window is the splash (`Qt693QWindowIcon`, 640x400, centred) at about 1.46 s, in every run. `python.exe launcher.py` from a terminal was not tried; it is not how the app is started.
3. **The fix was the shortcut change already in `manage.py`.** The user's existing shortcut was recreated with `python -c "import manage; manage.create_windows_shortcut()"`, after which two launches showed nothing before the splash. Candidate fixes A, B and C to the splash were not needed and were not made, so the splash behaves exactly as before. One observation for later: because `show_splash()` replaces the flags with `Qt.Window | ...`, the splash's native window has `WS_EX_TOPMOST` but not `WS_EX_TOOLWINDOW`, so it is an ordinary top-level window while loading - fix A would change that if it ever matters.
4. **The `.bat` to `uvw.exe` change mattered: it is the whole fix.** The earlier note that the flash was "probably not" the console was wrong only because the user's shortcut had not been recreated yet. Starting without the `.bat` also brings the splash up about 0.3 s sooner.

`tools/ui_checks.py` was not changed. On Windows 88 of its 89 checks pass, the splash-first checks included. The one failure, "Reset Interface restores the default splitter sizes" (`[1406, 290]`), already failed before this work and is unrelated.
