from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, 
                             QLabel, QComboBox, QPushButton, QLineEdit, QCheckBox)


class DeviceSettingsWidget(QWidget):
    def __init__(self, recording_controller, parent=None):
        super().__init__(parent)
        self.recording_controller = recording_controller
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
        
        dest_row = QHBoxLayout()
        dest_label = QLabel("Destination Folder:")
        self.dest_edit = QLineEdit(self.recording_controller.get_base_dir())
        self.dest_edit.setReadOnly(True)
        self.browse_btn = QPushButton("Change...")
        dest_row.addWidget(dest_label)
        dest_row.addWidget(self.dest_edit, 1)
        dest_row.addWidget(self.browse_btn)
        layout.addLayout(dest_row)
        
        self.auto_record_checkbox = QCheckBox("Auto-record to WAV when transcribing/translating")
        self.auto_record_checkbox.setChecked(False)
        layout.addWidget(self.auto_record_checkbox)
    
    def get_device_combo(self):
        return self.device_combo
    
    def get_speaker_combo(self):
        return self.speaker_combo
    
    def get_dest_edit(self):
        return self.dest_edit
    
    def get_browse_button(self):
        return self.browse_btn
    
    def get_auto_record_checkbox(self):
        return self.auto_record_checkbox
