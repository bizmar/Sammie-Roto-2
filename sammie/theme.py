"""
Application theme: a neutral dark look, loosely modelled on the chrome of
DaVinci Resolve and Final Cut Pro.

Everything visual comes from TOKENS. apply_theme() turns them into a Fusion
palette plus one stylesheet, so the look is the same on Windows, macOS and
Linux. Greys are deliberately neutral: this is a masking tool, and a tinted
interface would colour the viewer.

Widgets that need a colour should use palette roles (or color()) rather than
hard-coding one.
"""
from pathlib import Path
from string import Template

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QWidget

ICON_DIR = Path(__file__).resolve().parent / "resources" / "icons"

TOKENS = {
    "canvas": "#141414",         # viewer background
    "window": "#1c1c1e",         # window, menu bar
    "panel": "#232325",          # sidebar, bottom panels
    "field": "#19191b",          # inset input fields, tables
    "control": "#2f2f32",        # buttons
    "control_hover": "#3a3a3e",
    "control_pressed": "#26262a",
    "hairline": "#3a3a3c",       # 1px dividers and borders
    "text": "#e8e8ea",
    "text_dim": "#9a9aa0",       # at least 4.5:1 on panel
    "text_off": "#6a6a70",
    "accent": "#0a84ff",         # graphics: slider fill, focus, check boxes, links
    "selection": "#0a70e0",      # surfaces that carry white text (4.5:1): menus, rows, checked buttons
    "accent_hover": "#3a9bff",
    "on_accent": "#ffffff",
    "danger": "#ff6b6b",
    "positive": "#30d158",
    "radius": "6px",
    "radius_panel": "8px",
}


def color(name):
    """A token as a QColor."""
    return QColor(TOKENS[name])


def monospace_font(point_size=None):
    """A fixed-width font that exists on the platform, for readouts and the console."""
    font = QFont()
    font.setFamilies(["SF Mono", "Menlo", "Consolas", "DejaVu Sans Mono", "monospace"])
    font.setStyleHint(QFont.Monospace)
    font.setFixedPitch(True)
    if point_size:
        font.setPointSize(point_size)
    return font


def build_palette():
    palette = QPalette()
    roles = {
        QPalette.Window: "window",
        QPalette.WindowText: "text",
        QPalette.Base: "field",
        QPalette.AlternateBase: "panel",
        QPalette.ToolTipBase: "control",
        QPalette.ToolTipText: "text",
        QPalette.Text: "text",
        QPalette.Button: "control",
        QPalette.ButtonText: "text",
        QPalette.BrightText: "on_accent",
        QPalette.Highlight: "selection",
        QPalette.HighlightedText: "on_accent",
        QPalette.Link: "accent_hover",
        QPalette.PlaceholderText: "text_dim",
        QPalette.Light: "control_hover",
        QPalette.Midlight: "control_hover",
        QPalette.Mid: "hairline",
        QPalette.Dark: "canvas",
        QPalette.Shadow: "canvas",
    }
    for role, token in roles.items():
        palette.setColor(role, color(token))

    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        palette.setColor(QPalette.Disabled, role, color("text_off"))
    palette.setColor(QPalette.Disabled, QPalette.Button, color("panel"))
    palette.setColor(QPalette.Disabled, QPalette.Highlight, color("control_hover"))
    palette.setColor(QPalette.Disabled, QPalette.HighlightedText, color("text_off"))
    return palette


