from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget


class DragHandle(QWidget):
    """A small grip that lets the user drag the frameless bottom bar around."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(18)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip("Drag to move the bar")
        self._offset = None

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._offset = event.globalPosition().toPoint() - self.window().frameGeometry().topLeft()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()

    def mouseMoveEvent(self, event):
        if self._offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.window().move(event.globalPosition().toPoint() - self._offset)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._offset = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        event.accept()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#9a9a9a"))
        cx = self.width() // 2
        cy = self.height() // 2
        for i in (-6, 0, 6):
            painter.drawEllipse(cx - 1, cy + i - 1, 3, 3)
