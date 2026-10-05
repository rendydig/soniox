from PySide6.QtWidgets import (QWidget, QVBoxLayout, QLabel, QTextEdit)


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
        
        input_label = QLabel("Text to Translate (Press Ctrl+Enter to submit):")
        layout.addWidget(input_label)
        
        self.translation_input = QTextEdit()
        self.translation_input.setPlaceholderText("Type text to translate and press Ctrl+Enter...")
        self.translation_input.setMinimumHeight(80)
        layout.addWidget(self.translation_input)
    
    def get_translation_input(self):
        return self.translation_input
