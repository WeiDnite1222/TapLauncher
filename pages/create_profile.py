from pathlib import Path

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QWidget, QVBoxLayout, QComboBox, QListWidget, QPushButton, QLabel, QHBoxLayout

from core_lib.launcher.object import Launcher as LauncherObject

class CreateProfile(QWidget):
    def __init__(self, app, parent=None):
        super(CreateProfile, self).__init__(parent)
        self.app = app

        self.layout = QHBoxLayout()

        self.main_layout = QVBoxLayout()
        self.right_layout = QVBoxLayout()
        self.operate_layout = QHBoxLayout()

        # Some items
        self.version_type_label = QLabel("Version Type")
        self.version_type_dropdown = QComboBox()
        self.version_type_dropdown.setObjectName("Dropdown")

        self.mod_loader_icon_label = QLabel()
        icon = self.app.get_icon(Path(self.app.icon_dir, "mod_loader_temp.png"))
        pixmap = icon.pixmap(QSize(100, 100))
        self.mod_loader_icon_label.setPixmap(pixmap)
        self.mod_loader_label = QLabel("Mod Loader")
        self.mod_loader_dropdown = QComboBox()
        self.mod_loader_dropdown.setObjectName("Dropdown")

        self.version_list_type_label = QLabel("Version: Vanilla")
        self.version_list_label = QLabel("Select a version to continue:")
        self.version_list = QListWidget()
        self.version_list.setObjectName("ListWidget")

        self.create_profile = QPushButton("Create Profile")
        self.create_profile.setObjectName("Button")

        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setObjectName("Button")

        self.main_layout.addWidget(self.version_list_label)
        self.main_layout.addWidget(self.version_list)
        self.operate_layout.addWidget(self.version_list_type_label)
        self.operate_layout.addStretch()
        self.operate_layout.addWidget(self.refresh_button)
        self.operate_layout.addWidget(self.create_profile)

        self.main_layout.addLayout(self.operate_layout)

        self.right_layout.addWidget(self.mod_loader_icon_label)
        self.right_layout.addWidget(self.mod_loader_label)
        self.right_layout.addWidget(self.mod_loader_dropdown)
        self.right_layout.addWidget(self.version_type_label)
        self.right_layout.addWidget(self.version_type_dropdown)
        self.right_layout.addStretch()
        self.right_layout.setContentsMargins(0, 20, 0, 0)

        self.setLayout(self.layout)
        self.layout.addLayout(self.main_layout)
        self.layout.addLayout(self.right_layout)

