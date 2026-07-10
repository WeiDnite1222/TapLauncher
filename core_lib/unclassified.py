from PySide6.QtGui import QScreen
from PySide6.QtWidgets import QMainWindow, QApplication


def move_window_to_center(window: QMainWindow):
    main_screen = QApplication.primaryScreen()
    center = QScreen.availableGeometry(main_screen).center()
    geometry = window.frameGeometry()
    geometry.moveCenter(center)
    window.move(geometry.topLeft())