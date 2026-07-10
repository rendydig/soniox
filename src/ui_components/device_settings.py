from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, 
                             QLabel, QComboBox)


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
        user_layout.addWidget(QLabel("Input Device (Host):"))
        self.device_combo = QComboBox()
        self.device_combo.setMinimumWidth(180)
        user_layout.addWidget(self.device_combo)
        dev_layout.addLayout(user_layout, 1)
        
        speaker_layout = QVBoxLayout()
        speaker_layout.addWidget(QLabel("Input Device (Speaker):"))
        self.speaker_combo = QComboBox()
        self.speaker_combo.setMinimumWidth(180)
        speaker_layout.addWidget(self.speaker_combo)
        dev_layout.addLayout(speaker_layout, 1)
        
        layout.addLayout(dev_layout)
    
    def get_device_combo(self):
        return self.device_combo
    
    def get_speaker_combo(self):
        return self.speaker_combo
