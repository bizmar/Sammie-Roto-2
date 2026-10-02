"""
Behaviour checks for the sidebar widgets, run without a display, a GPU or the
models (torch and SAM2 are stubbed, as in ui_preview.py).

    python tools/ui_checks.py

The app has no automated tests, so this guards the parts of the UI that were
rebuilt for the new look: collapsible sections and the slider rows. Exits
non-zero if anything fails.
"""
import os
import sys
import tempfile
from pathlib import Path

import ui_preview  # sets the offscreen platform and puts the repo on sys.path

failures = []


def check(condition, message):
    # The main window redirects sys.stdout into its console widget, so write to the real one
    sys.__stdout__.write(("PASS  " if condition else "FAIL  ") + message + "\n")
    if not condition:
        failures.append(message)


def check_collapsible_group(app, mgr):
    from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget
    from sammie.gui_widgets import CollapsibleGroup

    host = QWidget()
    layout = QVBoxLayout(host)
    group = CollapsibleGroup("Test section")
    inner = QVBoxLayout(group.body)
    always, hidden_by_app = QLabel("always"), QLabel("hidden by the app")
    inner.addWidget(always)
    inner.addWidget(hidden_by_app)
    hidden_by_app.setVisible(False)
    layout.addWidget(group)
    host.show()
    app.processEvents()

    check(group.is_expanded() and always.isVisible(), "section starts expanded with its contents visible")
    check(not hidden_by_app.isVisible(), "a child the app hid stays hidden")

    group.header.click()
    app.processEvents()
    check(not group.is_expanded() and not always.isVisible(), "clicking the header collapses the section")
    check("Test section" in mgr.app_settings.collapsed_sections, "collapsed state is recorded in the app settings")
    hidden_by_app.setVisible(True)
    app.processEvents()
    check(not hidden_by_app.isVisible(), "the app showing a child while collapsed does not pop it out")
    hidden_by_app.setVisible(False)

    group.header.click()
    app.processEvents()
    check(group.is_expanded() and always.isVisible(), "clicking again expands it")
    check(not hidden_by_app.isVisible(), "the app-hidden child is still hidden after expanding")
    check("Test section" not in mgr.app_settings.collapsed_sections, "expanded state is recorded")

    group.header.click()  # leave it collapsed, then make a fresh one
    check(not CollapsibleGroup("Test section").is_expanded(), "a new section with the same title starts collapsed")
    check("Test section" in Path("sammie_settings.conf").read_text(), "the state is written to sammie_settings.conf")
    group.header.click()  # tidy up


def check_reset_interface_and_layout_persistence(app):
    from sammie.gui_widgets import CollapsibleGroup
    from sammie.settings_manager import ApplicationSettings

    window = ui_preview.create_main_window()
    window.resize(1400, 900)
    window.show()
    app.processEvents()

    groups = window.sidebar.findChildren(CollapsibleGroup)
    check(len(groups) == 16, f"the sidebar has 16 sections ({len(groups)})")

    # Sections that share a title (Instructions, Parameters, Postprocessing) move together
    instructions = [g for g in groups if g._title == "Instructions"]
    check(len(instructions) == 2, "the Matting and Object Removal tabs each have an Instructions section")
    instructions[0].set_expanded(False)
    check(not instructions[1].is_expanded(), "closing one Instructions section closes the other")
    instructions[1].set_expanded(True)
    check(instructions[0].is_expanded(), "reopening one reopens the other")

    unique = [g for g in groups if sum(o._title == g._title for o in groups) == 1][:3]
    for group in unique:
        group.set_expanded(False)
    window.main_splitter.setSizes([700, 700])
    app.processEvents()
    check(sum(not g.is_expanded() for g in groups) == 3, "three sections can be closed")

    # Layout survives a restart: save, then build a new window from the settings file
    window.main_splitter.setSizes([900, 400])
    app.processEvents()
    saved = window.main_splitter.sizes()
    window._save_window_and_splitter_settings()
    window.close()

    window = ui_preview.create_main_window()
    window.resize(1400, 900)
    window.show()
    app.processEvents()
    groups = window.sidebar.findChildren(CollapsibleGroup)
    sizes = window.main_splitter.sizes()
    check(abs(sizes[0] / sum(sizes) - saved[0] / sum(saved)) < 0.03, f"splitter sizes are restored on the next start ({saved} -> {sizes})")
    check(sum(not g.is_expanded() for g in groups) == 3, "closed sections are restored on the next start")

    window.reset_interface()
    app.processEvents()
    default = ApplicationSettings().main_splitter_sizes
    sizes = window.main_splitter.sizes()
    check(abs(sizes[0] / sum(sizes) - default[0] / sum(default)) < 0.03, f"Reset Interface restores the default splitter sizes ({sizes})")
    check(all(g.is_expanded() for g in groups), "Reset Interface reopens every section")
    window.close()


