import sys
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QSize
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QApplication, QStyle

from constant import LAUNCHER_VERSION
from core_lib.qt.hack import move_window_to_center, is_light_theme, \
    recolor_icon
from core_lib.qt import messagebox
from core_lib.launcher.object import Launcher as LauncherObject
from manager.account import AccountManager
from manager.game import GameManager
from manager.profile import ProfileManager
from manager.settings import SettingsManager
from manager.settings_models import AccountSettings, AppearanceSettings, GeneralSettings
from manager.widgets import WidgetManager
from window import LauncherMainWindow

class Launcher(QApplication, LauncherObject):
    def __init__(self, logger, debug: bool = False):
        super().__init__()
        # logger
        self.logger = logger
        self.debug = debug

        # dirs
        self.program_dir = Path(__file__).parent
        self.work_dir = Path.cwd()

        # Widget (Signal, Event)
        self.widget_manager = WidgetManager()
        # Manager
        self.settings_manager = SettingsManager(self.root_settings_dir)
        self.settings_manager.register("general", GeneralSettings)
        self.settings_manager.register("appearance", AppearanceSettings)
        self.settings_manager.register("account", AccountSettings)
        if self.root_settings_dir.is_file():
            self.settings_manager.load()
        else:
            self.settings_manager.load_defaults().save()
        self.profile_manager = ProfileManager(self, self.widget_manager)
        self.account_manager = AccountManager(self, self.widget_manager)
        self.game_manager = GameManager(self)

        # Window config
        self.setApplicationName("TestLauncher")
        self.main_window = LauncherMainWindow(
            app=self
        )
        self.main_window.setGeometry(0, 0, 800, 600)
        move_window_to_center(self.main_window)

        # Set icon
        if self.icon_path.exists():
            self.setWindowIcon(QIcon(self.icon_path.as_posix()))
        else:
            self.logger.error("No icon found.")

    def exec(self):
        # init managers
        self.profile_manager.profile_load.emit()
        self.account_manager.account_load.emit()

        self.main_window.show()
        self.main_window.toolbar.update_all()
        self.exec_()

    def get_icon(self, path: Path, no_color_change: bool = False) -> QIcon:
        icon = self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxWarning)
        if not path.exists() or not path.is_file():
            messagebox.error(
                self.main_window,
                "Resource Error",
                "Missing icon file: {}".format(path)
            )

            return icon

        try:
            if is_light_theme() and path.name.endswith(".png") and not no_color_change:
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
    def root_settings_dir(self):
        return self.data_dir / "settings.toml"

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
                None,
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
