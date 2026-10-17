import hashlib
import json
import logging
import os
import platform
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import requests

from ..common.common import get_platform_info, FileObject, download_multiple_files
from ..common.exception import RuntimeManifestFetchException, UnsupportedPlatformException, \
    RuntimeManifestDataException, HashMismatchException, DownloadException, LauncherException
from ..game.version_info import RUNTIME_PLATFORM_MAP, RUNTIME_ARCH_EMPTY, RUNTIME_ARCH_MAP

MOJANG_RUNTIME_MANIFEST = "https://launchermeta.mojang.com/v1/products/java-runtime/2ec0cc96c44e5a76b9c8b7c39df7210883d12871/all.json"
RUNTIME_CHECK_MAX_WORKERS = 10
RUNTIME_DOWNLOAD_MAX_WORKERS = 12

logger = logging.getLogger("Launcher.CoreLib")


def get_current_platform_runtime_key() -> str | None:
    """
    Get the current platform runtime key.
    :return:
        runtime_key: str
    """
    platform_name, arch, os_version = get_platform_info()

    runtime_os_name = RUNTIME_PLATFORM_MAP.get(platform_name, None)

    if runtime_os_name is None:
        return None

    runtime_arch_name = RUNTIME_ARCH_MAP.get(runtime_os_name, {}).get(arch, None)

    if runtime_arch_name is None:
        return None

    # If architecture type is x86_64, some platform's runtime key is same as runtime_os_name. (Such as linux and macOS)
    if runtime_arch_name == RUNTIME_ARCH_EMPTY:
        return runtime_os_name

    full_key = f"{runtime_os_name}-{runtime_arch_name}"

    return full_key


def fetch_runtime_manifest(manifest_url=MOJANG_RUNTIME_MANIFEST, timeout=10) -> dict:
    """
    Fetch the runtime manifest data.
    :param manifest_url:
    :param timeout:
    :return:
        root_manifest: dict
    """
    logger.debug("Getting version manifest from {}".format(manifest_url))

    try:
        r = requests.get(manifest_url, timeout=timeout)
        r.raise_for_status()
    except requests.exceptions.RequestException as e:
        raise RuntimeManifestFetchException(
            "Unable to fetch runtime manifest from {}: {}".format(manifest_url, e),
        )

    try:
        data = r.json()
        logger.debug("RuntimeManifest: {}".format(json.dumps(data, indent=4)))
        return data
    except ValueError as e:
        raise RuntimeManifestFetchException(
            "Unable to deserialize response data into dictionary: {}".format(e)
        )


def find_support_runtime_manifests_info(root_runtime_manifest: dict, require_component: str) -> list:
    """
    Find support runtime manifest (info) by platform.
    :param root_runtime_manifest:
    :param require_component:
    :return:
        manifests_info: list
    """
    runtime_key = get_current_platform_runtime_key()

    if not runtime_key:
        raise UnsupportedPlatformException(
            "Theres no runtime support the current platform or architecture."
        )

    runtime_section = root_runtime_manifest.get(runtime_key, {})

    if not runtime_section:
        raise RuntimeManifestDataException(
            "Root runtime manifest missing runtime key {} data.".format(runtime_key)
        )

    runtimes = runtime_section.get(require_component, [])

    if not runtimes:
        raise RuntimeManifestDataException(
            "Found require component section. But is empty: {}".format(require_component))

    usable = [
        item for item in runtimes
        if item.get("manifest", {}).get("url")
    ]

    if not usable:
        raise RuntimeManifestDataException(
            "No usable runtime manifest data found for component {}".format(require_component)
        )

    return usable


