import json
import os
import re
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
from core_lib.common.exception import JavaRuntimeException, VersionManifestFetchException, VersionManifestSaveException, \
    NoSpecifiedVersionKeyException
from core_lib.game.argument import ArgumentMappings, generate_launch_command
from core_lib.game.asset import check_assets_exist, download_assets, find_correct_assets_dir
from core_lib.game.library_core import check_full_libraries_exists, download_full_libraries, generate_classpath
from core_lib.game.mod.mod_core import merge_manifest
from core_lib.game.version_info import fetch_and_save_version_manifest, get_specific_version_manifest_url_and_hash, \
    save_version_manifest, find_useful_part_in_specific_version_manifest, download_core_file, get_latest_version, \
    LATEST_VERSION_ALIASES
from core_lib.runtime.java import find_java_installations, get_java_version
from core_lib.runtime.mojang import download_java_runtimes, fetch_runtime_manifest, get_current_platform_runtime_key
from manager.account import AccountManager, LaunchAccount
from manager.profile import LaunchProfile
from manager.widgets import SelectPathRequest, AskForRequest, SignalTransferItem

MAX_DOWNLOAD_ATTEMPTS = 3

@dataclass(frozen=True)
class AvailableVersion:
    id: str
    display_name: str
    version_type: str
    source: str
    inherits_from: str | None = None

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

    def list_available_profile_versions(self) -> list[AvailableVersion]:
        result: list[AvailableVersion] = []
        root_manifest = self.get_cached_version_manifest()
        vanilla_ids: set[str] = set()

        # For vanilla version
        for version in (root_manifest or {}).get("versions", []):
            version_id = version.get("id")
            if not version_id:
                continue

            vanilla_ids.add(version_id)
            result.append(
                AvailableVersion(
                    id=version_id,
                    display_name=f"Minecraft {version_id}",
                    version_type=version.get("type") or "custom",
                    source="vanilla",
                )
            )

        # Official launcher aliases are valid vanilla profile versions too.
        for alias_id, alias in LATEST_VERSION_ALIASES.items():
            result.append(
                AvailableVersion(
                    id=alias_id,
                    display_name=alias.get("displayName", alias_id),
                    version_type=(
                        "snapshot" if alias_id == "latest-snapshot" else "release"
                    ),
                    source="vanilla",
                )
            )

        # Locally created modded and custom versions.
        versions_dir = Path(self.app.work_dir, "versions")

        for manifest_path in versions_dir.glob("*/*.json"):
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                self.app.logger.warning(
                    f"Unable to read local version manifest {manifest_path}: {exc}"
                )
                continue

            version_id = manifest.get("id")
            if not version_id or version_id in vanilla_ids:
                continue

            inherits_from = manifest.get("inheritsFrom")
            result.append(
                AvailableVersion(
                    id=version_id,
                    display_name=(
                        f"{version_id} - Minecraft {inherits_from}"
                        if inherits_from else version_id
                    ),
                    version_type=manifest.get("type") or "custom",
                    source="modded" if inherits_from else "custom",
                    inherits_from=inherits_from,
                )
            )

        # Keep the first entry for each ID. The root manifest takes precedence
        # over locally cached copies of vanilla manifests.
        unique: dict[str, AvailableVersion] = {}
        for version in result:
            unique.setdefault(version.id, version)

        return list(unique.values())

@dataclass(frozen=True)
class JavaRuntime:
    id: str
    major_version: int
    raw_version: str
    executable: Path
    home_dir: Path
    source: Literal["system", "managed", "custom"]
    component: str | None = None
    valid: bool = True

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "major": self.major_version,
            "raw": self.raw_version,
            "executable": self.executable.as_posix(),
            "homeDir": self.home_dir.as_posix(),
            "source": self.source,
            "component": self.component,
        }

@dataclass(frozen=True)
class InstallableJavaRuntime:
    component: str
    major_version: int | None
    raw_version: str | None
    released: str | None = None

