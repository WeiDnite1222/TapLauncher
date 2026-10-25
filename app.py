import platform
import sys
import traceback
from collections.abc import Mapping
from pathlib import Path
from typing import Callable

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

from PySide6.QtCore import QSize
from PySide6.QtGui import QIcon, QPixmap, QPalette, QColor
from PySide6.QtWidgets import QApplication, QStyle, QToolButton, QWidget

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


PALETTE_ROLES = {
    "window": QPalette.ColorRole.Window,
    "window_text": QPalette.ColorRole.WindowText,
    "base": QPalette.ColorRole.Base,
    "alternate_base": QPalette.ColorRole.AlternateBase,
    "text": QPalette.ColorRole.Text,
    "button": QPalette.ColorRole.Button,
    "button_text": QPalette.ColorRole.ButtonText,
    "mid": QPalette.ColorRole.Mid,
    "midlight": QPalette.ColorRole.Midlight,
    "dark": QPalette.ColorRole.Dark,
    "highlight": QPalette.ColorRole.Highlight,
    "highlighted_text": QPalette.ColorRole.HighlightedText,
    "placeholder_text": QPalette.ColorRole.PlaceholderText,
}


class Launcher(QApplication, LauncherObject):
    def __init__(self, logger, log_capture_handler, debug: bool = False):
        super().__init__()
        self._system_palette = QPalette(self.palette()) # theme

        # logger
        self.logger = logger
        self.log_capture_handler = log_capture_handler

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
            self.load_settings()
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
        icon_existing = self.icon_path.exists()
        if icon_existing and platform.system().lower() != "darwin":
            self.setWindowIcon(QIcon(self.icon_path.as_posix()))
        elif not icon_existing:
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

    def locate_styles_path(self, relative_path: Path | str) -> Path:
        appearance = self.settings_manager.get("appearance", AppearanceSettings)
        theme = getattr(self, "_active_theme", appearance.theme)
        theme_directory = self._theme_packages().get(theme)

        if not theme_directory:
            return self.styles_path / relative_path

        full_path = theme_directory / "styles" / relative_path

        if not full_path.is_file():
            return self.styles_path / relative_path

        return full_path

    @property
    def built_in_themes_dir(self) -> Path:
        return self.resources_dir / "themes"

    @property
    def user_themes_dir(self) -> Path:
        return self.data_dir / "themes"

    def apply_qss(self, qss_relative_path: Path, apply_qss_callback: Callable[[str], None]) -> str:
        full_path = self.locate_styles_path(qss_relative_path)

        if not full_path.exists():
            messagebox.error(
                None,
                self.tr_text("Resource Error"),
                self.tr_text("Missing stylesheet file: {path}", path=full_path),
            )
            return ""

        try:
            data = full_path.read_text(encoding="utf-8")
            apply_qss_callback(data)
            target = getattr(apply_qss_callback, "__self__", None)
            if isinstance(target, QWidget):
                target.setProperty("qssRelativePath", str(qss_relative_path))
        except Exception as e:
            messagebox.error(
                None,
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

    def available_themes(self) -> dict[str, str]:
        """Return valid theme IDs and their display names."""
        themes = {"system": "Follow system settings"}
        for theme_id, directory in self._theme_packages().items():
            try:
                name = self._read_theme_manifest(directory / "theme.toml")
                colors = self._read_palette(directory / "palette.toml")
                self._palette_from_colors(colors)
            except (OSError, ValueError, tomllib.TOMLDecodeError) as error:
                self.logger.warning("Ignoring invalid theme %s: %s", directory, error)
                continue
            themes[theme_id] = name
        return themes

    def apply_theme(self, theme: str | None = None) -> None:
        if not theme:
            appearance = self.settings_manager.get("appearance", AppearanceSettings)
            theme = appearance.theme

        active_theme = theme
        if theme == "system":
            # Apply system palette
            palette = QPalette(self._system_palette)
        else:
            # Use custom theme pack palette
            directory = self._theme_packages().get(theme)
            if directory is None:
                self.logger.warning(
                    "Theme %r was not found; using the system theme instead.",
                    theme,
                )
                palette = QPalette(self._system_palette)
                active_theme = "system"
            else:
                try:
                    self._read_theme_manifest(directory / "theme.toml")
                    colors = self._read_palette(directory / "palette.toml")
                    palette = self._palette_from_colors(colors)
                except (OSError, ValueError, tomllib.TOMLDecodeError) as error:
                    self.logger.warning(
                        "Unable to apply theme %s; using the system theme: %s",
                        directory,
                        error,
                    )
                    palette = QPalette(self._system_palette)
                    active_theme = "system"

        self._active_theme = active_theme
        self.setPalette(palette)
        # Application-wide styles also reach parentless dialogs and message boxes.
        self.apply_qss(Path("main.qss"), self.setStyleSheet)

        for widget in self.allWidgets():
            qss_path = widget.property("qssRelativePath")
            if qss_path:
                self.apply_qss(Path(qss_path), widget.setStyleSheet)
            widget.style().unpolish(widget)
            widget.style().polish(widget)
            widget.update()

        if hasattr(self, "main_window"):
            self.reload_toolbutton_icons()
            self.main_window.toolbar.update_all()

    def _theme_packages(self) -> dict[str, Path]:
        """Discover theme package directories.

        User theme packages override built-in packages with the same directory
        name. A valid package contains both ``theme.toml`` and ``palette.toml``.
        """
        self.user_themes_dir.mkdir(parents=True, exist_ok=True)
        themes: dict[str, Path] = {}

        for directory in (self.built_in_themes_dir, self.user_themes_dir):
            if not directory.is_dir():
                continue

            for theme_dir in sorted(directory.iterdir()):
                if not theme_dir.is_dir() or theme_dir.name == "system":
                    continue

                themes[theme_dir.name] = theme_dir

        return themes

    @staticmethod
    def _read_theme_manifest(path: Path) -> str:
        with path.open("rb") as theme_file:
            data = tomllib.load(theme_file)

        name = data.get("name", path.parent.name)
        if not isinstance(name, str) or not name.strip():
            raise ValueError("theme name must be a non-empty string")
        return name.strip()

    @staticmethod
    def _read_palette(path: Path) -> Mapping[str, str]:
        with path.open("rb") as palette_file:
            data = tomllib.load(palette_file)

        colors = data.get("palette")
        if not isinstance(colors, dict):
            raise ValueError("palette must contain a [palette] table")

        missing = PALETTE_ROLES.keys() - colors.keys()
        if missing:
            raise ValueError(
                "palette file is missing palette colors: " + ", ".join(sorted(missing))
            )
        return colors

    @staticmethod
    def _palette_from_colors(colors: Mapping[str, str]) -> QPalette:
        palette = QPalette()
        for name, role in PALETTE_ROLES.items():
            value = colors[name]
            if not isinstance(value, str):
                raise ValueError(f"palette color {name!r} must be a string")
            color = QColor(value)
            if not color.isValid():
                raise ValueError(f"invalid palette color {name!r}: {value!r}")
            palette.setColor(role, color)
        return palette

    def load_settings(self):
        if hasattr(self, "settings_manager"):
            try:
                self.settings_manager.load()
            except Exception as e:
                messagebox.error_with_plain_text(
                    None,
                    "Settings Error",
                    "An unexpected error occurred while loading settings.",
                    f"Below are the raw data of the error\n\nError: {str(e)}\n\nTraceback:\n{traceback.format_exc()}",
                )
