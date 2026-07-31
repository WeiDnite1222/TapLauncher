from pathlib import Path

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QListWidget, QPushButton, QHBoxLayout, QListWidgetItem, \
    QMenu


class AccountWidget(QWidget):
    def __init__(self, account_name, account_head: QPixmap, login_status, parent=None,
                /, delete_account_callback=None, check_account_callback=None, switch_account_callback=None):
        QWidget.__init__(self, parent)

        self.layout = QHBoxLayout(self)

        self.head_icon_label = QLabel()
        self.head_icon_label.setObjectName("HeadIcon")
        self.head_icon_label.setPixmap(account_head)

        self.account_name = QLabel(account_name)

        self.status_label = QLabel(login_status)

        self.layout.addWidget(self.head_icon_label)
        self.layout.addWidget(self.account_name)
        self.layout.addStretch()
        self.layout.addWidget(self.status_label)

        self.delete_account_callback = delete_account_callback
        self.check_account_callback = check_account_callback
        self.switch_account_callback = switch_account_callback

        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_right_click_menu)

    def show_right_click_menu(self, position):
        context_menu = QMenu(self)

        switch_acc_action = context_menu.addAction("Switch to this account")
        check_log_stat_action = context_menu.addAction("Check login status")

        context_menu.addSeparator()

        delete_account_action = context_menu.addAction("Delete account")

        global_position = self.mapToGlobal(position)

        selected_action = context_menu.exec(global_position)

        if selected_action == delete_account_action:
            # handle callback here
            if callable(self.delete_account_callback): self.delete_account_callback()
        elif selected_action == check_log_stat_action and callable(self.check_account_callback): self.check_account_callback()
        elif selected_action == switch_acc_action and callable(self.switch_account_callback): self.switch_account_callback()


class AccountPage(QWidget):
    def __init__(self, app, parent=None):
        QWidget.__init__(self, parent)
        self.app = app

        self.layout = QHBoxLayout()

        self.main_layout = QVBoxLayout()
        self.right_layout = QVBoxLayout()

        self.account_list = QListWidget(self)

        self.add_account_button = QPushButton("Add Account")
        self.refresh_button = QPushButton("Refresh all")
        self.delete_all_button = QPushButton("Delete All")

        self.main_layout.addWidget(self.account_list)
        self.right_layout.addWidget(self.add_account_button)
        self.right_layout.addWidget(self.refresh_button)
        self.right_layout.addWidget(self.delete_all_button)
        self.right_layout.addStretch()

        self.layout.addLayout(self.main_layout)
        self.layout.addLayout(self.right_layout)

        self.setLayout(self.layout)

        self.test()

    def test(self):
        head_icon = self.app.get_icon(Path(self.app.icon_dir, "head.png"))
        for i in range(1, 11):
            name = f"Player_{i}"
            head_pixmap = head_icon.pixmap(QSize(50, 50))
            list_item = QListWidgetItem()

            def delete():
                self.account_list.removeItemWidget(list_item)
            item = AccountWidget(name, head_pixmap, self, delete_account_callback=delete)
            list_item.setSizeHint(item.sizeHint())
            self.account_list.addItem(list_item)
            self.account_list.setItemWidget(list_item, item)


