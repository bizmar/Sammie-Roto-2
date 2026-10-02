# UI overhaul: handoff

For anyone working on this fork in another thread. This is the short version; `docs/ui-modernization-plan.md` has the reasoning, the contrast numbers and the full list of deviations from the original plan.

- **Branch:** `claude/bold-brown-no64ko`, built on top of `exr-ingest` (`3fddde5`). It does not touch the README.
- **What it is:** a dark, flat, DaVinci Resolve / Final Cut Pro style interface. Only the interface changed. Nothing in segmentation, tracking, matting, removal or export was edited.
- **Tested:** Linux, Qt offscreen platform, Fusion style, torch and SAM2 stubbed. **Not tested:** Windows, macOS, or any real clip (load, track, matte, remove, export).

## What the user sees

- Dark neutral theme, same on every platform and **always dark, whatever the Windows or macOS light/dark setting** (Fusion style, a fixed palette and one generated stylesheet).
- New top bar over the viewer: **Load Video** | segmented view selector | per-view options | **Export Video** (pinned to the far right).
- View selector: *stage* (Segmentation / Matting / Removal) then *mode* (Edit / Matte / BG Color). Removal has one view, so the mode control hides.
- Sidebar sections are collapsible (state remembered, Reset Interface reopens them). Sliders have an accent fill and a value field.
- Timeline: thin white playhead, tinted in/out range, **click anywhere to jump**, then drag.
- Transport row: frame readout left, playback centre, in/out markers right.
- SVG icons everywhere the old PNGs were. Delete in the point list is a trash icon that turns red on hover.
- Keyboard focus rings (Tab / Shift+Tab only, not after mouse clicks).

## Where things live

| File | What it holds |
|---|---|
| `sammie/theme.py` | `TOKENS` (every colour), dark palette, the whole stylesheet, `monospace_font()`, keyboard-focus filter. `apply_theme(app)` is called in `main()`. |
| `sammie/icons.py` | `icons.icon("name", color=...)` renders `sammie/resources/icons/<name>.svg` tinted per state (normal, checked, disabled, selected). |
| `sammie/resources/icons/*.svg` | 18 files. All use `currentColor`, except `indicator-check.svg`, which the stylesheet loads and so is fixed white. |
| `sammie/gui_widgets.py` | New: `CollapsibleGroup`, `add_slider_row`, `SegmentedControl`, `ViewSelector`, `HoverIconButton`. Changed: `FrameSlider` (own track, click-to-jump). |
| `sammie_main.py` | Tabs use the new widgets. `_create_viewer_toolbar`, `_create_frame_controls`, `_create_playback_controls` were rebuilt. |
| `sammie/settings_manager.py` | One new app setting, `collapsed_sections` (list of titles). Older settings files load fine. |
| `tools/launch_probe.py` | Runs the real `launcher.py` headlessly and prints the order windows are first shown; `ui_checks.py` uses it to confirm the splash is first. |
| `tools/ui_preview.py` | Renders the main window and four dialogs to PNGs, no display needed. |
| `tools/ui_checks.py` | 89 behaviour checks, no display or models needed. |

## Rules for new UI code

1. **No hard-coded colours.** Use a palette role, a stylesheet token, or `theme.TOKENS`. The old black in/out markers vanished on dark; that is the failure to avoid. Standalone scripts that don't load the theme (`model_downloader.py` is run directly by `manage.py`) must not import it.
2. **Icons:** `icons.icon(...)`, not PNGs. Add an SVG with `currentColor` to `sammie/resources/icons/`.
3. **Sidebar groups:** `CollapsibleGroup("Title")` and put the layout on `group.body`, not on the group itself: `QVBoxLayout(group.body)`. Sections with the same title share open/closed state.
4. **Slider rows:** `add_slider_row(grid, row, label, min, max, value, default=..., tooltip=..., display=...)`. It returns `(slider, value_label)`; keep storing them under the existing `<name>_slider` / `<name>_value` attributes. The read-out follows the slider by itself; just connect `slider.valueChanged` to save.
5. **Views:** `view_combo` is still the source of truth and is hidden. Read or set the view through it as before; `ViewSelector` mirrors it. Don't add a view without adding it to `ViewSelector.STAGES`.
6. **Styling by name:** use `setObjectName` or dynamic properties and put the rule in `theme.py` (`hint`, `panelTitle`, `iconButton`, `caption`, `frameReadout`, `timeline`, `sliderValue`). Avoid new inline `setStyleSheet` calls.
7. **Keep body text at 12px or more**, and check any new text colour against the contrast table in the plan. White text needs the `selection` blue, not `accent`.
8. **Button text with `&`:** write `&&`. A lone `&` is a mnemonic; the styled title drew `"Format & Settings"` with a stray underscore.

