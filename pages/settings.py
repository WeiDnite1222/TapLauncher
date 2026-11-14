import uuid
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QImageReader, QPixmap
from PySide6.QtWidgets import (
    QComboBox, QCheckBox, QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget, QScrollArea, QSizePolicy, QSpinBox, QTextBrowser,
)

from constant import LAUNCHER_NAME, LAUNCHER_VERSION, LAUNCHER_DESCRIPTION_KEYWORD, \
    LAUNCHER_DESCRIPTION_MARKDOWN, LAUNCHER_DESCRIPTION_MARKDOWN_KEYWORD
from core_lib.qt import messagebox
from manager.settings_models import AccountSettings, AppearanceSettings, GeneralSettings, GameSettings, PageBarSettings
from pages.plugins import PluginsDialog

LANGUAGE_LABELS = {
    "en": "English",
    "zh-TW": "Chinese (Traditional)",
}
POSITION_LABELS = {
    "left": "Left",
    "right": "Right",
    "top": "Top",
    "bottom": "Bottom",
}
CREDENTIALS_SAVE_METHODS = {
    "system-keyring": "Use system keyring",
    "file": "Save as a regular file",
}
COMPATIBILITY_MODE_LABELS = {
    "none": "Disabled",
    "official-launcher": "Minecraft Launcher",
}
LAUNCH_ACTION_LABELS = {
    "close": "Close launcher window",
    "stay-open": "Keep launcher open",
    "minimize": "Minimize launcher window",
}


class SettingsItem(QPushButton):
    def __init__(self, title: str, description: str = "") -> None:
        super().__init__()
        self.setObjectName("settingsItem")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 10, 16, 10)
        layout.setSpacing(3)

        title_label = QLabel(title)
        title_label.setObjectName("settingsItemTitle")
        title_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(title_label)

        if description:
            description_label = QLabel(description)
            description_label.setObjectName("settingsItemDescription")
            description_label.setAttribute(
                Qt.WidgetAttribute.WA_TransparentForMouseEvents
            )
            layout.addWidget(description_label)


class SettingsSubPage(QWidget):
    def __init__(self, title: str, back_callback, /, expand_content: bool = False) -> None:
        super().__init__()
        self.setObjectName("settingsSubPage")

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 16, 20, 20)
        main_layout.setSpacing(16)

        header_layout = QHBoxLayout()
        back_button = QPushButton("←")
        back_button.setObjectName("settingsBackButton")
        back_button.setFixedSize(36, 36)
        back_button.setCursor(Qt.CursorShape.PointingHandCursor)
        back_button.clicked.connect(back_callback)

        title_label = QLabel(title)
        title_label.setObjectName("settingsSubPageTitle")
        header_layout.addWidget(back_button)
        header_layout.addWidget(title_label)
        header_layout.addStretch()

        self.content_layout = QVBoxLayout()
        main_layout.addLayout(header_layout)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(6)
        if expand_content:
            main_layout.addLayout(self.content_layout, 1)
        else:
            main_layout.addLayout(self.content_layout)
        main_layout.addStretch()

    def add_section_title(self, title: str) -> None:
        if self.content_layout.count():
            self.content_layout.addSpacing(16)
        label = QLabel(title)
        label.setObjectName("settingsSectionTitle")
        font = label.font()
        font.setPointSize(12)
        font.setBold(True)
        label.setFont(font)
        self.content_layout.addWidget(label)


