from PySide6.QtWidgets import QWidget, QHBoxLayout
from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWebEngineWidgets import QWebEngineView
from src.screen_protection import set_capture_protection
from .pane_resize_handle import PaneResizeHandle

# Default width of the always-on-top suggestion pane.
GEMINI_WINDOW_WIDTH = 400
# Narrowest the pane may be dragged to.
MIN_WINDOW_WIDTH = 200


class GeminiWindow(QWidget):
    """Frameless, always-on-top window showing only the Gemini suggestion card.

    Pinned to the primary screen's left or right edge (switchable at runtime),
    full height, no title bar, with a drag handle on its inner edge to resize
    the width. It is a separate top-level window (no Qt parent) so it can carry
    its own screen capture protection, mirroring ``MainWindow``.
    """

    # Emitted while the pane is resized / moved, so the bar can re-snap.
    geometry_changed = Signal()
    # Emitted when the edge or width settles and should be persisted.
    state_changed = Signal()

    def __init__(self, edge=None, width=None, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self._screen_protection_enabled = True
        self._edge = edge if edge in ("left", "right") else "right"
        self._width = self._clamp_width(width if width else GEMINI_WINDOW_WIDTH)
        self._init_ui()
        self._position_on_screen()

    def _init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.webview = QWebEngineView()
        self.webview.setUrl(QUrl("http://localhost:8765/gemini"))
        layout.addWidget(self.webview)

        self._resize_handle = PaneResizeHandle(self)
        self._apply_edge_layout()

    def _apply_edge_layout(self):
        """Put the resize handle on the pane's inner (screen-centre) edge."""
        layout = self.layout()
        layout.removeWidget(self._resize_handle)
        if self._edge == "right":
            layout.insertWidget(0, self._resize_handle)
        else:
            layout.addWidget(self._resize_handle)

    def _clamp_width(self, width):
        try:
            width = int(width)
        except (TypeError, ValueError):
            width = GEMINI_WINDOW_WIDTH
        screen = QGuiApplication.primaryScreen()
        max_width = screen.availableGeometry().width() if screen is not None else GEMINI_WINDOW_WIDTH
        return max(MIN_WINDOW_WIDTH, min(width, max_width))

    def _position_on_screen(self):
        """Snap to the primary screen's left/right edge at full height."""
        geo = QGuiApplication.primaryScreen().geometry()
        x = geo.left() if self._edge == "left" else geo.right() - self._width + 1
        self.setGeometry(x, geo.top(), self._width, geo.height())

    def get_edge(self):
        return self._edge

    def get_width(self):
        return self._width

    def set_edge(self, edge):
        """Pin the pane to ``edge`` ("left"/"right"), keeping the width."""
        if edge not in ("left", "right") or edge == self._edge:
            return
        self._edge = edge
        self._apply_edge_layout()
        self._position_on_screen()
        self.geometry_changed.emit()
        self.state_changed.emit()

    def set_width(self, width):
        """Resize the pane, keeping it pinned to its edge."""
        width = self._clamp_width(width)
        if width == self._width:
            return
        self._width = width
        self._position_on_screen()
        self.geometry_changed.emit()

    def resize_by_drag(self, delta_x, start_width):
        """Width from a handle drag: grow toward the screen centre."""
        width = start_width - delta_x if self._edge == "right" else start_width + delta_x
        self.set_width(width)

    def finish_resize(self):
        """Persist the width once a drag settles."""
        self.state_changed.emit()

    def reset_width(self):
        """Restore the default width (double-click the handle)."""
        self.set_width(GEMINI_WINDOW_WIDTH)
        self.finish_resize()

    def apply_screen_protection(self, enabled: bool):
        """Exclude (or restore) this window from screen capture."""
        self._screen_protection_enabled = bool(enabled)
        set_capture_protection(self, enabled)

    def get_webview(self):
        return self.webview

    def showEvent(self, event):
        super().showEvent(event)
        # Changing window flags / re-showing resets the display affinity,
        # so re-apply it whenever the window becomes visible.
        if self._screen_protection_enabled:
            set_capture_protection(self, True)
