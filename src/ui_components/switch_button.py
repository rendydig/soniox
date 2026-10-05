from PySide6.QtCore import Qt, Property, QPropertyAnimation, QEasingCurve, QSize
from PySide6.QtGui import QPainter, QColor
from PySide6.QtWidgets import QAbstractButton


class SwitchButton(QAbstractButton):
    """A small pill-style on/off toggle switch."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._width = 44
        self._height = 24
        self._margin = 3
        self._thumb_radius = (self._height - 2 * self._margin) / 2
        self._off_x = self._margin + self._thumb_radius
        self._on_x = self._width - self._margin - self._thumb_radius
        self._thumb_x = self._off_x
        self.setFixedSize(self._width, self._height)

        self._animation = QPropertyAnimation(self, b"thumb_x", self)
        self._animation.setDuration(150)
        self._animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self.toggled.connect(self._animate)

    def _animate(self, checked):
        self._animation.stop()
        self._animation.setStartValue(self._thumb_x)
        self._animation.setEndValue(self._on_x if checked else self._off_x)
        self._animation.start()

    def sizeHint(self):
        return QSize(self._width, self._height)

    def get_thumb_x(self):
        return self._thumb_x

    def set_thumb_x(self, value):
        self._thumb_x = value
        self.update()

    thumb_x = Property(float, get_thumb_x, set_thumb_x)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)

        track_color = QColor("#34c759") if self.isChecked() else QColor("#c8c8c8")
        painter.setBrush(track_color)
        radius = self._height / 2
        painter.drawRoundedRect(0, 0, self._width, self._height, radius, radius)

        painter.setBrush(QColor("white"))
        diameter = self._thumb_radius * 2
        painter.drawEllipse(int(self._thumb_x - self._thumb_radius),
                            int(self._height / 2 - self._thumb_radius),
                            int(diameter), int(diameter))
