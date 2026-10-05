import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLayout
from PySide6.QtGui import QGuiApplication
from src.ui import MainWindow, BAR_HEIGHT, INPUT_ROW_HEIGHT
from src.ui_components.live_window import LIVE_WINDOW_WIDTH
from src.ui_components.gemini_window import GEMINI_WINDOW_WIDTH

app = QApplication([])
w = MainWindow()
w.show()
app.processEvents()

# Offscreen screen is narrower than the layout minimum; drop the constraint so
# resize() isn't clamped and the positioning math is testable.
w.centralWidget().layout().setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
w.setMinimumSize(0, 0)
w._snap_to_bottom()
app.processEvents()

avail = QGuiApplication.primaryScreen().availableGeometry()
g = w.geometry()
print("avail:", avail, "geometry:", g)
assert g.left() == avail.left() + LIVE_WINDOW_WIDTH, (g.left(), avail.left())
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
assert not w.translation_section.isHidden()

w.close()
print("BAR GEOMETRY OK")
