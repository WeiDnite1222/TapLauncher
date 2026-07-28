import json
import logging

import requests

from core_lib.common.exception import VersionManifestFetchException, VersionDataKeyNotFoundException, \
    VersionManifestException

logger = logging.getLogger("Launcher.CoreLib")

FABRIC_META_VERSION_ENDPOINT_V2 = "https://meta.fabricmc.net/v2/versions"
FABRIC_META_LOADER_VERSION_ENDPOINT_V2 = "https://meta.fabricmc.net/v2/versions/loader/{}/"
FABRIC_META_LOADER_MANIFEST_ENDPOINT_V2 = "https://meta.fabricmc.net/v2/versions/loader/{}/{}/profile/json"
FABRIC_MAVEN_URL = "https://maven.fabricmc.net/"

def fetch_fabric_version_list(version_manifest_url: str=FABRIC_META_VERSION_ENDPOINT_V2, timeout: int=5) -> list[dict]:
    try:
        r = requests.get(version_manifest_url, timeout=timeout)
    except requests.exceptions.Timeout:
        raise VersionManifestFetchException(
            "Timeout while fetch from {}".format(version_manifest_url)
        )
    except requests.exceptions.ConnectionError as e:
        raise VersionManifestFetchException(
            "Connection error while fetch from {}: {}".format(version_manifest_url, e)
        )
    except requests.exceptions.HTTPError as e:
        raise VersionManifestFetchException(
            "HTTP error while fetch from {}: HTTP Status: {}".format(version_manifest_url, e.response.status_code)
        )
    except Exception as e:
        raise VersionManifestFetchException(
            "Unknown error while fetch from {}: {}".format(version_manifest_url, e)
        )

    try:
        data = r.json()
    except json.decoder.JSONDecodeError as e:
        raise VersionManifestFetchException(
            "JSON decode error while fetch from {}: {}".format(version_manifest_url, e)
        )

    versions = data.get("versions")

    if not versions:
        raise VersionManifestFetchException(
            "Version this is empty or not set yet in mod version manifest"
        )

    return versions

def is_version_supported_and_stable(fabric_version_list: list[dict], target_version: str) -> tuple[bool, bool | None]:
    if not fabric_version_list:
        raise VersionManifestException(
            "Provided fabric version list is empty."
        )

    for version in fabric_version_list:
        if version["version"] == target_version:
            is_stable = version.get("stable", None)
            return True, is_stable

    return False, None

def get_version_support_loader_list(target_version: str, loader_version_url: str=FABRIC_META_LOADER_VERSION_ENDPOINT_V2, timeout: int=5)\
        -> list[dict]:
    try:
        r = requests.get(loader_version_url.format(target_version), timeout=timeout)
    except requests.exceptions.Timeout:
        raise VersionManifestFetchException(
            "Timeout while fetch from {}".format(loader_version_url)
        )
    except requests.exceptions.ConnectionError as e:
        raise VersionManifestFetchException(
            "Connection error while fetch from {}: {}".format(loader_version_url, e)
        )
    except requests.exceptions.HTTPError as e:
        raise VersionManifestFetchException(
            "HTTP error while fetch from {}: HTTP Status: {}".format(loader_version_url, e.response.status_code)
        )
    except Exception as e:
        raise VersionManifestFetchException(
            "Unknown error while fetch from {}: {}".format(loader_version_url, e)
        )

    try:
        versions = r.json()
    except json.decoder.JSONDecodeError as e:
        raise VersionManifestFetchException(
            "JSON decode error while fetch from {}: {}".format(loader_version_url, e)
        )

    loaders = []

    for version in versions:
        loader = version.get("loader", None)
        if not loader:
            logger.warning("Found corrupted or unsupported loader manifest")
            continue

        loaders.append(loader)

    if not loaders:
        raise VersionManifestException(
            "No available loader found in {}".format(loader_version_url)
        )

    return loaders

def get_loader_manifest_from_loader_data(target_version: str, loader_data: dict,
                                             loader_manifest_url: str=FABRIC_META_LOADER_MANIFEST_ENDPOINT_V2) -> dict:
    loader_ver = loader_data.get("version", None)
    if not loader_ver:
        raise VersionDataKeyNotFoundException(
            "Version key not found in loader manifest {}".format(loader_manifest_url)
        )

    # Create url
    url = loader_manifest_url.format(target_version, loader_ver)
    logger.debug("Full manifest url: {}".format(url))

    try:
        r = requests.get(url, timeout=5)
    except requests.exceptions.Timeout:
        raise VersionManifestFetchException(
            "Timeout while fetch from {}".format(url)
        )
    except requests.exceptions.ConnectionError as e:
        raise VersionManifestFetchException(
            "Connection error while fetch from {}: {}".format(url, e)
        )
    except requests.exceptions.HTTPError as e:
        raise VersionManifestFetchException(
            "HTTP error while fetch from {}: {}".format(url, e.response.status_code)
        )
    except Exception as e:
        raise VersionManifestFetchException(
            "Unknown error while fetch from {}: {}".format(url, e)
        )

    # We don't need verify data, fabric didn't provide manifest hash.
    try:
        return r.json()
    except json.decoder.JSONDecodeError as e:
        raise VersionManifestFetchException(
            "JSON decode error while fetch from {}: {}".format(url, e)
        )
    except Exception as e:
        raise VersionManifestFetchException(
            "Unknown error while fetch from {}: {}".format(url, e)
        )




