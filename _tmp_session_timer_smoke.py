"""Throwaway smoke test: session timer composed into the Start/Stop button."""
import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from src.ui import MainWindow

app = QApplication([])


class FakeButton:
    def __init__(self):
        self._checked = False
        self.text = "Start"

    def isChecked(self):
        return self._checked

    def setChecked(self, value):
        self._checked = bool(value)

    def setText(self, text):
        self.text = text


class Stub:
    pass


s = Stub()
s._session_elapsed_seconds = 0.0
s._session_run_started = None
s._session_timer = QTimer()
s.btn_start = FakeButton()
for name in ("_current_session_seconds", "_update_start_button_text",
             "_start_session_timer", "_pause_session_timer", "_reset_session_timer"):
    setattr(s, name, (lambda n: lambda: getattr(MainWindow, n)(s))(name))

s._update_start_button_text()
assert s.btn_start.text == "Start 00:00:00", s.btn_start.text

# Start -> running label
s.btn_start.setChecked(True)
s._start_session_timer()
assert s.btn_start.text == "Stop 00:00:00", s.btn_start.text

# Tick ~1.2s, then Stop -> frozen value stays visible with the "Start" verb
time.sleep(1.2)
s._update_start_button_text()
assert s.btn_start.text == "Stop 00:00:01", s.btn_start.text
s.btn_start.setChecked(False)
s._pause_session_timer()
assert s.btn_start.text == "Start 00:00:01", s.btn_start.text
assert not s._session_timer.isActive()

# Frozen while stopped
time.sleep(0.6)
s._update_start_button_text()
assert s.btn_start.text == "Start 00:00:01", s.btn_start.text

# Resume -> accumulates to 00:00:02
s.btn_start.setChecked(True)
s._start_session_timer()
time.sleep(1.2)
s.btn_start.setChecked(False)
s._pause_session_timer()
assert s.btn_start.text == "Start 00:00:02", s.btn_start.text

# Reset (New Session)
s._reset_session_timer()
assert s.btn_start.text == "Start 00:00:00", s.btn_start.text
assert not s._session_timer.isActive()

# Resume after reset starts from zero
s.btn_start.setChecked(True)
s._start_session_timer()
time.sleep(1.2)
s.btn_start.setChecked(False)
s._pause_session_timer()
assert s.btn_start.text == "Start 00:00:01", s.btn_start.text

print("BUTTON_TIMER_OK")
