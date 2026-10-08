from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, 
                             QLabel, QComboBox)

from src.config import IS_MACOS


class DeviceSettingsWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()
    
    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        
        dev_layout = QHBoxLayout()
        
        user_layout = QVBoxLayout()
        user_layout.addWidget(QLabel("Input Device (Microphone):" if IS_MACOS else "Input Device (Host):"))
        self.device_combo = QComboBox()
        self.device_combo.setMinimumWidth(180)
        user_layout.addWidget(self.device_combo)
        dev_layout.addLayout(user_layout, 1)
        
        speaker_layout = QVBoxLayout()
        speaker_layout.addWidget(QLabel("System Audio (BlackHole):" if IS_MACOS else "Speaker Output (Loopback):"))
        self.speaker_combo = QComboBox()
        self.speaker_combo.setMinimumWidth(180)
        speaker_layout.addWidget(self.speaker_combo)
        dev_layout.addLayout(speaker_layout, 1)
        
        layout.addLayout(dev_layout)
        
        # macOS has no loopback API, so system audio only flows through a virtual
        # input device the user sets up themselves.
        self.speaker_hint = QLabel(
            "Captures audio played by other apps. Requires a virtual input device "
            "such as BlackHole — create a Multi-Output Device that includes it and "
            "select that as your system output so playback stays audible."
        )
        self.speaker_hint.setWordWrap(True)
        self.speaker_hint.setVisible(IS_MACOS)
        layout.addWidget(self.speaker_hint)
    
    def get_device_combo(self):
        return self.device_combo
    
    def get_speaker_combo(self):
        return self.speaker_combo
