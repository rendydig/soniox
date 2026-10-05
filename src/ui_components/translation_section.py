from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit)
from .switch_button import SwitchButton


class TranslationSectionWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()
    
    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        
        # translation_section_label = QLabel("Gemini Translation:")
        # layout.addWidget(translation_section_label)
        
        header = QHBoxLayout()
        input_label = QLabel("Text to Translate (Press Ctrl+Enter to submit):")
        header.addWidget(input_label)
        header.addStretch()
        self.manual_switch = SwitchButton()
        self.manual_switch.setChecked(True)
        self.manual_switch.setToolTip("Show or hide the manual translation input.")
        header.addWidget(self.manual_switch)
        layout.addLayout(header)
        
        self.translation_input = QTextEdit()
        self.translation_input.setPlaceholderText("Type text to translate and press Ctrl+Enter...")
        self.translation_input.setMinimumHeight(80)
        layout.addWidget(self.translation_input)
        
        self.manual_switch.toggled.connect(self.translation_input.setVisible)
    
    def get_translation_input(self):
        return self.translation_input
    
    def get_manual_switch(self):
        return self.manual_switch
