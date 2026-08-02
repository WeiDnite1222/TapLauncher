from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPalette, QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget, QLineEdit,
)


class SettingsItem(QPushButton):
    """
    A modern look settings button.
    """
    clicked_page = Signal()

    def __init__(self, title: str, description: str = ""):
        super().__init__()

        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # Widget size
        self.setMinimumHeight(68)
        self.setMaximumWidth(800)

        # Layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 10, 16, 10)
        layout.setSpacing(3)

        # Widgets
        self.title_label = QLabel(title)
        self.title_label.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents
        )

        self.description_label = QLabel(description)
        self.description_label.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents
        )

        layout.addWidget(self.title_label)

        # Show description if existing
        if description:
            layout.addWidget(self.description_label)

        self.update_palette()

    def update_palette(self):
        """
        Apply system palette
        :return:
        """
        palette = self.palette()

        button_text = palette.color(QPalette.ColorRole.ButtonText)
        placeholder_text = palette.color(QPalette.ColorRole.PlaceholderText)

        title_palette = self.title_label.palette()
        title_palette.setColor(
            QPalette.ColorRole.WindowText,
            button_text,
        )
        self.title_label.setPalette(title_palette)

        description_palette = self.description_label.palette()
        description_palette.setColor(
            QPalette.ColorRole.WindowText,
            placeholder_text,
        )
        self.description_label.setPalette(description_palette)

        title_font = self.title_label.font()
        title_font.setPointSize(11)
        title_font.setWeight(QFont.Weight.Bold)
        self.title_label.setFont(title_font)

        description_font = self.description_label.font()
        description_font.setPointSize(9)
        self.description_label.setFont(description_font)


class SettingsSubPage(QWidget):
    def __init__(self, title: str, back_callback):
        super().__init__()

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 16, 20, 20)
        main_layout.setSpacing(16)

        header_layout = QHBoxLayout()

        self.back_button = QPushButton("←")
        self.back_button.setFixedSize(36, 36)
        self.back_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.back_button.clicked.connect(back_callback)

        self.title_label = QLabel(title)

        title_font = self.title_label.font()
        title_font.setPointSize(15)
        title_font.setBold(True)
        self.title_label.setFont(title_font)

        header_layout.addWidget(self.back_button)
        header_layout.addWidget(self.title_label)
        header_layout.addStretch()

        self.content_layout = QVBoxLayout()
        self.content_layout.setSpacing(12)

        main_layout.addLayout(header_layout)
        main_layout.addLayout(self.content_layout)
        main_layout.addStretch()

        self.update_palette()

    def update_palette(self):
        # Apply system palette
        palette = self.palette()

        button_color = palette.color(QPalette.ColorRole.Button)
        border_color = palette.color(QPalette.ColorRole.Mid)

        self.back_button.setStyleSheet("""
            QPushButton {
                border: none;
                border-radius: 8px;
                background-color: transparent;
                font-size: 22px;
            }

            QPushButton:hover {
                background-color: palette(button);
            }

            QPushButton:pressed {
                background-color: palette(midlight);
            }
        """)

    def changeEvent(self, event):
        # Update when system palette change
        if event.type() in (
            event.Type.PaletteChange,
            event.Type.ApplicationPaletteChange,
        ):
            self.update_palette()

        super().changeEvent(event)


class SettingsPage(QWidget):
    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app

        self.setWindowTitle("Settings")
        self.resize(560, 440)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)

        self.stack = QStackedWidget()

        self.main_page = self.create_main_page()
        self.general_page = self.create_general_page()
        self.appearance_page = self.create_appearance_page()
        self.profile_page = self.create_profile_page()

        self.stack.addWidget(self.main_page)
        self.stack.addWidget(self.general_page)
        self.stack.addWidget(self.appearance_page)
        self.stack.addWidget(self.profile_page)

        root_layout.addWidget(self.stack)

    def create_main_page(self) -> QWidget:
        page = QWidget()

        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 20, 24, 24)
        layout.setSpacing(12)

        title = QLabel("Settings")

        title_font = title.font()
        title_font.setPointSize(18)
        title_font.setBold(True)
        title.setFont(title_font)

        # Setting options
        info_button = SettingsItem(
            "Wait!",
            "Setting page is not full implemented yet.",
        )

        general_button = SettingsItem(
            "General",
            "Some general settings for launcher ",
        )
        general_button.clicked.connect(
            lambda: self.open_page(self.general_page)
        )

        appearance_button = SettingsItem(
            "Appearance",
            "Settings to change the launcher look like",
        )
        appearance_button.clicked.connect(
            lambda: self.open_page(self.appearance_page)
        )

        profile_button = SettingsItem(
            "Profile",
            "Store profile settings",
        )
        profile_button.clicked.connect(
            lambda: self.open_page(self.profile_page)
        )

        layout.addWidget(title)
        layout.addSpacing(8)
        layout.addWidget(info_button)
        layout.addWidget(general_button)
        layout.addWidget(appearance_button)
        layout.addWidget(profile_button)
        layout.addStretch()

        return page

    def create_general_page(self) -> QWidget:
        page = SettingsSubPage("General", self.go_back)

        language_label = QLabel("Language")

        language_combo = QComboBox()
        language_combo.addItems([
            "English",
            "Chinese (Traditional)",
        ])

        launcher_dir_label = QLabel("Current launcher working directory")
        launcher_dir = QLineEdit(self.app.work_dir.as_posix())
        launcher_dir.setReadOnly(True)

        program_dir_label = QLabel("Current program directory")
        program_dir = QLineEdit(self.app.program_dir.as_posix())
        program_dir.setReadOnly(True)

        page.content_layout.addWidget(launcher_dir_label)
        page.content_layout.addWidget(launcher_dir)
        page.content_layout.addWidget(program_dir_label)
        page.content_layout.addWidget(program_dir)
        page.content_layout.addSpacing(8)
        page.content_layout.addWidget(language_label)
        page.content_layout.addWidget(language_combo)

        return page

    def create_appearance_page(self) -> QWidget:
        page = SettingsSubPage("Appearance", self.go_back)

        theme_label = QLabel("Theme")

        theme_combo = QComboBox()
        theme_combo.addItems([
            "Follow system settings",
            "Light (unfinished)",
            "Dark",
        ])

        page.content_layout.addWidget(theme_label)
        page.content_layout.addWidget(theme_combo)

        return page

    def create_profile_page(self) -> QWidget:
        page = SettingsSubPage("Profile", self.go_back)

        test_label = QLabel("Still in development...")

        page.content_layout.addWidget(test_label)

        return page

    def open_page(self, page: QWidget):
        self.stack.setCurrentWidget(page)

    def go_back(self):
        self.stack.setCurrentWidget(self.main_page)