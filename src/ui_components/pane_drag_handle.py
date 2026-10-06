from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget


class PaneDragHandle(QWidget):
    """A thin strip along a pane's top edge that moves the frameless window.

    The pane's content (a ``QWebEngineView``) consumes mouse events, so the
    handle is a sibling widget in the layout rather than an overlay. Drags are
    delegated to the parent window (see ``GeminiWindow`` / ``LiveWindow``),
    mirroring how ``DragHandle`` moves the bottom bar.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(12)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip("Drag to move the pane")
        self._offset = None
        self._hover = False

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._offset = event.globalPosition().toPoint() - self.window().frameGeometry().topLeft()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()

    def mouseMoveEvent(self, event):
        if self._offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.window().move_to(event.globalPosition().toPoint() - self._offset)
            event.accept()

    def mouseReleaseEvent(self, event):
        if self._offset is not None:
            self._offset = None
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            self.window().finish_move()
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
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(102, 126, 234, 60) if self._hover else QColor(0, 0, 0, 12))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#9a9a9a"))
        cx = self.width() // 2
        cy = self.height() // 2
        for i in (-8, 0, 8):
            painter.drawEllipse(cx + i - 1, cy - 1, 3, 3)
