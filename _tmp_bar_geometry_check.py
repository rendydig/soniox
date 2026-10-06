import os
import tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QGuiApplication
import src.ui_state as ui_state

# Use a throwaway state file so the real ui_state.json is never touched.
_tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
_tmp.close()
os.unlink(_tmp.name)
ui_state.STATE_PATH = _tmp.name

from src.ui import MainWindow, BAR_WIDTH, BAR_HEIGHT, INPUT_ROW_HEIGHT

app = QApplication([])
w = MainWindow()
w.show()
app.processEvents()

avail = QGuiApplication.primaryScreen().availableGeometry()
g = w.geometry()
print("avail:", avail, "geometry:", g)

# The bar has a fixed width and sits bottom-centre, just above the taskbar.
assert g.width() == BAR_WIDTH, g.width()
assert g.x() == avail.left() + (avail.width() - BAR_WIDTH) // 2, (g.x(), avail.left())
assert g.bottom() == avail.bottom(), (g.bottom(), avail.bottom())
assert g.height() == BAR_HEIGHT, g.height()

# Toggling the input on grows the bar upward, keeping the bottom edge fixed.
bottom = g.bottom()
w.manual_switch.setChecked(True)
app.processEvents()
g2 = w.geometry()
print("expanded geometry:", g2)
assert g2.height() == BAR_HEIGHT + INPUT_ROW_HEIGHT, g2.height()
assert g2.bottom() == bottom, (g2.bottom(), bottom)
assert g2.width() == BAR_WIDTH, g2.width()
assert not w.translation_section.isHidden()

w.close()
print("BAR GEOMETRY OK")
