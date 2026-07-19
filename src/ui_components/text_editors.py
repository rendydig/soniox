from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout,
                             QLabel, QTextEdit, QCheckBox, QComboBox,
                             QStackedWidget)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtCore import QUrl


class TextEditorsWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()
    
    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        
        # transcription_editors_label = QLabel("Output:")
        # layout.addWidget(transcription_editors_label)
        
        transcription_editors_row = QHBoxLayout()
        
        transcription_container = QVBoxLayout()

        transcription_header = QHBoxLayout()
        transcription_label = QLabel("Real-Time Transcription")
        self.view_mode_combo = QComboBox()
        self.view_mode_combo.addItem("Text Editor")
        self.view_mode_combo.addItem("Webview")
        self.view_mode_combo.setToolTip("Switch between text editor and webview")
        transcription_header.addWidget(transcription_label)
        transcription_header.addStretch()
        transcription_header.addWidget(QLabel("View mode:"))
        transcription_header.addWidget(self.view_mode_combo)

        self.view_stack = QStackedWidget()
        self.transcription_editor = QTextEdit()
        self.transcription_editor.setPlaceholderText("Transcription will appear here...")
        self.transcription_editor.setMinimumHeight(200)
        self.webview = QWebEngineView()
        self.webview.setUrl(QUrl("http://localhost:8765/"))
        self.webview.setMinimumHeight(200)
        self.view_stack.addWidget(self.transcription_editor)
        self.view_stack.addWidget(self.webview)

        self.view_mode_combo.currentIndexChanged.connect(self.view_stack.setCurrentIndex)

        transcription_container.addLayout(transcription_header)
        transcription_container.addWidget(self.view_stack)
        
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
    
    def get_view_mode_combo(self):
        return self.view_mode_combo
    
    def get_webview(self):
        return self.webview
