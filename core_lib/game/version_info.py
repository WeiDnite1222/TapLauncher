import json
import requests

from .core_init import logger

MOJANG_VERSION_MANIFEST_V2 = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"


def get_version_manifest(manifest_url=MOJANG_VERSION_MANIFEST_V2, timeout=10) -> dict | None:
    logger.debug("Getting version manifest from {}".format(manifest_url))

    try:
        r = requests.get(manifest_url, timeout=timeout)
    except requests.exceptions.RequestException as e:
        logger.error("Error getting version manifest from {}".format(manifest_url))
        logger.error("Exception: {}".format(e))
        return None

    try:
        data = r.json()
        logger.debug("VersionManifest: {}".format(json.dumps(data, indent=4)))
        return data
    except ValueError as e:
        logger.error("Unable to deserialize response data into dictionary.")
        logger.error("URL: {}".format(manifest_url))
        logger.error("Exception: {}".format(e))
        return None


def get_latest_version(version_manifest: dict, is_snapshot=False) -> None | str:
    latest = version_manifest.get("latest", {})

    if len(latest) == 0:
        logger.debug("No latest version section available in version manifest.")
        logger.debug("Data: {}".format(json.dumps(version_manifest, indent=4)))
        return None

    latest_ver = latest.get("release" if not is_snapshot else "snapshot", None)

    if latest_ver is None:
        logger.debug("No latest version available.")
    else:
        logger.debug("Latest version: {}".format(latest_ver))

    return latest_ver


def get_specific_version_manifest_url(version_manifest: dict,
                                      version_id: str, is_snapshot=False) -> str | None:
    versions = version_manifest.get("versions", [])

    if len(versions) == 0:
        logger.debug("No version section available in version manifest.")
        return None

    ver_type = "release" if not is_snapshot else "snapshot"
    versions = [version for version in versions if version.get("type") ==  ver_type]

    for version in versions:
        if version.get("id") == version_id:
            specific_ver_manifest_url = version.get("url", None)

            if specific_ver_manifest_url is None:
                logger.debug("Specific version manifest URL not available in version manifest.")
                return None

            return specific_ver_manifest_url

    logger.debug("No version section available in version manifest.")

    return None


def fetch_specific_version_manifest(version_manifest: dict, spec_version: str) -> dict | None:
    ver_url = get_specific_version_manifest_url(version_manifest, spec_version)

    if ver_url is None:
        logger.debug("Unable to get specific version manifest url from version manifest.\n"
                     "Version: {}".format(spec_version))
        return None

    try:
        r = requests.get(ver_url, timeout=10)
    except requests.exceptions.RequestException as e:
        logger.error("Error getting version manifest from {}".format(ver_url))
        logger.error("Exception: {}".format(e))
        return None

    try:
        data = r.json()
        logger.debug("SpecificVersionManifest: {}".format(json.dumps(data, indent=4)))
        return data
    except ValueError as e:
        logger.error("Unable to deserialize response data into dictionary.")


def find_useful_part_in_specific_version_manifest(spec_version_manifest: dict)\
        -> tuple[dict | None, dict | None, dict | None, dict | None, list | None, str | None]:
    arguments = spec_version_manifest.get("arguments", {})
    asset_index = spec_version_manifest.get("assetIndex", {})
    downloads = spec_version_manifest.get("downloads", {})
    java_version = spec_version_manifest.get("java_version", {})
    libraries = spec_version_manifest.get("libraries", [])
    main_class = spec_version_manifest.get("mainClass", None)

    if len(arguments) == 0:
        logger.debug("No arguments section available in version manifest.")

    if len(asset_index) == 0:
        logger.debug("No asset index section available in version manifest.")

    if len(downloads) == 0:
        logger.debug("No downloads section available in version manifest.")

    if len(java_version) == 0:
        logger.debug("No java version section available in version manifest.")

    if len(libraries) == 0:
        logger.debug("No libraries section available in version manifest.")

    if main_class is None:
        logger.debug("No main class section available in version manifest.")

    return arguments, asset_index, downloads, java_version, libraries, main_class