STYLESHEET = Template("""
QToolTip {
    background: $control; color: $text;
    border: 1px solid $hairline; padding: 4px 6px;
}

/* ---- menus ---- */
QMenuBar { background: $window; color: $text; }
QMenuBar::item { padding: 4px 10px; background: transparent; border-radius: 4px; }
QMenuBar::item:selected { background: $control_hover; }
QMenu {
    background: $panel; color: $text;
    border: 1px solid $hairline; border-radius: $radius; padding: 4px;
}
QMenu::item { padding: 5px 24px 5px 12px; border-radius: 4px; }
QMenu::item:selected { background: $selection; color: $on_accent; }
QMenu::item:disabled { color: $text_off; }
QMenu::separator { height: 1px; background: $hairline; margin: 4px 8px; }

/* ---- buttons ---- */
QPushButton {
    background: $control; color: $text;
    border: 1px solid $hairline; border-radius: $radius;
    padding: 4px 8px; min-height: 18px;
    qproperty-iconSize: 18px 18px;
}
QPushButton:hover { background: $control_hover; }
QPushButton:pressed { background: $control_pressed; }
QPushButton:checked { background: $selection; border-color: $selection; color: $on_accent; }
QPushButton:default { border-color: $accent; }
QPushButton:disabled { background: $panel; color: $text_off; border-color: $control; }

/* keyboard focus rings (see _KeyboardFocus) */
QPushButton[keyboardFocus="true"] { border-color: $accent_hover; }
QPushButton#sectionHeader[keyboardFocus="true"] { background: $control_pressed; color: $accent_hover; }
QCheckBox[keyboardFocus="true"]::indicator { border-color: $accent_hover; }

/* ---- text inputs ---- */
QLineEdit, QTextEdit, QPlainTextEdit {
    background: $field; color: $text;
    border: 1px solid $hairline; border-radius: $radius;
    padding: 3px 6px;
    selection-background-color: $selection; selection-color: $on_accent;
}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus { border-color: $accent; }
QLineEdit:disabled { color: $text_off; background: $panel; }

/* ---- check boxes ---- */
QCheckBox { spacing: 8px; }
QCheckBox::indicator {
    width: 16px; height: 16px;
    border: 1px solid $text_off; border-radius: 4px; background: $field;
}
QCheckBox::indicator:hover { border-color: $text_dim; }
QCheckBox::indicator:checked {
    background: $accent; border-color: $accent;
    image: url("$icon_dir/indicator-check.svg");
}
QCheckBox::indicator:disabled { border-color: $control_hover; background: $panel; }
QCheckBox::indicator:checked:disabled { background: $control_hover; border-color: $control_hover; }

/* ---- group boxes: flat sections (replaced by collapsible sections later) ---- */
QGroupBox {
    background: transparent;
    border: 1px solid $hairline; border-radius: $radius_panel;
    margin-top: 14px; padding: 8px 6px 6px 6px;
}
QGroupBox::title {
    subcontrol-origin: margin; subcontrol-position: top left;
    left: 8px; padding: 0 4px; color: $text; font-weight: 600;
}

/* ---- viewer and transport ---- */
QGraphicsView { background: $canvas; border: 0; }
QLabel#caption { color: $text_dim; }
QLabel#frameReadout {
    background: $field; border: 1px solid $hairline; border-radius: 4px;
    padding: 2px 8px; min-width: 52px;
}
QSlider#timeline { min-height: 26px; }
QSlider#timeline::groove:horizontal { height: 6px; background: transparent; border-radius: 0; }
QSlider#timeline::sub-page:horizontal { background: transparent; }
QSlider#timeline::handle:horizontal {
    width: 6px; height: 20px; margin: -7px 0; background: $text; border-radius: 3px;
}
QSlider#timeline::handle:horizontal:hover { background: $on_accent; }

/* ---- panels and status bar ---- */
QLabel#panelTitle { color: $text; font-weight: 600; padding: 4px 2px; }

/* ---- hint blocks (usage notes in the sidebar) ---- */
QLabel#hint {
    background: $panel; padding: 10px;
    border: 0; border-radius: $radius_panel; font-size: 12px;
}

/* ---- sidebar sections ---- */
QFrame#collapsibleGroup { background: transparent; border: 0; border-bottom: 1px solid $hairline; }
QWidget#sectionBody { background: transparent; }
QPushButton#sectionHeader, QPushButton#sectionHeader:checked {
    background: transparent; color: $text; border: 0; border-radius: 0;
    font-weight: 600; text-align: left;
    padding: 8px 12px; min-height: 18px;
    qproperty-iconSize: 12px 12px;
}
QPushButton#sectionHeader:hover { background: $control_pressed; }
QPushButton#sectionHeader:pressed { background: $control_pressed; }

/* ---- sliders (the timeline overrides these below) ---- */
QSlider:horizontal { min-height: 20px; }
QSlider::groove:horizontal { height: 4px; background: $control_hover; border-radius: 2px; }
QSlider::sub-page:horizontal { background: $accent; border-radius: 2px; }
QSlider::handle:horizontal {
    background: $text; width: 12px; height: 12px; margin: -4px 0; border-radius: 6px;
}
QSlider::handle:horizontal:hover { background: $on_accent; }
QSlider::sub-page:horizontal:disabled { background: $text_off; }
QLabel#sliderValue {
    color: $text; background: $field;
    border: 1px solid $hairline; border-radius: 4px;
    padding: 1px 6px; min-width: 28px;
}

/* ---- tabs ---- */
QTabWidget::pane { border: 0; border-top: 1px solid $hairline; top: -1px; }
QTabBar::tab {
    background: transparent; color: $text_dim;
    padding: 7px 6px; border: 0; border-bottom: 2px solid transparent;
}
QTabBar::tab:hover { color: $text; }
QTabBar::tab:selected { color: $text; border-bottom: 2px solid $accent; }

/* ---- tables ---- */
QTableView, QTableWidget {
    background: $field; alternate-background-color: $panel;
    border: 1px solid $hairline; border-radius: $radius;
    gridline-color: $hairline;
    selection-background-color: $selection; selection-color: $on_accent;
}
QHeaderView::section {
    background: $panel; color: $text_dim;
    border: 0; border-right: 1px solid $hairline; border-bottom: 1px solid $hairline;
    padding: 4px 6px;
}

/* ---- scroll bars ---- */
QScrollBar:vertical { background: transparent; width: 12px; margin: 0; }
QScrollBar:horizontal { background: transparent; height: 12px; margin: 0; }
QScrollBar::handle:vertical { background: $control_hover; border-radius: 4px; min-height: 28px; margin: 2px; }
QScrollBar::handle:horizontal { background: $control_hover; border-radius: 4px; min-width: 28px; margin: 2px; }
QScrollBar::handle:hover { background: $text_off; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

/* ---- splitters and status bar ---- */
QSplitter::handle { background: $window; }
QSplitter::handle:hover { background: $hairline; }
QStatusBar { background: $window; color: $text_dim; border-top: 1px solid $hairline; }
QStatusBar::item { border: 0; }

QProgressBar {
    background: $field; border: 1px solid $hairline; border-radius: $radius;
    text-align: center; color: $text;
}
QProgressBar::chunk { background: $accent; border-radius: 5px; }
""")


