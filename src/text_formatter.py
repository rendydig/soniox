from datetime import datetime
from PySide6.QtWidgets import QTextEdit
from PySide6.QtGui import QTextCursor


def append_timestamped_text(text_edit: QTextEdit, text: str, max_lines: int = None):
    """
    Append text to a QTextEdit component with a timestamp prefix.
    
    Args:
        text_edit: The QTextEdit component to append text to
        text: The text content to append
        max_lines: Maximum number of lines to keep (None = unlimited)
    
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
    
    if max_lines is not None:
        limit_text_edit_lines(text_edit, max_lines)


def limit_text_edit_lines(text_edit: QTextEdit, max_lines: int):
    """
    Limit the number of lines in a QTextEdit to prevent memory buildup.
    Removes oldest lines when limit is exceeded.
    
    Args:
        text_edit: The QTextEdit component to limit
        max_lines: Maximum number of lines to keep
    """
    document = text_edit.document()
    line_count = document.blockCount()
    
    if line_count > max_lines:
        lines_to_remove = line_count - max_lines
        
        cursor = QTextCursor(document)
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        
        for _ in range(lines_to_remove):
            cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
            cursor.removeSelectedText()
            cursor.deleteChar()
        
        text_edit.setTextCursor(cursor)
