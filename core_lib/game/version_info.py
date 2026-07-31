import json
import logging
import warnings
from collections.abc import Callable
from pathlib import Path

import requests

from ..common.common import FileObject, download_file
from ..common.exception import VersionManifestFetchException, NoVersionFoundException, \
    NoSpecifiedVersionKeyException, VersionDataKeyNotFoundException, VersionManifestSaveException, HashMismatchException

MOJANG_VERSION_MANIFEST_V2 = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
MOJANG_VERSION_MANIFEST = "https://piston-meta.mojang.com/mc/game/version_manifest.json"
MOJANG_LIBRARIES_ENDPOINT = "https://libraries.minecraft.net/"

NATIVE_OS_KEY_MAP = {
    "darwin": "macos",
    "macos": "macos",
    "osx": "macos",
    "linux": "linux",
    "windows": "windows",
}

NATIVE_OS_RULE_MAP = {
    "darwin": "osx",
    "macos": "osx",
    "osx": "osx",
    "linux": "linux",
    "windows": "windows",
}

NATIVE_ARCH_KEY_MAP = {
    "x86": "x86",
    "i386": "x86",
    "i486": "x86",
    "i586": "x86",
    "i686": "x86",

    "x86_64": "x86_64",
    "amd64": "x86_64",

    "aarch64": "arm64",
    "arm64": "arm64",
    "aarch_64": "arm64",
}

NATIVE_OLD_TO_NEW_ARCH = {
    "32": "x86",
    "64": "x86_64",

    "x86": "x86",
    "x86_64": "x86_64",
    "amd64": "x86_64",

    "aarch64": "arm64",
    "arm64": "arm64",
}

NATIVE_NEW_TO_OLD_ARCH = {
    "x86": "32",
    "x86_64": "64",
}

RUNTIME_PLATFORM_MAP = {
    "linux": "linux",
    "darwin": "mac-os",
    "macos": "mac-os",
    "osx": "mac-os",
    "windows": "windows",
    "win32": "windows",
    "cygwin": "windows",
    "msys": "windows",
}

RUNTIME_ARCH_EMPTY = "$EMPTY"

RUNTIME_ARCH_MAP = {
    "linux": {
        "i386": "i386",
        "i686": "i386",
        "x86": "i386",
        "amd64": RUNTIME_ARCH_EMPTY,
        "x86_64": RUNTIME_ARCH_EMPTY,
    },
    "windows": {
        "i386": "x86",
        "i686": "x86",
        "x86": "x86",
        "amd64": "x64",
        "x86_64": "x64",
        "aarch64": "arm64",
        "arm64": "arm64",
    },
    "mac-os": {
        "amd64": RUNTIME_ARCH_EMPTY,
        "x86_64": RUNTIME_ARCH_EMPTY,
        "aarch64": "arm64",
        "arm64": "arm64",
    },
}

logger = logging.getLogger("Launcher.CoreLib")

def get_version_manifest(manifest_url=MOJANG_VERSION_MANIFEST_V2, timeout=10) -> dict | None:
    """
    Get version manifest.
    :param manifest_url: Source of the version manifest. (Default use MOJANG_VERSION_MANIFEST_V2)
    :param timeout: Request timeout
    :return:
        version_manifest: dict
    """
    logger.debug("Getting version manifest from {}".format(manifest_url))

    try:
        r = requests.get(manifest_url, timeout=timeout)
        r.raise_for_status()
    except requests.exceptions.RequestException as e:
        raise VersionManifestFetchException(
            "Error getting version manifest from {}: {}".format(manifest_url, e)
        )

    try:
        data = r.json()
        logger.debug("VersionManifest: {}".format(json.dumps(data, indent=4)))
        return data
    except ValueError as e:
        raise VersionManifestFetchException(
            "Unable to deserialize response data into dictionary: {}".format(e)
        )

