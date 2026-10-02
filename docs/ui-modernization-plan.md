# UI modernization plan

Goal: make Sammie-Roto look like a modern pro video tool, taking **DaVinci Resolve Studio** and **Final Cut Pro** as references, without changing any processing behavior.

Status: plan only. Nothing here has been implemented, and I have not run the app. Findings below come from reading the code at `main` (`2be7283`).

## 1. What to borrow

| Trait | Resolve Studio | Final Cut Pro | How it applies here |
|---|---|---|---|
| Neutral dark theme | Flat grays, no color cast, so it doesn't bias color judgment | Dark gray, slightly softer | Pure neutral grays. This is a masking/matting tool, so the chrome must not tint the viewer. |
| One accent color | Used sparingly (selection, playhead) | Blue for selection and focus | One blue accent for focus, selection, playhead, in/out range. |
| Flat surfaces, hairline dividers | 1px separators, no bevels or groove boxes | Same, plus rounded corners | Drop `QGroupBox` frames and native bevels. Separate with luminance steps and 1px lines. |
| Dense inspector | Compact rows, collapsible sections, per-parameter reset | Collapsible sections with disclosure arrows, label left and control right | Sidebar becomes collapsible sections with uniform rows. |
| Scrubbable number fields | Slider and numeric field are one control | Slider plus field | One `SliderRow` widget replacing the hand-built slider rows. |
| Icon-first transport | Compact transport under the viewer, timecode readout | Minimal control bar under the viewer | Restyled transport with monospaced frame readout. |
| Page tabs / segmented controls | Page tabs along the bottom | Pill segmented controls | Sidebar tabs and view-mode selector become segmented/underline tabs. |
| Rounded, consistent geometry | Small radius | Larger radius | 6px controls, 8px panels, 4px spacing grid. |

## 2. Where the UI is today

- **No app-level styling.** `main()` in `sammie_main.py:3262` creates a bare `QApplication`. No `setStyle`, no palette. The app looks different on Windows and macOS because it uses each platform's native style.
- **Four inline stylesheets** in `sammie_main.py` (lines 145, 524, 806, 1559). They use `palette(...)`, so they will follow a new palette.
- **Hard-coded colors that will break on a dark theme:**
  - `sammie/gui_widgets.py:1131` draws the in/out markers in solid black. Invisible on dark.
  - `sammie/gui_widgets.py:185` hover color `#0078d4`.
  - `sammie/gui_widgets.py:102` gray swatch border.
  - `export_dialog.py:175` and `gui_widgets.py:295` use `color: gray`. `model_downloader.py:286` uses `color: red`.