def get_support_runtime_manifest(root_runtime_manifest: dict, require_component: str, no_hash_check=False) -> dict:
    runtime_info = find_support_runtime_manifests_info(root_runtime_manifest, require_component)[0]
    manifest_info = runtime_info.get("manifest", {})
    url = manifest_info.get("url")
    expected_sha1 = manifest_info.get("sha1")

    if not url:
        raise RuntimeManifestDataException(
            "Runtime info missing manifest url"
        )

    if not expected_sha1 and not no_hash_check:
        raise RuntimeManifestDataException(
            "Runtime manifest missing sha1 data from {}".format(url)
        )

    # Fetch data
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
    except requests.exceptions.RequestException as e:
        raise RuntimeManifestFetchException(
            "Unable to fetch runtime manifest from {}: {}".format(url, e),
        )

    # Verify it and convert it to dict
    content = r.content
    actual_sha1 = hashlib.sha1(content).hexdigest()
    try:
        if not no_hash_check and actual_sha1 != expected_sha1:
            raise RuntimeManifestFetchException(
                "Hash mismatch for runtime manifest from url {} got {} "
                "and root manifest expected {}".format(url, actual_sha1, expected_sha1)
            )

        data = json.loads(content.decode("utf-8"))
        logger.debug("RuntimeManifest: {}".format(json.dumps(data, indent=4)))
        return data
    except Exception as e:
        raise RuntimeManifestFetchException(
            "Unable to fetch runtime manifest from {}: {}".format(url, e),
        )

@dataclass
class RuntimeCheckResult:
    # file and dir
    is_executable: bool
    target_path: FileObject | Path | None

    # symlink only
    is_symlink: bool
    source_path: Path

def _check_runtime_file(relative_path, source_path: str | None, file_type: str, sha1: str | None, size: str | None, url: str | None,
                        executable: bool, runtime_dir: Path, no_hash_check: bool = False) -> RuntimeCheckResult:
    full_path = runtime_dir / Path(relative_path)
    source_path = (runtime_dir / Path(source_path)) if source_path else None

    result = RuntimeCheckResult(is_executable=executable, target_path=None, is_symlink=False, source_path=source_path)

    if (not sha1 and not no_hash_check) and file_type == "file":
        raise RuntimeManifestDataException(
            "Runtime manifest missing sha1 data from {}".format(url)
        )

    if not url and file_type == "file":
        raise RuntimeManifestDataException(
            "Runtime manifest missing file url. {}".format(relative_path)
        )

    if not file_type:
        raise RuntimeManifestDataException(
            "Runtime manifest missing file type. {}".format(relative_path)
        )

    if file_type == "file":
        target_file = FileObject(
            path=full_path,
            sha1=sha1,
            size=size,
            url=url,
        )

        if not target_file.expected_sha1 and not no_hash_check:
            raise RuntimeManifestDataException(
                "Runtime file hash is missing."
            )

        # Check file exist
        if target_file.exists and target_file.path.is_file():
            if no_hash_check and target_file.expected_size is not None:
                needs_download = not target_file.verify("size")
            else:
                needs_download = not target_file.verify("sha1")

            if not needs_download:
                suffix = " (no_hash_check=True)" if no_hash_check else ""
                logger.debug(
                    "Runtime file {} already exists.{}".format(
                        target_file,
                        suffix
                    )
                )
            else:
                result.target_path = target_file
    elif file_type == "directory":
        target_file = Path(full_path)

        if not target_file.exists() or not target_file.is_dir():
            result.target_path = target_file
    elif file_type == "link":
        if not Path(full_path).is_symlink() or os.readlink(full_path) != source_path:
            result.target_path = Path(full_path)
    else:
        raise RuntimeManifestDataException(
            "Unsupported file type: {}".format(file_type)
        )

    return result


