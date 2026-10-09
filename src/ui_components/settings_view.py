from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QComboBox, QCheckBox, QPushButton, QKeySequenceEdit)
from PySide6.QtCore import Signal
from src.purposes import PURPOSES, DEFAULT_PURPOSE
from .device_settings import DeviceSettingsWidget
from .language_selection import LanguageSelectionWidget

# Global-hotkey editors: (action name as persisted, field label). The action
# names must match ``src.global_hotkeys.HOTKEY_ACTIONS``.
_HOTKEY_FIELDS = (
    ("screenshot", "Screenshot:"),
    ("clear_screenshots", "Clear screenshots:"),
    ("send_images", "Send screenshots to AI:"),
    ("bullet_points", "Bullet points update:"),
)


class SettingsViewWidget(QWidget):
    back_requested = Signal()
    # Emitted when the user finishes editing a global-hotkey field.
    hotkeys_changed = Signal()

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

        view_mode_row = QHBoxLayout()
        view_mode_label = QLabel("View mode:")
        self.view_mode_combo = QComboBox()
        self.view_mode_combo.addItem("Text Editor")
        self.view_mode_combo.addItem("Webview")
        self.view_mode_combo.setCurrentIndex(1)
        self.view_mode_combo.setToolTip("Switch between text editor and webview")
        view_mode_row.addWidget(view_mode_label)
        view_mode_row.addWidget(self.view_mode_combo)
        view_mode_row.addStretch()
        layout.addLayout(view_mode_row)

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
        self.purpose_combo.setToolTip("Persona used for the AI auto-reply.")
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

        self.bullet_points_checkbox = QCheckBox("Auto Bullet Points")
        self.bullet_points_checkbox.setChecked(False)
        self.bullet_points_checkbox.setToolTip(
            "Automatically update a running bullet-point list of the conversation "
            "(every 15s / 12 lines). Off = update on demand with CTRL+ALT+P while "
            "the pane is open. Hiding the pane pauses auto updates."
        )
        layout.addWidget(self.bullet_points_checkbox)

        self.screen_protection_checkbox = QCheckBox("Screen Protection")
        self.screen_protection_checkbox.setChecked(True)
        self.screen_protection_checkbox.setToolTip(
            "Hide this window from screen capture while keeping it visible on the monitor."
        )
        layout.addWidget(self.screen_protection_checkbox)

        hotkeys_label = QLabel("Global Hotkeys")
        hotkeys_font = hotkeys_label.font()
        if hotkeys_font.pointSize() > 0:
            hotkeys_font.setPointSize(hotkeys_font.pointSize() + 1)
        hotkeys_font.setBold(True)
        hotkeys_label.setFont(hotkeys_font)
        layout.addWidget(hotkeys_label)

        self.hotkey_editors = {}
        for action, label_text in _HOTKEY_FIELDS:
            hotkey_row = QHBoxLayout()
            hotkey_row.addWidget(QLabel(label_text))
            editor = QKeySequenceEdit()
            editor.setMaximumSequenceLength(1)
            editor.setToolTip(
                "Click and press a new combination (e.g. Ctrl+Alt+P). "
                "It takes effect immediately and is remembered on restart."
            )
            editor.editingFinished.connect(self.hotkeys_changed.emit)
            hotkey_row.addWidget(editor)
            hotkey_row.addStretch()
            layout.addLayout(hotkey_row)
            self.hotkey_editors[action] = editor

        layout.addStretch()

    def get_device_combo(self):
        return self.device_settings.get_device_combo()

    def get_speaker_combo(self):
        return self.device_settings.get_speaker_combo()

    def get_language_selection(self):
        return self.language_selection

    def get_view_mode_combo(self):
        return self.view_mode_combo

    def get_gemini_lang_combo(self):
        return self.gemini_lang_combo

    def get_purpose_combo(self):
        return self.purpose_combo

    def get_pronunciation_checkbox(self):
        return self.pronunciation_checkbox

    def get_bullet_points_checkbox(self):
        return self.bullet_points_checkbox

    def get_screen_protection_checkbox(self):
        return self.screen_protection_checkbox

    def get_hotkey_editors(self):
        """Return the ``{action_name: QKeySequenceEdit}`` mapping."""
        return self.hotkey_editors
