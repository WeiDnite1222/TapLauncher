import logging
import textwrap

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMainWindow, QPushButton, QVBoxLayout, QWidget, QDialog, QPlainTextEdit, \
    QHBoxLayout
from core_lib.qt.hack import move_window_to_center
from core_lib.unclassified import get_latest_version, get_version_manifest, get_specific_version_manifest_url, \
    fetch_specific_version_manifest, find_useful_part_in_specific_version_manifest


class Launcher(QApplication):
    def __init__(self):
        super().__init__()
        self.setApplicationName("TestLauncher")
        self.main_window = QMainWindow()
        self.main_window.setGeometry(0, 0, 800, 600)

        move_window_to_center(self.main_window)

        self.logger = logging.getLogger("Launcher.MainWindow")

        self.test_dialog = self.TestDialog(self.main_window)
        self.test_dialog.show()

    class TestDialog(QDialog):
        def __init__(self, parent):
            super().__init__(parent)
            self.parent = parent
            self.resize(300, 200)
            self.setWindowFlags(self.windowFlags() | Qt.WindowMaximizeButtonHint)

            self.button = QPushButton("Fetch Version Data")
            self.button.setObjectName("ActionButton")
            self.button.clicked.connect(self.run_test)

            self.output = QPlainTextEdit()
            self.output.setReadOnly(True)

            self.layout = QHBoxLayout()
            self.layout.addWidget(self.output)

            self.right_layout = QVBoxLayout()
            self.right_layout.setObjectName("RightLayout")
            self.right_layout.setAlignment(Qt.AlignmentFlag.AlignRight)
            self.right_layout.addWidget(self.button)
            self.right_layout.addStretch()
            self.right_layout.setContentsMargins(0, 10, 0, 0)

            self.layout.addLayout(self.right_layout)

            self.setLayout(self.layout)

            self.setStyleSheet(
                textwrap.dedent("""
                QPushButton#ActionButton {
                    padding: 6px 12px;
                }          
                """))

        @property
        def app(self):
            return self.parent.parent

        def run_test(self):
            data = get_version_manifest()
            ver = get_latest_version(data)
            ver_data = fetch_specific_version_manifest(data, ver)
            arguments, asset_index, downloads, java_version, libraries, main_class = (
                find_useful_part_in_specific_version_manifest(ver_data))

            content = textwrap.dedent(f"""\
            Arguments: {arguments}\n
            
            Asset: {asset_index}\n
            
            Downloads: {downloads}\n
            
            Java Version: {java_version}\n
            
            Libraries: {libraries}\n
            
            Main Class: {main_class}\n
            """)

            self.output.setPlainText(content)

    def exec(self):
        self.main_window.show()
        self.exec_()
