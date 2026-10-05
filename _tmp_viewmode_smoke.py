import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from src.ui import MainWindow

app = QApplication([])
w = MainWindow()

# Output lives in the Live Window; the main window has no transcription editor.
assert w.transcription_editor is w.live_window.get_transcription_editor()

# View mode lives in Settings and drives the Live Window's output stack; default Webview.
assert w.view_mode_combo is w.settings_view.get_view_mode_combo()
assert w.view_mode_combo.currentIndex() == 1, w.view_mode_combo.currentIndex()
assert w.live_window.get_view_stack().currentIndex() == 1

w.view_mode_combo.setCurrentIndex(0)
assert w.live_window.get_view_stack().currentIndex() == 0
w.view_mode_combo.setCurrentIndex(1)
assert w.live_window.get_view_stack().currentIndex() == 1

# Manual translate pill switch: off by default; toggling reveals the input row.
switch = w.manual_switch
assert not switch.isChecked()
assert w.translation_section.isHidden()
switch.setChecked(True)
assert not w.translation_section.isHidden()
switch.setChecked(False)
assert w.translation_section.isHidden()

w.close()
print("SMOKE OK")
