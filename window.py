from pathlib import Path

from PySide6 import QtWidgets
from PySide6.QtCore import QSize
from PySide6.QtGui import QIcon, Qt, QPixmap
from PySide6.QtWidgets import QApplication, QMainWindow, QLabel, QVBoxLayout, QWidget, QToolButton, \
    QStackedWidget
from PySide6.QtCore import Slot
from PySide6.QtWidgets import QMessageBox, QFileDialog

from core_lib.qt import messagebox
from core_lib.qt.progress_dialog import ProgressDialog
from core_lib.qt.messagebox import ask_yes_no_with_plain_text
from constant import MAIN_REPO_URL
from manager.widgets import AskForRequest, SelectPathRequest
from pages.account import AccountPage
from pages.create_profile  import CreateProfilePage
from pages.launch_profile import LaunchProfilePage
from pages.manage_profile import ManageProfilePage
from pages.test import TestPage
from pages.settings import SettingsPage

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

class LauncherMainWindow(QMainWindow):
    def __init__(self, / ,app, parent: QWidget | None=None):
        super(LauncherMainWindow, self).__init__(parent)
        self.app = app
        self.widget_manager = app.widget_manager
        self.game_manager = app.game_manager

        # Main layout
        self.central = QStackedWidget()
        self.toolbar = ToolBar(self.app, self)

        # center message (will be deleted if launcher finished development)
        content = """Still digging!"""
        message = ("If you find an issue, you can report it in the main repository. "
                   "Suggestions are always welcome!")
        self.icon_label = QLabel()
        self.icon_label.setObjectName("icon_label")
        self.dev_info_box = QLabel(self.app.tr_text(content))
        self.dev_info_box.setObjectName("dev_info_box")
        self.dev_info_2 = QLabel(self.app.tr_text(message))
        self.dev_info_2.setObjectName("dev_info_message")
        self.version_label = QLabel(self.app.tr_text(
            "Current version: {version}", version=self.app.launcher_version
        ))
        self.version_label.setObjectName("version_label")
        self.repo_url_label = QLabel(
            f'<a href="{MAIN_REPO_URL}">{self.app.tr_text("Main repo")}</a>'
        )
        self.repo_url_label.setObjectName("repo_url_label")
        self.repo_url_label.setOpenExternalLinks(True)

        if Path(self.app.resources_dir, "pictures", "in_progress.png").exists():
            image = QPixmap(Path(self.app.resources_dir, "pictures", "in_progress.png"))
            self.icon_label.setPixmap(image.scaled(300, 300))
        else:
            self.icon_label.setText(self.app.tr_text("Ouch. The icon is missing."))

        # Dialog
        self.download_dialog = ProgressDialog(self)

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

        if self.app.debug:
            # test page
            self.test_page = TestPage(
                app=self.app,
                parent=self,
                widget_manager=self.app.widget_manager
            )

        self.launch_profile_page = LaunchProfilePage(
            app=self.app,
            parent=self,
        )

        # Account page
        self.account_page = AccountPage(self.app, self)

        # Profile page
        self.create_profile_page = CreateProfilePage(self.app, self)

        # Profile management page
        self.manage_profile_page = ManageProfilePage(self.app, self)

        # Settings page
        self.settings_page = SettingsPage(self.app, self)

        # Add page
        self.central.addWidget(self.home_page)
        if self.app.debug:
            self.central.addWidget(self.test_page)
        self.central.addWidget(self.account_page)
        self.central.addWidget(self.settings_page)
        self.central.addWidget(self.create_profile_page)
        self.central.addWidget(self.manage_profile_page)
        self.central.addWidget(self.launch_profile_page)

        # Bind toolbar and center widget
        self.addToolBar(Qt.ToolBarArea.LeftToolBarArea, self.toolbar)
        self.setCentralWidget(self.central)

        # Apply qss
        self.app.apply_qss(Path("main.qss"), self.setStyleSheet)
        self.app.apply_qss(Path("toolbar.qss"), self.toolbar.setStyleSheet)

        # Toolbar

        # Test Window btn
        if self.app.debug:
            self.open_test_page = self.toolbar.add_button(" Tests")
            self.app.set_reloadable_toolbutton_icon(
                self.open_test_page,
                Path(self.app.icon_dir, "debug.png"),
            )
            self.open_test_page.setObjectName("open_test_page")

        # Launch profile btn
        self.open_launch_profile_page = self.toolbar.add_button(" Launch Profile",
                                                                icon=self.app.get_icon(Path(self.app.icon_dir, "profile_default.png"), True))

        # Home btn
        self.home_button = self.toolbar.add_button(" Home")
        self.app.set_reloadable_toolbutton_icon(
            self.home_button,
            Path(self.app.icon_dir, "home.png"),
        )

        # Settings btn (will be moved to the bottom of the toolbar)
        self.open_settings_page = self.toolbar.add_button(" Settings")
        self.app.set_reloadable_toolbutton_icon(
            self.open_settings_page,
            Path(self.app.icon_dir, "settings.png"),
        )

        # Account btn (will be moved to the bottom (or last one item) of the toolbar
        self.open_account_page = self.toolbar.add_button(" Accounts", icon=self.app.get_icon(Path(self.app.icon_dir, "head.png"), True))
        self.account_page.set_related_button(self.open_account_page) # AccountPage require this to set button icon to
        # current account's avatar

        # Profile btn
        self.open_create_profile_page = self.toolbar.add_button("Create Profile")
        self.app.set_reloadable_toolbutton_icon(
            self.open_create_profile_page,
            Path(self.app.icon_dir, "add.png"),
        )

        # manage profile
        self.open_manage_profile_page = self.toolbar.add_button(
            " Manage Profiles",
            icon=self.app.get_icon(Path(self.app.icon_dir, "profile_edit.png"), True),
        )

        # Bind tool buttons
        self.toolbar.addWidget(self.home_button)
        if self.app.debug:
            self.toolbar.addWidget(self.open_test_page)
        self.toolbar.addWidget(self.open_create_profile_page)
        self.toolbar.addWidget(self.open_launch_profile_page)
        self.toolbar.addWidget(self.open_manage_profile_page)
        self.toolbar.setMovable(True)
        self.toolbar.setFloatable(False)
        self.toolbar.setAllowedAreas(Qt.ToolBarArea.AllToolBarAreas)

        self.toolbar.addWidget(self.toolbar.spacer)
        self.toolbar.addSeparator()
        self.toolbar.addWidget(self.open_settings_page)
        self.toolbar.addWidget(self.open_account_page)

        # Bind page-related button click event
        self.home_button.clicked.connect(
            lambda: self.set_current_page(self.home_page, self.home_button)
        )

        if self.app.debug:
            self.open_test_page.clicked.connect(
                lambda: self.set_current_page(self.test_page, self.open_test_page)
            )

        self.open_launch_profile_page.clicked.connect(
            lambda: self.set_current_page(self.launch_profile_page, self.open_launch_profile_page)
        )

        self.open_settings_page.clicked.connect(
            lambda: self.set_current_page(self.settings_page, self.open_settings_page)
        )

        self.open_account_page.clicked.connect(
            lambda: self.set_current_page(self.account_page, self.open_account_page)
        )

        self.open_create_profile_page.clicked.connect(
            lambda: self.set_current_page(self.create_profile_page, self.open_create_profile_page)
        )

        self.open_manage_profile_page.clicked.connect(
            lambda: self.set_current_page(self.manage_profile_page, self.open_manage_profile_page)
        )

        # Bind signal event
        self.bind_event()

        self.set_current_page(self.home_page, self.home_button)
        self.app.i18n.language_changed.connect(self.retranslate_ui)
        self.retranslate_ui()

    def retranslate_ui(self, *_args):
        tr = self.app.tr_text
        self.dev_info_box.setText(tr("Still digging!"))
        self.dev_info_2.setText(tr(
            "If you find an issue, you can report it in the main repository. "
            "Suggestions are always welcome!"
        ))
        self.version_label.setText(
            tr("Current version: {version}", version=self.app.launcher_version)
        )
        self.repo_url_label.setText(
            f'<a href="{MAIN_REPO_URL}">{tr("Main repo")}</a>'
        )
        self.home_button.setText(" " + tr("Home"))
        self.open_launch_profile_page.setText(" " + tr("Launch Profile"))
        self.open_settings_page.setText(" " + tr("Settings"))
        self.open_account_page.setText(" " + tr("Accounts"))
        self.open_create_profile_page.setText(" " + tr("Create Profile"))
        self.open_manage_profile_page.setText(" " + tr("Manage Profiles"))
        if self.app.debug:
            self.open_test_page.setText(" " + tr("Tests"))
        self.toolbar.update_all()

    @Slot(object)
    def ask_request(self, context: AskForRequest):
        if not context.use_plain_text:
            msg = QMessageBox.question(
                self,
                context.title,
                context.message,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            result = msg == QMessageBox.StandardButton.Yes
        else:
            result = ask_yes_no_with_plain_text(
                self,
                context.title,
                context.message,
                context.details,
            )

        if result:
            context.result_queue.put(True)
        else:
            context.result_queue.put(False)

        context.wait_event.set()

    @Slot(object)
    def ask_for_path(self, context: SelectPathRequest):
        path, _ = QFileDialog.getOpenFileName(
            self,
            context.title,
            "",
            context.filter,
        )

        context.result_queue.put(path)

        context.wait_event.set()

    @Slot(dict)
    def show_and_print_error(self, context: dict):
        error = context.get("error", None)
        title = context.get("title", self.app.tr_text("Error"))
        message = context.get("message", self.app.tr_text("No content"))

        if isinstance(error, list):
            self.app.logger.error("".join(error))
        elif isinstance(error, str):
            self.app.logger.error(error)
        elif isinstance(error, Exception):
            self.app.logger.exception(error)

        messagebox.error(
            self,
            title,
            message=message
        )

    @Slot(object)
    def enable_widget(self, widget):
        widget.setEnabled(True)

    @Slot(object)
    def disable_widget(self, widget):
        widget.setDisabled(True)

    @Slot(str)
    def show_error(self, message):
        messagebox.error(self, self.app.tr_text("Error"), message=message)

    @Slot(str)
    def show_warning(self, widget):
        messagebox.warning(self, self.app.tr_text("Warning"), message=widget)

    @Slot(str)
    def show_info(self, widget):
        messagebox.info(self, self.app.tr_text("Info"), message=widget)

    def set_current_page(self, page: QWidget, related_button: QToolButton):
        self.central.setCurrentWidget(page)
        related_button.setFocus()

    def bind_event(self):
        download_signal = self.widget_manager.download_signal
        widget_signal = self.widget_manager.signal

        download_signal.started.connect(
            self.download_dialog.add_task,
            Qt.ConnectionType.QueuedConnection,
        )
        download_signal.progress.connect(
            self.download_dialog.update_task,
            Qt.ConnectionType.QueuedConnection,
        )
        download_signal.finished.connect(
            self.download_dialog.finish_task,
            Qt.ConnectionType.QueuedConnection,
        )
        download_signal.failed.connect(
            self.download_dialog.fail_task,
            Qt.ConnectionType.QueuedConnection,
        )
        download_signal.removed.connect(
            self.download_dialog.remove_task,
            Qt.ConnectionType.QueuedConnection,
        )

        widget_signal.show_error_message.connect(
            self.show_error,
            Qt.ConnectionType.QueuedConnection,
        )
        
        widget_signal.show_warning_message.connect(
            self.show_warning,
            Qt.ConnectionType.QueuedConnection,
        )

        widget_signal.show_info_message.connect(
            self.show_info,
            Qt.ConnectionType.QueuedConnection,
        )

        widget_signal.show_and_print_error_message.connect(
            self.show_and_print_error
        )

        widget_signal.enable_widget.connect(
            self.enable_widget,
            Qt.ConnectionType.QueuedConnection,
        )

        widget_signal.disable_widget.connect(
            self.disable_widget,
            Qt.ConnectionType.QueuedConnection,
        )

        widget_signal.askyesno.connect(
            self.ask_request
        )

        widget_signal.ask_for_path.connect(
            self.ask_for_path
        )