def get_latest_version(version_manifest: dict, is_snapshot=False) -> None | str:
    """
    Get latest version (id) from version manifest.
    :param version_manifest: Version manifest.
    :param is_snapshot: Return latest snapshot version.
    :return:
        latest_version: str
    """
    latest = version_manifest.get("latest", {})

    if len(latest) == 0:
        raise NoVersionFoundException(
            "No latest version section available in version manifest."
        )

    latest_ver = latest.get("release" if not is_snapshot else "snapshot", None)

    if latest_ver is None:
        raise NoSpecifiedVersionKeyException(
            "No latest version available."
        )
    else:
        logger.debug("Latest version: {}".format(latest_ver))

    return latest_ver

def get_all_versions(version_manifest: dict, is_snapshot=False, include_all_type=False, specified_type=None) -> list:
    """
    Get all versions (id) from version manifest.
    :param version_manifest:
    :param is_snapshot: Return all versions that type is snapshot.
    :param include_all_type: Return all versions (all types included)
    :param specified_type: Specific version type
    :return:
        filtered_versions: list
    """
    all_vers = version_manifest.get("versions", [])

    if len(all_vers) == 0:
        raise NoVersionFoundException(
            "No version section available in version manifest."
        )

    if not specified_type:
        target_type = "release" if not is_snapshot else "snapshot"
    else:
        target_type = specified_type

    filtered = []

    for ver in all_vers:
        ver_id = ver.get("id", None)
        ver_type = ver.get("type")

        logger.debug("Ver: {}, Type: {}".format(ver_id, ver_type))

        if ver_type == target_type or include_all_type:
            filtered.append(ver)

    if len(filtered) == 0:
        raise NoSpecifiedVersionKeyException("No version matches specified type: {}".format(target_type))

    return filtered

def get_available_version_types(version_manifest: dict) -> list:
    """
    Get available version types from version manifest.
    :param version_manifest:
    :return:
        available_types: list
    """
    all_vers = version_manifest.get("versions", [])

    if len(all_vers) == 0:
        raise NoVersionFoundException(
            "No version section available in version manifest."
        )

    types = []

    for ver in all_vers:
        ver_type = ver.get("type")

        if ver_type not in types:
            types.append(ver_type)

    return types

def get_specific_version_manifest_url(version_manifest: dict, version_id: str) -> str | None:
    """
    Get specific version's manifest url from version manifest.
    :param version_manifest:
    :param version_id:
    :return:
        specific_version_manifest_url: str
    """
    versions = version_manifest.get("versions", [])

    if len(versions) == 0:
        raise NoVersionFoundException(
            "No version section available in version manifest."
        )

    for version in versions:
        if version.get("id") == version_id:
            specific_ver_manifest_url = version.get("url", None)

            if specific_ver_manifest_url is None:
                raise VersionManifestFetchException(
                    "Specific version manifest URL not available in version manifest."
                )

            return specific_ver_manifest_url

    raise NoSpecifiedVersionKeyException(
        "Specified version {} manifest URL not available in version manifest.".format(version_id)
    )

def get_specific_version_manifest_url_and_hash(version_manifest: dict, version_id: str) \
        -> tuple[str,str] | tuple[None, None]:
    """
    Get specific version's manifest url and hash from version manifest.
    :param version_manifest:
    :param version_id:
    :return:
    """
    versions = version_manifest.get("versions", [])

    if len(versions) == 0:
        raise NoVersionFoundException(
            "No version section available in version manifest."
        )

    for version in versions:
        if version.get("id") == version_id:
            specific_ver_manifest_url = version.get("url", None)
            specific_ver_manifest_hash = version.get("sha1", None)

            if specific_ver_manifest_url is None:
                raise VersionManifestFetchException(
                    "Specific version manifest URL is None. Is the manifest URL or source correct?"
                )

            if specific_ver_manifest_hash is None:
                logger.debug("Specific version manifest hash not available in version manifest.")

            return specific_ver_manifest_url, specific_ver_manifest_hash

    raise NoSpecifiedVersionKeyException(
        "Specified version {} manifest URL not available in version manifest.".format(version_id)
    )


