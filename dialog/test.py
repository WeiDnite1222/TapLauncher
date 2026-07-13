import json
import queue
import subprocess
import textwrap
import threading
import time
import traceback
from pathlib import Path

from PySide6.QtCore import Qt, QObject, Signal, Slot
from PySide6.QtWidgets import QPushButton, QVBoxLayout, QDialog, QPlainTextEdit, \
    QHBoxLayout, QComboBox, QMessageBox, QFileDialog

from core_lib.common.common import FileObject, download_multiple_files
from core_lib.common.exception import VersionNotSelectedException, UnsupportedPlatformException, \
    NativeResolveException, DownloadException, DependencyException, VersionManifestFetchException, \
    VersionManifestSaveException, NoSpecifiedVersionKeyException, AssetManifestFetchException, \
    AssetManifestSaveException, AssetDataKeyNotFoundException, VersionDataKeyNotFoundException
from core_lib.game.argument import ArgumentMappings, parse_and_generate_arguments, find_game_and_jvm_args, \
    generate_launch_command
from core_lib.game.asset import download_assets, check_assets_exist, find_correct_assets_dir
from core_lib.game.library import generate_classpath, download_full_libraries, check_libraries_exists, \
    check_full_libraries_exists

from core_lib.game.version_info import (find_useful_part_in_specific_version_manifest,
                                        get_core_file_download_url_and_hash, \
                                        get_all_versions, get_available_version_types, \
                                        fetch_and_save_version_manifest, get_specific_version_manifest_url_and_hash,
                                        download_core_file)
from core_lib.qt import messagebox
from core_lib.qt.hack import is_main_thread
from core_lib.qt.messagebox import ask_yes_no_with_plain_text
from core_lib.runtime.java import find_java_installations

MAX_DOWNLOAD_ATTEMPTS = 3


class AskForRequest:
    def __init__(self, title, message):
        self.title = title
        self.message = message
        self.result_queue = queue.Queue(maxsize=1)
        self.wait_event = threading.Event()

        self.details = None # Set this if flag use_plain_text is enabled

        # flags
        self.use_plain_text = True

    def wait(self, timeout: int | None = 10):
        return self.wait_event.wait(timeout)

    def result(self):
        try:
            return self.result_queue.get_nowait()
        except queue.Empty:
            return None

