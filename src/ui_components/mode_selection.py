from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, 
                             QLabel, QComboBox, QRadioButton, QButtonGroup)
from src.config import LANGUAGES


class ModeSelectionWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()
    
    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        
        layout.addWidget(QLabel("Mode:"))
        
        self.mode_group = QButtonGroup(self)
        self.rb_transcribe = QRadioButton("Live Transcription")
        self.rb_translate = QRadioButton("Live Translation")
        self.rb_transcribe.setChecked(True)
        
        self.mode_group.addButton(self.rb_transcribe)
        self.mode_group.addButton(self.rb_translate)
        
        radio_layout = QHBoxLayout()
        radio_layout.setContentsMargins(0, 0, 0, 0)
        radio_layout.addWidget(self.rb_transcribe)
        radio_layout.addWidget(self.rb_translate)
        radio_layout.addStretch()
        layout.addLayout(radio_layout)
        layout.addStretch()

        self.lang_container = QWidget()
        lang_layout = QVBoxLayout(self.lang_container)
        lang_layout.setContentsMargins(0, 0, 0, 0)
        lang_layout.setSpacing(4)
        
        self.lang_combo = QComboBox()
        for name, code in LANGUAGES.items():
            self.lang_combo.addItem(name, code)
        self.lang_combo.setCurrentText("Indonesian")
        
        lang_layout.addWidget(QLabel("Target Language:"))
        lang_layout.addWidget(self.lang_combo)
        lang_layout.addStretch()
        
        self.lang_container.setVisible(False)
    
    def get_mode_group(self):
        return self.mode_group
    
    def get_transcribe_radio(self):
        return self.rb_transcribe
    
    def get_translate_radio(self):
        return self.rb_translate
    
    def get_lang_container(self):
        return self.lang_container
    
    def get_lang_combo(self):
        return self.lang_combo
