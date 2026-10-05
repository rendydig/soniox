from PySide6.QtWidgets import QWidget, QVBoxLayout, QTextEdit, QStackedWidget
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtWebEngineWidgets import QWebEngineView
from src.screen_protection import set_capture_protection

# Width of the always-on-top live-view pane pinned to the left edge.
LIVE_WINDOW_WIDTH = 480


class LiveWindow(QWidget):
    """Frameless, always-on-top output window for the live view.

    Pinned to the primary screen's left edge, full height, no title bar. It
    hosts the output stack (text editor + webview) and is a separate top-level
    window (no Qt parent) so it can carry its own screen capture protection,
    mirroring ``MainWindow`` and ``GeminiWindow``.
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
        layout.addWidget(self.view_stack)

    def _position_on_screen(self):
        """Snap to the primary screen's left edge at full height."""
        geo = QGuiApplication.primaryScreen().geometry()
        self.setGeometry(
            geo.left(),
            geo.top(),
            LIVE_WINDOW_WIDTH,
            geo.height(),
        )

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
        # Changing window flags / re-showing resets the display affinity,
        # so re-apply it whenever the window becomes visible.
        if self._screen_protection_enabled:
            set_capture_protection(self, True)
