import json
import textwrap
import threading
import time
from pathlib import Path

from PySide6.QtCore import Qt, QObject, Signal, Slot
from PySide6.QtWidgets import QPushButton, QVBoxLayout, QDialog, QPlainTextEdit, \
    QHBoxLayout, QComboBox, QMessageBox

from core_lib.common.common import download_file, FileObject, download_multiple_files
from core_lib.common.exception import VersionNotSelectedException, UnsupportedPlatformException, \
    NativeResolveException, DownloadException, DependencyException, VersionManifestFetchException, \
    VersionManifestSaveException, NoSpecifiedVersionKeyException
from core_lib.game.library import collect_native_artifacts, download_libraries, unzip_natives, collect_library_artifacts

from core_lib.game.version_info import (find_useful_part_in_specific_version_manifest,
                                        get_core_file_download_url_and_hash, \
                                        get_all_versions, get_available_version_types, \
                                        fetch_and_save_version_manifest, get_specific_version_manifest_url_and_hash)
from core_lib.qt import messagebox
from core_lib.qt.hack import is_main_thread

MAX_DOWNLOAD_ATTEMPTS = 3


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

        self.button_2 = QPushButton("Download client")
        self.button_2.setObjectName("ActionButton")
        self.button_2.clicked.connect(self.run_download_client)

        self.button_3 = QPushButton("Download libraries")
        self.button_3.setObjectName("ActionButton")
        self.button_3.clicked.connect(self.run_download_libraries)

        self.button_4 = QPushButton("Refresh versions")
        self.button_4.setObjectName("ActionButton")
        self.button_4.clicked.connect(self.load_all_version)

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
        self.right_layout.addWidget(self.button_2)
        self.right_layout.addWidget(self.button_3)
        self.right_layout.addStretch()
        self.right_layout.addWidget(self.ver_type_dropdown)
        self.right_layout.addWidget(self.ver_dropdown)
        self.right_layout.addWidget(self.button_4)
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

        self.widget_signal.show_warning_message.connect(
            lambda msg: messagebox.warning(
                self.parent,
                "Warning",
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

        self.widget_signal.askyesno.connect(
            self.ask_request
        )

        self.widget_signal.get_selected_ver.connect(
            self.get_selected_ver
        )

        self.widget_signal.get_selected_type.connect(
            self.get_selected_type
        )

        self.widget_signal.clean_output.connect(
            lambda : self.output.clear()
        )

        self.load_all_types()

    class DownloadSignal(QObject):
        log = Signal(str)
        finished = Signal(int)
        failed = Signal(str)
        progress = Signal(str, float)

    class WidgetSignal(QObject):
        clean_ver_types_dropdown = Signal()
        clean_vers_dropdown = Signal()
        update_vers_dropdown = Signal(list)
        update_types_dropdown = Signal(list)
        show_error_message = Signal(str)
        show_warning_message = Signal(str)
        show_info_message = Signal(str)
        enable_widget = Signal(object)
        disable_widget = Signal(object)
        askyesno = Signal(dict)  # {"title", "targetEvent", "message", "result"}
        get_selected_ver = Signal(dict)
        get_selected_type = Signal(dict)
        clean_output = Signal()

    @Slot(dict)
    def ask_request(self, context: dict):
        title = context.get("title", "Info")
        message = context.get("message", "No content")
        event = context.get("event", None)
        msg = QMessageBox.question(
            self,
            title,
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )

        if msg == QMessageBox.StandardButton.Yes and type(event) == threading.Event:
            context["result"] = True

        if isinstance(event, threading.Event):
            event.set()

    @Slot(dict)
    def get_selected_ver(self, context: dict):
        context["version"] = self.ver_dropdown.currentText()
        event = context.get("event", None)
        if isinstance(event, threading.Event):
            event.set()

    @Slot(dict)
    def get_selected_type(self, context: dict):
        context["type"] = self.ver_type_dropdown.currentText()
        event = context.get("event", None)
        if isinstance(event, threading.Event):
            event.set()

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

    def _get_selected_version_unsafe(self):
        if is_main_thread():
            ver = self.ver_dropdown.currentText()
        else:
            event = threading.Event()
            context = {
                "event": event,
            }
            self.widget_signal.get_selected_ver.emit(context)

            if not event.wait(10):
                raise VersionNotSelectedException(
                    "Timed out while waiting for selected version from the UI thread.",
                    user_message="Unable to read selected version from the UI. Please try again."
                )

            ver = context.get("version", None)

        if not ver:
            raise VersionNotSelectedException()

        return ver

    def get_selected_version(self):
        try:
            ver = self._get_selected_version_unsafe()
            return ver
        except VersionNotSelectedException as e:
            self.widget_signal.show_error_message.emit(
                "Select a version before continuing.\n"
                "Details: {}".format(e.user_message)
            )
            return None

    def run_test(self):
        self.button.setDisabled(True)

        try:
            self.output.clear()
            ver = self.get_selected_version()

            if not ver:
                return

            ver_data = self.get_cached_version_manifest(ver)

            arguments, asset_index, downloads, java_version, libraries, main_class, legacy_game_args = (
                find_useful_part_in_specific_version_manifest(ver_data))

            content = textwrap.dedent(f"""\
                    Arguments: {arguments}\n

                    Asset: {asset_index}\n

                    Downloads: {downloads}\n

                    Java Version: {java_version}\n

                    Libraries: {libraries}\n

                    Main Class: {main_class}\n

                    Extra:
                    minecraftArguments: {legacy_game_args}
                    """)
            self.output.setPlainText(content)
        except Exception as e:
            self.widget_signal.show_error_message.emit(
                "Failed to run test. Details: {}".format(e)
            )
        finally:
            self.button.setDisabled(False)

    def run_download_client(self):
        self.button_2.setDisabled(True)

        self.output.clear()

        ver = self.get_selected_version()

        if not ver:
            self.widget_signal.enable_widget.emit(self.button_2)
            return

        thread = threading.Thread(
            target=self._download_client,
            daemon=True,
            args=(ver,)
        )
        thread.start()

    def run_download_libraries(self):
        self.button_3.setDisabled(True)

        self.output.clear()

        ver = self.get_selected_version()

        if not ver:
            self.widget_signal.enable_widget.emit(self.button_3)
            return

        thread = threading.Thread(
            target=self._download_libraries_process,
            daemon=True,
            args=(ver,)
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

        data = self.get_cached_version_manifest()
        if not data:
            return

        ver_types = get_available_version_types(data)
        self.widget_signal.update_types_dropdown.emit(ver_types)

    def _load_all_version(self, ver_type):
        self.widget_signal.clean_vers_dropdown.emit()

        data = self.get_cached_version_manifest()
        if not data:
            return

        vers = get_all_versions(
            data,
            specified_type=ver_type
        )
        self.widget_signal.update_vers_dropdown.emit(vers)

    #
    # ============ Version Data Cache ============
    #
    @property
    def version_manifest_path(self) -> Path:
        return Path(self.app.work_dir, "versions", "version_manifest_v2.json")

    def get_specific_version_manifest_path(self, target_version: str) -> Path | None:
        return Path(self.app.work_dir, "versions", target_version, f"{target_version}.json")

    def switch_between_specific_path(self, specified_ver: str | None = None):
        if specified_ver is None:
            path = self.version_manifest_path
        else:
            path = self.get_specific_version_manifest_path(specified_ver)

        return path

    def _cache_version_manifest(self, specified_ver: str | None = None, root_manifest: dict | None = None) \
            -> tuple[bool, dict | None]:
        data = None
        path = self.switch_between_specific_path(specified_ver)
        try:
            data = fetch_and_save_version_manifest(path, target_version=specified_ver, root_manifest=root_manifest)
        except VersionManifestFetchException as e:
            self.widget_signal.show_error_message.emit(
                "Unable to fetch version manifest: {}".format(e.user_message),
            )
        except VersionManifestSaveException as e:
            self.widget_signal.show_error_message.emit(
                "Unable to save version manifest: {}".format(e.user_message),
            )
        except Exception as e:
            self.widget_signal.show_error_message.emit(
                "An unexpected error occurred while caching version manifest: {}".format(e),
            )

        return True if data else False, data

    def _read_cached_version_manifest(self, specified_ver: str = None) -> dict | None:
        path = self.switch_between_specific_path(specified_ver)
        if not path.exists():
            self.widget_signal.show_error_message.emit(
                "Version manifest missing after check. Please try again later.",
            )
            return None

        try:
            version_manifest = json.loads(path.read_text())
            return version_manifest
        except Exception as e:
            self.widget_signal.show_error_message.emit(
                "Unable to read version manifest:\n{}".format(e),
            )
            return None

    def get_cached_version_manifest(self, specified_ver: str = None, max_age: int = 3600) -> dict | None:
        path = self.switch_between_specific_path(specified_ver)
        file = FileObject(path)
        sha1 = None
        root_manifest = None

        if specified_ver:
            root_manifest = self.get_cached_version_manifest()

            if root_manifest is None:
                return None

            try:
                _, sha1 = get_specific_version_manifest_url_and_hash(root_manifest, specified_ver)
            except NoSpecifiedVersionKeyException as e:
                self.widget_signal.show_error_message.emit(
                    f"Version {specified_ver} does not exist in version manifest.\n{e.user_message}"
                )
                return None

        if file.exists:
            age = time.time() - path.stat().st_mtime

            # For root manifest
            if not specified_ver and age < max_age:
                return self._read_cached_version_manifest()

            # Below are all for specific ver
            if specified_ver and sha1 is None:
                self.app.logger.warning("Specified version '{}' hash doesn't exist.".format(specified_ver))

            # Also check sha1
            if specified_ver and age < max_age and (sha1 is None or file.verify("sha1", sha1)):
                return self._read_cached_version_manifest(specified_ver)

        result, data = self._cache_version_manifest(specified_ver, root_manifest=root_manifest)

        if not result:
            return None

        return data

    #
    # ============ Game Files ============
    #
    # INFO: All are not in main thread
    def _download_client(self, ver: str):
        try:
            ver_data = self.get_cached_version_manifest(ver)

            if not ver_data:
                return

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
        except DownloadException as e:
            self.widget_signal.show_error_message.emit(
                "Unable to download client while downloading it: {}".format(e.user_message),
            )
        except Exception as e:
            self.widget_signal.show_error_message.emit(
                "Unable to download client: {}".format(e),
            )
        finally:
            self.widget_signal.enable_widget.emit(self.button_2)

    def _download_libraries_process(self, ver: str):
        output_dir = Path(self.app.work_dir, "libraries")
        output_dir.mkdir(parents=True, exist_ok=True)

        try:
            self.widget_signal.clean_output.emit()

            ver_data = self.get_cached_version_manifest(ver)

            if not ver_data:
                return

            # libraries
            libraries = collect_library_artifacts(ver_data)

            # natives
            natives = collect_native_artifacts(ver_data)

            # all
            full = list(libraries)
            full.extend(natives)

            self.download_signal.log.emit(
                "Supported native count: {}".format(len(natives))
            )

            # Start download
            fails, successes = download_libraries(full, output_dir,
                                                  progress_callback=self.download_signal.progress.emit)

            download_ok, fails = self.redownload_files(fails)

            if not download_ok:
                self.widget_signal.show_error_message.emit(
                    "Unable to continue process due to certain libraries download failed:\n"
                    + "\n".join(file.posix_path for file in fails)
                )
            else:
                # Start unzip natives
                natives_dest = Path(self.app.work_dir, "versions", ver, "natives")
                unzip_natives(natives, output_dir, natives_dest)
        except DependencyException as e:
            self.widget_signal.show_error_message.emit(
                "Unable to collect library artifacts.\n"
                f"{e.user_message}"
            )
        except DownloadException as e:
            self.widget_signal.show_error_message.emit(
                "Unable to collect library artifacts. An download error occurred:\n"
                f"{e.user_message}"
            )
        except UnsupportedPlatformException as e:
            self.widget_signal.show_error_message.emit(
                "Unable to collect native artifacts.\n"
                f"{e.user_message}"
            )
        except NativeResolveException as e:
            self.widget_signal.show_error_message.emit(
                "Unable to collect native artifacts.\n"
                f"{e.user_message}"
            )
        except Exception as e:
            self.widget_signal.show_error_message.emit(
                "Unable to collect library artifacts. An unknown error occurred:\n"
                f"{str(e) + f"\n{type(e)}"}"
            )
        finally:
            self.widget_signal.enable_widget.emit(self.button_3)

    def redownload_files(self, files: list[FileObject]) -> tuple[bool, list[FileObject]]:
        if not files:
            return True, []

        message = (
                "Some files failed to download.\n"
                "Would you like to retry downloading them?\n\n"
                + "\n".join(file.posix_path for file in files)
        )
        ask_event = threading.Event()
        context = {
            "event": ask_event,
            "title": "Retry downloading",
            "message": message,
        }

        self.widget_signal.askyesno.emit(context)

        if not ask_event.wait(60):
            self.widget_signal.show_error_message.emit(
                "Timed out while waiting for confirmation. Please try again."
            )
            return False, files

        if not context.get("result", False):
            return False, files

        # copy
        pending = list(files)

        for retry_time in range(1, MAX_DOWNLOAD_ATTEMPTS + 1):
            if not pending:
                return True, []

            self.download_signal.log.emit(f"Attempt {retry_time}/{len(pending)}")

            fails, successes = download_multiple_files(pending, progress_callback=self.download_signal.progress.emit)

            for file in successes:
                self.download_signal.log.emit(f"Downloaded {file.posix_path}.")

            if fails:
                pending = fails
            else:
                pending = []

        if not pending:
            return True, []

        failed_list = "\n".join(file.posix_path for file in pending)
        self.app.logger.warning(
            "Unable to download these files:\n{}".format(failed_list)
        )

        return False, pending
