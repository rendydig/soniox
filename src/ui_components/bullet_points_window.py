from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout
from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWebEngineWidgets import QWebEngineView
from src.screen_protection import set_capture_protection
from .pane_resize_handle import PaneResizeHandle
from .pane_drag_handle import PaneDragHandle

# Default width of the always-on-top bullet-points pane.
BULLET_POINTS_WINDOW_WIDTH = 400
# Narrowest / shortest the pane may be dragged to.
MIN_WINDOW_WIDTH = 200
MIN_WINDOW_HEIGHT = 120
# Default floating placement (fraction of the screen height + insets in px).
DEFAULT_HEIGHT_RATIO = 0.55
DEFAULT_INSET = 12
DEFAULT_TOP = 60


class BulletPointsWindow(QWidget):
    """Frameless, always-on-top window showing the bullet-point list.

    Mirrors ``GeminiWindow``/``LiveWindow``: a top drag strip moves it, the
    inner-edge handle resizes its width, the bottom-edge handle resizes its
    height, and it can be docked to the screen's left or right edge. Unlike the
    other panes it starts **free-floating** (not edge-docked) on the right so it
    does not collide with the docked Gemini/Live panes by default. It is a
    separate top-level window (no Qt parent) so it can carry its own screen
    capture protection.
    """

    # Emitted while the pane is resized / moved, so the bar can re-snap.
    geometry_changed = Signal()
    # Emitted when the geometry settles and should be persisted.
    state_changed = Signal()

    def __init__(self, edge=None, width=None, height=None, x=None, y=None, docked=None, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self._screen_protection_enabled = True
        self._edge = edge if edge in ("left", "right") else "right"
        self._width = self._clamp_width(width if width else BULLET_POINTS_WINDOW_WIDTH)

        # Default to floating (not edge-docked) when there is no saved state.
        saved_floating = docked is False and x is not None and y is not None
        if saved_floating:
            self._docked = False
            self._height = self._clamp_height(height if height else self._default_height())
            self._x, self._y = self._clamp_position(int(x), int(y))
        elif docked is True:
            self._docked = True
            self._height = self._screen_height()
            self._x, self._y = self._edge_position()
        else:
            self._docked = False
            self._height = self._clamp_height(height if height else self._default_height())
            self._x, self._y = self._clamp_position(*self._default_position())

        self._init_ui()
        self._apply_geometry()

    def _init_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._drag_handle = PaneDragHandle(self)
        outer.addWidget(self._drag_handle)

        self.webview = QWebEngineView()
        self.webview.setUrl(QUrl("http://localhost:8765/bullets"))
        self._content_row = QHBoxLayout()
        self._content_row.setContentsMargins(0, 0, 0, 0)
        self._content_row.setSpacing(0)
        self._content_row.addWidget(self.webview)
        outer.addLayout(self._content_row, 1)

        self._height_handle = PaneResizeHandle(self, orientation="vertical")
        outer.addWidget(self._height_handle)

        self._width_handle = PaneResizeHandle(self, orientation="horizontal")
        self._apply_edge_layout()

    def _apply_edge_layout(self):
        """Put the width handle on the pane's inner (screen-centre) edge."""
        self._content_row.removeWidget(self._width_handle)
        if self._edge == "right":
            self._content_row.insertWidget(0, self._width_handle)
        else:
            self._content_row.addWidget(self._width_handle)

    def _screen_height(self):
        screen = QGuiApplication.primaryScreen()
        return screen.geometry().height() if screen is not None else 720

    def _default_height(self):
        return int(self._screen_height() * DEFAULT_HEIGHT_RATIO)

    def _default_position(self):
        """Top-left for the default floating placement (right side, inset)."""
        geo = QGuiApplication.primaryScreen().geometry()
        return geo.right() - self._width - DEFAULT_INSET + 1, geo.top() + DEFAULT_TOP

    def _edge_position(self):
        """Top-left for the pane docked to its edge at the current width."""
        geo = QGuiApplication.primaryScreen().geometry()
        x = geo.left() if self._edge == "left" else geo.right() - self._width + 1
        return x, geo.top()

    def _clamp_width(self, width):
        try:
            width = int(width)
        except (TypeError, ValueError):
            width = BULLET_POINTS_WINDOW_WIDTH
        screen = QGuiApplication.primaryScreen()
        max_width = screen.geometry().width() if screen is not None else BULLET_POINTS_WINDOW_WIDTH
        return max(MIN_WINDOW_WIDTH, min(width, max_width))

    def _clamp_height(self, height):
        try:
            height = int(height)
        except (TypeError, ValueError):
            height = self._screen_height()
        screen = QGuiApplication.primaryScreen()
        max_height = screen.geometry().height() if screen is not None else height
        return max(MIN_WINDOW_HEIGHT, min(height, max_height))

    def _clamp_position(self, x, y):
        """Keep the pane within the primary screen so it can't be lost off-screen."""
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return x, y
        geo = screen.geometry()
        x = max(geo.left(), min(x, geo.right() - self._width + 1))
        y = max(geo.top(), min(y, geo.bottom() - self._height + 1))
        return x, y

    def _apply_geometry(self):
        self.setGeometry(self._x, self._y, self._width, self._height)

    def _dock(self):
        """Pin to the current edge at full height."""
        self._docked = True
        self._height = self._screen_height()
        self._x, self._y = self._edge_position()
        self._apply_geometry()

    def get_edge(self):
        return self._edge

    def is_docked(self):
        return self._docked

    def get_width(self):
        return self._width

    def get_height(self):
        return self._height

    def get_x(self):
        return self._x

    def get_y(self):
        return self._y

    def set_edge(self, edge):
        """Dock the pane to ``edge`` ("left"/"right") at full height."""
        if edge not in ("left", "right"):
            return
        if edge == self._edge and self._docked:
            return
        self._edge = edge
        self._apply_edge_layout()
        self._dock()
        self.geometry_changed.emit()
        self.state_changed.emit()

    def set_width(self, width):
        """Resize the width, keeping the pane's top-left anchored."""
        width = self._clamp_width(width)
        if width == self._width:
            return
        self._width = width
        if self._docked:
            self._x, self._y = self._edge_position()
        self._apply_geometry()
        self.geometry_changed.emit()

    def set_height(self, height):
        """Resize the height, un-docking the pane (top-left anchored)."""
        height = self._clamp_height(height)
        if height == self._height and not self._docked:
            return
        self._height = height
        self._docked = False
        self._x, self._y = self._clamp_position(self._x, self._y)
        self._apply_geometry()
        self.geometry_changed.emit()

    def move_to(self, point):
        """Move the pane (un-docking it) from a drag position."""
        x, y = self._clamp_position(int(point.x()), int(point.y()))
        if (x, y) == (self._x, self._y) and not self._docked:
            return
        self._x, self._y = x, y
        self._docked = False
        self._apply_geometry()
        self.geometry_changed.emit()

    def resize_by_drag(self, delta_x, start_width):
        """Width from a handle drag: grow toward the screen centre."""
        width = start_width - delta_x if self._edge == "right" else start_width + delta_x
        self.set_width(width)

    def resize_height_by_drag(self, delta_y, start_height):
        """Height from the bottom handle: grow downward from the top edge."""
        self.set_height(start_height + delta_y)

    def finish_resize(self):
        """Persist the geometry once a resize drag settles."""
        self.state_changed.emit()

    def finish_move(self):
        """Persist the geometry once a move drag settles."""
        self.state_changed.emit()

    def reset_width(self):
        """Restore the default width (double-click the width handle)."""
        self.set_width(BULLET_POINTS_WINDOW_WIDTH)
        self.finish_resize()

    def reset_height(self):
        """Restore the default height (double-click the height handle)."""
        self.set_height(self._default_height())
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
