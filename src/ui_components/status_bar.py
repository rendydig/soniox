from PySide6.QtWidgets import (QWidget, QHBoxLayout, QLabel)


class StatusBarWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()
    
    def _init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        self.status_label = QLabel("Ready")
        font = self.status_label.font()
        font.setPointSize(font.pointSize() + 1)
        self.status_label.setFont(font)
        layout.addWidget(self.status_label, 1)
        
        self.memory_label = QLabel("")
        self.memory_label.setStyleSheet("color: #666; font-size: 11px;")
        layout.addWidget(self.memory_label)
    
    def get_status_label(self):
        return self.status_label
    
    def get_memory_label(self):
        return self.memory_label