class SettingsPage(QWidget):
    def __init__(self, app, parent=None) -> None:
        super().__init__(parent)
        self.app = app
        self.settings = app.settings_manager
        self.account_mgr = app.account_manager
        self._settings_dirty = False
        self.setObjectName("settingsPage")

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()

        self.main_page = self._create_main_page()
        self.general_page = self._create_general_page()
        self.game_page = self._create_game_page()
        self.appearance_page = self._create_appearance_page()
        self.account_page = self._create_account_page()
        self.about_page = self._create_about_page()
        self.log_page = self._create_log_page()
        for page in (
                self.main_page,
                self.general_page,
                self.game_page,
                self.appearance_page,
                self.account_page,
                self.about_page,
                self.log_page,
        ):
            self.stack.addWidget(page)

        root_layout.addWidget(self.stack)
        self.app.apply_qss(Path("settings.qss"), self.setStyleSheet)
        self.language_combo.currentIndexChanged.connect(self._mark_settings_dirty)
        self.client_id_edit.textEdited.connect(self._mark_settings_dirty)

        self.theme_combo.currentIndexChanged.connect(
            self._apply_selected_theme
        )

        self.credentials_save_method.currentIndexChanged.connect(
            self._mark_settings_dirty
        )
        self.app.i18n.language_changed.connect(self.retranslate_ui)

    def _apply_selected_theme(self) -> None:
        theme = self.theme_combo.currentData()
        self.app.apply_theme(theme)
        self._mark_settings_dirty()

    def retranslate_ui(self, *_args) -> None:
        """Rebuild this page so every label uses the active catalog."""
        current_page = self.stack.currentIndex()
        while self.stack.count():
            old_page = self.stack.widget(0)
            self.stack.removeWidget(old_page)
            old_page.deleteLater()

        self.main_page = self._create_main_page()
        self.general_page = self._create_general_page()
        self.game_page = self._create_game_page()
        self.appearance_page = self._create_appearance_page()
        self.account_page = self._create_account_page()
        self.about_page = self._create_about_page()
        for page in (
                self.main_page,
                self.general_page,
                self.game_page,
                self.appearance_page,
                self.account_page,
                self.about_page,
        ):
            self.stack.addWidget(page)
        self.stack.setCurrentIndex(min(current_page, self.stack.count() - 1))
        self.language_combo.currentIndexChanged.connect(self._mark_settings_dirty)
        self.client_id_edit.textEdited.connect(self._mark_settings_dirty)
        self.theme_combo.currentIndexChanged.connect(self._apply_selected_theme)

    def _create_main_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("settingsMainPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)

        scroll_area = QScrollArea()
        scroll_area.setObjectName("settingsScrollArea")
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)

        scroll_content = QWidget()
        scroll_content.setObjectName("settingsScrollContent")
        scroll_area.setWidget(scroll_content)
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(24, 20, 24, 24)
        scroll_layout.setSpacing(12)

        tr = self.app.tr_text
        title = QLabel(tr("Settings"))
        title.setObjectName("settingsPageTitle")
        scroll_layout.addWidget(title)
        scroll_layout.addSpacing(8)

        pages = (
            (tr("General"), tr("Language and launcher directories"), "general_page"),
            (tr("Game"), tr("Game downloading and launching configuration"), "game_page"),
            (tr("Appearance"), tr("Launcher theme"), "appearance_page"),
            (tr("Account"), tr("Microsoft authentication settings"), "account_page"),
            (tr("About"), tr("Version and project information"), "about_page"),
            (tr("Logger"), tr("Launcher log"), "log_page"),
        )
        for title_text, description, page_name in pages:
            button = SettingsItem(title_text, description)
            button.clicked.connect(
                lambda checked=False, name=page_name: self._open_page(
                    getattr(self, name)
                )
            )
            scroll_layout.addWidget(button)

        plugins_button = SettingsItem(tr("Plugins"), tr("Browse installed plugins"))
        plugins_button.clicked.connect(self._open_plugins_dialog)
        scroll_layout.addWidget(plugins_button)
        scroll_layout.addStretch()
        layout.addWidget(scroll_area)
        return page

    def _open_plugins_dialog(self):
        dialog = PluginsDialog(self.app, self.app.plugin_manager, self)
        dialog.setWindowFlags(Qt.Window)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dialog.show()

    def _create_general_page(self) -> QWidget:
        tr = self.app.tr_text
        page = SettingsSubPage(tr("General"), self._go_back)
        current = self.settings.get("general", GeneralSettings)
        pagebar_setting = self.settings.get("page-bar", PageBarSettings)

        page.add_section_title(tr("Environment Information"))
        page.content_layout.addWidget(QLabel(tr("Current launcher working directory")))
        launcher_dir = QLineEdit(self.app.work_dir.as_posix())
        launcher_dir.setReadOnly(True)
        page.content_layout.addWidget(launcher_dir)

        page.content_layout.addWidget(QLabel(tr("Current program directory")))
        program_dir = QLineEdit(self.app.program_dir.as_posix())
        program_dir.setReadOnly(True)
        page.content_layout.addWidget(program_dir)

        page.content_layout.addWidget(QLabel(tr("Current game directory")))
        program_dir = QLineEdit(self.app.game_dir.as_posix())
        program_dir.setReadOnly(True)
        page.content_layout.addWidget(program_dir)

        page.add_section_title(tr("Language"))
        self.language_combo = self._choice_combo(
            "general", "language", LANGUAGE_LABELS, current.language
        )
        page.content_layout.addWidget(self.language_combo)
        page.add_section_title(tr("PageBar"))
        self.reset_to_last_used_page = QCheckBox(tr("Reset to last used page"))
        self.reset_to_last_used_page.setChecked(pagebar_setting.focus_at_after_restart)
        self.reset_to_last_used_page.toggled.connect(
            self._mark_settings_dirty
        )
        page.content_layout.addWidget(self.reset_to_last_used_page)

        page.content_layout.addSpacing(2)
        page.content_layout.addWidget(QLabel(tr("Position")))
        self.pagebar_position_combo = self._choice_combo(
            "page-bar", "page_bar_position", POSITION_LABELS, pagebar_setting.page_bar_position
        )
        self.pagebar_position_combo.currentIndexChanged.connect(
            self._mark_settings_dirty
        )
        page.content_layout.addWidget(self.pagebar_position_combo)

        page.content_layout.addSpacing(2)
        page.add_section_title(tr("Compatibility Mode"))
        self.compatibility_mode_combo = self._choice_combo(
            "general", "compatibility_mode", COMPATIBILITY_MODE_LABELS, current.compatibility_mode
        )
        self.compatibility_mode_combo.currentIndexChanged.connect(
            self._mark_settings_dirty
        )
        page.content_layout.addWidget(self.compatibility_mode_combo)
        page.content_layout.addSpacing(2)
        return page

    def _create_game_page(self) -> QWidget:
        tr = self.app.tr_text
        page = SettingsSubPage(tr("Game"), self._go_back)
        current = self.settings.get("game", GameSettings)

        page.add_section_title(tr("Download"))
        self.verify_hash_on_download = QCheckBox(tr("Verify file hashes when downloading"))
        self.verify_hash_on_download.setChecked(current.verify_hash_on_download)
        self.verify_hash_on_download.toggled.connect(self._mark_settings_dirty)
        page.content_layout.addWidget(self.verify_hash_on_download)

        page.add_section_title(tr("Game Launching"))
        self.verify_hash_on_launch = QCheckBox(tr("Verify library hashes before launch"))
        self.verify_hash_on_launch.setChecked(current.verify_hash_on_launch)
        self.verify_hash_on_launch.toggled.connect(self._mark_settings_dirty)
        page.content_layout.addWidget(self.verify_hash_on_launch)

        self.open_log_view_when_launch = QCheckBox(tr("Open game log when launching"))
        self.open_log_view_when_launch.setChecked(current.open_log_view_when_launch)
        self.open_log_view_when_launch.toggled.connect(self._mark_settings_dirty)
        page.content_layout.addWidget(self.open_log_view_when_launch)

        page.content_layout.addWidget(QLabel(tr("After game launch")))
        self.action_after_launch = self._choice_combo(
            "game", "action_after_launch", LAUNCH_ACTION_LABELS, current.action_after_launch
        )
        self.action_after_launch.currentIndexChanged.connect(self._mark_settings_dirty)
        page.content_layout.addWidget(self.action_after_launch)

        return page

    def _create_appearance_page(self) -> QWidget:
        tr = self.app.tr_text
        page = SettingsSubPage(tr("Appearance"), self._go_back)
        current = self.settings.get("appearance", AppearanceSettings)

        # Theme
        page.add_section_title(tr("Theme"))
        self.theme_combo = QComboBox()
        for theme_id, name in self.app.available_themes().items():
            self.theme_combo.addItem(tr(name), theme_id)

        index = self.theme_combo.findData(current.theme)
        self.theme_combo.setCurrentIndex(max(index, 0))
        page.content_layout.addWidget(self.theme_combo)

        help_label = QLabel(tr(
            "Add theme folders containing theme.toml and palette.toml to: {path}",
            path=self.app.user_themes_dir,
        ))
        help_label.setObjectName("settingsHelpText")
        help_label.setWordWrap(True)
        page.content_layout.addWidget(help_label)

        # Launch game page background
        page.add_section_title(tr("Launch page background"))
        self.launch_background = current.launch_background
        self.background_preview = QLabel()
        self.background_preview.setFixedSize(320, 180)
        self.background_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        page.content_layout.addWidget(self.background_preview)
        self._update_background_preview()
        background_actions = QHBoxLayout()
        choose_background = QPushButton(tr("Choose background image"))
        choose_background.clicked.connect(self._choose_launch_background)
        reset_background = QPushButton(tr("Restore default background"))
        reset_background.clicked.connect(self._reset_launch_background)
        background_actions.addWidget(choose_background)
        background_actions.addWidget(reset_background)
        background_actions.addStretch()
        page.content_layout.addLayout(background_actions)
        return page

    def _update_background_preview(self):
        path = self.launch_background or str(Path(self.app.icon_dir, "profile_default.png"))
        pixmap = QPixmap(path)
        self.background_preview.setPixmap(pixmap.scaled(
            320, 180, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        ))

    def _choose_launch_background(self):
        formats = " ".join("*." + bytes(fmt).decode("ascii")
                           for fmt in QImageReader.supportedImageFormats())
        filename, _ = QFileDialog.getOpenFileName(
            self, self.app.tr_text("Choose background image"), "",
            self.app.tr_text("Images") + f" ({formats})",
        )
        if not filename:
            return
        reader = QImageReader(filename)
        reader.setDecideFormatFromContent(True)
        reader.setAutoTransform(True)
        image = reader.read()
        if image.isNull():
            QMessageBox.warning(self, self.app.tr_text("Settings error"),
                                self.app.tr_text("Image format is not supported."))
            return
        try:
            directory = Path(self.app.work_dir) / "backgrounds"
            directory.mkdir(parents=True, exist_ok=True)
            destination = directory / f"{uuid.uuid4().hex}.png"
            if not image.save(str(destination), "PNG"):
                raise OSError(self.app.tr_text("Unable to save background image."))
        except OSError as error:
            QMessageBox.warning(self, self.app.tr_text("Settings error"), str(error))
            return
        self.launch_background = str(destination.resolve())
        self._update_background_preview()
        self._mark_settings_dirty()

    def _reset_launch_background(self):
        self.launch_background = ""
        self._update_background_preview()
        self._mark_settings_dirty()

    def _create_account_page(self) -> QWidget:
        tr = self.app.tr_text
        page = SettingsSubPage(tr("Account"), self._go_back)
        current = self.settings.get("account", AccountSettings)

        # TokeUpdater
        page.add_section_title(tr("TokenUpdater"))

        self.enable_token_updater_checkbox = QCheckBox(tr("Enable token updater"))
        page.content_layout.addWidget(self.enable_token_updater_checkbox)
        page.content_layout.addWidget(QLabel(tr("Token refresh check interval")))
        self.token_refresh_interval = QSpinBox()
        self.token_refresh_interval.setRange(1, 1440)  # minutes
        self.token_refresh_interval.setSingleStep(1)
        self.token_refresh_interval.setSuffix(
            " " + tr("minutes")
        )
        self.token_refresh_interval.setValue(current.token_refresh_interval // 60)
        self.token_refresh_interval.valueChanged.connect(self._mark_settings_dirty)
        page.content_layout.addWidget(self.token_refresh_interval)

        page.add_section_title(tr("Custom"))

        page.content_layout.addWidget(QLabel(tr("Credentials save method")))
        self.credentials_save_method = self._choice_combo(
            "account", "credentials_save_method", CREDENTIALS_SAVE_METHODS,
            current.credentials_save_method,
        )
        page.content_layout.addWidget(self.credentials_save_method)

        page.content_layout.addWidget(QLabel(tr("Microsoft OAuth Client ID")))
        custom_client_id_raw = self.account_mgr.settings_custom_client_id

        if not custom_client_id_raw:
            custom_client_id = ""
        else:
            custom_client_id = custom_client_id_raw

        self.client_id_edit = QLineEdit(str(custom_client_id))
        self.client_id_edit.setPlaceholderText(
            "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
        )
        page.content_layout.addWidget(self.client_id_edit)

        help_label = QLabel(tr(
            "The Client ID must belong to an Azure application configured "
            "for Microsoft device-code authentication."
        ))
        help_label.setObjectName("settingsHelpText")
        help_label.setWordWrap(True)
        page.content_layout.addWidget(help_label)
        return page

    def _create_about_page(self) -> QWidget:
        tr = self.app.tr_text
        page = SettingsSubPage(tr("About"), self._go_back, expand_content=True)
        brand_label = QLabel(LAUNCHER_NAME)
        brand_label.setObjectName("settingsBrand")
        version_label = QLabel(tr("Version: {version}", version=LAUNCHER_VERSION))
        version_label.setObjectName("settingsVersion")

        description_text = self.app.tr_text(LAUNCHER_DESCRIPTION_MARKDOWN_KEYWORD)
        description = QTextBrowser()
        # description.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        description.setObjectName("settingsDescription")
        description.setReadOnly(True)
        description.setOpenExternalLinks(True)

        data = description_text if description_text != LAUNCHER_DESCRIPTION_MARKDOWN_KEYWORD else LAUNCHER_DESCRIPTION_MARKDOWN
        description.setMarkdown(data)

        page.content_layout.addWidget(brand_label)
        page.content_layout.addWidget(version_label)
        page.content_layout.addWidget(description)
        return page

    def _create_log_page(self) -> QWidget:
        tr = self.app.tr_text
        page = SettingsSubPage(tr("Log View"), self._go_back, expand_content=True)
        messages = "\n".join(self.app.log_capture_handler.get_messages())
        log_text = QPlainTextEdit(messages)
        log_text.setObjectName("settingsLogText")
        log_text.setReadOnly(True)
        self.app.log_capture_handler.emitter.message_emitted.connect(
            log_text.appendPlainText
        )
        log_text.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        page.content_layout.addWidget(log_text, 1)
        return page

    def _choice_combo(
            self,
            section: str,
            field: str,
            labels: dict[str, str],
            current: str,
    ) -> QComboBox:
        combo = QComboBox()
        for value in self.settings.choices(section, field):
            combo.addItem(
                self.app.tr_text(labels.get(value, str(value))),
                value,
            )
        index = combo.findData(current)
        combo.setCurrentIndex(max(index, 0))
        return combo

    def _mark_settings_dirty(self, *_args) -> None:
        self._settings_dirty = True

    def _save_pending_settings(self, *, show_error: bool = True) -> bool:
        if not self._settings_dirty:
            return True

        previous_credentials_method = (
            self.settings
            .get("account", AccountSettings)
            .credentials_save_method  # sec
        )

        previous_token_refresh_interval = (
            self.settings.get("account", AccountSettings)
            .token_refresh_interval
        )

        previous_page_bar_position = (
            self.settings.get("page-bar", PageBarSettings)
            .page_bar_position
        )

        previous_compatibility_mode = (
            self.settings.get("general", GeneralSettings)
            .compatibility_mode
        )

        current_token_refresh_interval = (
                self.token_refresh_interval.value() * 60  # minutes to seconds
        )

        selected_credentials_method = (
            self.credentials_save_method.currentData()
        )

        current_page_bar_position = self.pagebar_position_combo.currentData()
        current_compatibility_mode = self.compatibility_mode_combo.currentData()

        credentials_method_changed = (
                previous_credentials_method
                != selected_credentials_method
        )

        token_refresh_interval_changed = (
                previous_token_refresh_interval
                != current_token_refresh_interval
        )

        previous_page_bar_position_changed = (
                previous_page_bar_position
                != current_page_bar_position
        )

        compatibility_mode_changed = (
                previous_compatibility_mode
                != current_compatibility_mode
        )

        client_id = self.client_id_edit.text().strip()

        try:
            client_id = uuid.UUID(client_id) if client_id else None
        except ValueError:
            if show_error:
                QMessageBox.warning(
                    self,
                    self.app.tr_text("Invalid Client ID"),
                    self.app.tr_text(
                        "Client ID must be a valid UUID.\n\n"
                        "Example: 12345678-1234-5678-9abc-123456789abc"
                    ),
                )

            self.client_id_edit.setFocus()
            self.client_id_edit.selectAll()
            return False

        old_theme = self.settings.get("appearance", AppearanceSettings).theme
        data = {
            "general": {"language": self.language_combo.currentData(),
                        "compatibility_mode": current_compatibility_mode},
            "page-bar": {
                "page_bar_position": current_page_bar_position,
                "focus_at_after_restart": self.reset_to_last_used_page.isChecked()
            },
            "game": {"verify_hash_on_download": self.verify_hash_on_download.isChecked(),
                     "verify_hash_on_launch": self.verify_hash_on_launch.isChecked(),
                     "open_log_view_when_launch": self.open_log_view_when_launch.isChecked(),
                     "action_after_launch": self.action_after_launch.currentData()},
            "appearance": {"theme": self.theme_combo.currentData(),
                           "launch_background": self.launch_background},
            "account": {"custom_client_id": client_id if client_id else None,
                        "credentials_save_method": selected_credentials_method,
                        "token_refresh_interval":
                            current_token_refresh_interval
                        }
        }
        try:
            self.settings.validate(data)
            for section, value in data.items():
                self.settings.set(section, value)
            self.settings.save()

            # Handle credentials data migration
            if credentials_method_changed:
                success, _ = self.account_mgr.reload()

                if not success:
                    # Rollback to previous credentials method if migration failed
                    rollback_account = dict(data["account"])
                    rollback_account["credentials_save_method"] = (
                        previous_credentials_method
                    )

                    self.settings.set("account", rollback_account)
                    self.settings.save()

                    index = self.credentials_save_method.findData(
                        previous_credentials_method
                    )
                    self.credentials_save_method.setCurrentIndex(index)

                    if show_error:
                        QMessageBox.critical(
                            self,
                            self.app.tr_text("Credential migration failed"),
                            self.app.tr_text(
                                "The credential storage method was restored "
                                "to its previous value."
                            ),
                        )
                    return False

            # Handle token refresh interval update
            if token_refresh_interval_changed:
                self.account_mgr.set_token_refresh_interval(current_token_refresh_interval)
        except Exception as error:
            if show_error:
                QMessageBox.critical(self, self.app.tr_text("Settings error"), str(error))
            return False

        if old_theme != self.settings.get("appearance", AppearanceSettings).theme:
            messagebox.info(None, "Launcher",
                            self.app.tr_text("To make all page apply new theme."
                                             " Is recommend to restart the launcher after change it."))

        if previous_page_bar_position_changed:
            main_window = getattr(self.app, "main_window")

            if main_window:
                main_window.apply_page_bar_settings()

        if compatibility_mode_changed:
            messagebox.info(
                None,
                "Launcher",
                self.app.tr_text(
                    "Compatibility mode changed. Please restart the launcher to apply the changes."
                )
            )

        self._settings_dirty = False
        selected_language = data["general"]["language"]
        self.app.apply_language(selected_language)
        return True

    def _open_page(self, page: QWidget) -> None:
        self.stack.setCurrentWidget(page)

    def _go_back(self) -> None:
        if self._save_pending_settings():
            self.stack.setCurrentWidget(self.main_page)

    def hideEvent(self, event) -> None:
        self._save_pending_settings()
        super().hideEvent(event)
