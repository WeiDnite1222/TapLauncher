from __future__ import annotations

import webbrowser
from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal, QTimer
from PySide6.QtGui import QPixmap, QFontDatabase
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget, QDialog, QLineEdit, QApplication,
)

from constant import CLIENT_ID, MICROSOFT_VERIFY_ENDPOINT

from core_lib.qt.hack import move_window_to_center
from manager.account import AccountManager, AccountSummary


class AccountWidget(QWidget):
    def __init__(self, account_name: str, account_head: QPixmap, login_status: str,  parent=None,
        /, delete_account_callback=None, check_account_callback=None, switch_account_callback=None,):
        super().__init__(parent)

        # Layout
        self.layout = QHBoxLayout(self)

        # Widgets
        self.head_icon_label = QLabel()
        self.head_icon_label.setObjectName("HeadIcon")
        self.head_icon_label.setFixedSize(account_head.size())
        self.head_icon_label.setPixmap(account_head)

        self.account_name = QLabel(account_name)
        self.status_label = QLabel(login_status)

        # Bind widgets
        self.layout.addWidget(self.head_icon_label)
        self.layout.addWidget(self.account_name)
        self.layout.addStretch()
        self.layout.addWidget(self.status_label)

        # Callback
        self.delete_account_callback = delete_account_callback
        self.check_account_callback = check_account_callback
        self.switch_account_callback = switch_account_callback

        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_right_click_menu)

    def show_right_click_menu(self, position):
        menu = QMenu(self)
        switch_action = menu.addAction("Switch to this account")
        check_action = menu.addAction("Check login status")
        menu.addSeparator()
        delete_action = menu.addAction("Delete account")
        selected = menu.exec(self.mapToGlobal(position))

        if selected == delete_action and callable(self.delete_account_callback):
            self.delete_account_callback()
        elif selected == check_action and callable(self.check_account_callback):
            self.check_account_callback()
        elif selected == switch_action and callable(self.switch_account_callback):
            self.switch_account_callback()

class LoginDialog(QDialog):
    def __init__(self, app, parent=None, code="", error_message=""):
        super().__init__(parent)
        self.app = app
        self.setWindowTitle("Microsoft Login")
        self.setMinimumWidth(440)
        self.setMinimumHeight(380)
        self.resize(440, 420)
        move_window_to_center(self)

        # Layout
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(24, 22, 24, 22)
        self.layout.setSpacing(14)

        # Top widgets
        self.title_label = QLabel("Login Minecraft Account")
        self.title_label.setObjectName("dialogTitle")
        self.help_label = QLabel("Copy the code below, then continue in your browser.")
        self.help_label.setObjectName("helpText")
        self.help_label.setWordWrap(True)

        # Center
        self.code_edit = QLineEdit()
        self.code_edit.setObjectName("codeEdit")
        self.code_edit.setReadOnly(True)
        self.code_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.code_edit.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.code_edit.setText(code)
        self.code_label = self.code_edit
        self.error_label = QLabel()
        self.error_label.setObjectName("errorMessage")
        self.error_label.setWordWrap(True)
        self.error_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        # Button
        self.copy_code_button = QPushButton("Copy code")
        self.copy_code_button.setObjectName("copyCodeButton")
        self.open_browser_button = QPushButton("Open browser")
        self.open_browser_button.setObjectName("openBrowserButton")

        self.center_layout = QVBoxLayout()
        self.center_layout.setSpacing(10)
        self.center_layout.addWidget(self.code_edit)
        self.center_layout.addWidget(self.error_label)

        self.button_layout = QHBoxLayout()
        self.button_layout.setSpacing(8)
        self.button_layout.addWidget(self.copy_code_button)
        self.button_layout.addWidget(self.open_browser_button)

        self.layout.addWidget(self.title_label)
        self.layout.addWidget(self.help_label)
        self.layout.addStretch()
        self.layout.addLayout(self.center_layout)
        self.layout.addStretch()
        self.layout.addLayout(self.button_layout)
        self.set_error_message(error_message)

        self.copy_code_button.clicked.connect(self.copy_code)

        self.app.apply_qss(Path("login_dialog.qss"), self.setStyleSheet)

    @property
    def code(self):
        return self.code_edit.text()

    def set_code(self, code):
        self.code_edit.setText(str(code or ""))

    def copy_code(self):
        QApplication.clipboard().setText(self.code)
        self.copy_code_button.setText("Copied!")
        self.copy_code_button.setEnabled(False)
        QTimer.singleShot(1200, self._reset_copy_button)

    def _reset_copy_button(self):
        self.copy_code_button.setText("Copy code")
        self.copy_code_button.setEnabled(True)

    def set_error_message(self, message):
        message = str(message or "").strip()
        self.error_label.setText(message)
        self.error_label.setVisible(bool(message))

