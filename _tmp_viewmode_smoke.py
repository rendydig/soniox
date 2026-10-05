import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from src.ui import MainWindow

app = QApplication([])
w = MainWindow()

# View mode moved to Settings, default Webview.
assert w.view_mode_combo is w.settings_view.get_view_mode_combo()
assert w.view_mode_combo.currentIndex() == 1, w.view_mode_combo.currentIndex()
assert w.text_editors.get_view_stack().currentIndex() == 1

w.view_mode_combo.setCurrentIndex(0)
assert w.text_editors.get_view_stack().currentIndex() == 0
w.view_mode_combo.setCurrentIndex(1)
assert w.text_editors.get_view_stack().currentIndex() == 1

# Manual translate pill switch: visible by default, collapses the input when off.
switch = w.translation_section.get_manual_switch()
assert switch.isChecked()
assert not w.translation_input.isHidden()
switch.setChecked(False)
assert w.translation_input.isHidden()
switch.setChecked(True)
assert not w.translation_input.isHidden()

print("SMOKE OK")
