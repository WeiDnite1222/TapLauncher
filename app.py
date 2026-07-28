import logging
import os
import sys
from pathlib import Path
from typing import Callable

from PySide6 import QtWidgets
from PySide6.QtCore import QSize
from PySide6.QtGui import QIcon, Qt, QPixmap
from PySide6.QtWidgets import QApplication, QWidget, QStyle, QToolButton

from constant import LAUNCHER_VERSION
from core_lib.qt.hack import move_window_to_center, is_light_theme, \
    recolor_icon
from core_lib.qt import messagebox
from core_lib.launcher.object import Launcher as LauncherObject
from manager.profile import ProfileManager
from manager.widgets import WidgetManager
from window import LauncherMainWindow

class ToolBar(QtWidgets.QToolBar):
    def __init__(self, app: QApplication, parent=None):
        super(ToolBar, self).__init__(parent)
        self.app = app
        self.spacer = QWidget()
        self.orientationChanged.connect(self._update_widget_size)

    def _update_widget_size(self, orientation):
        vertical = orientation == Qt.Orientation.Vertical

        if vertical:
            self.spacer.setSizePolicy(
                    QtWidgets.QSizePolicy.Policy.Preferred,
                    QtWidgets.QSizePolicy.Policy.Expanding,
                )
        else:
            self.spacer.setSizePolicy(
                QtWidgets.QSizePolicy.Policy.Expanding,
                QtWidgets.QSizePolicy.Policy.Preferred,
            )

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
                button.setMinimumWidth(60)

    def add_button(self, text=None, icon: QIcon=None) -> QToolButton:
        button = QtWidgets.QToolButton(self)

        if text:
            text = " "+text
            button.setText(text)
        # else:
        #     button.setText("\u00a0")

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
        button.setFixedHeight(60)

        return button

    def update_all(self):
        self._update_widget_size(self.orientation())
        self.update()

class Launcher(QApplication, LauncherObject):
    def __init__(self, logger):
        super().__init__()
        # logger
        self.logger = logger

        # dirs
        self.program_dir = Path(__file__).parent
        self.work_dir = Path.cwd()

        # Widget (Signal, Event)
        self.widget_manager = WidgetManager()

        # Manager
        self.profile_manager = ProfileManager(self, self.widget_manager)

        # Window config
        self.setApplicationName("TestLauncher")
        self.main_window = LauncherMainWindow(
            app=self,
            widget_manager=self.widget_manager,
        )
        self.main_window.setGeometry(0, 0, 800, 600)
        move_window_to_center(self.main_window)

        # Set icon
        if self.icon_path.exists():
            self.setWindowIcon(QIcon(self.icon_path.as_posix()))
        else:
            self.logger.error("No icon found.")

    def exec(self):
        self.main_window.show()
        self.main_window.toolbar.update_all()

        # init managers
        self.profile_manager.profile_load.emit()

        self.exec_()

    def get_icon(self, path: Path):
        icon = self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxWarning)
        if not path.exists() or not path.is_file():
            messagebox.error(
                self.main_window,
                "Resource Error",
                "Missing icon file: {}".format(path)
            )

            return icon

        try:
            if is_light_theme() and path.name.endswith(".png"):
                icon = recolor_icon(
                    path
                )
            else:
                icon = QIcon(path.as_posix())
        except Exception as e:
            messagebox.error(
                self.main_window,
                "Resource Error",
                "Failed to load icon {}: {}".format(path, e)
            )

        return icon

    def get_picture(self, path: Path, size: QSize, custom_error: str=None) -> QPixmap:
        picture = self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxWarning).pixmap(size)
        if not path.exists() or not path.is_file():
            messagebox.error(
                self.main_window,
                "Resource Error",
                "Missing icon file: {}".format(path) if not custom_error else custom_error
            )

            return picture

        try:
            picture = QPixmap(path.as_posix())
        except Exception as e:
            messagebox.error(
                self.main_window,
                "Resource Error",
                "Failed to load icon {}: {}".format(path, e)
            )

        return picture

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
    def default_game_dir(self) -> Path:
        return self.work_dir / "minecraft" if sys.platform.lower() == "darwin" else self.work_dir / ".minecraft"

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

    def get_main_window(self):
        return self.main_window
