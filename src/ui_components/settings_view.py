from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QComboBox, QCheckBox, QPushButton, QKeySequenceEdit)
from PySide6.QtCore import Signal
from src.purposes import BUILTIN_PURPOSES, DEFAULT_PURPOSE
from .device_settings import DeviceSettingsWidget
from .language_selection import LanguageSelectionWidget

# Global-hotkey editors: (action name as persisted, field label). The action
# names must match ``src.global_hotkeys.HOTKEY_ACTIONS``.
_HOTKEY_FIELDS = (
    ("screenshot", "Screenshot:"),
    ("clear_screenshots", "Clear screenshots:"),
    ("send_images", "Send screenshots to AI:"),
    ("bullet_points", "Bullet points update:"),
    ("toggle_windows", "Hide/Show all windows:"),
)


class SettingsViewWidget(QWidget):
    back_requested = Signal()
    # Emitted when the user finishes editing a global-hotkey field.
    hotkeys_changed = Signal()

    def __init__(self, purpose_store=None, parent=None):
        super().__init__(parent)
        # The store is the source of truth (built-ins + user edits + AI-learned
        # purposes); without one we fall back to the built-in seed.
        self._purpose_store = purpose_store
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
        if self._purpose_store is not None:
            for key, label in self._purpose_store.labels():
                self.purpose_combo.addItem(label, key)
        else:
            for key, purpose in BUILTIN_PURPOSES.items():
                self.purpose_combo.addItem(purpose["label"], key)
        default_index = self.purpose_combo.findData(DEFAULT_PURPOSE)
        if default_index >= 0:
            self.purpose_combo.setCurrentIndex(default_index)
        self.purpose_combo.setToolTip("Persona used for the AI auto-reply.")
        purpose_row.addWidget(purpose_label)
        purpose_row.addWidget(self.purpose_combo)
        purpose_row.addStretch()
        layout.addLayout(purpose_row)

        host_role_row = QHBoxLayout()
        host_role_label = QLabel("I am:")
        self.host_role_combo = QComboBox()
        self.host_role_combo.addItem("Smart (auto)", "smart")
        self.host_role_combo.setMinimumWidth(150)
        self.host_role_combo.setToolTip(
            "Who you (the Host) are in this conversation. Smart lets the AI decide."
        )
        host_role_row.addWidget(host_role_label)
        host_role_row.addWidget(self.host_role_combo)
        host_role_row.addStretch()
        layout.addLayout(host_role_row)

        self.smart_decision_checkbox = QCheckBox("Smart Decision (JEV)")
        # Default on; a no-op unless JEV is enabled + keyed in .env.
        self.smart_decision_checkbox.setChecked(True)
        self.smart_decision_checkbox.setToolTip(
            "Let a fast decision model decide whether to reply, as whom, and which "
            "speech act to use before the AI writes the reply."
        )
        layout.addWidget(self.smart_decision_checkbox)

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

    def get_host_role_combo(self):
        return self.host_role_combo

    def get_smart_decision_checkbox(self):
        return self.smart_decision_checkbox

    def populate_host_roles(self, roles, remembered="smart"):
        """Refill the ``I am:`` combo from a purpose's roles.

        A single-role purpose shows only ``Smart (auto)`` and is disabled (there
        is nothing to choose). ``remembered`` is restored when it still exists.
        """
        was_blocked = self.host_role_combo.blockSignals(True)
        self.host_role_combo.clear()
        self.host_role_combo.addItem("Smart (auto)", "smart")
        role_items = list((roles or {}).items())
        if len(role_items) > 1:
            for key, role in role_items:
                self.host_role_combo.addItem(role.get("label", key), key)
            self.host_role_combo.setEnabled(True)
        else:
            self.host_role_combo.setEnabled(False)
            remembered = "smart"
        index = self.host_role_combo.findData(remembered)
        self.host_role_combo.setCurrentIndex(index if index >= 0 else 0)
        self.host_role_combo.blockSignals(was_blocked)

    def get_pronunciation_checkbox(self):
        return self.pronunciation_checkbox

    def get_bullet_points_checkbox(self):
        return self.bullet_points_checkbox

    def get_screen_protection_checkbox(self):
        return self.screen_protection_checkbox

    def get_hotkey_editors(self):
        """Return the ``{action_name: QKeySequenceEdit}`` mapping."""
        return self.hotkey_editors
