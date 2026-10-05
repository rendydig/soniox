from PySide6.QtWidgets import QWidget, QVBoxLayout
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtWebEngineWidgets import QWebEngineView
from src.screen_protection import set_capture_protection

# Width of the always-on-top suggestion pane pinned to the right edge.
GEMINI_WINDOW_WIDTH = 400


class GeminiWindow(QWidget):
    """Frameless, always-on-top window showing only the Gemini suggestion card.

    Pinned to the primary screen's right edge, full height, no title bar. It is
    a separate top-level window (no Qt parent) so it can carry its own screen
    capture protection, mirroring ``MainWindow``.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self._screen_protection_enabled = True
        self._init_ui()
        self._position_on_screen()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.webview = QWebEngineView()
        self.webview.setUrl(QUrl("http://localhost:8765/gemini"))
        layout.addWidget(self.webview)

    def _position_on_screen(self):
        """Snap to the primary screen's right edge at full height."""
        geo = QGuiApplication.primaryScreen().geometry()
        self.setGeometry(
            geo.right() - GEMINI_WINDOW_WIDTH + 1,
            geo.top(),
            GEMINI_WINDOW_WIDTH,
            geo.height(),
        )

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
