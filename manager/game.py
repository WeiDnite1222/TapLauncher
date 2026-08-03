import json
import os
import subprocess
import sys
import threading
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from threading import Thread
from typing import Literal
from uuid import uuid4
from PySide6.QtCore import QObject, Signal

from constant import CLIENT_ID, LAUNCHER_VERSION
from core_lib.common.common import FileObject, download_multiple_files
from core_lib.common.exception import VersionManifestFetchException, VersionManifestSaveException, \
    NoSpecifiedVersionKeyException
from core_lib.game.argument import ArgumentMappings, generate_launch_command
from core_lib.game.asset import check_assets_exist, download_assets, find_correct_assets_dir
from core_lib.game.library_core import check_full_libraries_exists, download_full_libraries, generate_classpath
from core_lib.game.mod.mod_core import merge_manifest
from core_lib.game.version_info import fetch_and_save_version_manifest, get_specific_version_manifest_url_and_hash, \
    save_version_manifest, find_useful_part_in_specific_version_manifest, download_core_file, get_latest_version, \
    LATEST_VERSION_ALIASES
from core_lib.runtime.java import find_java_installations
from manager.account import AccountManager, LaunchAccount
from manager.profile import LaunchProfile
from manager.widgets import SelectPathRequest, AskForRequest, SignalTransferItem

MAX_DOWNLOAD_ATTEMPTS = 3

