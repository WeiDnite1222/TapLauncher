from PySide6.QtWidgets import QApplication, QWidget, QMainWindow

from core_lib.unclassified import move_window_to_center


class Launcher(QApplication):
    def __init__(self):
        super().__init__()
        self.setApplicationName("TestLauncher")
        self.main_window = QMainWindow()
        self.main_window.setGeometry(0, 0, 800, 600)

        move_window_to_center(self.main_window)

    def exec(self):
        self.main_window.show()
        self.exec_()