class JavaManager:
    def __init__(self, app):
        self.app = app
        self.widget_mgr = app.widget_manager
        self.runtimes: list[JavaRuntime] = self._read_runtimes()

    #
    # JVM Management
    #
    @property
    def jvm_settings_path(self) -> Path:
        return Path(self.app.work_dir) / "jvms.json"

    @staticmethod
    def _runtime_from_dict(data: dict) -> JavaRuntime:
        """
        Convert runtime data to JavaRuntime object
        :param data:
        :return:
        """
        executable = Path(data["executable"])
        home_dir = Path(data.get("homeDir") or data.get("home_dir") or executable.parent.parent)

        return JavaRuntime(
            id=str(data.get("id") or uuid4()),
            major_version=int(data["major"]),
            raw_version=str(data.get("raw") or data["major"]),
            executable=executable,
            home_dir=home_dir,
            source=data.get("source") or "system",
            component=data.get("component"),
            valid=executable.is_file(),
        )

    def _read_runtimes(self) -> list[JavaRuntime]:
        """
        Read existing runtime data from jvms.json
        :return:
        """
        if not self.jvm_settings_path.is_file():
            return []
        try:
            data = json.loads(self.jvm_settings_path.read_text(encoding="utf-8"))

            if not isinstance(data, list):
                raise ValueError("JVM settings root must be a list")

            return [self._runtime_from_dict(item) for item in data if isinstance(item, dict)]
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self.app.logger.warning(f"Unable to read JVM settings: {exc}")
            return []

    def save_runtimes(self) -> None:
        """
        Save memory runtimes to jvms.json
        :return:
        """
        self.jvm_settings_path.parent.mkdir(parents=True, exist_ok=True)

        temporary = self.jvm_settings_path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps([runtime.to_dict() for runtime in self.runtimes], indent=4),
            encoding="utf-8",
        )

        temporary.replace(self.jvm_settings_path)

    @staticmethod
    def inspect_runtime(executable: str | Path,
                        *,
                        source: Literal["system", "managed", "custom"] = "custom",
                        component: str | None = None,
                        runtime_id: str | None = None,
                        ) -> JavaRuntime:
        """
        Check runtime version
        :param executable:
        :param source:
        :param component:
        :param runtime_id:
        :return:
            runtime: JavaRuntime
        """
        executable = Path(executable).expanduser().resolve()

        if not executable.is_file():
            raise JavaRuntimeException(f"Java executable does not exist: {executable}")

        major, raw = get_java_version(executable)
        return JavaRuntime(
            id=runtime_id or uuid4().hex,
            major_version=major,
            raw_version=raw,
            executable=executable,
            home_dir=executable.parent.parent,
            source=source,
            component=component,
        )

    def discover_runtimes(self, extra_install_patterns: list | None = None) -> tuple[list[JavaRuntime], list[Path]]:
        """
        Find available runtimes
        :param extra_install_patterns:
        :return:
            discovered: list[JavaRuntime]
            errors: list[Path]
        """
        installations, errors = find_java_installations(extra_install_patterns)
        known_ids = {runtime.executable.resolve(): runtime.id for runtime in self.runtimes}

        discovered = []
        for item in installations:
            executable = Path(item["executable"]).resolve()

            discovered.append(self._runtime_from_dict({
                **item,
                "id": known_ids.get(executable, uuid4().hex),
                "source": "system",
            }))

        return discovered, errors

    def refresh_runtimes(self, extra_install_patterns: list | None = None) -> tuple[list[JavaRuntime], list[Path]]:
        """
        Discover available runtimes and save
        :param extra_install_patterns:
        :return:
            runtimes: list[JavaRuntime]
            errors: list[Path]
        """
        discovered, errors = self.discover_runtimes(extra_install_patterns)
        retained = [runtime for runtime in self.runtimes if runtime.source != "system"]
        by_executable = {runtime.executable.resolve(): runtime for runtime in retained}

        for runtime in discovered:
            by_executable.setdefault(runtime.executable.resolve(), runtime)

        self.runtimes = list(by_executable.values())
        self.save_runtimes()
        return list(self.runtimes), errors

    def register_runtime(self, executable: str | Path) -> JavaRuntime:
        """
        Register runtime to manage's runtimes
        :param executable:
        :return:
        """
        candidate = Path(executable).expanduser().resolve()

        for runtime in self.runtimes:
            if runtime.executable.resolve() == candidate:
                return runtime

        runtime = self.inspect_runtime(candidate, source="custom")
        self.runtimes.append(runtime)
        self.save_runtimes()
        return runtime

    @staticmethod
    def _runtime_major_version(raw_version: str | None) -> int | None:
        if not raw_version:
            return None
        match = re.match(r"^(?:1\.)?(\d+)", raw_version)
        return int(match.group(1)) if match else None

    def list_installable_runtimes(self) -> list[InstallableJavaRuntime]:
        """Return Mojang components with the Java version carried by each one."""
        manifest = fetch_runtime_manifest()
        platform_key = get_current_platform_runtime_key()
        if not platform_key:
            return []
        platform_runtimes = manifest.get(platform_key, {})
        result = []
        for component, versions in platform_runtimes.items():
            if not isinstance(versions, list) or not versions:
                continue
            latest = versions[0] if isinstance(versions[0], dict) else {}
            version = latest.get("version") or {}
            raw_version = version.get("name")
            result.append(InstallableJavaRuntime(
                component=component,
                major_version=self._runtime_major_version(raw_version),
                raw_version=raw_version,
                released=version.get("released"),
            ))
        return sorted(result, key=lambda item: (item.major_version or -1, item.component), reverse=True)

    def list_installable_components(self) -> list[str]:
        """Compatibility API returning component names only."""
        return [runtime.component for runtime in self.list_installable_runtimes()]

    def unregister_runtime(self, runtime_id: str) -> bool:
        """
        Remove runtime from manage's runtimes
        :param runtime_id:
        :return:
        """
        original_count = len(self.runtimes)
        self.runtimes = [runtime for runtime in self.runtimes if runtime.id != runtime_id]

        changed = len(self.runtimes) != original_count

        if changed:
            self.save_runtimes()

        return changed

    def get_or_cache_jvm_settings(self) -> list[dict]:
        if not self.runtimes:
            self.refresh_runtimes()

        return [runtime.to_dict() for runtime in self.runtimes]

    def get_support_runtime_jvm_executable(self, major_version: int | str, no_error: bool=False) -> str | None:
        runtime = self.resolve_runtime(major_version=int(major_version))
        if runtime:
            return runtime.executable.as_posix()

        if not no_error:
            self.widget_mgr.signal.show_error_message.emit(
                "No Java executable found for major version {}.".format(major_version)
            )

        return None

    def list_runtimes(self, *, refresh: bool = False) -> list[JavaRuntime]:
        if refresh:
            self.refresh_runtimes()
        return list(self.runtimes)

    def resolve_runtime(self, *, manifest: dict | None = None, major_version: int | None = None,
                        preferred_runtime_id: str | None = None) -> JavaRuntime | None:
        java_requirement = (manifest or {}).get("javaVersion", {})
        required_major = major_version or java_requirement.get("majorVersion")

        if required_major is None:
            return None

        runtimes = self.list_runtimes()
        if not runtimes:
            runtimes, _ = self.refresh_runtimes()

        if preferred_runtime_id:
            preferred = next((item for item in runtimes if item.id == preferred_runtime_id), None)
            if preferred and preferred.valid and preferred.major_version == int(required_major):
                return preferred

        source_order = {"managed": 0, "custom": 1, "system": 2}
        matches = [item for item in runtimes if item.valid and item.major_version == int(required_major)]
        return min(matches, key=lambda item: source_order[item.source], default=None)

    @property
    def launcher_runtime_dir(self) -> Path:
        return Path(self.app.work_dir) / "runtimes"

    def install_runtime(self, component: str, *, progress_callback=None, redownload_callback=None) -> JavaRuntime:
        destination = self.launcher_runtime_dir / component
        download_java_runtimes(
            component,
            destination,
            progress_callback=progress_callback,
            redownload_callback=redownload_callback,
        )
        executable_name = "java.exe" if sys.platform == "win32" else "java"
        candidates = sorted(destination.rglob(executable_name))
        if not candidates:
            raise JavaRuntimeException(f"Installed runtime has no {executable_name}: {destination}")
        runtime = self.inspect_runtime(candidates[0], source="managed", component=component)
        self.runtimes = [item for item in self.runtimes if item.executable.resolve() != runtime.executable.resolve()]
        self.runtimes.append(runtime)
        self.save_runtimes()
        return runtime

    def ensure_runtime(self, manifest: dict, *, auto_install: bool = False, progress_callback=None,
                       redownload_callback=None) -> JavaRuntime:
        runtime = self.resolve_runtime(manifest=manifest)

        if runtime:
            return runtime

        requirement = manifest.get("javaVersion") or {}
        component = requirement.get("component")
        major = requirement.get("majorVersion")

        if not auto_install or not component:
            raise JavaRuntimeException(f"No compatible Java runtime found (required major version: {major})")

        runtime = self.install_runtime(
            component,
            progress_callback=progress_callback,
            redownload_callback=redownload_callback,
        )
        if major is not None and runtime.major_version != int(major):
            raise JavaRuntimeException(
                f"Installed Java {runtime.major_version}, but Minecraft requires Java {major}"
            )

        return runtime


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
    fail_callback: Callable | None = None

    @property
    def success(self) -> bool:
        return self.process is not None and self.error_message is None

    def fail(self, message: str) -> "LaunchResult":
        self.error_message = message
        if callable(self.fail_callback):
            self.fail_callback()
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

        def fail_callback():
            self.profile_failed(profile.profile_id)

        result.fail_callback = fail_callback
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

            # Resolve a compatible runtime, then offer the Mojang runtime from
            # the version manifest before falling back to a custom executable.
            runtime = self.java_mgr.resolve_runtime(manifest=version_manifest)
            java_path = runtime.executable.as_posix() if runtime else None

            if not java_path:
                component = java_version.get("component")
                if component:
                    install_request = AskForRequest(
                        "Java Runtime Required",
                        f"Minecraft {version_id} requires Java {java_major_version}. "
                        f"Download the Mojang runtime now?",
                    )
                    self.widget_mgr.signal.askyesno.emit(install_request)
                    if install_request.wait(120) and install_request.result():
                        callback, task_id = self.manifest_mgr.create_download_progress_callback(
                            f"Installing Java {java_major_version}"
                        )
                        try:
                            runtime = self.java_mgr.ensure_runtime(
                                version_manifest,
                                auto_install=True,
                                progress_callback=callback,
                                redownload_callback=self.game_file_mgr.redownload_files,
                            )
                        except Exception as exc:
                            self.widget_mgr.download_signal.failed.emit(task_id, str(exc))
                            self.app.logger.warning(f"Automatic Java installation failed: {exc}")
                        else:
                            self.widget_mgr.download_signal.finished.emit(task_id)
                            java_path = runtime.executable.as_posix()

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
                    try:
                        runtime = self.java_mgr.register_runtime(java_path)
                    except JavaRuntimeException as exc:
                        return result.fail(f"The selected Java executable is invalid: {exc}")
                    if runtime.major_version != int(java_major_version):
                        return result.fail(
                            f"Minecraft requires Java {java_major_version}, but the selected executable is "
                            f"Java {runtime.major_version}."
                        )
                    java_path = runtime.executable.as_posix()
                    self.app.logger.debug(f"Use specified java executable path: {java_path}")
                else:
                    return result.fail(f"Java {java_major_version} is required to launch this version.")

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

    def profile_failed(self, profile_id: str) -> None:
        try:
            self.launched_profiles.remove(profile_id)
        except ValueError:
            pass

        try:
            self.launching_profiles.remove(profile_id)
        except ValueError:
            pass

        self.app.logger.debug(
            f"Profile {profile_id} exited."
        )

    def profile_finished(self, profile_id: str, exit_code: int) -> None:
        try:
            self.launched_profiles.remove(profile_id)
        except ValueError:
            pass

        try:
            self.launching_profiles.remove(profile_id)
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
