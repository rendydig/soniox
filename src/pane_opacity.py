"""Whole-window opacity for the always-on-top panes.

Qt maps ``QWidget.setWindowOpacity`` onto ``NSWindow.alphaValue`` on macOS (see
``QCocoaWindow::setOpacity``) and onto a layered window on Windows, so the whole
window — web content included — composites at the requested alpha.

Per-pixel translucency (``WA_TranslucentBackground`` + a transparent
``QWebEnginePage`` background) is deliberately not used: QtWebEngine renders
transparent areas as black on macOS.

Values are clamped to MIN_PANE_OPACITY..MAX_PANE_OPACITY so a pane can never be
faded below the point where it stays readable and clickable.
"""

from src.config import PANE_OPACITY

MIN_PANE_OPACITY = 0.3
MAX_PANE_OPACITY = 1.0


def clamp_opacity(value, default=PANE_OPACITY):
    """Coerce ``value`` (float, int, or a string from JSON/.env) into the range."""
    try:
        value = float(value)
    except (TypeError, ValueError):
        return float(default)
    return max(MIN_PANE_OPACITY, min(value, MAX_PANE_OPACITY))


def set_pane_opacity(widget, value):
    """Composite the top-level ``widget`` (a pane) at ``value`` opacity."""
    widget.setWindowOpacity(clamp_opacity(value))