- **`QGroupBox` is the sidebar's only structure** (16 uses across the Segmentation, Matting and Object Removal tabs).
- **The slider row is hand-built about ten times, in several slightly different variants** (label, `QSlider`, value `QLabel`, double-click-to-reset via `ClickableLabel`). The reset gesture already matches Resolve, so only the widget needs consolidating.
- **`FrameSlider` (`gui_widgets.py:950`) paints on top of the native slider** and reads the groove rect from the style. Restyling it with QSS changes that geometry, so it is the riskiest widget.
- **Icons are 16px raster PNGs** (Yusuke Kamiyamane's set, credited in the README) baked into `sammie/resources/resources.py`. The `.qrc` source is not in the repo. 11 icons are in use. They will look soft on HiDPI and can't be recolored.
- **Everything lives in two big files:** `sammie_main.py` (3270 lines, all tabs and `MainWindow`) and `sammie/gui_widgets.py`.
- **There are no tests.** Verification has to be visual.

## 3. Design tokens (starting values, tune on screen)

| Token | Value | Use |
|---|---|---|
| `canvas` | `#141414` | Viewer background |
| `window` | `#1c1c1e` | Window, menu bar |
| `panel` | `#232325` | Sidebar, bottom panels |
| `control` | `#2f2f32` | Inputs, buttons |
| `control-hover` | `#3a3a3e` | Hover |
| `hairline` | `#3a3a3c` | 1px dividers |
| `text` / `text-dim` / `text-off` | `#e8e8ea` / `#9a9aa0` / `#5c5c61` | Dim text must stay at least 4.5:1 on `panel` |
| `accent` | `#0a84ff` | Focus, selection, playhead, in/out range |
| Radius | 6px controls, 8px panels | |
| Spacing | 4 / 8 / 12 / 16px | |
| Type | System UI font, 12px body | Monospace with tabular numerals for frame readout and console |

Neutral grays only. No tint.

## 4. Phases

Each phase is independently shippable and leaves the app working. Phases 1-2 are restyle only (no logic changes). Phases 3-5 touch layout.

### Phase 0 - Safety net
- Decide the base branch (see section 6).
- Add `tools/ui_preview.py`: builds the main window offscreen (`QT_QPA_PLATFORM=offscreen`), stubs the model/torch imports, and saves PNGs with `widget.grab()`. Neither PySide6 nor torch is installed in this cloud environment, so the harness needs PySide6 plus a stub for `torch`.
- Capture baseline screenshots of the main window (each of the 3 tabs), Export, Settings, and Hotkeys dialogs, so every phase can be compared before and after.
- **Done when:** one command produces the same set of PNGs on a clean checkout.

### Phase 1 - Theme foundation
- New `sammie/theme.py`: `apply_theme(app)` sets Fusion, builds a `QPalette` from the tokens, and installs one QSS string generated from the same tokens.
- Call it in `main()` before `MainWindow` is created.
- Fix every hard-coded color listed in section 2. Move the four inline stylesheets to object names or dynamic properties in the QSS.
- Dev aid: reload the QSS from disk on a key press, so styling iterations don't need a restart.
- **Done when:** the whole app, including every dialog, is dark and consistent on Windows and macOS, with nothing unreadable. Frame slider markers are visible.

### Phase 2 - Icons
- Replace the 11 PNGs with SVG icons from a permissively licensed set (Lucide is ISC, Phosphor is MIT).
- Add `icon(name)` that renders the SVG tinted with the palette's text color (dim when disabled), at the device pixel ratio.
- Load from `sammie/resources/icons/` on disk rather than regenerating `resources.py`.
- Update the README acknowledgements.
- **Done when:** transport and sidebar icons are crisp at 100%, 150% and 200% scaling and recolor correctly when disabled.

### Phase 3 - Sidebar as an inspector
- `CollapsibleSection` widget (header with chevron, hairline, open/closed state saved in session settings) replaces each `QGroupBox`.
- `SliderRow` widget (label, slider, editable number field, double-click label to reset, same signals as today) replaces the hand-built rows.
- Sidebar tabs become an underline or segmented tab bar.
- The instruction text blocks become muted hint text.
- Files: `sammie_main.py` (`SegmentationTab` 73, `MattingTab` 413, `ObjectRemovalTab` 745, `Sidebar` 1129), new widgets in `sammie/gui_widgets.py`.
- Keep the existing attribute names (`holes_slider`, `holes_value`, ...) so the rest of `MainWindow` keeps working.
- **Done when:** every control has the same row layout, values still persist, and reset still works.

### Phase 4 - Viewer and transport
- Viewer on the `canvas` color with a thin top bar for view mode and the existing checkboxes and color picker.
- Transport bar under the viewer: centered transport buttons, in/out buttons, monospaced `frame / total` readout.
- Restyle `FrameSlider` as a thin timeline scrubber: accent playhead, tinted in/out range, bracket markers drawn with the new colors. Verify `_frame_to_pixel` and `_draw_range_highlight` against the new groove geometry.
- View selector: restyle the combo first. Turning it into a segmented control is optional, since `view_combo` is referenced by several handlers.
- **Done when:** scrubbing, in/out ranges and playback look right at several window sizes and the dynamic per-view widgets still swap correctly.

### Phase 5 - Chrome and dialogs
- Bottom panels (point list, console) get proper panel headers. Console font per platform (Consolas on Windows, Menlo on macOS) instead of relying on the monospace fallback.
- Status bar gets a quiet style with a separate progress area.
- Export, Image Export, Settings, Model Download and Hotkeys dialogs: check spacing and alignment under the new theme and fix outliers.
- **Done when:** no dialog looks like it belongs to a different app.

### Phase 6 - QA and polish
- Windows 10/11 and macOS screenshots at 100%, 150%, 200% scale.
- Disabled, hover, pressed and keyboard-focus states for every control type.
- Contrast check on all text tokens. Minimum 12px body text.
- Confirm "Reset interface" and persisted splitter sizes still work.

## 5. Risks

- **`FrameSlider` geometry.** QSS on `QSlider` changes the groove rect the custom painting depends on. Handle in Phase 4 and test first on a throwaway branch.
- **Fusion on macOS is not native.** The menu bar stays native, but controls will look the same as on Windows. That is the intent, but worth a look before committing.
- **Merge conflicts.** `sammie_main.py` is one 3270-line file and the fork's real work is on `exr-ingest`. Put new code in new files (`theme.py`, widgets) and keep edits to `sammie_main.py` small. Do not move code between files in the same change as restyling.
- **No automated tests.** A silent break (a slider no longer saving) would not be caught. Keep widget attribute names and signals identical and check them by hand in Phase 3.
- **QSS is easy to over-engineer.** Prefer palette plus a small stylesheet over per-widget rules.

## 6. Decisions needed from you

1. **Base branch.** The README says the real work is on `exr-ingest`, which exists on GitHub but is not in this checkout (this session started from `main`). Should the UI work go on top of `exr-ingest`?
2. **Scope.** Restyle only (Phases 0-2), or the full layout changes (Phases 3-5) too? I recommend doing 0-2 first and looking at the result before deciding.
3. **Light theme.** Dark only, or keep the tokens structured so a light variant can be added later? Dark only is much less work.
4. **Icon set.** Lucide (line icons, closest to Resolve and FCP) or Phosphor (more weights)? I would pick Lucide.
5. **Fonts.** I recommend system fonts and no bundled font. Say if you want a bundled font for identical looks on both platforms.
