"""A painted microphone glyph for the control bar's mute toggle.

Drawn with ``QPainter`` (no shipped asset): crisp at any device-pixel ratio and
independent of the image-format plugins, matching the other painted widgets
(``switch_button.py``, ``drag_handle.py``). Live is a filled capsule; muted is
the same shape outlined, with a red diagonal slash so the state is unmistakable
even at 16 px.
"""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap

# The glyph is designed in a 24x24 box and scaled to the requested size.
_VIEWBOX = 24.0
_GLYPH_COLOR = "#4b5563"   # grey, matching the pane-control glyphs
_MUTED_COLOR = "#dc2626"   # red slash, matching the app's error accent


def mic_icon(muted: bool = False, size: int = 18, ratio: float = 2.0) -> QIcon:
    """A mic glyph: filled when live, outlined + red slash when muted.

    ``size`` is the logical (device-independent) side length and ``ratio`` the
    device-pixel ratio, so the rendered pixmap stays sharp on HiDPI screens.
    """
    ratio = max(1.0, float(ratio))
    side = max(1, int(round(size * ratio)))
    pixmap = QPixmap(side, side)
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(size / _VIEWBOX, size / _VIEWBOX)

        glyph = QColor(_GLYPH_COLOR)
        pen = QPen(glyph)
        pen.setWidthF(2.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)

        body = QRectF(9.0, 3.0, 6.0, 11.0)     # capsule
        cradle = QRectF(6.0, 7.0, 12.0, 11.0)  # arc bounding box

        # Capsule: filled when live, outlined when muted.
        if muted:
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
        else:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(glyph)
        painter.drawRoundedRect(body, 3.0, 3.0)

        # Cradle arc + stem + base, stroked in both states.
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawArc(cradle, 180 * 16, 180 * 16)  # left -> bottom -> right
        painter.drawLine(QPointF(12.0, 18.0), QPointF(12.0, 21.0))
        painter.drawLine(QPointF(8.0, 21.0), QPointF(16.0, 21.0))

        if muted:
            slash = QPen(QColor(_MUTED_COLOR))
            slash.setWidthF(2.2)
            slash.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(slash)
            painter.drawLine(QPointF(4.5, 19.5), QPointF(19.5, 4.5))
    finally:
        painter.end()

    return QIcon(pixmap)
