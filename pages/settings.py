import uuid
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget, QScrollArea, QSizePolicy, QSpinBox,
)

from constant import LAUNCHER_DESCRIPTION, LAUNCHER_NAME, LAUNCHER_VERSION, LAUNCHER_DESCRIPTION_KEYWORD
from core_lib.qt import messagebox
from manager.settings_models import AccountSettings, AppearanceSettings, GeneralSettings
from pages.plugins import PluginsDialog

LANGUAGE_LABELS = {
    "en": "English",
    "zh-TW": "Chinese (Traditional)",
}
CREDENTIALS_SAVE_METHODS = {
    "system-keyring": "Use system keyring",
    "file": "Save as a regular file",
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
        self.content_layout.setSpacing(12)
        main_layout.addLayout(header_layout)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(6)
        if expand_content:
            main_layout.addLayout(self.content_layout, 1)
        else:
            main_layout.addLayout(self.content_layout)
        main_layout.addStretch()


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
        self.appearance_page = self._create_appearance_page()
        self.account_page = self._create_account_page()
        self.about_page = self._create_about_page()
        self.log_page = self._create_log_page()
        for page in (
                self.main_page,
                self.general_page,
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
        self.appearance_page = self._create_appearance_page()
        self.account_page = self._create_account_page()
        self.about_page = self._create_about_page()
        for page in (
                self.main_page,
                self.general_page,
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

        page.content_layout.addWidget(QLabel(tr("Current launcher working directory")))
        launcher_dir = QLineEdit(self.app.work_dir.as_posix())
        launcher_dir.setReadOnly(True)
        page.content_layout.addWidget(launcher_dir)

        page.content_layout.addWidget(QLabel(tr("Current program directory")))
        program_dir = QLineEdit(self.app.program_dir.as_posix())
        program_dir.setReadOnly(True)
        page.content_layout.addWidget(program_dir)

        page.content_layout.addSpacing(8)
        page.content_layout.addWidget(QLabel(tr("Language")))
        self.language_combo = self._choice_combo(
            "general", "language", LANGUAGE_LABELS, current.language
        )
        page.content_layout.addWidget(self.language_combo)
        return page

    def _create_appearance_page(self) -> QWidget:
        tr = self.app.tr_text
        page = SettingsSubPage(tr("Appearance"), self._go_back)
        current = self.settings.get("appearance", AppearanceSettings)

        page.content_layout.addWidget(QLabel(tr("Theme")))
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
        return page

    def _create_account_page(self) -> QWidget:
        tr = self.app.tr_text
        page = SettingsSubPage(tr("Account"), self._go_back)
        current = self.settings.get("account", AccountSettings)

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

        page.content_layout.addWidget(
            QLabel(tr("Token refresh check interval"))
        )

        self.token_refresh_interval = QSpinBox()
        self.token_refresh_interval.setRange(1, 1440) # minutes
        self.token_refresh_interval.setSingleStep(1)
        self.token_refresh_interval.setSuffix(
            " " + tr("minutes")
        )
        self.token_refresh_interval.setValue(current.token_refresh_interval // 60)

        self.token_refresh_interval.valueChanged.connect(self._mark_settings_dirty)

        page.content_layout.addWidget(self.token_refresh_interval)
        page.content_layout.addWidget(help_label)
        return page

    def _create_about_page(self) -> QWidget:
        tr = self.app.tr_text
        page = SettingsSubPage(tr("About"), self._go_back, expand_content=True)
        brand_label = QLabel(LAUNCHER_NAME)
        brand_label.setObjectName("settingsBrand")
        version_label = QLabel(tr("Version: {version}", version=LAUNCHER_VERSION))
        version_label.setObjectName("settingsVersion")

        description_text = self.app.tr_text(LAUNCHER_DESCRIPTION_KEYWORD)
        description = QPlainTextEdit(description_text if description_text != LAUNCHER_DESCRIPTION_KEYWORD else LAUNCHER_DESCRIPTION)
        description.setObjectName("settingsDescription")
        description.setReadOnly(True)

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
            .credentials_save_method # sec
        )

        previous_token_refresh_interval = (
            self.settings.get("account", AccountSettings)
            .token_refresh_interval
        )

        current_token_refresh_interval = (
                self.token_refresh_interval.value() * 60 # minutes to seconds
        )

        selected_credentials_method = (
            self.credentials_save_method.currentData()
        )

        credentials_method_changed = (
                previous_credentials_method
                != selected_credentials_method
        )

        token_refresh_interval_changed = (
            previous_token_refresh_interval
            != current_token_refresh_interval
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
            "general": {"language": self.language_combo.currentData()},
            "appearance": {"theme": self.theme_combo.currentData()},
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

        if old_theme !=self.settings.get("appearance", AppearanceSettings).theme:
            messagebox.info(None, "Launcher",
                            self.app.tr_text("To make all page apply new theme."
                                         " Is recommend to restart the launcher after change it."))

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