def check_sliders(app, mgr):
    import sammie_main
    from sammie.gui_widgets import ClickableLabel

    sidebar = sammie_main.Sidebar()
    sidebar.resize(320, 900)
    sidebar.show()
    app.processEvents()
    seg, mat, rem = sidebar.segmentation_tab, sidebar.matting_tab, sidebar.removal_tab

    def label_for(tab, text):
        return next(label for label in tab.findChildren(ClickableLabel) if label.text() == text)

    for key in ("holes", "dots", "border_fix", "grow"):
        slider, value = getattr(seg, f"{key}_slider"), getattr(seg, f"{key}_value")
        slider.setValue(slider.maximum() // 2 or 3)
        check(value.text() == str(slider.value()), f"segmentation {key}: read-out follows the slider")
        check(mgr.get_session_setting(key) == slider.value(), f"segmentation {key}: saved to the session settings")
    label_for(seg, "Remove Holes:").doubleClicked.emit()
    check(seg.holes_slider.value() == 0 and seg.holes_value.text() == "0", "segmentation holes: double-clicking the label resets it")

    mat.gamma_slider.setValue(150)
    check(mat.gamma_value.text() == "1.5", "gamma: a slider value of 150 reads 1.5")
    check(mgr.get_session_setting("matany_gamma") == 1.5, "gamma: stored as a float")
    label_for(mat, "Gamma:").doubleClicked.emit()
    check(mat.gamma_slider.value() == 100 and mat.gamma_value.text() == "1.0", "gamma: double-click resets to 1.0")
    check("1.0" in label_for(mat, "Gamma:").toolTip(), "gamma: the reset tooltip names the default")
    mat.shrink_grow_slider.setValue(-4)
    check(mat.shrink_grow_value.text() == "-4" and mgr.get_session_setting("matany_grow") == -4, "matting shrink/grow: read-out and setting")

    rem.shrink_grow_slider.setValue(9)
    check(rem.shrink_grow_value.text() == "9" and mgr.get_session_setting("inpaint_grow") == 9, "removal shrink/grow: read-out and setting")
    rem.minimax_steps_slider.setValue(8)
    check(rem.minimax_steps_value.text() == "8" and mgr.get_session_setting("minimax_steps") == 8, "minimax steps: read-out and setting")
    rem.opencv_radius_slider.setValue(5)
    check(rem.opencv_radius_value.text() == "5" and mgr.get_session_setting("inpaint_radius") == 5, "opencv radius: read-out and setting")
    label_for(rem, "Steps:").doubleClicked.emit()
    check(rem.minimax_steps_slider.value() == mgr.app_settings.default_minimax_steps, "minimax steps: double-click resets to the app default")

    mgr.set_session_setting("holes", 11)
    mgr.set_session_setting("matany_gamma", 2.0)
    mgr.set_session_setting("minimax_steps", 10)
    sidebar.load_values_from_settings()
    app.processEvents()
    check(seg.holes_slider.value() == 11 and seg.holes_value.text() == "11", "loading settings updates a segmentation slider and its read-out")
    check(mat.gamma_slider.value() == 200 and mat.gamma_value.text() == "2.0", "loading settings updates gamma and its read-out")
    check(rem.minimax_steps_slider.value() == 10 and rem.minimax_steps_value.text() == "10", "loading settings updates minimax steps")


def check_timeline_and_view_bar(app):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QStyle, QStyleOptionSlider

    window = ui_preview.create_main_window()
    window.resize(1400, 900)
    window.show()
    app.processEvents()
    slider = window.frame_slider

    def handle_centre_x():
        opt = QStyleOptionSlider()
        slider.initStyleOption(opt)
        return slider.style().subControlRect(QStyle.CC_Slider, opt, QStyle.SC_SliderHandle, slider).center().x()

    def x_for(fraction):
        opt = QStyleOptionSlider()
        slider.initStyleOption(opt)
        groove = slider.style().subControlRect(QStyle.CC_Slider, opt, QStyle.SC_SliderGroove, slider)
        return int(groove.left() + groove.width() * fraction)

    slider.blockSignals(True)  # no clip is loaded, so keep frame changes from reaching the frame cache
    slider.setRange(0, 239)
    for value in (0, 60, 120, 239):
        slider.setValue(value)
        offset = abs(slider._frame_to_pixel(value) - handle_centre_x())
        check(offset <= 2, f"timeline: marker position for frame {value} is within 2px of the playhead ({offset}px)")

    y = slider.height() // 2
    slider.setValue(0)
    QTest.mouseClick(slider, Qt.LeftButton, Qt.NoModifier, QPoint(x_for(0.5), y))
    check(abs(slider.value() - 120) <= 4, f"timeline: clicking the middle of the track jumps there ({slider.value()})")

    QTest.mousePress(slider, Qt.LeftButton, Qt.NoModifier, QPoint(x_for(0.1), y))
    jumped = slider.value()
    QTest.mouseMove(slider, QPoint(x_for(0.8), y))
    QTest.mouseRelease(slider, Qt.LeftButton, Qt.NoModifier, QPoint(x_for(0.8), y))
    check(abs(jumped - 24) <= 4, f"timeline: pressing at 10% jumps to about frame 24 ({jumped})")
    check(abs(slider.value() - 191) <= 5, f"timeline: dragging on from there follows the mouse ({slider.value()})")

    slider.set_in_point(30)
    slider.set_out_point(180)
    slider.setValue(100)
    pixmap = slider.grab()
    check(not pixmap.isNull(), "timeline: paints with an in/out range set")
    slider.blockSignals(False)

    # The options on the right of the view bar follow the selected view
    window.view_combo.setCurrentText("Segmentation-BGcolor")
    app.processEvents()
    check(window.color_picker is not None and window.antialias_checkbox is not None, "view bar: the BG colour view shows antialias and a colour picker")
    window.view_combo.setCurrentText("Segmentation-Edit")
    app.processEvents()
    check(window.show_masks_checkbox is not None and window.color_picker is None, "view bar: the edit view shows the mask and outline options")
    window.view_combo.setCurrentText("ObjectRemoval")
    app.processEvents()
    check(window.show_removal_mask_checkbox is not None, "view bar: the removal view shows the mask option")
    window.close()


def check_view_selector_and_toolbar_buttons(app):
    from PySide6.QtWidgets import QPushButton

    window = ui_preview.create_main_window()
    window.show()
    app.processEvents()
    selector, combo = window.view_selector, window.view_combo

    def pick(control, key):
        control._buttons[key].click()
        app.processEvents()

    check(not combo.isVisible(), "view selector: the combo box that holds the view is not shown")
    check(selector.stage_control.current() == "Segmentation" and selector.mode_control.current() == "Segmentation-Edit", "view selector: starts on Segmentation / Edit")

    pick(selector.mode_control, "Segmentation-BGcolor")
    check(combo.currentText() == "Segmentation-BGcolor", "view selector: picking a mode sets the view")
    check(window.color_picker is not None, "view selector: the view's options follow (colour picker)")

    pick(selector.stage_control, "Matting")
    check(combo.currentText() == "Matting-BGcolor", "view selector: switching stage keeps the same mode (BG Color)")
    check(selector.mode_control.keys() == ["Matting-Matte", "Matting-BGcolor"], "view selector: Matting offers Matte and BG Color only")

    combo.setCurrentText("Segmentation-Edit")
    app.processEvents()
    pick(selector.stage_control, "Matting")
    check(combo.currentText() == "Matting-Matte", "view selector: Edit has no Matting equivalent, so Matting opens on Matte")

    pick(selector.stage_control, "Removal")
    check(combo.currentText() == "ObjectRemoval" and not selector.mode_control.isVisible(), "view selector: Removal has one view and hides the mode control")

    combo.setCurrentText("Matting-Matte")  # something else changing the view, as the sidebar tabs do
    app.processEvents()
    check(selector.stage_control.current() == "Matting" and selector.mode_control.current() == "Matting-Matte", "view selector: follows the view when other code changes it")

    calls = []
    window.open_file = lambda: calls.append("load")
    window.export_video = lambda: calls.append("export")
    texts = {b.text(): b for b in window.findChildren(QPushButton)}
    load, export = texts["Load Video"], texts["Export Video"]
    load.click()
    export.click()
    check(calls == ["load", "export"], f"toolbar: Load Video and Export Video call the same handlers as the File menu ({calls})")
    layout_x = [load.mapTo(window, load.rect().topLeft()).x(), selector.mapTo(window, selector.rect().topLeft()).x(), export.mapTo(window, export.rect().topLeft()).x()]
    check(layout_x == sorted(layout_x), "toolbar: order is Load Video, view selector, Export Video")
    # Export Video is the last thing on the bar, and never moves
    export_x, export_right = set(), set()
    for view in ("Segmentation-Edit", "Segmentation-BGcolor", "Segmentation-Matte", "Matting-Matte", "Matting-BGcolor", "ObjectRemoval"):
        combo.setCurrentText(view)
        app.processEvents()
        export_x.add(export.mapTo(window, export.rect().topLeft()).x())
        export_right.add(export.mapTo(window, export.rect().topRight()).x())
    check(len(export_x) == 1, f"toolbar: Export Video stays in the same place in all six views ({sorted(export_x)})")
    options = window.dynamic_widgets_container
    check(options.mapTo(window, options.rect().topRight()).x() <= export.mapTo(window, export.rect().topLeft()).x(), "toolbar: the view options sit to the left of Export Video")
    viewer_right = window.viewer.mapTo(window, window.viewer.rect().topRight()).x()
    check(abs(viewer_right - max(export_right)) <= 10, f"toolbar: Export Video lines up with the viewer's right edge ({max(export_right)} vs {viewer_right})")
    window.close()


def check_point_delete_buttons(app):
    from PySide6.QtWidgets import QPushButton

    window = ui_preview.create_main_window()
    window.show()
    window.point_manager.add_point(10, 0, True, 100, 100)
    window.point_manager.add_point(10, 0, False, 50, 60)
    app.processEvents()
    buttons = [b for b in window.point_table.findChildren(QPushButton) if b.objectName() == "iconButton"]
    check(len(buttons) == 2, f"point list: each point has a delete button ({len(buttons)})")
    check(all(b.text() == "" and not b.icon().isNull() for b in buttons), "point list: the delete buttons are icon-only")
    check(all(b.toolTip() for b in buttons), "point list: the delete buttons have a tooltip")

    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QEnterEvent
    button = buttons[0]
    idle = button.icon().cacheKey()
    app.sendEvent(button, QEnterEvent(button.rect().center(), button.rect().center(), button.rect().center()))
    hovered = button.icon().cacheKey()
    app.sendEvent(button, QEvent(QEvent.Leave))
    check(hovered != idle and button.icon().cacheKey() == idle, "point list: the delete icon changes under the mouse and goes back")
    window.close()


def check_launch_is_quiet():
    import subprocess

    result = subprocess.run([sys.executable, str(Path(__file__).with_name("launch_probe.py"))],
                            capture_output=True, text=True, timeout=120)
    order = [line for line in result.stdout.splitlines() if line.strip()]
    check(bool(order), f"launch: the launcher ran and showed windows ({order or result.stderr[-200:]})")
    check(order[:1] == ["QSplashScreen"], f"launch: the splash screen is the first window shown (order: {order})")
    check(order.index("MainWindow") > order.index("QSplashScreen") if {"MainWindow", "QSplashScreen"} <= set(order) else False,
          "launch: the main window appears only after the splash")


def check_windows_shortcut_does_not_open_a_console():
    import importlib.util
    import tempfile

    spec = importlib.util.spec_from_file_location("sammie_manage", ui_preview.REPO / "manage.py")
    manage = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(manage)

    with tempfile.TemporaryDirectory() as app_dir:
        script = manage.windows_shortcut_script(app_dir, "C:/Desktop/Sammie-Roto-2.lnk")
        check("run_sammie.bat" in script and "WindowStyle = 7" in script, "shortcut: without uvw.exe it falls back to the .bat, started minimised")

        os.makedirs(os.path.join(app_dir, ".uv"))
        Path(app_dir, ".uv", "uvw.exe").write_bytes(b"")
        script = manage.windows_shortcut_script(app_dir, "C:/Desktop/Sammie-Roto-2.lnk")
        check("uvw.exe" in script and "run_sammie.bat" not in script, "shortcut: with uvw.exe it runs it directly, so no console window is created")
        check('Arguments = "run --no-sync launcher.py"' in script, "shortcut: it passes the same arguments the .bat does")
        check("WorkingDirectory" in script and app_dir in script, "shortcut: it starts in the app folder")


def check_settings_dialog_fits(app, mgr):
    from sammie.settings_dialog import SettingsDialog

    dialog = SettingsDialog(mgr)
    dialog.show()
    app.processEvents()
    available = dialog.screen().availableGeometry().height()
    check(dialog.height() <= available * 0.9 + 1, f"settings: the dialog is capped to 90% of the screen height ({dialog.height()} of {available})")
    for index in range(dialog.tab_widget.count()):
        dialog.tab_widget.setCurrentIndex(index)
        app.processEvents()
        scroll = dialog.tab_widget.currentWidget()
        name = dialog.tab_widget.tabText(index)
        check(scroll.verticalScrollBar().maximum() == 0, f"settings: the {name} tab shows in full without scrolling")
    dialog.close()


def check_dark_whatever_the_system_says(app):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QPushButton

    def is_dark():
        return app.palette().color(app.palette().ColorRole.Window).lightness() < 60

    hints = app.styleHints()
    hints.setColorScheme(Qt.ColorScheme.Light)   # as if Windows were set to light mode
    app.processEvents()
    from sammie import theme
    theme.apply_theme(app)
    app.processEvents()
    # (The colour scheme hint itself, which darkens the native title bar, is not
    # reported by the offscreen platform, so it can only be checked on a real desktop.)
    check(is_dark(), "dark mode: the window colour is dark under a light system setting")

    button = QPushButton("probe")
    button.show()
    app.processEvents()
    pixel = button.grab().toImage().pixelColor(2, button.height() // 2)
    check(pixel.lightness() < 90, f"dark mode: a push button draws dark under a light system setting (lightness {pixel.lightness()})")
    button.close()

    hints.setColorScheme(Qt.ColorScheme.Light)   # Windows flips to light while the app is open
    app.processEvents()
    check(is_dark(), "dark mode: the palette stays dark if the system switches to light while running")


def check_entry_points_apply_theme():
    """
    The app is normally started through launcher.py, which makes its own
    QApplication and never runs sammie_main.main(). Any file that creates the
    QApplication has to apply the theme, or the app shows in the system's
    light or dark style instead.
    """
    for name in ("launcher.py", "sammie_main.py"):
        source = (ui_preview.REPO / name).read_text(encoding="utf-8")
        if "QApplication(" in source:
            check("theme.apply_theme(app)" in source, f"entry point: {name} creates the QApplication and applies the theme")


def check_keyboard_focus(app):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QPushButton, QVBoxLayout, QWidget

    host = QWidget()
    layout = QVBoxLayout(host)
    first, second = QPushButton("first"), QPushButton("second")
    layout.addWidget(first)
    layout.addWidget(second)
    host.show()
    host.activateWindow()
    QTest.qWaitForWindowActive(host)

    # A window gives its first widget focus when it activates, so start elsewhere
    second.setFocus(Qt.MouseFocusReason)
    app.processEvents()
    first.setFocus(Qt.TabFocusReason)
    app.processEvents()
    check(first.property("keyboardFocus") is True, "keyboard focus: Tab onto a button marks it for the focus ring")
    second.setFocus(Qt.MouseFocusReason)
    app.processEvents()
    check(not first.property("keyboardFocus"), "keyboard focus: the ring leaves a button when focus moves away")
    check(not second.property("keyboardFocus"), "keyboard focus: clicking a button (mouse focus) does not ring it")
    first.setFocus(Qt.BacktabFocusReason)
    app.processEvents()
    check(first.property("keyboardFocus") is True, "keyboard focus: Shift+Tab onto a button marks it too")
    check(first.hasFocus(), "keyboard focus: the button really has focus (the check ran on a live window)")
    host.close()


def main():
    os.chdir(tempfile.mkdtemp(prefix="sammie-ui-checks-"))  # settings are written relative to the cwd
    ui_preview.install_stubs()

    from PySide6.QtWidgets import QApplication
    from sammie import settings_manager, theme

    app = QApplication([])
    theme.apply_theme(app)
    mgr = settings_manager.initialize_settings()

    check_collapsible_group(app, mgr)
    check_sliders(app, mgr)
    check_reset_interface_and_layout_persistence(app)
    check_timeline_and_view_bar(app)
    check_view_selector_and_toolbar_buttons(app)
    check_point_delete_buttons(app)
    check_keyboard_focus(app)
    check_settings_dialog_fits(app, mgr)
    check_launch_is_quiet()
    check_windows_shortcut_does_not_open_a_console()
    check_dark_whatever_the_system_says(app)
    check_entry_points_apply_theme()

    sys.__stdout__.write(f"\n{len(failures)} failure(s)\n")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
