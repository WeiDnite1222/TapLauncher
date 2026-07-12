import json
import logging
import shutil
from collections.abc import Callable
from pathlib import Path

import requests

from core_lib.common.common import FileObject, download_multiple_files
from core_lib.common.exception import VersionDataKeyNotFoundException, AssetManifestFetchException, \
    HashMismatchException, AssetManifestSaveException, AssetDataKeyNotFoundException
from core_lib.game.version_info import find_useful_part_in_specific_version_manifest

MOJANG_RESOURCE_ENDPOINT = "https://resources.download.minecraft.net/{beginning}/{hash}"

logger = logging.getLogger("Launcher.CoreLib")

def fetch_asset_manifest(target_version_manifest: dict, raw=False) -> tuple[dict | bytes, str]:
    """
    Fetch the asset manifest from target version's manifest.
    :param target_version_manifest:
    :param raw: Return raw asset manifest.
    :return:
        asset_manifest: dict
        hash: str (sha1)
    """
    _, asset_index, _, _, _, _, _ = find_useful_part_in_specific_version_manifest(target_version_manifest)

    if not asset_index:
        raise VersionDataKeyNotFoundException(
            "Version data section (assetIndex) not found."
        )

    asset_manifest_url = asset_index.get("url", "")
    sha1 = asset_index.get("sha1", "")

    if not asset_manifest_url:
        raise VersionDataKeyNotFoundException(
            "Asset manifest url not found in assetIndex."
        )

    try:
        r = requests.get(asset_manifest_url)
        r.raise_for_status()
    except requests.exceptions.RequestException as e:
        raise AssetManifestFetchException(
            "Failed to fetch version manifest URL: {}\n{}".format(asset_manifest_url, e)
        )

    try:
        if raw:
            return r.content, sha1

        data = r.json()
        return data, sha1
    except ValueError as e:
        raise AssetManifestFetchException(
            "Unable to deserialize asset response data into dictionary: {} ".format(e)
        )

def fetch_and_save_asset_manifest(target_version_manifest: dict, destination: Path) -> dict:
    """
    Fetch the asset manifest from target version's manifest and save it.
    :param target_version_manifest:
    :param destination:
    :return:
        asset_manifest: dict
    """
    data, sha1 = fetch_asset_manifest(target_version_manifest, raw=True)

    if not sha1:
        logger.warning(
            "Target version's manifest does not contain asset manifest sha1 hash. "
        )

    file = FileObject(
        path=destination,
        sha1=sha1,
    )

    destination.parent.mkdir(parents=True, exist_ok=True)

    try:
        with file.path.open("wb") as f:
            f.write(data)

        if sha1 is not None and not file.verify_sha1(sha1):
            raise HashMismatchException(
                "sha1",
                file.sha1,
                sha1,
                file.posix_path
            )

        return json.loads(data.decode("utf-8"))
    except Exception as e:
        raise AssetManifestSaveException(
            "Error saving version manifest:\n{}".format(e)
        )

def collect_assets_from_manifest(asset_id: str, manifest: dict, assets_dir: Path) -> tuple[list[FileObject], list[dict]]:
    """
    Collect assets from asset manifest.
    :param asset_id:
    :param manifest:
    :param assets_dir:
    :return:
        assets: list[FileObject]
        legacy_assets: list[dict] (Contains target and destination of the legacy asset)
    """
    objects = manifest.get("objects", [])
    virtual = manifest.get("virtual", False)

    files = []
    legacy_assets = []

    if not objects:
        raise AssetDataKeyNotFoundException(
            "Assets section (objects) not found in asset manifest."
        )

    for relative_path in objects:
        data = objects[relative_path]
        hash_raw = data.get("hash", "")

        if not hash_raw:
            raise AssetDataKeyNotFoundException(
                "Asset that inside assets section (objects) missing hash."
            )

        beginning = hash_raw[:2]

        full_path = Path(assets_dir, "objects", beginning, hash_raw) # For newer assets
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_url = MOJANG_RESOURCE_ENDPOINT.format(beginning=beginning, hash=hash_raw)
        file = FileObject(path=full_path, sha1=hash_raw, url=full_url)

        if virtual:
            # For legacy assets
            full_path_old = Path(assets_dir, "virtual", asset_id, relative_path)
            legacy_assets.append({
                "target": full_path,
                "destination": full_path_old,
                "sha1": hash_raw,
            })

        if (full_path.exists() and full_path.is_file()) and file.verify_sha1(hash_raw):
            logger.debug("Asset hash {} (Aka {}) already exists.".format(hash_raw, relative_path))
            continue

        files.append(file)

    return files, legacy_assets


def download_assets_and_copy(assets: list[FileObject], legacy_assets: list[dict], progress_callback: Callable[str]) -> list[FileObject]:
    """
    Download assets from target version's asset manifest. (Not sure why this function exist, may for compatibly)
    Also, this function will copy
    :param assets:
    :param legacy_assets:
    :param progress_callback:
    :return:
        files: list[FileObject] (files that download failed)
    """

    fails , _ = download_multiple_files(assets, progress_callback=progress_callback)

    for asset in legacy_assets:
        target = asset.get("target")
        destination = asset.get("destination")
        sha1 = asset.get("sha1")

        if not target or not destination:
            raise ValueError(
                "Legacy asset missing target or destination key."
            )

        # Check source file
        source_asset = FileObject(path=target)
        if not source_asset.exists or (sha1 and not source_asset.verify("sha1", sha1)):
            logger.warning("Target asset {} not found.".format(target))
            continue

        destination.parent.mkdir(parents=True, exist_ok=True)

        # Check destination file
        old_asset = FileObject(path=destination)
        if old_asset.exists and (sha1 and old_asset.verify("sha1", sha1)):
            continue

        shutil.copyfile(target, destination)

    return fails

def correct_assets_name_and_copy(manifest: dict, assets_dir: Path, output_dir: Path) -> list[str]:
    """
    Correct the asset name and copy to output folder. (Left this for somebody who want)
    IMPORTANT: This function will copy the target asset to another directory (rename to its original name).
    And, you must download all assets inside the asset_manifest before you use this function.
    :param manifest:
    :param assets_dir:
    :param output_dir:
    :return:
        missing: list[str] (Contains missing or incorrect hash asset keys)
    """
    missing = []

    objects = manifest.get("objects", [])

    if not objects:
        raise AssetDataKeyNotFoundException(
            "Assets section (objects) not found in asset manifest."
        )

    for key in objects:
        data = objects[key]
        hash_raw = data.get("hash", "")

        if not hash_raw:
            raise AssetDataKeyNotFoundException(
                "Asset that inside assets section (objects) missing hash."
            )

        beginning = hash_raw[:2]

        full_path = Path(assets_dir, "objects", beginning, hash_raw)

        full_url = MOJANG_RESOURCE_ENDPOINT.format(beginning=beginning, hash=hash_raw)
        file = FileObject(path=full_path, sha1=hash_raw, url=full_url)

        if not ((full_path.exists() and full_path.is_file()) and file.verify_sha1(hash_raw)):
            missing.append(key)
            continue

        full_path_new = Path(output_dir, key)
        full_path_new.parent.mkdir(parents=True, exist_ok=True)

        shutil.copy(file.posix_path, full_path_new.as_posix())

    return missing