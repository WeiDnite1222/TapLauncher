from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel


class AccountPage(QWidget):
    def __init__(self, app, parent=None):
        QWidget.__init__(self, parent)
        self.app = app

        self.layout = QVBoxLayout()

        # center message (will be deleted if launcher finished development)
        content = """Still digging!"""
        message = "If you found that something might be a issue. You can report it to the main repo! Any suggestion are welcome."
        self.icon_label = QLabel()
        self.icon_label.setObjectName("icon_label")
        self.dev_info_box = QLabel(content)
        self.dev_info_box.setObjectName("dev_info_box")
        self.dev_info_2 = QLabel(message)
        self.dev_info_2.setObjectName("dev_info_message")

        self.layout.addStretch()
        self.layout.addWidget(self.icon_label, alignment=Qt.AlignmentFlag.AlignCenter)
        self.layout.addWidget(self.dev_info_box, alignment=Qt.AlignmentFlag.AlignHCenter)
        self.layout.addWidget(self.dev_info_2, alignment=Qt.AlignmentFlag.AlignHCenter)
        self.layout.addStretch()

        if Path(self.app.resources_dir, "pictures", "in_progress.png").exists():
            image = QPixmap(Path(self.app.resources_dir, "pictures", "in_progress.png"))
            self.icon_label.setPixmap(image.scaled(300, 300))
        else:
            self.icon_label.setText("Ouch. The icon is missing.")

        self.setLayout(self.layout)
        self.app.apply_qss(Path("main.qss"), self.setStyleSheet)