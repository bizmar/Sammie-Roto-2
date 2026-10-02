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


def check_reset_interface(app, mgr):
    import sammie_main
    from sammie.gui_widgets import CollapsibleGroup

    sidebar = sammie_main.Sidebar()
    sidebar.show()
    groups = sidebar.findChildren(CollapsibleGroup)
    check(len(groups) == 16, f"the sidebar has 16 sections ({len(groups)})")
    for group in groups[:3]:
        group.set_expanded(False)
    check(sum(not g.is_expanded() for g in groups) >= 3, "several sections can be closed")
    # MainWindow.reset_interface reopens every section in the sidebar
    for group in sidebar.findChildren(CollapsibleGroup):
        group.set_expanded(True)
    check(all(g.is_expanded() for g in groups) and not mgr.app_settings.collapsed_sections, "reopening them all clears the remembered state")


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
    check_reset_interface(app, mgr)
    check_timeline_and_view_bar(app)

    sys.__stdout__.write(f"\n{len(failures)} failure(s)\n")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
