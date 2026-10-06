from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget


class PaneResizeHandle(QWidget):
    """A thin grip on a side pane's edge that resizes it when dragged.

    ``orientation="horizontal"`` is a vertical strip on the pane's inner edge
    that resizes the width; ``orientation="vertical"`` is a horizontal strip on
    the pane's bottom edge that resizes the height. It is a sibling of the
    pane's content (a ``QWebEngineView``), which consumes mouse events, so the
    handle must live in the layout rather than overlay it. Drags are delegated
    to the parent window (see ``GeminiWindow`` / ``LiveWindow``), mirroring how
    ``DragHandle`` drives its window.
    """

    def __init__(self, parent=None, orientation="horizontal"):
        super().__init__(parent)
        self._orientation = orientation
        if orientation == "vertical":
            self.setFixedHeight(6)
            self.setCursor(Qt.CursorShape.SizeVerCursor)
        else:
            self.setFixedWidth(6)
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        self.setToolTip("Drag to resize")
        self._start = None
        self._start_size = 0
        self._hover = False

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._start = event.globalPosition()
            if self._orientation == "vertical":
                self._start_size = self.window().get_height()
            else:
                self._start_size = self.window().get_width()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._start is not None and event.buttons() & Qt.MouseButton.LeftButton:
            pos = event.globalPosition()
            if self._orientation == "vertical":
                self.window().resize_height_by_drag(pos.y() - self._start.y(), self._start_size)
            else:
                self.window().resize_by_drag(pos.x() - self._start.x(), self._start_size)
            event.accept()

    def mouseReleaseEvent(self, event):
        if self._start is not None:
            self._start = None
            self.window().finish_resize()
            event.accept()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self._orientation == "vertical":
                self.window().reset_height()
            else:
                self.window().reset_width()
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
