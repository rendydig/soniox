from PySide6.QtWidgets import QWidget, QGridLayout, QTextEdit, QStackedWidget
from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWebEngineWidgets import QWebEngineView
from src.macos_window import set_always_on_top
from src.screen_protection import set_capture_protection
from .pane_edge_handle import PaneEdgeHandle
from .pane_drag_handle import PaneDragHandle

# Default width of the always-on-top live-view pane.
LIVE_WINDOW_WIDTH = 480
# Narrowest / shortest the pane may be dragged to.
MIN_WINDOW_WIDTH = 200
MIN_WINDOW_HEIGHT = 120


class LiveWindow(QWidget):
    """Frameless, always-on-top output window for the live view.

    Free-floating: a top drag strip moves it anywhere on the primary screen and
    border grips resize it freely from any edge or corner. It can still be
    docked to the screen's left or right edge at full height (switchable at
    runtime via the ⇤/⇥ buttons). It hosts the output stack (text editor +
    webview) and is a separate top-level window (no Qt parent) so it can carry
    its own screen capture protection, mirroring ``MainWindow`` and
    ``GeminiWindow``.
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
        # macOS: a Qt::Tool window is an NSPanel whose hidesOnDeactivate is YES,
        # so macOS hides it the moment the app loses focus. This attribute (set
        # before show()) keeps the pane visible while the app is inactive.
        self.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow, True)
        self._always_on_top = True
        self._screen_protection_enabled = True
        self._edge = edge if edge in ("left", "right") else "left"
        self._width = self._clamp_width(width if width else LIVE_WINDOW_WIDTH)

        # A pane is docked (edge-pinned, full height) unless the saved state
        # says otherwise. Missing/legacy state (no "docked" key) defaults to
        # docked, matching the previous edge+width-only behaviour.
        floating = docked is False and x is not None and y is not None
        self._docked = not floating
        if floating:
            self._height = self._clamp_height(height if height else self._screen_height())
            self._x, self._y = self._clamp_position(int(x), int(y))
        else:
            self._height = self._screen_height()
            self._x, self._y = self._edge_position()

        # Active free-resize drag state (set by the border grips).
        self._resize_direction = None
        self._resize_origin = None
        self._resize_start = None

        self._init_ui()
        self._apply_geometry()

    def _init_ui(self):
        outer = QGridLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Border grips resize the pane from any edge or corner. The top-centre
        # strip is the move handle; its two corner grips still resize from the
        # top edge.
        self._tl_handle = PaneEdgeHandle(self, "top-left")
        self._drag_handle = PaneDragHandle(self)
        self._tr_handle = PaneEdgeHandle(self, "top-right")
        self._left_handle = PaneEdgeHandle(self, "left")
        self._right_handle = PaneEdgeHandle(self, "right")
        self._bl_handle = PaneEdgeHandle(self, "bottom-left")
        self._bottom_handle = PaneEdgeHandle(self, "bottom")
        self._br_handle = PaneEdgeHandle(self, "bottom-right")

        self.view_stack = QStackedWidget()
        self.transcription_editor = QTextEdit()
        self.transcription_editor.setPlaceholderText("Transcription will appear here...")
        self.transcription_editor.setStyleSheet(
            "QTextEdit { font-family: 'Menlo', 'Monaco', 'Courier New', monospace; font-size: 13px; }"
        )
        self.webview = QWebEngineView()
        self.webview.setUrl(QUrl("http://localhost:8765/live"))
        self.view_stack.addWidget(self.transcription_editor)
        self.view_stack.addWidget(self.webview)
        self.view_stack.setCurrentIndex(1)

        outer.addWidget(self._tl_handle, 0, 0)
        outer.addWidget(self._drag_handle, 0, 1)
        outer.addWidget(self._tr_handle, 0, 2)
        outer.addWidget(self._left_handle, 1, 0)
        outer.addWidget(self.view_stack, 1, 1)
        outer.addWidget(self._right_handle, 1, 2)
        outer.addWidget(self._bl_handle, 2, 0)
        outer.addWidget(self._bottom_handle, 2, 1)
        outer.addWidget(self._br_handle, 2, 2)
        outer.setRowStretch(1, 1)
        outer.setColumnStretch(1, 1)

    def _screen_height(self):
        screen = QGuiApplication.primaryScreen()
        return screen.geometry().height() if screen is not None else 720

    def _edge_position(self):
        """Top-left for the pane docked to its edge at the current width."""
        geo = QGuiApplication.primaryScreen().geometry()
        x = geo.left() if self._edge == "left" else geo.right() - self._width + 1
        return x, geo.top()

    def _clamp_width(self, width):
        try:
            width = int(width)
        except (TypeError, ValueError):
            width = LIVE_WINDOW_WIDTH
        screen = QGuiApplication.primaryScreen()
        max_width = screen.geometry().width() if screen is not None else LIVE_WINDOW_WIDTH
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

    def begin_edge_resize(self, direction, global_pos):
        """Start a free resize drag from an edge or corner grip."""
        self._resize_direction = direction
        self._resize_origin = global_pos
        self._resize_start = (self._x, self._y, self._width, self._height)

    def perform_edge_resize(self, global_pos):
        """Resize from the active edge(s), keeping the opposite edge anchored."""
        direction = self._resize_direction
        if direction is None or self._resize_start is None:
            return
        dx = global_pos.x() - self._resize_origin.x()
        dy = global_pos.y() - self._resize_origin.y()
        x, y, w, h = self._resize_start
        if "left" in direction:
            x, w = x + dx, w - dx
        if "right" in direction:
            w = w + dx
        if "top" in direction:
            y, h = y + dy, h - dy
        if "bottom" in direction:
            h = h + dy
        x, y, w, h = self._edge_rect(x, y, w, h, direction)
        if (x, y, w, h) == (self._x, self._y, self._width, self._height) and not self._docked:
            return
        self._x, self._y, self._width, self._height = x, y, w, h
        self._docked = False
        self._apply_geometry()
        self.geometry_changed.emit()

    def end_edge_resize(self):
        """Finish a free resize drag and persist the new geometry."""
        self._resize_direction = None
        self._resize_start = None
        self.finish_resize()

    def _edge_rect(self, x, y, w, h, direction):
        """Clamp a candidate rect to the pane minimums and the primary screen.

        When a dragged edge passes a limit, the *opposite* edge stays put (the
        anchored edge), so hitting the screen border stops growth instead of
        sliding the whole pane.
        """
        w = max(MIN_WINDOW_WIDTH, w)
        h = max(MIN_WINDOW_HEIGHT, h)
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return x, y, w, h
        geo = screen.geometry()
        w = min(w, geo.width())
        h = min(h, geo.height())
        start_x, start_y, start_w, start_h = self._resize_start
        if "left" in direction:
            anchor_right = start_x + start_w
            x = max(geo.left(), min(x, anchor_right - MIN_WINDOW_WIDTH))
            w = anchor_right - x
        elif "right" in direction:
            x = max(geo.left(), min(x, geo.right() - MIN_WINDOW_WIDTH + 1))
            w = max(MIN_WINDOW_WIDTH, min(w, geo.right() - x + 1))
        else:
            x = max(geo.left(), min(x, geo.right() - w + 1))
        if "top" in direction:
            anchor_bottom = start_y + start_h
            y = max(geo.top(), min(y, anchor_bottom - MIN_WINDOW_HEIGHT))
            h = anchor_bottom - y
        elif "bottom" in direction:
            y = max(geo.top(), min(y, geo.bottom() - MIN_WINDOW_HEIGHT + 1))
            h = max(MIN_WINDOW_HEIGHT, min(h, geo.bottom() - y + 1))
        else:
            y = max(geo.top(), min(y, geo.bottom() - h + 1))
        return x, y, w, h

    def finish_resize(self):
        """Persist the geometry once a resize drag settles."""
        self.state_changed.emit()

    def finish_move(self):
        """Persist the geometry once a move drag settles."""
        self.state_changed.emit()

    def reset_width(self):
        """Restore the default width (double-click the width handle)."""
        self.set_width(LIVE_WINDOW_WIDTH)
        self.finish_resize()

    def reset_height(self):
        """Restore full screen height (double-click the height handle)."""
        self.set_height(self._screen_height())
        self.finish_resize()

    def apply_always_on_top(self, enabled: bool):
        """Pin (or unpin) this pane above other windows (Tool ▾ > Always on Top)."""
        enabled = bool(enabled)
        changed = self._always_on_top != enabled
        self._always_on_top = enabled
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, enabled)
        if changed and self.isVisible():
            # Changing flags on a visible window hides it, so re-show it;
            # showEvent re-applies the native level and the capture protection.
            self.show()
        set_always_on_top(self, enabled)

    def apply_screen_protection(self, enabled: bool):
        """Exclude (or restore) this window from screen capture."""
        self._screen_protection_enabled = bool(enabled)
        set_capture_protection(self, enabled)

    def get_view_stack(self):
        return self.view_stack

    def get_transcription_editor(self):
        return self.transcription_editor

    def get_webview(self):
        return self.webview

    def showEvent(self, event):
        super().showEvent(event)
        # Changing window flags / re-showing can reset both the capture
        # exclusion and the native (macOS) window level, so re-apply on show.
        set_always_on_top(self, self._always_on_top)
        if self._screen_protection_enabled:
            set_capture_protection(self, True)
