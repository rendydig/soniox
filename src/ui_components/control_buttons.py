from PySide6.QtWidgets import (QWidget, QHBoxLayout, QPushButton)
from PySide6.QtCore import Signal


class ControlButtonsWidget(QWidget):
    new_session_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()
    
    def _init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        self.btn_start = QPushButton("Start")
        self.btn_start.setCheckable(True)
        layout.addWidget(self.btn_start)

        self.btn_new = QPushButton("New")
        self.btn_new.setToolTip("Start a new session (the current one is archived)")
        self.btn_new.clicked.connect(self.new_session_clicked.emit)
        layout.addWidget(self.btn_new)
    
    def get_start_button(self):
        return self.btn_start

    def get_new_button(self):
        return self.btn_new
