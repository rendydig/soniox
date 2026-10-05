from PySide6.QtWidgets import (QWidget, QVBoxLayout, QLabel, QComboBox)
from src.config import LANGUAGES


class LanguageSelectionWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.lang_combo = QComboBox()
        for name, code in LANGUAGES.items():
            self.lang_combo.addItem(name, code)
        self.lang_combo.setCurrentText("Indonesian")

        layout.addWidget(QLabel("Speech Translation Target:"))
        layout.addWidget(self.lang_combo)
        layout.addStretch()

        self.setVisible(False)

    def get_lang_combo(self):
        return self.lang_combo
