import json
import time
import traceback
from pathlib import Path
from uuid import uuid4
from PySide6.QtCore import QObject

from core_lib.common.common import FileObject
from core_lib.common.exception import VersionManifestFetchException, VersionManifestSaveException, \
    NoSpecifiedVersionKeyException
from core_lib.game.version_info import fetch_and_save_version_manifest, get_specific_version_manifest_url_and_hash


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


class GameManager(QObject):
    def __init__(self, app, parent=None):
        super(GameManager, self).__init__(parent)
        self.app = app
        self.widget_mgr = app.widget_manager
        self.manifest = ManifestManager(self.app)