import base64

from PySide6.QtCore import QBuffer, QIODevice, Qt
from PySide6.QtGui import QGuiApplication

# Downscale every capture to this width (height follows the aspect ratio) so the
# payload stays small over the local WebSocket.
SCREENSHOT_MAX_WIDTH = 1200
SCREENSHOT_JPEG_QUALITY = 80


def capture_screen_data_url(
    max_width: int = SCREENSHOT_MAX_WIDTH,
    quality: int = SCREENSHOT_JPEG_QUALITY,
) -> str:
    """Capture the primary screen and return a JPEG ``data:`` URL.

    The image is scaled to ``max_width`` with the height following the aspect
    ratio, then JPEG-encoded at ``quality`` and base64-encoded for transport.
    Returns an empty string if the screen could not be captured.
    """
    screen = QGuiApplication.primaryScreen()
    if screen is None:
        print("[Screenshot] No primary screen available")
        return ""

    pixmap = screen.grabWindow(0)
    if pixmap.isNull():
        print("[Screenshot] Capture returned a null pixmap")
        return ""

    if pixmap.width() > max_width:
        pixmap = pixmap.scaledToWidth(max_width, Qt.TransformationMode.SmoothTransformation)

    # QBuffer must own its QByteArray; passing a temporary one gets collected
    # and crashes on save().
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not pixmap.save(buffer, "JPEG", quality):
        print("[Screenshot] Failed to encode capture as JPEG")
        buffer.close()
        return ""

    encoded = base64.b64encode(bytes(buffer.data())).decode("ascii")
    buffer.close()
    return f"data:image/jpeg;base64,{encoded}"