class _KeyboardFocus(QObject):
    """
    Sets the dynamic property `keyboardFocus` on widgets that received focus
    from the keyboard (Tab, Shift+Tab or a shortcut).

    A plain :focus rule can't tell keyboard from mouse, so every button would
    keep a focus ring after being clicked. Styling the property instead rings
    only what keyboard users navigate to.
    """
    KEYBOARD_REASONS = (Qt.TabFocusReason, Qt.BacktabFocusReason, Qt.ShortcutFocusReason)

    def eventFilter(self, obj, event):
        if isinstance(obj, QWidget):
            if event.type() == QEvent.FocusIn:
                self._mark(obj, event.reason() in self.KEYBOARD_REASONS)
            elif event.type() == QEvent.FocusOut:
                self._mark(obj, False)
        return False

    @staticmethod
    def _mark(widget, on):
        if bool(widget.property("keyboardFocus")) != on:
            widget.setProperty("keyboardFocus", on)
            widget.style().unpolish(widget)
            widget.style().polish(widget)


def build_stylesheet():
    return STYLESHEET.substitute(TOKENS, icon_dir=ICON_DIR.as_posix())


def apply_theme(app):
    """Install the dark Fusion theme on a QApplication."""
    app.setStyle("Fusion")
    try:
        # Dark native title bars on Windows 11 and macOS (Qt 6.8+).
        app.styleHints().setColorScheme(Qt.ColorScheme.Dark)
    except AttributeError:
        pass
    app.setPalette(build_palette())
    app.setStyleSheet(build_stylesheet())
    # Parented to the app so it lives as long as it does
    app.installEventFilter(_KeyboardFocus(app))
