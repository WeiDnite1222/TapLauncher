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
    QWidget, QScrollArea,
)

from constant import LAUNCHER_DESCRIPTION, LAUNCHER_NAME, LAUNCHER_VERSION
from manager.settings_models import AccountSettings, AppearanceSettings, GeneralSettings


LANGUAGE_LABELS = {
    "en": "English",
    "zh-TW": "Chinese (Traditional)",
}
THEME_LABELS = {
    "system": "Follow system settings",
    "light": "Light",
    "dark": "Dark",
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
    def __init__(self, title: str, back_callback) -> None:
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
        main_layout.addLayout(self.content_layout)
        main_layout.addStretch()


class SettingsPage(QWidget):
    def __init__(self, app, parent=None) -> None:
        super().__init__(parent)
        self.app = app
        self.settings = app.settings_manager
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
        for page in (
            self.main_page,
            self.general_page,
            self.appearance_page,
            self.account_page,
            self.about_page,
        ):
            self.stack.addWidget(page)

        root_layout.addWidget(self.stack)
        self.app.apply_qss(Path("settings.qss"), self.setStyleSheet)
        self.language_combo.currentIndexChanged.connect(self._mark_settings_dirty)
        self.client_id_edit.textEdited.connect(self._mark_settings_dirty)

        self.theme_combo.currentIndexChanged.connect(
            self._apply_selected_theme
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
        )
        for title_text, description, page_name in pages:
            button = SettingsItem(title_text, description)
            button.clicked.connect(
                lambda checked=False, name=page_name: self._open_page(
                    getattr(self, name)
                )
            )
            scroll_layout.addWidget(button)

        scroll_layout.addStretch()
        layout.addWidget(scroll_area)
        return page

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
        self.theme_combo = self._choice_combo(
            "appearance", "theme", THEME_LABELS, current.theme
        )
        page.content_layout.addWidget(self.theme_combo)
        return page

    def _create_account_page(self) -> QWidget:
        tr = self.app.tr_text
        page = SettingsSubPage(tr("Account"), self._go_back)
        current = self.settings.get("account", AccountSettings)

        page.content_layout.addWidget(QLabel(tr("Microsoft OAuth Client ID")))
        self.client_id_edit = QLineEdit(str(current.client_id))
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
        page = SettingsSubPage(tr("About"), self._go_back)
        brand_label = QLabel(LAUNCHER_NAME)
        brand_label.setObjectName("settingsBrand")
        version_label = QLabel(tr("Version: {version}", version=LAUNCHER_VERSION))
        version_label.setObjectName("settingsVersion")
        description = QPlainTextEdit(LAUNCHER_DESCRIPTION)
        description.setObjectName("settingsDescription")
        description.setReadOnly(True)

        page.content_layout.addWidget(brand_label)
        page.content_layout.addWidget(version_label)
        page.content_layout.addWidget(description)
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

        data = {
            "general": {"language": self.language_combo.currentData()},
            "appearance": {"theme": self.theme_combo.currentData()},
            "account": {"client_id": self.client_id_edit.text().strip()},
        }
        try:
            self.settings.validate(data)
            for section, value in data.items():
                self.settings.set(section, value)
            self.settings.save()
        except Exception as error:
            if show_error:
                QMessageBox.critical(self, self.app.tr_text("Settings error"), str(error))
            return False

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