def collect_runtime_files(manifest: dict, runtime_dir: Path, max_workers=RUNTIME_CHECK_MAX_WORKERS,
                          no_hash_check=False, use_raw=True) -> tuple[list[FileObject], list[FileObject], list[Path], list[dict[str, Path]]]:
    """
    Download runtime files from given manifest.
    :param manifest:
    :param runtime_dir:
    :param max_workers:
    :param no_hash_check:
    :param use_raw: Download raw files instead of download compressed files.
    :return:
        executables: Executable files that need to be downloaded and fix permission on some platform
        files: Runtime files that need to be downloaded
        dirs: Directories that need to be created
        symlinks: Symbolic links that need to be created
    """
    result_executables = []
    result_files = []
    result_dirs = []
    result_symlinks = []
    files = manifest.get("files", {})

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = []

        for relative_path in files:
            data = files[relative_path]
            target_path = data.get("target")
            downloads = data.get("downloads", {})
            artifact = downloads.get("raw" if use_raw else "lzma", {})
            file_type = data.get("type")
            sha1 = artifact.get("sha1")
            size = artifact.get("size")
            url = artifact.get("url")
            executable = data.get("executable", False)

            futures.append(executor.submit(_check_runtime_file, relative_path, target_path, file_type, sha1, size, url,
                                           executable, runtime_dir, no_hash_check))


        for future in as_completed(futures):
            result: RuntimeCheckResult = future.result()
            target_path = result.target_path

            if not target_path:
                logger.debug("No target path found, skip process: {}".format(target_path))
                continue

            if not isinstance(target_path, (FileObject, Path)):
                logger.debug("Target path is not FileObject or Path, skip process: {}".format(target_path))
                continue

            if isinstance(target_path, FileObject):
                target_list = result_executables if result.is_executable else result_files
                target_list.append(target_path)
            elif isinstance(target_path, Path):
                if result.is_symlink:
                    result_symlinks.append({""})
                else:
                    result_dirs.append(target_path)

            if result.target_path and isinstance(result.target_path, FileObject) and not result.is_executable:
                result_files.append(result.target_path)
            elif result.target_path and isinstance(result.target_path, FileObject) and result.is_executable:
                result_executables.append(result.target_path)
            elif result.target_path and isinstance(result.target_path, Path):
                if result.is_symlink:
                    if not result.source_path:
                        raise RuntimeManifestDataException("Runtime data missing symlink source path.")

                    result_symlinks.append({"destination": result.target_path, "source": result.source_path})
                else:
                    result_dirs.append(result.target_path)

    if not use_raw:
        logger.warning(
            "The \"raw\" flag is not enabled, but the launcher does not support compressed files yet. "
            "You will likely need to decompress all files before using them."
        )

    return result_executables, result_files, result_dirs, result_symlinks


def post_process_runtime_dir(dirs: list[Path], executables: list[Path | FileObject], symlinks: list[dict[str, Path]], max_workers=6):
    def _worker(path: Path | FileObject, is_executable: bool):
        if isinstance(path, FileObject):
            path = path.path

        if is_executable:
            if platform.system() != "Windows" and path.exists():
                path.chmod(path.stat().st_mode | 0o755)
            return

        path.mkdir(parents=True, exist_ok=True)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(
            _worker,
            path,
            False)
            for path in dirs
        ]

        futures.extend(
            executor.submit(_worker, path, True)
            for path in executables
        )
        for future in as_completed(futures):
            future.result()

    for value in symlinks:
        dest_path = value.get("destination")
        source_path = value.get("source")

        # ignore existing
        if Path(source_path).is_symlink() and os.readlink(source_path) == dest_path:
            return

        try:
            os.symlink(source_path, dest_path)
        except Exception as exc:
            raise LauncherException(f"Failed to symlink {source_path} to {dest_path}: {exc}")

def download_java_runtimes(component: str, runtime_dir: Path, no_hash_check: bool = False,
                           progress_callback: Callable[[str, float], None] = None,
                           redownload_callback: Callable[[list[FileObject]], tuple[bool, list[FileObject]]] = None,
                           max_download_workers=RUNTIME_DOWNLOAD_MAX_WORKERS,
                           max_check_workers=RUNTIME_CHECK_MAX_WORKERS) -> None:
    """
    Download runtime files from given component.
    :param component: Target component of the java runtime (e.g. java-runtime-alpha, java-runtime-beta)
    :param runtime_dir:
    :param no_hash_check:
    :param progress_callback:
    :param redownload_callback:
    :param max_download_workers:
    :param max_check_workers:
    :return:
        None
    """
    # Fetch manifest
    root_manifest = fetch_runtime_manifest()
    manifest = get_support_runtime_manifest(root_manifest, component, no_hash_check=no_hash_check)
    executables, files, dirs, symlinks = collect_runtime_files(manifest, runtime_dir, max_workers=max_check_workers,
                                                     no_hash_check=no_hash_check)

    # Download runtime files
    full_files = list(files)
    full_files.extend(list(executables))
    fails, successes = download_multiple_files(full_files, max_workers=max_download_workers,
                                               progress_callback=progress_callback)

    download_ok = len(fails) == 0

    if fails and callable(redownload_callback):
        download_ok, fails = redownload_callback(fails)

    if not download_ok:
        logger.warning(
            "Download failed for runtime files: \n"
            + "\n".join([asset.posix_path for asset in fails])
        )
        raise DownloadException(
            "Unable to download some runtime files.\n"
        )

    post_process_runtime_dir(dirs, executables, symlinks, max_workers=max_check_workers)

    return
