import logging
from pathlib import Path
from typing import Callable

from PySide6 import QtWidgets
from PySide6.QtCore import QSize
from PySide6.QtGui import QIcon, Qt, QPixmap
from PySide6.QtWidgets import QApplication, QMainWindow, QLabel, QVBoxLayout, QWidget, QPushButton, QStyle, QToolButton, \
    QStackedWidget

from core_lib.qt.hack import move_window_to_center, recolor_standard_icon
from core_lib.qt import messagebox
from pages.test import TestPage

LAUNCHER_VERSION = "alpha_0.0.1"
MAIN_REPO_URL = "https://repo.weispace.net/wei/Launcher/"

class ToolBar(QtWidgets.QToolBar):
    def __init__(self, app: QApplication, parent=None):
        super(ToolBar, self).__init__(parent)
        self.app = app
        self.orientationChanged.connect(self._update_widget_size)

    def _update_widget_size(self, orientation):
        vertical = orientation == Qt.Orientation.Vertical

        for button in self.findChildren(QToolButton):
            if vertical:
                button.setToolButtonStyle(
                    Qt.ToolButtonStyle.ToolButtonIconOnly
                )
                button.setFixedSize(60, 60)
                continue

            button.setMinimumSize(0, 0)
            button.setMaximumSize(16777215, 16777215)

            if not button.icon().isNull() and not button.text():
                button.setToolButtonStyle(
                    Qt.ToolButtonStyle.ToolButtonIconOnly
                )
                button.setFixedSize(60, 60)
            elif button.icon().isNull():
                button.setToolButtonStyle(
                    Qt.ToolButtonStyle.ToolButtonTextOnly
                )
                button.setFixedWidth(150)
            else:
                button.setToolButtonStyle(
                    Qt.ToolButtonStyle.ToolButtonTextBesideIcon
                )
                button.setFixedWidth(150)

    def add_button(self, text=None, icon: QIcon=None) -> QToolButton:
        button = QtWidgets.QToolButton(self)

        if text:
            text = " "+text
            button.setText(text)

        if icon:
            button.setIcon(icon)
            button.setIconSize(QSize(32, 32))

        if text:
            button.setToolButtonStyle(
                Qt.ToolButtonStyle.ToolButtonTextBesideIcon
            )
        else:
            button.setToolButtonStyle(
                Qt.ToolButtonStyle.ToolButtonIconOnly
            )

        button.setAutoRaise(True)

        return button

    def update_all(self):
        self._update_widget_size(self.orientation())
        self.update()

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

        # Set icon
        if self.icon_path.exists():
            self.setWindowIcon(QIcon(self.icon_path.as_posix()))
        else:
            self.logger.error("No icon found.")

        # Main layout
        self.central = QStackedWidget()
        self.toolbar = ToolBar(self, self.main_window)

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

        if Path(self.resources_dir, "pictures", "in_progress.png").exists():
            image = QPixmap(Path(self.resources_dir, "pictures", "in_progress.png"))
            self.icon_label.setPixmap(image.scaled(300, 300))
        else:
            self.icon_label.setText("Ouch. The icon is missing.")

        # Homepage
        self.home_page = QWidget()
        self.home_layout = QVBoxLayout(self.home_page)
        self.home_layout.addStretch()
        self.home_layout.addWidget(self.icon_label, alignment=Qt.AlignmentFlag.AlignCenter)
        self.home_layout.addWidget(self.dev_info_box, alignment=Qt.AlignmentFlag.AlignHCenter)
        self.home_layout.addWidget(self.dev_info_2, alignment=Qt.AlignmentFlag.AlignHCenter)
        self.home_layout.addWidget(self.version_label, alignment=Qt.AlignmentFlag.AlignHCenter)
        self.home_layout.addWidget(self.repo_url_label, alignment=Qt.AlignmentFlag.AlignHCenter)
        self.home_layout.addStretch()

        # test page
        self.test_page = TestPage(self, self.main_window)

        # Add page
        self.central.addWidget(self.home_page)
        self.central.addWidget(self.test_page)

        # Bind toolbar and center widget
        self.main_window.addToolBar(Qt.ToolBarArea.LeftToolBarArea, self.toolbar)
        self.main_window.setCentralWidget(self.central)

        # Apply qss
        self.apply_qss(Path("main.qss"), self.setStyleSheet)
        self.apply_qss(Path("toolbar.qss"), self.toolbar.setStyleSheet)

        # Toolbar

        # Test Window btn
        self.open_test_page = self.toolbar.add_button(" Tests", icon=QIcon(Path(self.icon_dir, "debug.png").as_posix()))
        self.open_test_page.setObjectName("open_test_page")

        # Home btn
        self.home_button = self.toolbar.add_button(icon=QIcon(Path(self.icon_dir, "home.png").as_posix()))
        self.home_button.clicked.connect(
            lambda: self.central.setCurrentWidget(self.home_page)
        )

        # Bind tool buttons
        self.toolbar.addWidget(self.home_button)
        self.toolbar.addSeparator()
        self.toolbar.addWidget(self.open_test_page)
        self.toolbar.setMovable(True)
        self.toolbar.setFloatable(False)
        self.toolbar.setAllowedAreas(Qt.ToolBarArea.AllToolBarAreas)

        self.home_button.clicked.connect(
            lambda: self.set_current_page(self.home_page, self.home_button)
        )

        self.open_test_page.clicked.connect(
            lambda: self.set_current_page(self.test_page, self.open_test_page)
        )

        self.set_current_page(self.home_page, self.home_button)

    def exec(self):
        self.main_window.show()
        self.toolbar.update_all()
        self.exec_()

    def set_current_page(self, page: QWidget, related_button: QToolButton):
        self.central.setCurrentWidget(page)
        related_button.setFocus()

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
    def icon_dir(self):
        return self.resources_dir / "icons"

    @property
    def launcher_version(self):
        return LAUNCHER_VERSION

    @property
    def styles_path(self):
        return self.resources_dir / "styles"

    def apply_qss(self, qss_relative_path: Path, apply_qss_callback: Callable[[str], None]) -> str:
        full_path = self.styles_path / qss_relative_path
        if not full_path.exists():
            messagebox.error(
                self.main_window,
                "Resource Error",
                "Missing stylesheet file: {}".format(full_path),
            )
            return ""

        try:
            data = full_path.read_text()
            apply_qss_callback(data)
        except Exception as e:
            messagebox.error(
                self.main_window,
                "Resource Error",
                "Unable to apply QSS stylesheet {}: {}".format(full_path, e),
            )

        return ""




