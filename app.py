import logging
import textwrap
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMainWindow, QPushButton, QVBoxLayout, QDialog, QPlainTextEdit, \
    QHBoxLayout

from core_lib.common.common import download_file, FileObject, download_multiple_files
from core_lib.qt.hack import move_window_to_center
from core_lib.game.version_info import get_version_manifest, get_latest_version, \
    fetch_specific_version_manifest, find_useful_part_in_specific_version_manifest, get_core_file_download_url_and_hash


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
            self.resize(800, 600)
            self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowMaximizeButtonHint)

            self.button = QPushButton("Fetch Version Data")
            self.button.setObjectName("ActionButton")
            self.button.clicked.connect(self.run_test)

            self.button_2 = QPushButton("Download client")
            self.button_2.setObjectName("ActionButton")
            self.button_2.clicked.connect(self.run_download_client)

            self.button_3 = QPushButton("Download libraries")
            self.button_3.setObjectName("ActionButton")
            self.button_3.clicked.connect(self.run_download_libraries)

            self.output = QPlainTextEdit()
            self.output.setReadOnly(True)

            self.layout = QHBoxLayout()
            self.layout.addWidget(self.output)

            self.right_layout = QVBoxLayout()
            self.right_layout.setObjectName("RightLayout")
            self.right_layout.setAlignment(Qt.AlignmentFlag.AlignRight)
            self.right_layout.addWidget(self.button)
            self.right_layout.addWidget(self.button_2)
            self.right_layout.addWidget(self.button_3)
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
            self.output.clear()
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

        def run_download_client(self):
            self.output.clear()

            data = get_version_manifest()
            ver = get_latest_version(data)
            ver_data = fetch_specific_version_manifest(data, ver)
            url, sha1 = get_core_file_download_url_and_hash(ver_data)

            dest = Path(Path(__file__).parent, "temp", f"client-{ver}.jar")

            if url:
                file = FileObject(dest, url=url)
                download_file(file)
            else:
                self.output.setPlainText("Download URL not found.")
                return

            self.output.setPlainText("Client downloaded." if dest.exists() else "Client not found.")

        def run_download_libraries(self):
            self.output.clear()

            def log_file_downloaded(filepath):
                self.output.appendPlainText(f"Downloaded {filepath}.")

            data = get_version_manifest()
            ver = get_latest_version(data)
            ver_data = fetch_specific_version_manifest(data, ver)
            _, _, _, _, libraries, _ = find_useful_part_in_specific_version_manifest(ver_data)

            output_dir = Path(Path(__file__).parent, "tmp", f"libraries-{ver}")

            output_dir.mkdir(parents=True, exist_ok=True)

            items = []

            for library in libraries:
                url = library.get("downloads", {}).get("artifact", {}).get("url")
                sha1 = library.get("downloads", {}).get("artifact", {}).get("sha1")
                relative_path = library.get("downloads", {}).get("artifact", {}).get("path")
                full_path = output_dir / relative_path

                if not url:
                    continue

                file = FileObject(full_path, url=url, sha1=sha1)
                items.append(file)

            download_multiple_files(items, download_callback=log_file_downloaded)


    def exec(self):
        self.main_window.show()
        self.exec_()
