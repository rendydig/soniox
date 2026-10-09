from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget

# Thickness of the straight edge strips and the square corner grips. Uniform so
# the border has no dead zones where a corner out-sizes a neighbouring edge.
EDGE_THICKNESS = 12
CORNER_SIZE = 12


class PaneEdgeHandle(QWidget):
    """A border grip that resizes a frameless pane from any edge or corner.

    ``direction`` is one of ``left``, ``right``, ``top``, ``bottom`` or a
    corner (``top-left``, ``top-right``, ``bottom-left``, ``bottom-right``).
    Straight edges are thin strips; corners are small squares so both axes can
    be dragged at once. It is a sibling of the pane's content (a
    ``QWebEngineView``), which consumes mouse events, so the handle must live in
    the layout rather than overlay it. Drags are delegated to the parent window
    (see ``GeminiWindow`` / ``LiveWindow`` / ``BulletPointsWindow``).
    """

    _CURSORS = {
        "left": Qt.CursorShape.SizeHorCursor,
        "right": Qt.CursorShape.SizeHorCursor,
        "top": Qt.CursorShape.SizeVerCursor,
        "bottom": Qt.CursorShape.SizeVerCursor,
        "top-left": Qt.CursorShape.SizeFDiagCursor,
        "bottom-right": Qt.CursorShape.SizeFDiagCursor,
        "top-right": Qt.CursorShape.SizeBDiagCursor,
        "bottom-left": Qt.CursorShape.SizeBDiagCursor,
    }

    def __init__(self, parent=None, direction="right"):
        super().__init__(parent)
        self._direction = direction
        self.setCursor(self._CURSORS.get(direction, Qt.CursorShape.ArrowCursor))
        self.setToolTip("Drag to resize")
        if "-" in direction:
            self.setFixedSize(CORNER_SIZE, CORNER_SIZE)
        elif direction in ("left", "right"):
            self.setFixedWidth(EDGE_THICKNESS)
        else:
            self.setFixedHeight(EDGE_THICKNESS)
        self._active = False
        self._hover = False

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._active = True
            self.window().begin_edge_resize(
                self._direction, event.globalPosition().toPoint()
            )
            event.accept()

    def mouseMoveEvent(self, event):
        if self._active and event.buttons() & Qt.MouseButton.LeftButton:
            self.window().perform_edge_resize(event.globalPosition().toPoint())
            event.accept()

    def mouseReleaseEvent(self, event):
        if self._active:
            self._active = False
            self.window().end_edge_resize()
            event.accept()

    def enterEvent(self, event):
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        color = QColor(102, 126, 234, 90) if self._hover else QColor(0, 0, 0, 10)
        painter.fillRect(self.rect(), color)