class ManifestManager:
    def __init__(self, app):
        self.app = app
        self.widget_mgr = app.widget_manager

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
            self.widget_mgr.signal.show_error_message.emit(
                e.user_message,
            )
        except VersionManifestSaveException as e:
            self.widget_mgr.signal.show_error_message.emit(
                e.user_message,
            )
        except Exception as e:
            self.widget_mgr.signal.show_and_print_error_message.emit(
                {
                    "error": traceback.format_exception(e),
                    "title": "Cache Error",
                    "message": "An unexpected error occurred while caching version manifest."
                }
            )

        return True if data else False, data

    def _cache_custom_version_manifest(self, version_id: str, fetch_manifest_handler: Callable[[str], tuple[dict, str | None]]):
        data = None
        manifest_sha1 = None
        path = self.get_specific_version_manifest_path(version_id)

        # Fetch data
        try:
            data, manifest_sha1 = fetch_manifest_handler(version_id)
        except VersionManifestFetchException as e:
            self.widget_mgr.signal.show_error_message.emit(
                e.user_message,
            )
        except VersionManifestSaveException as e:
            self.widget_mgr.signal.show_error_message.emit(
                e.user_message,
            )
        except Exception as e:
            self.widget_mgr.signal.show_and_print_error_message.emit(
                {
                    "error": traceback.format_exception(e),
                    "title": "Cache Error",
                    "message": "An unexpected error occurred while caching version manifest."
                }
            )

        # Save data
        if data:
            try:
                save_version_manifest(data, path, sha1=manifest_sha1)
            except VersionManifestSaveException as e:
                self.widget_mgr.signal.show_error_message.emit(
                    e.user_message,
                )
                return False, None
            except Exception as e:
                self.widget_mgr.signal.show_and_print_error_message.emit(
                    {
                        "error": traceback.format_exception(e),
                        "title": "Cache Error",
                        "message": "An unexpected error occurred while caching version manifest."
                    }
                )
                return False, None

        return True if data else False, data

    def _read_cached_version_manifest(self, specified_ver: str = None) -> dict | None:
        path = self.switch_between_specific_path(specified_ver)
        if not path.exists():
            self.widget_mgr.signal.show_error_message.emit(
                "Version manifest missing after check. Please try again later.",
            )
            return None

        try:
            version_manifest = json.loads(path.read_text())
            return version_manifest
        except Exception as e:
            self.widget_mgr.signal.show_and_print_error_message.emit(
                {
                    "error": traceback.format_exception(e),
                    "title": "Cache Error",
                    "message": "Unable to read version manifest."
                }
            )
            return None

    def get_cached_version_manifest(self, specified_ver: str = None,
                                    max_age: int = 3600) -> dict | None:
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
                self.widget_mgr.signal.show_error_message.emit(
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

    def get_cached_custom_version_manifest(self, specified_ver: str,
                                           fetch_manifest_handler: Callable[[str], tuple[dict, str | None]],
                                           max_age=1260000) -> dict | None:
        path = self.get_specific_version_manifest_path(specified_ver)
        file = FileObject(path)

        if file.exists:
            age = time.time() - path.stat().st_mtime

            # Check file stat
            if age < max_age:
                return self._read_cached_version_manifest(specified_ver)

        result, data = self._cache_custom_version_manifest(specified_ver, fetch_manifest_handler=fetch_manifest_handler)

        if not result:
            return None

        return data

    def create_download_progress_callback(self, progress_title: str):
        task_id = uuid4().hex
        signals = self.widget_mgr.download_signal

        signals.started.emit(task_id, progress_title)

        def callback(name, percent):
            signals.progress.emit(
                task_id,
                f"Downloading {name}",
                percent,
            )

        return callback, task_id

    @dataclass(frozen=True)
    class ResolvedVersionManifest:
        manifest: dict
        version_id: str
        client_version_id: str

    def resolve_manifest(self, version_id: str, visited: set[str] | None = None) -> ResolvedVersionManifest | None:
        visited = set() if visited is None else visited

        if version_id in visited:
            self.widget_mgr.signal.show_error_message.emit(
                f"Circular version inheritance detected: {version_id}"
            )
            return None

        visited.add(version_id)

        manifest_path = self.get_specific_version_manifest_path(version_id)

        # Read custom (or mod loader) manifest first. If not exist, get manifest from official data
        if manifest_path.is_file():
            manifest = self._read_cached_version_manifest(version_id)
        else:
            manifest = self.get_cached_version_manifest(version_id)

        if not manifest:
            return None

        parent_id = manifest.get("inheritsFrom")

        # Return if the version don't need to merge manifest
        if not parent_id:
            return self.ResolvedVersionManifest(
                manifest=manifest,
                version_id=version_id,
                client_version_id=version_id,
            )

        # Get inherits if needed
        parent = self.resolve_manifest(parent_id, visited)

        if parent is None:
            return None

        try:
            # Merge official and loader manifest
            merged = merge_manifest(
                inherits_version_manifest=parent.manifest,
                mod_version_manifest=manifest,
            )
        except Exception as exc:
            self.widget_mgr.signal.show_error_message.emit(
                f"Unable to merge version {version_id} with {parent_id}: {exc}"
            )
            return None

        return self.ResolvedVersionManifest(
            manifest=merged,
            version_id=version_id,
            client_version_id=parent.client_version_id,
        )

    def resolve_version_alias(self, version_id: str) -> str | None:
        """
        Resolve version alias to related version_id (Such as latest-release)
        :param version_id:
        :return:
        """
        if version_id not in LATEST_VERSION_ALIASES:
            return version_id

        root_manifest = self.get_cached_version_manifest()

        if not root_manifest:
            return None

        return get_latest_version(
            root_manifest,
            is_snapshot=version_id == "latest-snapshot",
        )

class JavaManager:
    def __init__(self, app):
        self.app = app
        self.widget_mgr = app.widget_manager

    #
    # JVM Management
    #
    @property
    def jvm_settings_path(self) -> Path:
        return Path(self.app.work_dir) / "jvms.json"

    def _find_and_save_jvm_search_result(self):
        installations, errors = find_java_installations()
        if not installations:
            self.widget_mgr.signal.show_warning_message.emit(
                "There are no Java installations available in you system.\n"
            )
            return []

        if errors:
            request = AskForRequest("Java Virtual Machine Finder", message = (
                "Unable to detect below java installation version:\n"
            ))
            request.details = "\n".join(path.as_posix() for path in errors)
            request.use_plain_text = True

            self.widget_mgr.signal.askyesno.emit(request)

        self.jvm_settings_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            with self.jvm_settings_path.open("w") as file:
                json.dump(installations, file, indent=4)

            return installations
        except Exception as e:
            self.widget_mgr.signal.show_and_print_error_message.emit(
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
            self.widget_mgr.signal.show_and_print_error_message.emit(
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
            self.widget_mgr.signal.show_error_message.emit(
                "No Java executable found for major version {}.".format(major_version)
            )

        return None

class GameFileDownloadRequest(SignalTransferItem):
    def __init__(self, job_name: Literal["download_client", "download_libraries", "download_assets"],
                 args: tuple):
        SignalTransferItem.__init__(self)
        self.job_name: str = job_name
        self.args: tuple = args

class GameFileManager:
    def __init__(self, app, manifest_manager: ManifestManager):
        self.app = app
        self.widget_mgr = app.widget_manager
        self.manifest_mgr = manifest_manager
        self.jobs = {
            "download_client": self.download_client,
            "download_libraries": self.download_libraries,
            "download_assets": self.download_assets,
        }

    def get_manifest(self, target_version: str,
                     manifest: dict | None, failed_message: str,
                     vanilla: bool=False) -> dict | None:
        if manifest is None:
            # Version manifest
            if not vanilla:
                resolved = self.manifest_mgr.resolve_manifest(target_version)
            else:
                resolved = self.manifest_mgr.get_cached_version_manifest(target_version)

            if resolved is None:
                self.widget_mgr.signal.show_error_message.emit(
                    failed_message,
                )
                return None

            if isinstance(resolved, self.manifest_mgr.ResolvedVersionManifest):
                manifest = resolved.manifest
            else:
                manifest = resolved

        return manifest

    def download_client(self, target_version: str, core_file_path, manifest: dict | None=None) -> bool:
        """
        Download client
        :param target_version: THIS should be the vanilla version id!
        :param core_file_path:
        :param manifest:
        :return:
        """
        manifest = self.get_manifest(target_version, manifest,
                                     "Unable to download client for version {}, failed to fetch version manifest".format(target_version),
                                     vanilla=True)

        if manifest is None:
            return False

        callback, task_id = self.manifest_mgr.create_download_progress_callback(
            "Downloading dependencies..."
        )

        try:
            download_core_file(manifest, core_file_path,
                               raise_for_null_hash=True,
                               progress_callback=callback)
        except Exception as e:
            self.widget_mgr.download_signal.failed.emit(task_id, str(e))
            self.widget_mgr.signal.show_error_message.emit(
                "Unable to download client for version {}".format(target_version)
            )
            return False
        else:
            self.widget_mgr.download_signal.finished.emit(task_id)

        return True

    def download_libraries(self, target_version: str, libraries_dir: Path, natives_dir: Path, manifest: dict | None=None) -> bool:
        manifest = self.get_manifest(target_version, manifest,
                                     "Unable to download dependencies for version {}, failed to fetch version manifest.".format(
                                         target_version)
                                     )
        if manifest is None:
            return False


        callback, task_id = self.manifest_mgr.create_download_progress_callback(
            "Downloading dependencies..."
        )

        try:
            download_full_libraries(manifest, libraries_dir, natives_dir,
                                    progress_callback=callback,
                                    redownload_callback=self.redownload_files)
        except Exception as e:
            self.widget_mgr.download_signal.failed.emit(task_id, str(e))
            self.widget_mgr.signal.show_error_message.emit(
                "Unable to download dependencies for version {}".format(target_version)
            )
            return False
        else:
            self.widget_mgr.download_signal.finished.emit(task_id)

        return True

    def download_assets(self, target_version: str, assets_dir: Path, manifest: dict | None = None,
                        allow_missing: bool = True) -> bool:
        """
        Download assets
        :param target_version:
        :param assets_dir:
        :param manifest:
        :param allow_missing:
        :return:
        """
        manifest = self.get_manifest(target_version, manifest,
                                     "Unable to download assets for version {}, failed to fetch version manifest.".format(target_version))

        if manifest is None:
            return False

        callback, task_id = self.manifest_mgr.create_download_progress_callback(
            "Downloading assets"
        )

        try:
            fails = download_assets(
                manifest,
                assets_dir,
                no_hash_check=True,
                progress_callback=callback,
                launcher_root=self.app.work_dir,
            )

            result, fails = self.redownload_files(fails)

            if not result:
                if allow_missing:
                    self.widget_mgr.signal.show_warning_message.emit(
                        "Some assets could not be downloaded. They are not required to launch the game,"
                        " but missing assets may cause texture issues while you play."
                        " (Allow missing assets flag is enabled)"
                    )
                else:
                    self.widget_mgr.signal.show_error_message.emit(
                        "Some assets could not be downloaded. They are not required to launch the game,"
                        " but missing assets may cause texture issues while you play."
                        " Try relaunching to download them automatically."
                    )
                    self.widget_mgr.download_signal.failed.emit(task_id, "Some assets could not be downloaded.")
                    return False
        except Exception as e:
            self.widget_mgr.download_signal.failed.emit(task_id, str(e))
            self.widget_mgr.signal.show_error_message.emit(
                "Unable to download assets for version {}".format(target_version)
            )
            return False
        else:
            self.widget_mgr.download_signal.finished.emit(task_id)

        return True

    def start_task(self, request: GameFileDownloadRequest) -> Thread:
        job_name = request.job_name
        args = request.args

        # Check target job function is existing
        if not job_name in self.jobs:
            raise NotImplementedError("Job {} not implemented".format(job_name))

        def worker():
            try:
                result = self.jobs[request.job_name](*request.args)
                request.result_queue.put(result)
            except Exception as exc:
                self.app.logger.exception("Game file task failed")
                request.result_queue.put(exc)
            finally:
                request.wait_event.set()

        thread = Thread(target=worker, daemon=True)
        thread.start()

        return thread

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

            self.widget_mgr.download_signal.log.emit(f"Attempt {retry_time}/{MAX_DOWNLOAD_ATTEMPTS}")

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

@dataclass
class LaunchResult:
    process: subprocess.Popen | None = None
    error_message: str | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return self.process is not None and self.error_message is None

    def fail(self, message: str) -> "LaunchResult":
        self.error_message = message
        return self

    def add_warning(self, message: str) -> None:
        self.warnings.append(message)

class LaunchManager:
    def __init__(self, app, manifest_manager: ManifestManager, java_manager: JavaManager, game_file_manager: GameFileManager,
                 account_manager: AccountManager):
        self.app = app
        self.manifest_mgr = manifest_manager
        self.widget_mgr = app.widget_manager
        self.java_mgr = java_manager
        self.game_file_mgr = game_file_manager
        self.account_mgr = account_manager
        self.launching_profiles: set[str] = set()
        self.launched_profiles: list[str] = []
        self.signal = self.LaunchSignal()

    class LaunchSignal(QObject):
        finished = Signal(object, object)  # LaunchProfile, LaunchResult

    def launch(self, profile: LaunchProfile) -> LaunchResult:
        result = LaunchResult()
        try:
            version_id = profile.version_id
            version_id = self.manifest_mgr.resolve_version_alias(version_id)

            if version_id is None:
                return result.fail("Unable to resolve the correct version id of the profile.")

            # Version manifest
            resolved = self.manifest_mgr.resolve_manifest(version_id)

            if resolved is None:
                return result.fail(
                    f"Unable to resolve version manifest: {version_id}"
                )

            version_manifest = resolved.manifest
            client_version_id = resolved.client_version_id

            arguments, asset_index, downloads, java_version, libraries, main_class, old_args = (
                find_useful_part_in_specific_version_manifest(version_manifest)
            )

            # Vars
            asset_id = asset_index.get("id")
            java_major_version = java_version.get("majorVersion")

            # Game paths
            core_file_path = Path(self.app.work_dir, "versions", client_version_id, f"{client_version_id}.jar")
            natives_dir = Path(self.app.work_dir, "versions", version_id, "natives")
            libraries_dir = Path(self.app.work_dir, "libraries")

            game_dir = profile.game_dir

            if not game_dir:
                game_dir = Path(self.app.temp_dir, "minecraft")
            elif not game_dir.exists():
                game_dir.mkdir(parents=True, exist_ok=True)

            # Check client
            if not core_file_path.exists():
                request = GameFileDownloadRequest(
                    "download_client",
                    (client_version_id, core_file_path, version_manifest,)
                )
                self.game_file_mgr.start_task(request)

                request.wait(None)

                client_result = request.result()

                if client_result is not True:
                    return result.fail(
                        f"Unable to launch game. Client download failed."
                    )

            # Libraries
            if not check_full_libraries_exists(version_manifest, libraries_dir, natives_dir):
                request = GameFileDownloadRequest(
                    "download_libraries",
                    (version_id, libraries_dir, natives_dir, version_manifest)
                )
                self.game_file_mgr.start_task(request)

                request.wait(None)

                lib_result = request.result()

                if lib_result is not True:
                    return result.fail(
                        "Unable to launch game due to certain dependencies download failure."
                    )

            current_account_id = self.account_mgr.get_current_account_id()

            if not current_account_id:
                return result.fail(
                    "Select a account before launching."
                )

            launch_account: LaunchAccount = self.account_mgr.get_launch_account()

            # Asset
            default_assets_dir = Path(self.app.work_dir, "assets")
            if not check_assets_exist(version_manifest, default_assets_dir, launcher_root=self.app.work_dir):
                request = GameFileDownloadRequest(
                    "download_assets",
                    (version_id, default_assets_dir, version_manifest)
                )
                self.game_file_mgr.start_task(request)

                request.wait(None)

                asset_result = request.result()

                if asset_result is not True:
                    return result.fail(
                        "Unable to launch game due to certain assets download failure."
                    )

            assets_dir = find_correct_assets_dir(asset_id, default_assets_dir, self.app.work_dir)

            classpath = generate_classpath(
                version_manifest,
                libraries_dir,
                core_file_path,
            )

            # Mappings
            arg_maps = ArgumentMappings(
                player_name=launch_account.player_name,
                version_name=version_id,
                game_directory=game_dir.as_posix(),
                assets_root=assets_dir.as_posix(),
                legacy_assets_root=assets_dir,
                assets_index_name=asset_id,
                auth_uuid=launch_account.minecraft_uuid,
                auth_access_token=launch_account.access_token,
                clientid=CLIENT_ID,
                user_type=launch_account.user_type,
                version_type=profile.version_type,
                natives_directory=natives_dir.as_posix(),
                launcher_name="TestLauncher",
                launcher_version=LAUNCHER_VERSION,
                classpath=classpath,
                classpath_separator=os.pathsep,
                library_directory=libraries_dir.as_posix(),
            )

            target_args = arguments if arguments else old_args

            if not target_args:
                return result.fail(
                    "Unable to parse arguments because data are invalid."
                )

            # Use found java runtime (if available)
            java_path = self.java_mgr.get_support_runtime_jvm_executable(
                java_major_version,
                no_error=True
            )

            if not java_path:
                # Ask for a support java version. If not, use system environment java
                request = SelectPathRequest(
                    title="Require a java executable path to launch game. (Major Version: {})".format(
                        java_major_version),
                    message=None,
                    filter_raw="Java executable (java.exe javaw.exe);;All files (*)"
                )

                self.widget_mgr.signal.ask_for_path.emit(request)

                if not request.wait(120):
                    return result.fail(
                        "Timed out while waiting for Java executable selection."
                    )

                java_path = request.result()

                if java_path:
                    self.app.logger.debug(f"Use specified java executable path: {java_path}")
                else:
                    self.app.logger.debug("Use system environment java.")
                    java_path = "java"

            self.app.logger.debug(f"Java executable path is: {java_path}")

            # Finally, generate launch command
            cmd = generate_launch_command(
                arg_maps=arg_maps,
                main_class=main_class,
                java_path=java_path,
                full_args=target_args
            )

            safe_cmd = ["<access token>" if value == launch_account.access_token else value for value in cmd]
            self.app.logger.debug(f"Launch command: {safe_cmd}")

            # run it
            process = subprocess.Popen(
                cmd,
                cwd=game_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=(
                    subprocess.CREATE_NO_WINDOW
                    if sys.platform == "win32"
                    else 0
                ),
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            self.launched_profiles.append(profile.profile_id)
            result.process = process
            return result
        except Exception as e:
            result.fail(
                "Unable to launch. An unknown error occurred:\n{}".format(
                    "".join(traceback.format_exception(e))
                )
            )

        return result

    def start_launch_task(self, profile: LaunchProfile) -> Thread | None:
        def worker():
            result = self.launch(profile)
            self.signal.finished.emit(profile, result)
            return result

        profile_id = profile.profile_id

        # Check if profile is in launching process
        if profile_id in self.launching_profiles:
            return None

        self.launching_profiles.add(profile_id)

        thread = threading.Thread(
            target=worker,
            name=f"launch-{profile.profile_id}",
            daemon=True,
        )
        thread.start()
        return thread

    def is_profile_running(self, profile_id: str) -> bool:
        return (
                profile_id in self.launching_profiles
                or profile_id in self.launched_profiles
        )

    def profile_finished(self, profile_id: str, exit_code: int) -> None:
        try:
            self.launched_profiles.remove(profile_id)
        except ValueError:
            pass

        self.app.logger.debug(
            f"Profile {profile_id} exited with code {exit_code}."
        )

class GameManager(QObject):
    def __init__(self, app, parent=None):
        super(GameManager, self).__init__(parent)
        self.app = app
        self.account_manager = app.account_manager
        self.widget_mgr = app.widget_manager
        self.manifest = ManifestManager(self.app)
        self.java = JavaManager(self.app)
        self.game_file = GameFileManager(self.app, manifest_manager=self.manifest)
        self.launch = LaunchManager(self.app, self.manifest, self.java, self.game_file, self.account_manager)
