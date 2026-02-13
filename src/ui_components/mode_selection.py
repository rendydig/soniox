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
        layout.setSpacing(12)
        
        mode_layout = QHBoxLayout()
        mode_layout.addWidget(QLabel("Mode:"))
        
        self.mode_group = QButtonGroup(self)
        self.rb_transcribe = QRadioButton("Live Transcription")
        self.rb_translate = QRadioButton("Live Translation")
        self.rb_transcribe.setChecked(True)
        
        self.mode_group.addButton(self.rb_transcribe)
        self.mode_group.addButton(self.rb_translate)
        
        mode_layout.addWidget(self.rb_transcribe)
        mode_layout.addWidget(self.rb_translate)
        mode_layout.addStretch()
        layout.addLayout(mode_layout)
        
        self.lang_container = QWidget()
        lang_layout = QHBoxLayout(self.lang_container)
        lang_layout.setContentsMargins(0, 0, 0, 0)
        
        self.lang_combo = QComboBox()
        for name, code in LANGUAGES.items():
            self.lang_combo.addItem(name, code)
        self.lang_combo.setCurrentText("Indonesian")
        
        lang_layout.addWidget(QLabel("Target Language:"))
        lang_layout.addWidget(self.lang_combo, 1)
        
        layout.addWidget(self.lang_container)
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
