import sys
from PySide6.QtWidgets import QApplication
from src.logging_setup import setup_logging
from src.ui import MainWindow

if __name__ == "__main__":
    setup_logging()
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    app.exec()
