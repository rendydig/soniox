from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, 
                             QLabel, QTextEdit, QCheckBox)


class TextEditorsWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()
    
    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        
        transcription_editors_label = QLabel("Output:")
        layout.addWidget(transcription_editors_label)
        
        transcription_editors_row = QHBoxLayout()
        
        transcription_container = QVBoxLayout()
        transcription_label = QLabel("Real-Time Transcription")
        self.transcription_editor = QTextEdit()
        self.transcription_editor.setPlaceholderText("Transcription will appear here...")
        self.transcription_editor.setMinimumHeight(200)
        transcription_container.addWidget(transcription_label)
        transcription_container.addWidget(self.transcription_editor)
        
        gemini_container = QVBoxLayout()
        gemini_header = QHBoxLayout()
        gemini_label = QLabel("Gemini Suggestion")
        self.auto_reply_checkbox = QCheckBox("Auto reply")
        gemini_header.addWidget(gemini_label)
        gemini_header.addWidget(self.auto_reply_checkbox)
        gemini_header.addStretch()
        self.gemini_text = QTextEdit()
        self.gemini_text.setPlaceholderText("Gemini translation will appear here...")
        self.gemini_text.setMinimumHeight(200)
        self.gemini_text.setReadOnly(True)
        gemini_container.addLayout(gemini_header)
        gemini_container.addWidget(self.gemini_text)
        
        transcription_editors_row.addLayout(transcription_container)
        transcription_editors_row.addLayout(gemini_container)
        layout.addLayout(transcription_editors_row)
    
    def get_transcription_editor(self):
        return self.transcription_editor
    
    def get_gemini_text(self):
        return self.gemini_text
    
    def get_auto_reply_checkbox(self):
        return self.auto_reply_checkbox
