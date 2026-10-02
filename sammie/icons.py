"""
Interface icons, drawn from the SVG files in sammie/resources/icons and
tinted to match the theme.

The SVGs use `currentColor`, so one file serves every state: the colour is
swapped in when the icon is rendered. Pixmaps are rendered at several sizes
so Qt can pick a sharp one at any display scaling.

    button.setIcon(icons.icon("play"))
    item.setIcon(icons.icon("plus", color="positive"))
"""
from functools import lru_cache

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from sammie import theme

# Pixel sizes to render; Qt scales the nearest one for the requested size.
_SIZES = (16, 24, 32, 48)


def _hex(color):
    """A theme token name or a literal colour, as a hex string."""
    return theme.TOKENS.get(color, color)


def _pixmap(name, size, color):
    path = theme.ICON_DIR / f"{name}.svg"
    svg = path.read_bytes().replace(b"currentColor", _hex(color).encode())
    renderer = QSvgRenderer(QByteArray(svg))
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return pixmap


@lru_cache(maxsize=None)
def icon(name, color="text", checked_color="on_accent"):
    """
    Build a QIcon from resources/icons/<name>.svg.

    color          colour when enabled (a theme token name or a hex string)
    checked_color  colour on a checked button, which has an accent background
    Disabled icons are dimmed; icons on a selected row use the on-accent colour.
    """
    result = QIcon()
    for size in _SIZES:
        result.addPixmap(_pixmap(name, size, color), QIcon.Normal, QIcon.Off)
        result.addPixmap(_pixmap(name, size, checked_color), QIcon.Normal, QIcon.On)
        result.addPixmap(_pixmap(name, size, "text_off"), QIcon.Disabled, QIcon.Off)
        result.addPixmap(_pixmap(name, size, "text_off"), QIcon.Disabled, QIcon.On)
        result.addPixmap(_pixmap(name, size, "on_accent"), QIcon.Selected, QIcon.Off)
        result.addPixmap(_pixmap(name, size, "on_accent"), QIcon.Selected, QIcon.On)
    return result
