from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout,
                             QLabel, QTextEdit,
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

        self.view_stack = QStackedWidget()
        self.transcription_editor = QTextEdit()
        self.transcription_editor.setPlaceholderText("Transcription will appear here...")
        self.transcription_editor.setMinimumHeight(200)
        self.webview = QWebEngineView()
        self.webview.setUrl(QUrl("http://localhost:8765/"))
        self.webview.setMinimumHeight(200)
        self.view_stack.addWidget(self.transcription_editor)
        self.view_stack.addWidget(self.webview)

        transcription_container.addWidget(self.view_stack)

        transcription_editors_row.addLayout(transcription_container)
        layout.addLayout(transcription_editors_row)

    def get_transcription_editor(self):
        return self.transcription_editor

    def get_view_stack(self):
        return self.view_stack
    
    def get_webview(self):
        return self.webview
