from PySide6.QtCore import Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QLabel, QSizePolicy


class ElidedLabel(QLabel):
    """A label that shrinks with an ellipsis instead of forcing its parent wider.

    Its horizontal size policy is ``Ignored`` so the layout may give it less than
    its full text width; the visible text is re-elided to the current width.
    """

    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self._full_text = text
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        super().setText(text)

    def setText(self, text):
        self._full_text = text
        self._update_elided()

    def fullText(self):
        return self._full_text

    def _update_elided(self):
        metrics = QFontMetrics(self.font())
        elided = metrics.elidedText(self._full_text, Qt.TextElideMode.ElideRight, max(self.width(), 0))
        super().setText(elided)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_elided()