class SelectPathRequest(AskForRequest):
    def __init__(self, title, message, filter_raw=None):
        super().__init__(title, message)
        self.filter = filter_raw


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

        self.button_5 = QPushButton("Download assets")
        self.button_5.setObjectName("ActionButton")
        self.button_5.clicked.connect(self.download_assets)

        self.button_6 = QPushButton("Parse Arguments")
        self.button_6.setObjectName("ActionButton")
        self.button_6.clicked.connect(self.parse_argument)

        self.button_7 = QPushButton("Launch Game! (Offline)")
        self.button_7.setObjectName("ActionButton")
        self.button_7.clicked.connect(self.launch_offline_game)

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
        self.right_layout.addWidget(self.button_5)
        self.right_layout.addWidget(self.button_6)
        self.right_layout.addWidget(self.button_7)
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

        self.widget_signal.show_and_print_error_message.connect(
            self.show_and_print_error
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

        self.widget_signal.ask_for_path.connect(
            self.ask_for_path
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
        show_and_print_error_message = Signal(dict)
        show_warning_message = Signal(str)
        show_info_message = Signal(str)
        enable_widget = Signal(object)
        disable_widget = Signal(object)
        askyesno = Signal(object)
        ask_for_path = Signal(object)
        get_selected_ver = Signal(dict)
        get_selected_type = Signal(dict)
        clean_output = Signal()

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

    @Slot(dict)
    def show_and_print_error(self, context: dict):
        error = context.get("error", None)
        title = context.get("title", "Error")
        message = context.get("message", "No content")

        if isinstance(error, list):
            self.app.logger.error("".join(error))
        elif isinstance(error, str):
            self.app.logger.error(error)
        elif isinstance(error, Exception):
            self.app.logger.exception(error)

        messagebox.error(
            self.parent,
            title,
            message=message
        )

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
            self.widget_signal.show_and_print_error_message.emit(
                {
                    "error": traceback.format_exception(e),
                    "title": "Test Error",
                    "message": "Failed to run test."
                }
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
            target=self._download_libraries,
            daemon=True,
            args=(ver,)
        )
        thread.start()

    def download_assets(self):
        self.button_5.setDisabled(True)

        self.output.clear()

        ver = self.get_selected_version()

        if not ver:
            self.widget_signal.enable_widget.emit(self.button_5)
            return

        thread = threading.Thread(
            target=self._download_assets,
            daemon=True,
            args=(ver,)
        )
        thread.start()

    def parse_argument(self):
        self.button_6.setDisabled(True)

        self.output.clear()

        ver = self.get_selected_version()

        if not ver:
            self.widget_signal.enable_widget.emit(self.button_6)
            return

        thread = threading.Thread(
            target=self._parse_argument,
            daemon=True,
            args=(ver,)
        )
        thread.start()

    def launch_offline_game(self):
        self.button_7.setDisabled(True)

        self.output.clear()

        ver = self.get_selected_version()

        if not ver:
            self.widget_signal.enable_widget.emit(self.button_7)
            return

        thread = threading.Thread(
            target=self._launch_offline_game,
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
                e.user_message,
            )
        except VersionManifestSaveException as e:
            self.widget_signal.show_error_message.emit(
                e.user_message,
            )
        except Exception as e:
            self.widget_signal.show_and_print_error_message.emit(
                {
                    "error": traceback.format_exception(e),
                    "title": "Cache Error",
                    "message": "An unexpected error occurred while caching version manifest."
                }
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
            self.widget_signal.show_and_print_error_message.emit(
                {
                    "error": traceback.format_exception(e),
                    "title": "Cache Error",
                    "message": "Unable to read version manifest."
                }
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
            if specified_ver and age < max_age and file.verify("sha1", sha1):
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

            client_dest = Path(self.app.work_dir, "versions", ver, f"{ver}.jar")
            download_core_file(ver_data, client_dest, progress_callback=self.download_signal.progress.emit,
                               raise_for_null_hash=True)
            self.download_signal.log.emit(f"Downloaded {ver} client to {client_dest}")
        except DownloadException as e:
            self.widget_signal.show_error_message.emit(
                "Unable to download client while downloading it: {}".format(e.user_message),
            )
        except VersionDataKeyNotFoundException as e:
            self.widget_signal.show_and_print_error_message.emit(
                {
                    "error": traceback.format_exception(e),
                    "title": "Fetch Error",
                    "message": "Unable to download client due to some necessary key is missing.",
                }
            )
        except Exception as e:
            self.widget_signal.show_and_print_error_message.emit(
                {
                    "error": traceback.format_exception(e),
                    "title": "Download Error",
                    "message": "Unable to download client, an unexpected error occurred."
                }
            )
        finally:
            self.widget_signal.enable_widget.emit(self.button_2)

    def _download_libraries(self, ver: str):
        try:
            self.widget_signal.clean_output.emit()

            ver_data = self.get_cached_version_manifest(ver)

            if not ver_data:
                return

            libraries_dir = Path(self.app.work_dir, "libraries")
            natives_dest = Path(self.app.work_dir, "versions", ver, "natives")
            libraries_dir.mkdir(parents=True, exist_ok=True)
            natives_dest.mkdir(parents=True, exist_ok=True)

            download_full_libraries(
                ver_data,
                libraries_dir,
                natives_dest,
                progress_callback=self.download_signal.progress.emit,
                redownload_callback=self.redownload_files
            )
            self.download_signal.log.emit(
                "All libraries downloaded successfully."
            )
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
            self.widget_signal.show_and_print_error_message.emit(
                {
                    "error": traceback.format_exception(e),
                    "title": "Download Error",
                    "message": "Unable to collect library artifacts. An unknown error occurred."
                }
            )
        finally:
            self.widget_signal.enable_widget.emit(self.button_3)

    def _download_assets(self, ver: str):
        try:
            self.widget_signal.clean_output.emit()

            ver_data = self.get_cached_version_manifest(ver)

            if not ver_data:
                return

            assets_dir = Path(self.app.work_dir, "assets")

            fails = download_assets(ver_data, assets_dir,
                                    no_hash_check=True,
                                    progress_callback=self.download_signal.progress.emit,
                                    launcher_root=self.app.work_dir)

            if fails:
                self.widget_signal.show_warning_message.emit(
                    "Some assets were not downloaded. Although is not necessary for launching game."
                    " But it may cause some texture issue when you playing. (Such as missing textures)"
                )
            else:
                self.download_signal.log.emit(
                    "All assets downloaded successfully."
                )
        except AssetManifestFetchException as e:
            self.widget_signal.show_error_message.emit(
                f"Unable to fetch asset manifest.\n{e.user_message}"
            )
        except AssetManifestSaveException as e:
            self.widget_signal.show_error_message.emit(
                f"Unable to save asset manifest.\n{e.user_message}"
            )
        except AssetDataKeyNotFoundException as e:
            self.widget_signal.show_error_message.emit(
                f"Unable to collect assets.\n{e.user_message}"
            )
        except Exception as e:
            self.widget_signal.show_and_print_error_message.emit(
                {
                    "error": traceback.format_exception(e),
                    "title": "Download Error",
                    "message": "Unable to download assets. An unknown error occurred."
                }
            )
        finally:
            self.widget_signal.enable_widget.emit(self.button_5)

    def _parse_argument(self, ver):
        try:
            ver_data = self.get_cached_version_manifest(ver)

            if not ver_data:
                return

            new_args, asset_index, _, _, _, _, old_args = find_useful_part_in_specific_version_manifest(ver_data)

            target_args = new_args if new_args else old_args

            if not target_args:
                self.widget_signal.show_error_message.emit(
                    "Unable to parse arguments because data are invalid.\n"
                )
                return

            arg_maps = ArgumentMappings()
            game_args, jvm_args = find_game_and_jvm_args(target_args)
            parsed_jvm_args = parse_and_generate_arguments(
                jvm_args,
                arg_maps
            )
            parsed_game_args = parse_and_generate_arguments(
                game_args,
                arg_maps
            )
            self.download_signal.log.emit(f"Parsed jvm arguments: \n{parsed_jvm_args}\n{" ".join(parsed_jvm_args)}")
            self.download_signal.log.emit(f"Parsed game arguments: \n{parsed_game_args}\n{" ".join(parsed_game_args)}")
        except Exception as e:
            self.widget_signal.show_and_print_error_message.emit(
                {
                    "error": traceback.format_exception(e),
                    "title": "Parse Error",
                    "message": "Unable to parse arguments. An unknown error occurred."
                }
            )
        finally:
            self.widget_signal.enable_widget.emit(self.button_6)

    def _launch_offline_game(self, ver):
        """
        Launch offline game
        :param ver:
        :return:
        """
        try:
            current_status = 0 # 0 = fetch version manifest, 1 = check client, 2 = check libraries
            # , 3 = check assets

            # Version manifest
            ver_data = self.get_cached_version_manifest(ver)

            if not ver_data:
                return

            arguments, asset_index, downloads, java_version, libraries, main_class, old_args = (
                find_useful_part_in_specific_version_manifest(ver_data)
            )

            # Vars
            asset_id = asset_index.get("id")
            java_major_version = java_version.get("majorVersion")

            # Some paths
            core_file_path = Path(self.app.work_dir, "versions", ver, f"{ver}.jar")
            game_dir = Path(self.app.temp_dir, "minecraft")
            game_dir.mkdir(parents=True, exist_ok=True)
            natives_dir = Path(self.app.work_dir, "versions", ver, "natives")
            libraries_dir = Path(self.app.work_dir, "libraries")

            # Check client
            current_status = 1
            if not core_file_path.exists():
                download_core_file(ver_data, core_file_path, raise_for_null_hash=True)

            # Libraries
            current_status = 2
            if not check_full_libraries_exists(ver_data, libraries_dir, natives_dir):
                download_full_libraries(ver_data, libraries_dir, natives_dir)

            # Asset
            current_status = 3
            default_assets_dir = Path(self.app.work_dir, "assets")
            if not check_assets_exist(ver_data, default_assets_dir, launcher_root=self.app.work_dir):
                download_assets(ver_data, default_assets_dir,
                                no_hash_check=True,
                                progress_callback=self.download_signal.progress.emit,
                                launcher_root=self.app.work_dir)

            assets_dir = find_correct_assets_dir(asset_id, default_assets_dir, self.app.work_dir)

            current_status = 4
            classpath = generate_classpath(
                ver_data,
                libraries_dir,
                core_file_path,
            )

            # Mappings
            arg_maps = ArgumentMappings(
                player_name="Player",
                version_name=ver,
                game_directory=game_dir.as_posix(),
                assets_root=assets_dir.as_posix(),
                legacy_assets_root=assets_dir,
                assets_index_name=asset_id,
                auth_uuid="00000000000000000000000000000000",
                auth_access_token="0",
                user_type="legacy",
                version_type="release",
                natives_directory=natives_dir.as_posix(),
                launcher_name="TestLauncher",
                launcher_version="0.1",
                classpath=classpath,
                classpath_separator=";",
                library_directory=libraries_dir.as_posix(),
            )

            target_args = arguments if arguments else old_args

            if not target_args:
                self.widget_signal.show_error_message.emit(
                    "Unable to parse arguments because data are invalid.\n"
                )
                return

            # Use found java runtime (if available)
            java_path = self.get_support_runtime_jvm_executable(
                java_major_version,
                no_error=True
            )

            if not java_path:
                # Ask for a support java version. If not, use system environment java
                request = SelectPathRequest(
                    title="Require a java executable path to launch game. (Major Version: {})".format(java_major_version),
                    message=None,
                    filter_raw="Java executable (java.exe javaw.exe);;All files (*)"
                )

                self.widget_signal.ask_for_path.emit(request)

                if not request.wait(120):
                    self.widget_signal.show_error_message.emit(
                        "Timed out while waiting for Java executable selection."
                    )
                    return

                java_path = request.result()

                if java_path:
                    self.download_signal.log.emit(f"Use specified java executable path: {java_path}")
                else:
                    self.download_signal.log.emit("Use system environment java.")
                    java_path = "java"

            # Finally, generate launch command
            cmd = generate_launch_command(
                arg_maps=arg_maps,
                main_class=main_class,
                java_path=java_path,
                full_args=target_args,
            )

            self.download_signal.log.emit(f"Launch command: {cmd}")

            # run it
            process = subprocess.Popen(
                cmd,
                cwd=game_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )

            for line in process.stdout:
                self.download_signal.log.emit(line.rstrip())
        except Exception as e:
            self.widget_signal.show_and_print_error_message.emit(
                {
                    "error": traceback.format_exception(e),
                    "title": "Launch Error",
                    "message": "Unable to launch error. An unknown error occurred."
                }
            )
        finally:
            self.widget_signal.enable_widget.emit(self.button_7)

    def redownload_files(self, files: list[FileObject]) -> tuple[bool, list[FileObject]]:
        if not files:
            return True, []

        message = (
                "Some files failed to download.\n"
                "Would you like to retry downloading them?\n\n"
        )

        request = AskForRequest("Redownload", message)
        request.details = "\n".join(file.posix_path for file in files)

        self.widget_signal.askyesno.emit(request)

        if not request.wait(60):
            self.widget_signal.show_error_message.emit(
                "Timed out while waiting for confirmation. Please try again."
            )
            return False, files

        result = request.result()

        if not result:
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

    #
    # JVM Management
    #
    @property
    def jvm_settings_path(self) -> Path:
        return Path(self.app.work_dir) / "jvms.json"

    def _find_and_save_jvm_search_result(self):
        installations, errors = find_java_installations()
        if not installations:
            self.widget_signal.show_warning_message.emit(
                "There are no Java installations available in you system.\n"
            )
            return []

        if errors:
            request = AskForRequest("Java Virtual Machine Finder", message = (
                "Unable to detect below java installation version:\n"
            ))
            request.details = "\n".join(path.as_posix() for path in errors)
            request.use_plain_text = True

            self.widget_signal.askyesno.emit(request)

        self.jvm_settings_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            with self.jvm_settings_path.open("w") as file:
                json.dump(installations, file, indent=4)

            return installations
        except Exception as e:
            self.widget_signal.show_and_print_error_message.emit(
                {
                    "error": traceback.format_exception(e),
                    "title": "Settings Error",
                    "message": "An error occurred while attempting to save jvm settings. Please try again.",
                }
            )

    def _read_exist_jvm_settings(self):
        try:
            return json.loads(self.jvm_settings_path.read_text())
        except Exception as e:
            self.widget_signal.show_and_print_error_message.emit(
                {
                    "error": traceback.format_exception(e),
                    "title": "Settings Error",
                    "message": "An error occurred while reading jvm settings.",
                }
            )
            return None

    def get_or_cache_jvm_settings(self) -> list:
        if self.jvm_settings_path.exists():
            exists = self._read_exist_jvm_settings()

            if exists:
                return exists

        return self._find_and_save_jvm_search_result()

    def get_support_runtime_jvm_executable(self, major_version: int | str, no_error: bool=False) -> str | None:
        result = self.get_or_cache_jvm_settings()

        if not result:
            return None

        for item in result:
            version = item.get("major", None)
            executable = item.get("executable", None)

            try:
                version = str(version)
                major_version = str(major_version)
            except Exception as e:
                self.app.logger.warning(
                    f"Unable to convert version {version} to string: {e}"
                )

            if major_version == version and executable:
                return executable

        if not no_error:
            self.widget_signal.show_error_message.emit(
                "No Java executable found for major version {}.".format(major_version)
            )

        return None