## Running the tools

```
pip install PySide6-essentials==6.9.3 numpy opencv-python-headless requests packaging pillow tqdm av OpenEXR
python tools/ui_preview.py --out ui-preview     # PNGs of the main window and dialogs
python tools/ui_checks.py                       # exits non-zero on any failure
```

On a bare Linux box Qt also needs `libegl1 libgl1 libxkbcommon0 libfontconfig1`. Run from anywhere: both tools work in a temporary directory, because the app reads and writes its settings relative to the current directory.

## Gotchas found along the way

- **A blank window before the splash was the console from `run_sammie.bat`.** A shortcut to a `.bat` always opens a console, which sits empty until the script exits. The desktop shortcut made by `manage.py` now runs `.uv\uvw.exe run --no-sync launcher.py` directly (no console), or falls back to the `.bat` started minimised. Existing shortcuts are only rewritten when `manage.py` next creates them (install or update); to fix one by hand, set its Target to `<app folder>\.uv\uvw.exe run --no-sync launcher.py` and Start in to the app folder, or just set Run to Minimized. Double-clicking `run_sammie.bat` itself still opens a console. The launcher also shows the splash before doing any other setup, including the theme.

- **The app is started by `launcher.py`, not `sammie_main.main()`.** `run_sammie.bat` and `run_sammie.sh` run the launcher, which makes its own `QApplication`. The theme was first only applied in `main()`, so in normal use it never applied and Windows' light/dark setting showed through. Any file that creates a `QApplication` must call `theme.apply_theme(app)`; `tools/ui_checks.py` checks this. The screenshot tools call `apply_theme` themselves, so they cannot reveal a missing call.

- `MainWindow` redirects `sys.stdout` into its console widget. Anything a script prints after the window exists vanishes; the tools write to `sys.__stdout__`.
- `QIcon.Active` is applied for keyboard focus, not hover. Hover colour changes need an enter/leave swap (`HoverIconButton`).
- Stylesheet images can't use `currentColor`, which is why `indicator-check.svg` is a separate fixed-colour file.
- Hiding the children of a `QGroupBox` to collapse it breaks widgets the app shows and hides itself (the VideoMaMa rows would pop out). `CollapsibleGroup` hides its own body widget instead.
- A plain `:focus` rule rings every clicked button. The theme flags keyboard-focused widgets with a `keyboardFocus` property instead.

## Merging

- Heaviest conflict risk is `sammie_main.py` (about 500 lines changed: all 16 group boxes, the ten slider rows, the toolbar and transport). If another thread edits those regions, expect to merge by hand and keep the new helpers.
- `sammie/gui_widgets.py` also changed (`FrameSlider`, `PointTable` delete button, new widgets).
- The old PNG icons are still embedded in `sammie/resources/resources.py` but no longer used. The README credit to Yusuke Kamiyamane is left in place for that reason.

## Open items

- Check on Windows with the system set to **light** as well as dark: the whole app should look the same, including the title bar (`setColorScheme`, which the offscreen test platform cannot report). If the title bar stays light, set the Windows dark title-bar attribute per window as a fallback.
- Check the narrow-window behaviour of the top bar.
- Run a real clip end to end (load, track, matte, remove, export) with the new interface.
- Settings dialog now sizes itself to its tallest tab (capped to 90% of the screen) so nothing scrolls at normal sizes.
- Possible follow-ups: editable or draggable number fields, a light theme (the colours are all in `TOKENS`), a fixed slot for the mode control if the top bar should never reflow.
