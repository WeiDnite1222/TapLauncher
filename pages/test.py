import json
import subprocess
import sys
import textwrap
import threading
import traceback
from pathlib import Path

from PySide6.QtCore import Qt, QObject, Signal, Slot
from PySide6.QtWidgets import QPushButton, QVBoxLayout, QPlainTextEdit, \
    QHBoxLayout, QComboBox, QWidget

from core_lib.common.common import FileObject, download_multiple_files
from core_lib.common.exception import VersionNotSelectedException, UnsupportedPlatformException, \
    NativeResolveException, DownloadException, DependencyException, AssetManifestFetchException, \
    AssetManifestSaveException, AssetDataKeyNotFoundException, VersionDataKeyNotFoundException
from core_lib.game.argument import ArgumentMappings, parse_and_generate_arguments, find_game_and_jvm_args, \
    generate_launch_command
from core_lib.game.asset import download_assets, check_assets_exist, find_correct_assets_dir
from core_lib.game.library_core import generate_classpath, download_full_libraries, check_full_libraries_exists

from core_lib.game.version_info import (find_useful_part_in_specific_version_manifest, \
                                        get_all_versions, get_available_version_types,
                                        download_core_file)
from core_lib.qt.hack import is_main_thread
from core_lib.runtime.java import find_java_installations
from manager.game import ManifestManager, JavaManager
from manager.widgets import SelectPathRequest, AskForRequest

MAX_DOWNLOAD_ATTEMPTS = 3