def fetch_specific_version_manifest(version_manifest: dict, spec_version: str) -> tuple[bytes, str | None]:
    """
    Get specific version's manifest data and hash from version manifest.
    :param version_manifest:
    :param spec_version:
    :return:
        specific_version_manifest_data: bytes
        hash: str (sha1)
    """
    ver_url, sha1 = get_specific_version_manifest_url_and_hash(version_manifest, spec_version)

    try:
        r = requests.get(ver_url, timeout=10)
        r.raise_for_status()
    except requests.exceptions.RequestException as e:
        raise VersionManifestFetchException(
            "Failed to fetch version manifest URL: {}\n{}".format(ver_url, e)
        )

    return r.content, sha1

# mapping
get_specific_version_manifest = fetch_specific_version_manifest

def default_java_version():
    return {"component": "jre-legacy", "majorVersion": 8}

def find_useful_part_in_specific_version_manifest(spec_version_manifest: dict,
                                                  failback_java_version: dict | None=None) \
        -> tuple[dict | None, dict | None, dict | None, dict | None, list | None, str | None, str | None]:
    """
    Return useful part from version manifest.
    :param spec_version_manifest: Specific version's data
    :param failback_java_version: Failback java version data (default is Java 8)
    :return:
        arguments: dict (contains jvm and game args, for newer version of Minecraft)
        asset_index: dict
        downloads: dict (Game core files are store in here)
        java_version: dict
        libraries: dict
        main_class: str
        legacy_game_args: str (aka "minecraftArguments" in old Minecraft version data)
    """
    arguments = spec_version_manifest.get("arguments", {})
    asset_index = spec_version_manifest.get("assetIndex", {})
    downloads = spec_version_manifest.get("downloads", {})
    libraries = spec_version_manifest.get("libraries", [])
    main_class = spec_version_manifest.get("mainClass", None)
    legacy_game_args = spec_version_manifest.get("minecraftArguments", None)

    if failback_java_version is None:
        failback_java_version = default_java_version()

    java_version = spec_version_manifest.get("javaVersion", failback_java_version)

    if not arguments and not legacy_game_args:
        raise VersionDataKeyNotFoundException(
            "No version manifest available in version manifest. (\"arguments\" or \"minecraftArguments\")"
        )

    if len(asset_index) == 0:
        raise VersionDataKeyNotFoundException(
            "No asset index section available in version manifest. (\"assetIndex\")"
        )

    if len(downloads) == 0:
        raise VersionDataKeyNotFoundException(
            "No downloads section available in version manifest. (\"downloads\")"
        )

    if len(java_version) == 0:
        raise VersionDataKeyNotFoundException(
            "No java version section available in version manifest. (\"javaVersion\")"
        )

    if len(libraries) == 0:
        raise VersionDataKeyNotFoundException(
            "No libraries section available in version manifest. (\"libraries\")"
        )

    if main_class is None:
        raise VersionDataKeyNotFoundException(
            "No main class section available in version manifest. (\"mainClass\")"
        )

    return arguments, asset_index, downloads, java_version, libraries, main_class, legacy_game_args

