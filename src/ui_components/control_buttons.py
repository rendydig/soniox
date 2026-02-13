from PySide6.QtWidgets import (QWidget, QHBoxLayout, QPushButton)


class ControlButtonsWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()
    
    def _init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        self.btn_start = QPushButton("Start Transcription")
        self.btn_start.setCheckable(True)
        self.btn_start.setMinimumHeight(56)
        layout.addWidget(self.btn_start)
        
        self.record_btn = QPushButton("Record to File")
        self.record_btn.setCheckable(True)
        self.record_btn.setMinimumHeight(56)
        layout.addWidget(self.record_btn)
    
    def get_start_button(self):
        return self.btn_start
    
    def get_record_button(self):
        return self.record_btn
