import re
import textwrap
import threading
from pathlib import Path

from PySide6.QtCore import Qt, QObject, Signal
from PySide6.QtWidgets import QPushButton, QVBoxLayout, QDialog, QPlainTextEdit, \
    QHBoxLayout, QComboBox

from core_lib.common.common import download_file, FileObject, download_multiple_files, get_platform_info
from core_lib.game.library import generate_formatted_artifact_with_name, get_natives_platform_info, is_library_allowed, \
    is_native_allowed, is_legacy_native_allowed
from core_lib.game.version_info import get_version_manifest, \
    fetch_specific_version_manifest, find_useful_part_in_specific_version_manifest, get_core_file_download_url_and_hash, \
    get_all_versions, get_available_version_types, get_specific_version_manifest_url_and_hash
from core_lib.qt import messagebox


class TestDialog(QDialog):
    def __init__(self, app, parent):
        super().__init__(parent)
        self.app = app
        self.parent = parent
        self.resize(800, 600)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowMaximizeButtonHint)

        self.button = QPushButton("Fetch Version Data")
        self.button.setObjectName("ActionButton")
        self.button.clicked.connect(self.run_test)

        self.button_6 = QPushButton("Download Version Data")
        self.button_6.setObjectName("ActionButton")
        self.button_6.clicked.connect(self.run_download_specific_version_manifest)

        self.button_2 = QPushButton("Download client")
        self.button_2.setObjectName("ActionButton")
        self.button_2.clicked.connect(self.run_download_client)

        self.button_3 = QPushButton("Download libraries")
        self.button_3.setObjectName("ActionButton")
        self.button_3.clicked.connect(self.run_download_libraries)

        self.button_4 = QPushButton("Download and unzip natives")
        self.button_4.setObjectName("ActionButton")
        self.button_4.clicked.connect(lambda : self.run_download_and_unzip_natives())

        self.button_5 = QPushButton("Refresh versions")
        self.button_5.setObjectName("ActionButton")
        self.button_5.clicked.connect(self.load_all_version)

        self.ver_dropdown = QComboBox()
        self.ver_dropdown.setObjectName("Dropdown")

        self.ver_type_dropdown = QComboBox()
        self.ver_type_dropdown.setObjectName("Dropdown")

        self.ver_type_dropdown.currentTextChanged.connect(
            self.load_all_version
        )

        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)

        self.layout = QHBoxLayout()
        self.layout.addWidget(self.output)

        self.right_layout = QVBoxLayout()
        self.right_layout.setObjectName("RightLayout")
        self.right_layout.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.right_layout.addWidget(self.button)
        self.right_layout.addWidget(self.button_6)
        self.right_layout.addWidget(self.button_2)
        self.right_layout.addWidget(self.button_3)
        self.right_layout.addWidget(self.button_4)
        self.right_layout.addStretch()
        self.right_layout.addWidget(self.ver_type_dropdown)
        self.right_layout.addWidget(self.ver_dropdown)
        self.right_layout.addWidget(self.button_5)
        self.right_layout.setContentsMargins(0, 10, 0, 0)

        self.layout.addLayout(self.right_layout)

        self.setLayout(self.layout)

        self.setStyleSheet(
            textwrap.dedent("""
            QPushButton#ActionButton {
                padding: 6px 12px;
            }          
            """))

        # Bind signal functions
        self.download_signal = self.DownloadSignal(self)
        self.widget_signal = self.WidgetSignal(self)

        self.download_signal.log.connect(
            self.output.appendPlainText
        )

        self.download_signal.finished.connect(
            lambda count: self.output.appendPlainText(
                f"Download finished, failed: {count}"
            )
        )

        self.download_signal.progress.connect(
            lambda name, progress: self.output.setPlainText(
                f"Downloading {name}: {self.get_progress(progress)}"
            )
        )

        self.widget_signal.clean_ver_types_dropdown.connect(
            self.ver_type_dropdown.clear
        )

        self.widget_signal.update_types_dropdown.connect(
            lambda types: self.update_type_dropdown(types)
        )

        self.widget_signal.clean_vers_dropdown.connect(
            self.ver_dropdown.clear
        )

        self.widget_signal.update_vers_dropdown.connect(
            lambda vers: self.update_version_dropdown(vers)
        )

        self.widget_signal.show_error_message.connect(
            lambda msg: messagebox.error(
                self.parent,
                "Error",
                message=msg
            )
        )

        self.widget_signal.show_info_message.connect(
            lambda msg: messagebox.info(
                self.parent,
                "Info",
                message=msg
            )
        )

        self.widget_signal.enable_widget.connect(
            lambda widget: widget.setEnabled(True)
        )

        self.widget_signal.disable_widget.connect(
            lambda widget: widget.setDisabled(True)
        )

        self.load_all_types()

    class DownloadSignal(QObject):
        log = Signal(str)
        finished = Signal(int)
        failed = Signal(str)
        progress = Signal(str, int)

    class WidgetSignal(QObject):
        clean_ver_types_dropdown = Signal()
        clean_vers_dropdown = Signal()
        update_vers_dropdown = Signal(list)
        update_types_dropdown = Signal(list)
        show_error_message = Signal(str)
        show_info_message = Signal(str)
        enable_widget = Signal(object)
        disable_widget = Signal(object)

    @staticmethod
    def get_progress(value):
        width = 30
        filled = int(width * value / 100)

        bar = "█" * filled + "░" * (width - filled)

        return f"[{bar}] {value:.1f}%"

    def update_type_dropdown(self, types: list):
        if "release" in types:
            types.pop(types.index("release"))
            types.insert(0, "release")

        self.ver_type_dropdown.addItems(types)

        if len(self.ver_type_dropdown.currentText()) == 0:
            self.ver_type_dropdown.setCurrentIndex(0)

    def update_version_dropdown(self, versions: list):
        ids = []

        for version in versions:
            ver_id = version.get("id", None)
            if ver_id is not None:
                ids.append(ver_id)

        self.ver_dropdown.addItems(ids)

        if len(self.ver_dropdown.currentText()) == 0:
            self.ver_dropdown.setCurrentIndex(0)

    def run_test(self):
        self.button.setDisabled(True)

        self.output.clear()
        data = get_version_manifest()
        ver = self.ver_dropdown.currentText()

        if len(ver) == 0 or ver is None:
            messagebox.error(
                self.parent,
                "Error",
                "Please select a version before running the test.",
            )

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
        self.button.setDisabled(False)

    def run_download_specific_version_manifest(self):
        self.button_6.setDisabled(True)

        self.output.clear()

        thread = threading.Thread(
            target=self._download_specific_version_manifest,
            daemon=True,
        )
        thread.start()

    def run_download_client(self):
        self.button_2.setDisabled(True)

        self.output.clear()

        thread = threading.Thread(
            target=self._download_client,
            daemon=True,
        )
        thread.start()

        # self.output.setPlainText("Client downloaded." if dest.exists() else "Client not found.")

    def run_download_libraries(self):
        self.button_3.setDisabled(True)

        self.output.clear()

        thread = threading.Thread(
            target=self._download_libraries_process,
            daemon=True,
        )
        thread.start()

    def run_download_and_unzip_natives(self):
        self.button_4.setDisabled(True)

        self.output.clear()

        thread = threading.Thread(
            target=self._download_and_unzip_natives,
            daemon=True,
        )
        thread.start()

    def load_all_version(self):
        ver_type = self.ver_type_dropdown.currentText()

        thread = threading.Thread(
            target=self._load_all_version,
            daemon=True,
            args=(ver_type,)
        )
        thread.start()
        self.download_signal.log.emit("Loading all versions...")

    def load_all_types(self):
        thread = threading.Thread(
            target=self._load_all_types,
            daemon=True
        )
        thread.start()
        self.download_signal.log.emit("Loading all types...")

    # All functions below that must be run in background thread
    def _load_all_types(self):
        self.widget_signal.clean_ver_types_dropdown.emit()
        data = get_version_manifest()
        ver_types = get_available_version_types(data)
        self.widget_signal.update_types_dropdown.emit(ver_types)

    def _load_all_version(self, ver_type):
        self.widget_signal.clean_vers_dropdown.emit()
        data = get_version_manifest()
        vers = get_all_versions(
            data,
            specific_type=ver_type
        )
        self.widget_signal.update_vers_dropdown.emit(vers)

    def _download_specific_version_manifest(self, ver=None):
        data = get_version_manifest()

        if not ver:
            ver = self.ver_dropdown.currentText()

        if not ver:
            self.widget_signal.show_error_message.emit(
                "Select a version before download the version manifest."
            )
            return

        ver_manifest_url, sha1 = get_specific_version_manifest_url_and_hash(data, ver)

        if ver_manifest_url is None:
            self.widget_signal.show_error_message.emit(
                f"Unable to get the version {ver} manifest url."
            )
            return
        else:
            self.download_signal.log.emit(f"Version {ver} manifest url: {ver_manifest_url} sha1: {sha1}")

        filepath = Path(self.app.work_dir, "versions", ver, f"{ver}.json")

        manifest_file = FileObject(
            filepath,
            url=ver_manifest_url,
            sha1=sha1,
        )

        if not manifest_file.exists or manifest_file.verify("sha1", sha1):
            download_file(manifest_file, progress_callback=self.download_signal.progress.emit)

        self.download_signal.log.emit(f"File {filepath} downloaded.")
        self.widget_signal.enable_widget.emit(self.button_6)

    def _download_client(self, ver=None):
        data = get_version_manifest()

        if not ver:
            ver = self.ver_dropdown.currentText()

        if not ver:
            self.widget_signal.show_error_message.emit(
                "Select a version before download the client."
            )
            return

        ver_data = fetch_specific_version_manifest(data, ver)
        url, sha1 = get_core_file_download_url_and_hash(ver_data)

        dest = Path(self.app.work_dir, "versions", ver, "client.jar")

        file = FileObject(dest, url=url)

        if sha1 is None:
            self.app.logger.warning("Client has no sha1.")

        if file.exists and file.verify("sha1", sha1):
            self.download_signal.log.emit(f"Client existed and sha1 matches.")
        elif url is not None:
            download_file(file, progress_callback=self.download_signal.progress.emit)
        elif not url:
            self.download_signal.failed.emit("Download URL not found.")

        self.download_signal.log.emit(f"Downloaded URL: {url}")
        self.widget_signal.enable_widget.emit(self.button_2)

    def _download_libraries_process(self, ver=None):
        self.output.clear()

        def log_file_downloaded(filepath):
            self.download_signal.log.emit(f"Downloaded {filepath}.")

        data = get_version_manifest()

        if not ver:
            ver = self.ver_dropdown.currentText()

        if not ver:
            self.widget_signal.show_error_message.emit(
                "Select a version before download libraries."
            )
            self.widget_signal.enable_widget.emit(self.button_3)
            return

        ver_data = fetch_specific_version_manifest(data, ver)
        _, _, _, _, libraries, _ = find_useful_part_in_specific_version_manifest(ver_data)

        output_dir = Path(self.app.work_dir, "libraries")

        output_dir.mkdir(parents=True, exist_ok=True)

        items = []

        # Same as natives
        _, _, os_version = get_platform_info()
        platform_key_name, platform_rule_name, platform_arch_type = get_natives_platform_info()

        for library in libraries:
            name = library.get("name", "")
            url = library.get("downloads", {}).get("artifact", {}).get("url")
            sha1 = library.get("downloads", {}).get("artifact", {}).get("sha1")
            relative_path = library.get("downloads", {}).get("artifact", {}).get("path")
            rules = library.get("rules", [])
            full_path = output_dir / relative_path
            classifiers = library.get("downloads", {}).get("classifiers", {})
            natives = library.get("natives", {})

            # Ignore natives
            if (len(natives) > 0 or bool(re.search(r":natives-[^:]+$", name)) or
                    any(native.startswith("natives-") for native in classifiers)):
                continue

            if not url:
                continue

            if not is_library_allowed(
                    rules,
                    platform_rule_name,
                    platform_arch_type,
                    os_version,
            ):
                self.app.logger.debug(f"Library {name} can't pass library rules.")
                continue

            file = FileObject(full_path, url=url, sha1=sha1)

            if sha1 is None:
                self.app.logger.warning(f"File {full_path} has no SHA1 hash.")

            if file.exists and (sha1 is None or file.verify("sha1", sha1)):
                log_file_downloaded(file.posix_path)
                continue

            items.append(file)

        try:
            fails = download_multiple_files(items,
                                            progress_callback=self.download_signal.progress.emit)
            self.download_signal.finished.emit(len(fails))
        except Exception as e:
            self.download_signal.failed.emit(e)

        self.widget_signal.enable_widget.emit(self.button_3)

    def _download_and_unzip_natives(self, ver=None, unspecified_arch_policy: str= "x86_64"):
        valid_non_arch_values = {
            "universal",
            "x86",
            "x86_64",
            "arm64",
        }

        if unspecified_arch_policy not in valid_non_arch_values:
            raise ValueError(
                f"Unsupported considered_non_arch: "
                f"{unspecified_arch_policy!r}"
            )

        try:
            self.output.clear()
            data = get_version_manifest()

            if not ver:
                ver = self.ver_dropdown.currentText()

            if not ver:
                self.widget_signal.show_error_message.emit(
                    "Select a version before download natives."
                )
                self.widget_signal.enable_widget.emit(self.button_3)
                return

            filtered = []

            # Convert current platform and architecture type to same formula
            _, _, os_version = get_platform_info()
            platform_key_name, platform_rule_name, platform_arch_type = get_natives_platform_info()

            if platform_key_name is None or platform_arch_type is None or platform_rule_name is None:
                self.app.logger.error("Platform or arch are not supported.")
                self.widget_signal.show_error_message.emit("Current platform or arch are not supported.")
                return

            ver_data = fetch_specific_version_manifest(data, ver)
            _, _, _, _, libraries, _ = find_useful_part_in_specific_version_manifest(ver_data)

            for library in libraries:
                name = library.get("name", "")
                artifact = library.get("downloads", {}).get("artifact", {})
                # For newer Minecraft (VER>1.7.10)
                rules = library.get("rules", [])
                # For legacy version (VER<1.8)
                classifiers = library.get("downloads", {}).get("classifiers", {})
                natives = library.get("natives", {})

                result_artifact = None
                is_natives = False

                # Check if library is a native
                if (len(natives) > 0 or bool(re.search(r":natives-[^:]+$", name)) or
                        any(native.startswith("natives-") for native in classifiers)):
                    is_natives = True

                if not is_natives:
                    continue

                content = f"Name: {name}\nRaw Rules: {rules}\n\n"

                if rules and classifiers:
                    content += f"This native use multiple native rules!\n"
                elif rules:
                    content += f"This native use new native rules!\n"
                elif classifiers:
                    content += f"This native use legacy native rules!\n"

                # =============== New rules ===============

                # Parse action section
                content += "Rules:\n"

                if not is_library_allowed(
                    rules,
                    platform_rule_name,
                    platform_arch_type,
                    os_version,
                ):
                    self.app.logger.debug(f"Library {name} can't pass library rules.")
                    continue

                if is_native_allowed(
                    name,
                    platform_key_name,
                    platform_arch_type,
                ):
                    result_artifact = generate_formatted_artifact_with_name(name, artifact)
                    filtered.append(result_artifact)
                    # For some reason, we still need to continue process because some version use multiple type of
                    # classifier. (Such as 1.14.2)
                else:
                    self.app.logger.debug(f"Library {name} can't pass native rules.")

                # =============== Old rules ===============
                self.app.logger.debug(
                    "Library {} doesn't have native key. This library may use old rule.".format(name)
                )

                result, result_artifact = is_legacy_native_allowed(
                    natives,
                    classifiers,
                    platform_rule_name,
                    platform_arch_type,
                )

                if not result:
                    self.app.logger.debug(f"Library {name} can't pass legacy native rules.")
                    continue
                else:
                    result_artifact = generate_formatted_artifact_with_name(name, result_artifact)

                if result_artifact:
                    filtered.append(result_artifact)

                self.output.appendPlainText(
                    content
                )
                self.app.logger.debug(content)

            self.output.appendPlainText(
                "Supported native count: {}".format(len(filtered))
            )
        except Exception as exc:
            self.app.logger.exception(
                "Unexpected exception occurred: {}".format(exc)
            )
            self.widget_signal.show_error_message.emit(
                "Unexpected exception occurred while finding natives: {}".format(exc)
            )
        finally:
            self.button_4.setDisabled(False)
