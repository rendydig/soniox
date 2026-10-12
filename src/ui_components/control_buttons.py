from PySide6.QtWidgets import (QWidget, QHBoxLayout, QPushButton, QToolButton)
from PySide6.QtCore import Signal, QSize

from .mic_icon import mic_icon


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

        # Soft mute of the host (microphone) input. A QToolButton, deliberately:
        # the shared button stylesheet paints QPushButton:checked red, and red
        # already means "session running" on the adjacent Start/Stop button — so
        # the icon alone carries the mute state here. Not persisted (see ui.py).
        self.btn_mic = QToolButton()
        self.btn_mic.setCheckable(True)
        self.btn_mic.setIcon(mic_icon(muted=False))
        self.btn_mic.setIconSize(QSize(16, 16))
        self.btn_mic.setFixedWidth(30)
        self.btn_mic.setToolTip("Mute the microphone (host input)")
        layout.addWidget(self.btn_mic)

        self.btn_new = QPushButton("New")
        self.btn_new.setToolTip("Start a new session (the current one is archived)")
        self.btn_new.clicked.connect(self.new_session_clicked.emit)
        layout.addWidget(self.btn_new)
    
    def get_start_button(self):
        return self.btn_start

    def get_mic_button(self):
        return self.btn_mic

    def get_new_button(self):
        return self.btn_new