class AccountPage(QWidget):
    account_authenticated = Signal(dict)

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.widget_manager = app.widget_manager
        self.account_manager: AccountManager = app.account_manager
        self.client_id = CLIENT_ID

        self.login_dialog = None

        # Layout
        main_layout = QVBoxLayout()
        right_layout = QVBoxLayout()
        layout = QHBoxLayout(self)

        # Widgets
        self.account_list = QListWidget(self)
        self.add_account_button = QPushButton("Add Account")
        self.refresh_button = QPushButton("Refresh all")
        self.delete_all_button = QPushButton("Delete All")

        # Button click handle
        self.add_account_button.clicked.connect(self.start_login_page)
        self.refresh_button.clicked.connect(self.refresh_accounts)
        self.delete_all_button.clicked.connect(self.account_manager.delete_all_accounts)

        # Bind widget
        main_layout.addWidget(self.account_list)
        right_layout.addWidget(self.add_account_button)
        right_layout.addWidget(self.refresh_button)
        right_layout.addWidget(self.delete_all_button)
        right_layout.addStretch()

        layout.addLayout(main_layout, 1)
        layout.addLayout(right_layout)

        self.account_manager.accounts_changed.connect(self._render_accounts)
        self.account_manager.current_account_changed.connect(self._current_account_changed)
        self.account_manager.login_signal.device_code_ready.connect(self._show_device_code)
        self.account_manager.login_signal.login_succeeded.connect(self._login_succeeded)
        self.account_manager.login_signal.login_failed.connect(self._login_failed)
        self.account_manager.login_signal.finished.connect(self._login_finished)
        self.account_manager.head_signal.updated.connect(self._account_head_updated)
        self._render_accounts()

    def _render_accounts(self):
        self.account_list.clear()

        current_id = self.account_manager.get_current_account_id()
        accounts = self.account_manager.list_accounts()

        # Add suggestion to account list if no account available
        if not accounts:
            empty_item = QListWidgetItem("No accounts yet. Use Add Account to sign in.")
            empty_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.account_list.addItem(empty_item)

        for account in accounts:
            self._add_account_item(account, account.id == current_id)

    def _add_account_item(self, account: AccountSummary, is_current: bool):
        list_item = QListWidgetItem()
        list_item.setData(Qt.ItemDataRole.UserRole, account.id)

        head_size = QSize(32, 32)
        widget = AccountWidget(
            account.display_name,
            self.account_manager.get_head_pixmap(account.avatar, head_size),
            "Current" if is_current else "Available",
            self,
            delete_account_callback=lambda: self._delete_account(account.id),
            check_account_callback=lambda: self._show_account_status(account.id),
            switch_account_callback=lambda: self._switch_account(account.id),
        )

        list_item.setSizeHint(widget.sizeHint())
        self.account_list.addItem(list_item)
        self.account_list.setItemWidget(list_item, widget)

        if not self.account_manager.has_saved_head(account.avatar):
            self.account_manager.request_account_head(
                account.id,
                account.minecraft_name or account.username,
                max(head_size.width(), head_size.height()),
            )

    def _account_head_updated(self, account_id: str):
        account = self.account_manager.get_account(account_id)
        if account is None:
            return

        for row in range(self.account_list.count()):
            item = self.account_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) != account_id:
                continue
            widget = self.account_list.itemWidget(item)
            if isinstance(widget, AccountWidget):
                widget.head_icon_label.setPixmap(
                    self.account_manager.get_head_pixmap(account.avatar, QSize(32, 32))
                )
            break

    def _delete_account(self, account_id: str):
        if self.account_manager.remove_account(account_id):
            self.account_manager.save()

    def _show_account_status(self, account_id: str):
        account = self.account_manager.get_account(account_id)

        if account is None:
            return

        QMessageBox.information(
            self,
            "Account status",
            f"{account.display_name} — Minecraft profile "
            f"{'available' if account.minecraft_uuid else 'not available'}",
        )

    def _switch_account(self, account_id: str):
        self.account_manager.set_current_account(account_id)
        self.account_manager.save()

    def _current_account_changed(self, _account_id):
        self._render_accounts()

    def refresh_accounts(self):
        self.account_manager.reload()

    # Microsoft sign-in
    def start_login_page(self):
        # Active existing login dialog
        if self.login_dialog is not None:
            self.login_dialog.raise_()
            self.login_dialog.activateWindow()
            return

        # Create login dialog
        self.add_account_button.setEnabled(False)
        self.login_dialog = LoginDialog(parent=self, app=self.app)
        self.login_dialog.help_label.setText("Requesting a Microsoft sign-in code…")
        self.login_dialog.copy_code_button.setEnabled(False)
        self.login_dialog.open_browser_button.setEnabled(False)
        self.login_dialog.open_browser_button.clicked.connect(self.open_sign_in_page)
        self.login_dialog.rejected.connect(self.account_manager.cancel_login)
        self.login_dialog.show()

        self.account_manager.start_login()

    def _show_device_code(self, device: dict):
        self._verification_uri = device.get("verification_uri", MICROSOFT_VERIFY_ENDPOINT)

        if self.login_dialog is not None:
            self.login_dialog.help_label.setText(
                device.get("message") or "Copy the code below, then continue in your browser."
            )
            self.login_dialog.set_code(device.get("user_code", ""))
            self.login_dialog.copy_code_button.setEnabled(True)
            self.login_dialog.open_browser_button.setEnabled(True)

        self.open_sign_in_page()

    def open_sign_in_page(self):
        webbrowser.open(self._verification_uri)

    def _login_succeeded(self, account: dict):
        created_id = self.account_manager.login_succeeded(account)

        # Cleanup
        if self.login_dialog is not None:
            dialog = self.login_dialog
            self.login_dialog = None
            dialog.accept()
            dialog.deleteLater()

        if created_id is not None:
            self.account_authenticated.emit({"account_id": created_id})

    def _login_failed(self, message: str):
        if self.login_dialog is not None:
            self.login_dialog.set_error_message(message)
            self.login_dialog.help_label.setText("Microsoft sign-in could not be completed.")
            self.login_dialog.copy_code_button.setEnabled(False)
            self.login_dialog.open_browser_button.setEnabled(False)
        else:
            QMessageBox.critical(self, "Microsoft sign-in failed", message)

    def _login_finished(self):
        self.add_account_button.setEnabled(True)
