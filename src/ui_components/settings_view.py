from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QComboBox, QCheckBox, QPushButton)
from PySide6.QtCore import Signal
from src.purposes import PURPOSES, DEFAULT_PURPOSE
from .device_settings import DeviceSettingsWidget
from .language_selection import LanguageSelectionWidget


class SettingsViewWidget(QWidget):
    back_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        header = QHBoxLayout()
        title = QLabel("Settings")
        font = title.font()
        if font.pointSize() > 0:
            font.setPointSize(font.pointSize() + 2)
        title.setFont(font)
        header.addWidget(title)
        header.addStretch()
        self.back_button = QPushButton("Back")
        self.back_button.clicked.connect(self.back_requested.emit)
        header.addWidget(self.back_button)
        layout.addLayout(header)

        self.device_settings = DeviceSettingsWidget()
        layout.addWidget(self.device_settings)

        self.language_selection = LanguageSelectionWidget()
        layout.addWidget(self.language_selection)

        gemini_lang_row = QHBoxLayout()
        gemini_lang_label = QLabel("AI Reply Language:")
        self.gemini_lang_combo = QComboBox()
        self.gemini_lang_combo.addItems(["English", "Arabic", "Japanese", "Chinese", "Korean"])
        self.gemini_lang_combo.setMinimumWidth(150)
        gemini_lang_row.addWidget(gemini_lang_label)
        gemini_lang_row.addWidget(self.gemini_lang_combo)
        gemini_lang_row.addStretch()
        layout.addLayout(gemini_lang_row)

        purpose_row = QHBoxLayout()
        purpose_label = QLabel("Purpose:")
        self.purpose_combo = QComboBox()
        for key, purpose in PURPOSES.items():
            self.purpose_combo.addItem(purpose["label"], key)
        default_index = self.purpose_combo.findData(DEFAULT_PURPOSE)
        if default_index >= 0:
            self.purpose_combo.setCurrentIndex(default_index)
        self.purpose_combo.setToolTip("Persona used for the Gemini auto-reply.")
        purpose_row.addWidget(purpose_label)
        purpose_row.addWidget(self.purpose_combo)
        purpose_row.addStretch()
        layout.addLayout(purpose_row)

        self.pronunciation_checkbox = QCheckBox("Pronunciation")
        self.pronunciation_checkbox.setChecked(False)
        self.pronunciation_checkbox.setToolTip(
            "Include syllables/pronunciation and English translation in the auto-reply. "
            "Off = answer in the target language only."
        )
        layout.addWidget(self.pronunciation_checkbox)

        self.screen_protection_checkbox = QCheckBox("Screen Protection")
        self.screen_protection_checkbox.setChecked(True)
        self.screen_protection_checkbox.setToolTip(
            "Hide this window from screen capture while keeping it visible on the monitor."
        )
        layout.addWidget(self.screen_protection_checkbox)

        layout.addStretch()

    def get_device_combo(self):
        return self.device_settings.get_device_combo()

    def get_speaker_combo(self):
        return self.device_settings.get_speaker_combo()

    def get_language_selection(self):
        return self.language_selection

    def get_gemini_lang_combo(self):
        return self.gemini_lang_combo

    def get_purpose_combo(self):
        return self.purpose_combo

    def get_pronunciation_checkbox(self):
        return self.pronunciation_checkbox

    def get_screen_protection_checkbox(self):
        return self.screen_protection_checkbox
