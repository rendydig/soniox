from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget


class PaneResizeHandle(QWidget):
    """A thin grip on a side pane's inner edge that resizes its width when dragged.

    It is a sibling of the pane's content (a ``QWebEngineView``), which consumes
    mouse events, so the handle must live in the layout rather than overlay it.
    Drags are delegated to the parent window (see ``GeminiWindow`` /
    ``LiveWindow``), mirroring how ``DragHandle`` drives its window.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(6)
        self.setCursor(Qt.CursorShape.SizeHorCursor)
        self.setToolTip("Drag to resize")
        self._start_x = None
        self._start_width = 0
        self._hover = False

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._start_x = event.globalPosition().x()
            self._start_width = self.window().get_width()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._start_x is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.window().resize_by_drag(event.globalPosition().x() - self._start_x, self._start_width)
            event.accept()

    def mouseReleaseEvent(self, event):
        if self._start_x is not None:
            self._start_x = None
            self.window().finish_resize()
            event.accept()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
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