def get_core_file_download_url_and_hash(version_manifest: dict, is_server: bool=False) -> tuple[str, str] | tuple[None, None]:
    """
    Get core file download url and hash from version manifest.
    :param version_manifest:
    :param is_server: Download server version core file (aka "server.jar") if is enabled. Default is False and ony
     download client version core file ("client.jar")
    :return:
        core_file_download_url: str
        hash: str (sha1)
    """
    core_downloads = version_manifest.get("downloads", {})

    if len(core_downloads) == 0:
        raise VersionDataKeyNotFoundException(
            "No downloads section available in version manifest. (\"downloads\")"
        )

    core_name = "client" if not is_server else "server"
    core_section = core_downloads.get(core_name, {})

    if len(core_section) == 0:
        raise VersionDataKeyNotFoundException(
            logger.debug("No target core section available in version manifest. Wants: {}".format(core_name))
        )

    download_url = core_section.get("url", None)
    sha1 = core_section.get("sha1", None)

    if download_url is None:
        raise VersionDataKeyNotFoundException(
            "Core file url is None.\n"
        )

    if sha1 is None:
        warnings.warn(
            "Core file sha1 is None. This may cause security issues.\n"
        )

    return download_url, sha1

def save_version_manifest(manifest: dict, dest: Path, sha1: str | None=None) -> dict:
    """
    Save version manifest with hash verify
    :param manifest:
    :param dest:
    :param sha1:
    :return:
        data: dict
    """
    file = FileObject(
        path=dest,
        sha1=sha1,
    )

    dest.parent.mkdir(parents=True, exist_ok=True)

    try:
        method = "wb" if isinstance(manifest, bytes) else "w"
        with dest.open(method) as f:
            if isinstance(manifest, bytes):
                f.write(manifest)
            elif isinstance(manifest, dict):
                json.dump(manifest, f)

        if sha1 is not None and not file.verify_sha1(sha1):
            raise HashMismatchException(
                "sha1",
                file.sha1,
                sha1,
                file.posix_path
            )

        if isinstance(manifest, bytes):
            # Convert the data back to dict
            return json.loads(manifest.decode("utf-8"))
        else:
            return manifest
    except Exception as e:
        logger.exception(e)
        raise VersionManifestSaveException(
            "Error saving version manifest:\n{}".format(e)
        )

def fetch_and_save_version_manifest(dest: Path, target_version: str=None, root_manifest=None) -> dict | None:
    """
    Fetch and save version manifest. (Two types. One is root version manifest, another is specific version manifest)
    :param dest: Destination of the version manifest.
    :param target_version: Target version to fetch manifest from. Set this to a Minecraft version if you want to save
    its version data.
    :param root_manifest: Root manifest to fetch specific version manifest from. If not set the function will auto
     fetch it.
    :return:
        version_manifest: dict
    """
    if root_manifest is None:
        root_manifest = get_version_manifest()

    if target_version:
        # For specified ver
        data, sha1 = fetch_specific_version_manifest(root_manifest, target_version)
    else:
        # For root version manifest (contains all versions)
        data = root_manifest
        sha1 = None

    return save_version_manifest(data, dest, sha1)

def download_core_file(manifest: dict, destination: Path, is_server=False, raise_for_null_hash=False,
                       progress_callback: Callable[[str, float], None]=None) -> FileObject:
    """
    Download core file from version manifest.
    :param manifest:
    :param destination:
    :param is_server:
    :param raise_for_null_hash:
    :param progress_callback:
    :return:
        client_file: FileObject
    """
    url, sha1 = get_core_file_download_url_and_hash(manifest, is_server=is_server)

    destination.parent.mkdir(parents=True, exist_ok=True)
    file = FileObject(destination, url=url)

    if sha1 is None and raise_for_null_hash:
        raise VersionDataKeyNotFoundException(
            "Core file hash is missing. Enable \"raise_for_null_hash\" flag to ignore this exception.\n"
        )
    elif sha1 is None:
        logger.warning("Client has no sha1.")

    if file.exists and file.verify("sha1", sha1):
        logger.info(f"Client existed and sha1 matches.")
    elif url is not None:
        download_file(file, progress_callback=progress_callback)
    elif not url:
        raise VersionDataKeyNotFoundException(
            "Core file url is None. Unable to download it."
        )

    return file


LATEST_VERSION_ALIASES = {
    "latest-release": {"displayName": "Latest Release"},
    "latest-snapshot": {"displayName": "Latest Snapshot"},
}
