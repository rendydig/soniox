from datetime import datetime
from PySide6.QtWidgets import QTextEdit


def append_timestamped_text(text_edit: QTextEdit, text: str):
    """
    Append text to a QTextEdit component with a timestamp prefix.
    
    Args:
        text_edit: The QTextEdit component to append text to
        text: The text content to append
    
    Format: [HH:MM] text
    Example: [07:15] Hello world
    """
    timestamp = datetime.now().strftime("%H:%M")
    
    is_empty = text_edit.toPlainText().strip() == ""
    
    if is_empty:
        formatted_text = f"[{timestamp}] {text}"
    else:
        formatted_text = f"\n[{timestamp}] {text}"
    
    cursor = text_edit.textCursor()
    cursor.movePosition(cursor.MoveOperation.End)
    cursor.insertText(formatted_text)
    text_edit.setTextCursor(cursor)
    text_edit.ensureCursorVisible()
