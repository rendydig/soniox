from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, 
                             QLabel, QComboBox, QTextEdit)


class TranslationSectionWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()
    
    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        
        translation_section_label = QLabel("Gemini Translation:")
        layout.addWidget(translation_section_label)
        
        gemini_lang_row = QHBoxLayout()
        gemini_lang_label = QLabel("Target translation Language:")
        self.gemini_lang_combo = QComboBox()
        self.gemini_lang_combo.addItems(["English", "Arabic", "Japanese", "Chinese", "Korean"])
        self.gemini_lang_combo.setMinimumWidth(150)
        
        gemini_lang_row.addWidget(gemini_lang_label)
        gemini_lang_row.addWidget(self.gemini_lang_combo)
        gemini_lang_row.addStretch()
        layout.addLayout(gemini_lang_row)
        
        input_label = QLabel("Text to Translate (Press Ctrl+Enter to submit):")
        layout.addWidget(input_label)
        
        self.translation_input = QTextEdit()
        self.translation_input.setPlaceholderText("Type text to translate and press Ctrl+Enter...")
        self.translation_input.setMinimumHeight(80)
        layout.addWidget(self.translation_input)
    
    def get_gemini_lang_combo(self):
        return self.gemini_lang_combo
    
    def get_translation_input(self):
        return self.translation_input
