import logging
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMainWindow

from core_lib.qt.hack import move_window_to_center
from dialog.test import TestDialog

class Launcher(QApplication):
    def __init__(self):
        super().__init__()
        # Window config
        self.setApplicationName("TestLauncher")
        self.main_window = QMainWindow()
        self.main_window.setGeometry(0, 0, 800, 600)
        move_window_to_center(self.main_window)

        # logger
        self.logger = logging.getLogger("Launcher.MainWindow")

        # dirs
        self.program_dir = Path(__file__).parent
        self.work_dir = Path.cwd()

        # test page
        self.test_dialog = TestDialog(self, self.main_window)
        self.test_dialog.show()


    def exec(self):
        self.main_window.show()
        self.exec_()

    @property
    def temp_dir(self):
        return self.work_dir / "temp"

    @property
    def config_dir(self):
        return self.work_dir / "config"

    @property
    def data_dir(self):
        return self.work_dir / "data"

    @property
    def log_dir(self):
        return self.work_dir / "log"