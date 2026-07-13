import logging
from pathlib import Path

from PySide6.QtGui import QIcon, Qt, QImage, QPixmap
from PySide6.QtWidgets import QApplication, QMainWindow, QLabel, QVBoxLayout, QWidget

from core_lib.qt.hack import move_window_to_center
from dialog.test import TestDialog

LAUNCHER_VERSION = "alpha_0.0.1"
MAIN_REPO_URL = "https://repo.weispace.net/wei/Launcher/"

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

        # Set icon
        if self.icon_path.exists():
            self.setWindowIcon(QIcon(self.icon_path.as_posix()))
        else:
            self.logger.error("No icon found.")

        self.central = QWidget()

        # center message (will be deleted if launcher finished development)
        content = """Still digging!"""
        message = "If you found that something might be a issue. You can report it to the main repo! Any suggestion are welcome."
        self.icon_label = QLabel()
        self.icon_label.setObjectName("icon_label")
        self.dev_info_box = QLabel(content)
        self.dev_info_box.setObjectName("dev_info_box")
        self.dev_info_2 = QLabel(message)
        self.dev_info_2.setObjectName("dev_info_message")
        self.version_label = QLabel("Current version: {}".format(self.launcher_version))
        self.version_label.setObjectName("version_label")
        self.repo_url_label = QLabel(f"<a href=\"{MAIN_REPO_URL}\">Main repo</a>")
        self.repo_url_label.setObjectName("repo_url_label")
        self.repo_url_label.setOpenExternalLinks(True)
        self.main_layout = QVBoxLayout(self.central)

        if Path(self.resources_dir, "pictures", "in_progress.png").exists():
            image = QPixmap(Path(self.resources_dir, "pictures", "in_progress.png"))
            self.icon_label.setPixmap(image.scaled(300, 300))
        else:
            self.icon_label.setText("Ouch. The icon is missing.")

        self.main_layout.addStretch()
        self.main_layout.addWidget(self.icon_label, alignment=Qt.AlignmentFlag.AlignCenter)
        self.main_layout.addWidget(self.dev_info_box, alignment=Qt.AlignmentFlag.AlignHCenter)
        self.main_layout.addWidget(self.dev_info_2, alignment=Qt.AlignmentFlag.AlignHCenter)
        self.main_layout.addWidget(self.version_label, alignment=Qt.AlignmentFlag.AlignHCenter)
        self.main_layout.addWidget(self.repo_url_label, alignment=Qt.AlignmentFlag.AlignHCenter)
        self.main_layout.addStretch()

        self.main_window.setCentralWidget(self.central)

        self.setStyleSheet("""
        QLabel#dev_info_box {
            font-size: 20pt;
            font-weight: bold;
        }
        
        QLabel#dev_info_message {
            font-size: 10pt;
        }
        
        QLabel#version_label, QLabel#version_label {
            font-weight: bold; 
        }
        
        QLabel#icon_label {
            border-radius: 20px; 
        }
        """)

    def exec(self):
        self.main_window.show()
        self.test_dialog.show()
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

    @property
    def resources_dir(self):
        return self.program_dir / "resources"

    @property
    def icon_path(self):
        return self.resources_dir / "icons" / "icon.png"

    @property
    def launcher_version(self):
        return LAUNCHER_VERSION
