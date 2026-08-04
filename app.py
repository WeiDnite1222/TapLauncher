import sys
from _colorize import Theme
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QSize
from PySide6.QtGui import QIcon, QPixmap, QPalette, QColor
from PySide6.QtWidgets import QApplication, QStyle, QToolButton

from constant import LAUNCHER_VERSION
from core_lib.qt.hack import move_window_to_center, is_light_theme, \
    recolor_icon
from core_lib.qt import messagebox
from core_lib.i18n import TranslationManager
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
        self._system_palette = QPalette(self.palette()) # theme

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

        general = self.settings_manager.get("general", GeneralSettings)
        self.i18n = TranslationManager(
            self.resources_dir / "translations",
            general.language,
        )

        self.apply_theme()

        self.profile_manager = ProfileManager(self, self.widget_manager)
        self.account_manager = AccountManager(self, self.widget_manager)
        self.game_manager = GameManager(self)

        # Window config
        self.setApplicationName("TapLauncher")
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
                self.tr_text("Resource Error"),
                self.tr_text("Missing icon file: {path}", path=path)
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
                self.tr_text("Resource Error"),
                self.tr_text("Failed to load icon {path}: {error}", path=path, error=e)
            )

        return icon

    def tr_text(self, key: str, /, **values) -> str:
        """Translate a stable English source string for the active language."""
        return self.i18n.translate(key, **values)

    def apply_language(self, language: str) -> None:
        if language != self.i18n.language:
            self.i18n.set_language(language)
            messagebox.info(None,"Launcher",
                            self.tr_text("To make all page apply new language."
                                         " Is recommend to restart the launcher after change it."))

    def set_reloadable_toolbutton_icon(
        self,
        button: QToolButton,
        path: Path,
        no_color_change: bool = False,
    ) -> None:
        """Set an icon and retain its source so theme changes can reload it."""
        button.setProperty("themeIconPath", str(path))
        button.setProperty("themeIconNoColorChange", no_color_change)
        button.setIcon(self.get_icon(path, no_color_change))

    def reload_toolbutton_icons(self) -> None:
        for button in self.allWidgets():
            if not isinstance(button, QToolButton):
                continue

            path = button.property("themeIconPath")
            if not path:
                continue

            no_color_change = bool(
                button.property("themeIconNoColorChange")
            )
            button.setIcon(
                self.get_icon(Path(path), no_color_change)
            )

    def get_picture(self, path: Path, size: QSize, custom_error: str=None) -> QPixmap:
        picture = self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxWarning).pixmap(size)
        if not path.exists() or not path.is_file():
            messagebox.error(
                self.main_window,
                self.tr_text("Resource Error"),
                self.tr_text("Missing icon file: {path}", path=path)
                if not custom_error else custom_error
            )

            return picture

        try:
            picture = QPixmap(path.as_posix())
        except Exception as e:
            messagebox.error(
                self.main_window,
                self.tr_text("Resource Error"),
                self.tr_text("Failed to load icon {path}: {error}", path=path, error=e)
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
        # Completely with official Minecraft launcher
        return self.work_dir

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
                self.tr_text("Resource Error"),
                self.tr_text("Missing stylesheet file: {path}", path=full_path),
            )
            return ""

        try:
            data = full_path.read_text()
            apply_qss_callback(data)
        except Exception as e:
            messagebox.error(
                self.main_window,
                self.tr_text("Resource Error"),
                self.tr_text(
                    "Unable to apply QSS stylesheet {path}: {error}",
                    path=full_path,
                    error=e,
                ),
            )

        return ""

    def get_main_window(self):
        return self.main_window

    def apply_theme(self, theme: Theme | None=None):
        if not theme:
            appearance = self.settings_manager.get("appearance", AppearanceSettings)

            theme = appearance.theme

        if theme == "system":
            palette = self._system_palette
        elif theme == "dark":
            palette = self._dark_palette()
        elif theme == "light":
            palette = self._light_palette()
        else:
            raise ValueError(f"Unsupported theme: {theme}")

        self.setPalette(palette)

        for widget in self.allWidgets():
            widget.style().unpolish(widget)
            widget.style().polish(widget)
            widget.update()

        if hasattr(self, "main_window"):
            self.reload_toolbutton_icons()
            self.main_window.toolbar.update_all()

    @staticmethod
    def _light_palette() -> QPalette:
        palette = QPalette()

        palette.setColor(QPalette.ColorRole.Window, QColor("#f5f5f5"))
        palette.setColor(QPalette.ColorRole.WindowText, QColor("#202020"))
        palette.setColor(QPalette.ColorRole.Base, QColor("#ffffff"))
        palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#eeeeee"))
        palette.setColor(QPalette.ColorRole.Text, QColor("#202020"))
        palette.setColor(QPalette.ColorRole.Button, QColor("#ffffff"))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor("#202020"))
        palette.setColor(QPalette.ColorRole.Mid, QColor("#c5c5c5"))
        palette.setColor(QPalette.ColorRole.Midlight, QColor("#e2e2e2"))
        palette.setColor(QPalette.ColorRole.Dark, QColor("#aaaaaa"))
        palette.setColor(QPalette.ColorRole.Highlight, QColor("#bf265e"))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
        palette.setColor(
            QPalette.ColorRole.PlaceholderText,
            QColor("#707070"),
        )

        return palette
    @staticmethod
    def _dark_palette() -> QPalette:
        palette = QPalette()

        palette.setColor(QPalette.ColorRole.Window, QColor("#202124"))
        palette.setColor(QPalette.ColorRole.WindowText, QColor("#f1f3f4"))
        palette.setColor(QPalette.ColorRole.Base, QColor("#17181a"))
        palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#292a2d"))
        palette.setColor(QPalette.ColorRole.Text, QColor("#f1f3f4"))
        palette.setColor(QPalette.ColorRole.Button, QColor("#292a2d"))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor("#f1f3f4"))
        palette.setColor(QPalette.ColorRole.Mid, QColor("#4a4c50"))
        palette.setColor(QPalette.ColorRole.Midlight, QColor("#383a3e"))
        palette.setColor(QPalette.ColorRole.Dark, QColor("#121315"))
        palette.setColor(QPalette.ColorRole.Highlight, QColor("#bf265e"))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
        palette.setColor(
            QPalette.ColorRole.PlaceholderText,
            QColor("#a0a4aa"),
        )

        return palette