class TestPage(QWidget):
    def __init__(self, /, app, parent, widget_manager):
        super().__init__(parent)
        self.app = app
        self.parent = parent
        self.widget_mgr = widget_manager
        self.manifest_mgr: ManifestManager = app.game_manager.manifest
        self.java_mgr: JavaManager = app.game_manager.java

        self.resize(800, 600)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowMaximizeButtonHint)

        self.button = QPushButton(self.app.tr_text("Fetch Version Data"))
        self.button.setObjectName("ActionButton")
        self.button.clicked.connect(self.run_test)

        self.button_2 = QPushButton(self.app.tr_text("Download client"))
        self.button_2.setObjectName("ActionButton")
        self.button_2.clicked.connect(self.run_download_client)

        self.button_3 = QPushButton(self.app.tr_text("Download libraries"))
        self.button_3.setObjectName("ActionButton")
        self.button_3.clicked.connect(self.run_download_libraries)

        self.button_4 = QPushButton(self.app.tr_text("Refresh versions"))
        self.button_4.setObjectName("ActionButton")
        self.button_4.clicked.connect(self.load_all_version)

        self.button_5 = QPushButton(self.app.tr_text("Download assets"))
        self.button_5.setObjectName("ActionButton")
        self.button_5.clicked.connect(self.download_assets)

        self.button_6 = QPushButton(self.app.tr_text("Parse Arguments"))
        self.button_6.setObjectName("ActionButton")
        self.button_6.clicked.connect(self.parse_argument)

        self.button_7 = QPushButton(self.app.tr_text("Launch Game! (Offline)"))
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

        self.signals = self.PageSignals(self)

        # Bind signal functions
        self.widget_mgr.download_signal.log.connect(
            self.output.appendPlainText
        )

        # self.widget_mgr.download_signal.finished.connect(
        #     lambda count: self.output.appendPlainText(
        #         f"Download finished, failed: {count}"
        #     )
        # )
        #
        # self.widget_mgr.download_signal.progress.connect(
        #     lambda name, progress: self.output.setPlainText(
        #         f"Downloading {name}: {self.get_progress(progress)}"
        #     )
        # )

        self.signals.clean_ver_types_dropdown.connect(
            self.ver_type_dropdown.clear
        )

        self.signals.update_types_dropdown.connect(
            lambda types: self.update_type_dropdown(types)
        )

        self.signals.clean_vers_dropdown.connect(
            self.ver_dropdown.clear
        )

        self.signals.update_vers_dropdown.connect(
            lambda vers: self.update_version_dropdown(vers)
        )

        self.signals.get_selected_ver.connect(
            self.get_selected_ver
        )

        self.signals.get_selected_type.connect(
            self.get_selected_type
        )

        self.signals.clean_output.connect(
            lambda : self.output.clear()
        )

        self.load_all_types()

    class PageSignals(QObject):
        clean_ver_types_dropdown = Signal()
        clean_vers_dropdown = Signal()
        update_vers_dropdown = Signal(list)
        update_types_dropdown = Signal(list)
        get_selected_ver = Signal(dict)
        get_selected_type = Signal(dict)
        clean_output = Signal()

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
            self.signals.get_selected_ver.emit(context)

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
            self.widget_mgr.signal.show_error_message.emit(
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

            ver_data = self.manifest_mgr.get_cached_version_manifest(ver)

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
            self.widget_mgr.signal.show_and_print_error_message.emit(
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
            self.widget_mgr.signal.enable_widget.emit(self.button_2)
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
            self.widget_mgr.signal.enable_widget.emit(self.button_3)
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
            self.widget_mgr.signal.enable_widget.emit(self.button_5)
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
            self.widget_mgr.signal.enable_widget.emit(self.button_6)
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
            self.widget_mgr.signal.enable_widget.emit(self.button_7)
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
        self.widget_mgr.download_signal.log.emit("Loading all versions...")

    def load_all_types(self):
        thread = threading.Thread(
            target=self._load_all_types,
            daemon=True
        )
        thread.start()
        self.widget_mgr.download_signal.log.emit("Loading all types...")

    # All functions below that must be run in background thread
    def _load_all_types(self):
        self.signals.clean_ver_types_dropdown.emit()

        data = self.manifest_mgr.get_cached_version_manifest()
        if not data:
            return

        ver_types = get_available_version_types(data)
        self.signals.update_types_dropdown.emit(ver_types)

    def _load_all_version(self, ver_type):
        self.signals.clean_vers_dropdown.emit()

        data = self.manifest_mgr.get_cached_version_manifest()
        if not data:
            return

        vers = get_all_versions(
            data,
            specified_type=ver_type
        )
        self.signals.update_vers_dropdown.emit(vers)

    #
    # ============ Game Files ============
    #
    # INFO: All are not in main thread
    def _download_client(self, ver: str):
        callback, task_id = self.manifest_mgr.create_download_progress_callback(f"Downloading {ver} client")
        try:
            ver_data = self.manifest_mgr.get_cached_version_manifest(ver)

            if not ver_data:
                self.widget_mgr.download_signal.failed.emit(
                    task_id,
                    "Version manifest is unavailable.",
                )
                return

            client_dest = Path(self.app.work_dir, "versions", ver, f"{ver}.jar")
            download_core_file(
                ver_data,
                client_dest,
                progress_callback=callback,
                raise_for_null_hash=True,
            )
            self.widget_mgr.download_signal.log.emit(f"Downloaded {ver} client to {client_dest}")
        except DownloadException as e:
            self.widget_mgr.download_signal.failed.emit(
                task_id,
                e.user_message,
            )
            self.widget_mgr.signal.show_error_message.emit(
                "Unable to download client while downloading it: {}".format(e.user_message),
            )
        except VersionDataKeyNotFoundException as e:
            self.widget_mgr.download_signal.failed.emit(
                task_id,
                e.user_message,
            )
            self.widget_mgr.signal.show_and_print_error_message.emit(
                {
                    "error": traceback.format_exception(e),
                    "title": "Fetch Error",
                    "message": "Unable to download client due to some necessary key is missing.",
                }
            )
        except Exception as e:
            self.widget_mgr.download_signal.failed.emit(
                task_id,
                str(e),
            )
            self.widget_mgr.signal.show_and_print_error_message.emit(
                {
                    "error": traceback.format_exception(e),
                    "title": "Download Error",
                    "message": "Unable to download client, an unexpected error occurred."
                }
            )
        else:
            self.widget_mgr.download_signal.finished.emit(task_id)
        finally:
            self.widget_mgr.signal.enable_widget.emit(self.button_2)

    def _download_libraries(self, ver: str):
        callback, task_id = self.manifest_mgr.create_download_progress_callback(f"Downloading libraries for version {ver}")
        try:
            self.signals.clean_output.emit()

            ver_data = self.manifest_mgr.get_cached_version_manifest(ver)

            if not ver_data:
                self.widget_mgr.download_signal.failed.emit(
                    task_id,
                    "Version manifest is unavailable.",
                )
                return

            libraries_dir = Path(self.app.work_dir, "libraries")
            natives_dest = Path(self.app.work_dir, "versions", ver, "natives")
            libraries_dir.mkdir(parents=True, exist_ok=True)
            natives_dest.mkdir(parents=True, exist_ok=True)

            download_full_libraries(
                ver_data,
                libraries_dir,
                natives_dest,
                progress_callback=callback,
                redownload_callback=self.redownload_files
            )
            self.widget_mgr.download_signal.log.emit(
                "All libraries downloaded successfully."
            )
        except DependencyException as e:
            self.widget_mgr.download_signal.failed.emit(
                task_id,
                e.user_message,
            )
            self.widget_mgr.signal.show_error_message.emit(
                "Unable to collect library artifacts.\n"
                f"{e.user_message}"
            )
        except DownloadException as e:
            self.widget_mgr.download_signal.failed.emit(
                task_id,
                e.user_message,
            )

            self.widget_mgr.signal.show_error_message.emit(
                "Unable to collect library artifacts. An download error occurred:\n"
                f"{e.user_message}"
            )
        except UnsupportedPlatformException as e:
            self.widget_mgr.download_signal.failed.emit(
                task_id,
                e.user_message,
            )
            self.widget_mgr.signal.show_error_message.emit(
                "Unable to collect native artifacts.\n"
                f"{e.user_message}"
            )
        except NativeResolveException as e:
            self.widget_mgr.download_signal.failed.emit(
                task_id,
                e.user_message,
            )
            self.widget_mgr.signal.show_error_message.emit(
                "Unable to collect native artifacts.\n"
                f"{e.user_message}"
            )
        except Exception as e:
            self.widget_mgr.download_signal.failed.emit(
                task_id,
                str(e),
            )
            self.widget_mgr.signal.show_and_print_error_message.emit(
                {
                    "error": traceback.format_exception(e),
                    "title": "Download Error",
                    "message": "Unable to collect library artifacts. An unknown error occurred."
                }
            )
        else:
            self.widget_mgr.download_signal.finished.emit(task_id)
        finally:
            self.widget_mgr.signal.enable_widget.emit(self.button_3)

    def _download_assets(self, ver: str):
        callback, task_id = self.manifest_mgr.create_download_progress_callback(f"Downloading assets for version {ver}")
        try:
            self.signals.clean_output.emit()

            ver_data = self.manifest_mgr.get_cached_version_manifest(ver)

            if not ver_data:
                self.widget_mgr.download_signal.failed.emit(
                    task_id,
                    "Version manifest is unavailable.",
                )
                return

            assets_dir = Path(self.app.work_dir, "assets")

            fails = download_assets(ver_data, assets_dir,
                                    no_hash_check=True,
                                    progress_callback=callback,
                                    launcher_root=self.app.work_dir)

            if fails:
                self.widget_mgr.download_signal.failed.emit(
                    task_id,
                    f"{len(fails)} asset files failed to download.",
                )
                self.widget_mgr.signal.show_warning_message.emit(
                    "Some assets could not be downloaded. They are not required to launch the game,"
                    " but missing assets may cause texture issues while you play."
                )
            else:
                self.widget_mgr.download_signal.log.emit(
                    "All assets downloaded successfully."
                )
        except AssetManifestFetchException as e:
            self.widget_mgr.download_signal.failed.emit(
                task_id,
                e.user_message,
            )
            self.widget_mgr.signal.show_error_message.emit(
                f"Unable to fetch asset manifest.\n{e.user_message}"
            )
        except AssetManifestSaveException as e:
            self.widget_mgr.download_signal.failed.emit(
                task_id,
                e.user_message,
            )
            self.widget_mgr.signal.show_error_message.emit(
                f"Unable to save asset manifest.\n{e.user_message}"
            )
        except AssetDataKeyNotFoundException as e:
            self.widget_mgr.download_signal.failed.emit(
                task_id,
                e.user_message,
            )
            self.widget_mgr.signal.show_error_message.emit(
                f"Unable to collect assets.\n{e.user_message}"
            )
        except Exception as e:
            self.widget_mgr.signal.show_and_print_error_message.emit(
                {
                    "error": traceback.format_exception(e),
                    "title": "Download Error",
                    "message": "Unable to download assets. An unknown error occurred."
                }
            )
        else:
            self.widget_mgr.download_signal.finished.emit(task_id)
        finally:
            self.widget_mgr.signal.enable_widget.emit(self.button_5)

    def _parse_argument(self, ver):
        try:
            ver_data = self.manifest_mgr.get_cached_version_manifest(ver)

            if not ver_data:
                return

            new_args, asset_index, _, _, _, _, old_args = find_useful_part_in_specific_version_manifest(ver_data)

            target_args = new_args if new_args else old_args

            if not target_args:
                self.widget_mgr.signal.show_error_message.emit(
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
            self.widget_mgr.download_signal.log.emit(f"Parsed jvm arguments: \n{parsed_jvm_args}\n{" ".join(parsed_jvm_args)}")
            self.widget_mgr.download_signal.log.emit(f"Parsed game arguments: \n{parsed_game_args}\n{" ".join(parsed_game_args)}")
        except Exception as e:
            self.widget_mgr.signal.show_and_print_error_message.emit(
                {
                    "error": traceback.format_exception(e),
                    "title": "Parse Error",
                    "message": "Unable to parse arguments. An unknown error occurred."
                }
            )
        finally:
            self.widget_mgr.signal.enable_widget.emit(self.button_6)

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
            ver_data = self.manifest_mgr.get_cached_version_manifest(ver)

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
                callback, task_id = self.manifest_mgr.create_download_progress_callback(
                    "Downloading missing assets"
                )

                try:
                    download_assets(
                        ver_data,
                        default_assets_dir,
                        no_hash_check=True,
                        progress_callback=callback,
                        launcher_root=self.app.work_dir,
                    )
                except Exception as e:
                    self.widget_mgr.download_signal.failed.emit(task_id, str(e))
                    raise
                else:
                    self.widget_mgr.download_signal.finished.emit(task_id)

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
                self.widget_mgr.signal.show_error_message.emit(
                    "Unable to parse arguments because data are invalid.\n"
                )
                return

            # Use found java runtime (if available)
            java_path = self.java_mgr.get_support_runtime_jvm_executable(
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

                self.widget_mgr.signal.ask_for_path.emit(request)

                if not request.wait(120):
                    self.widget_mgr.signal.show_error_message.emit(
                        "Timed out while waiting for Java executable selection."
                    )
                    return

                java_path = request.result()

                if java_path:
                    self.widget_mgr.download_signal.log.emit(f"Use specified java executable path: {java_path}")
                else:
                    self.widget_mgr.download_signal.log.emit("Use system environment java.")
                    java_path = "java"

            # Finally, generate launch command
            cmd = generate_launch_command(
                arg_maps=arg_maps,
                main_class=main_class,
                java_path=java_path,
                full_args=target_args,
            )

            self.widget_mgr.download_signal.log.emit(f"Launch command: {cmd}")

            # run it
            process = subprocess.Popen(
                cmd,
                cwd=game_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                creationflags=(
                    subprocess.CREATE_NO_WINDOW
                    if sys.platform == "win32"
                    else 0
                ),
                text=True,
                encoding="utf-8",
                errors="replace",
            )

            for line in process.stdout:
                self.widget_mgr.download_signal.log.emit(line.rstrip())
        except Exception as e:
            self.widget_mgr.signal.show_and_print_error_message.emit(
                {
                    "error": traceback.format_exception(e),
                    "title": "Launch Error",
                    "message": "Unable to launch error. An unknown error occurred."
                }
            )
        finally:
            self.widget_mgr.signal.enable_widget.emit(self.button_7)

    def redownload_files(self, files: list[FileObject]) -> tuple[bool, list[FileObject]]:
        if not files:
            return True, []

        message = (
                "Some files failed to download.\n"
                "Would you like to retry downloading them?\n\n"
        )

        request = AskForRequest("Redownload", message)
        request.details = "\n".join(file.posix_path for file in files)

        self.widget_mgr.signal.askyesno.emit(request)

        if not request.wait(60):
            self.widget_mgr.signal.show_error_message.emit(
                "Timed out while waiting for confirmation. Please try again."
            )
            return False, files

        result = request.result()

        if not result:
            return False, files

        # copy
        pending = list(files)

        callback, task_id = self.manifest_mgr.create_download_progress_callback(f"Redownloading {len(files)} files.")

        for retry_time in range(1, MAX_DOWNLOAD_ATTEMPTS + 1):
            if not pending:
                return True, []

            self.widget_mgr.download_signal.log.emit(f"Attempt {retry_time}/{len(pending)}")

            fails, successes = download_multiple_files(pending,
                                                       progress_callback=callback)

            for file in successes:
                self.widget_mgr.download_signal.log.emit(f"Downloaded {file.posix_path}.")

            if fails:
                pending = fails
            else:
                self.widget_mgr.download_signal.finished.emit(task_id)
                pending = []

        if not pending:
            return True, []

        failed_list = "\n".join(file.posix_path for file in pending)
        self.widget_mgr.download_signal.failed.emit(
            task_id,
            f"{len(pending)} files still failed after retries.",
        )
        self.app.logger.warning(
            "Unable to download these files:\n{}".format(failed_list)
        )

        return False, pending

