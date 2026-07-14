import json
import logging
import shutil
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

from core_lib.common.common import FileObject, download_multiple_files
from core_lib.common.exception import VersionDataKeyNotFoundException, AssetManifestFetchException, \
    HashMismatchException, AssetManifestSaveException, AssetDataKeyNotFoundException, DownloadException, \
    AssetManifestException
from core_lib.game.version_info import find_useful_part_in_specific_version_manifest

MOJANG_RESOURCE_ENDPOINT = "https://resources.download.minecraft.net/{beginning}/{hash}"

ASSET_DOWNLOAD_MAX_WORKERS = 20
ASSET_CHECK_MAX_WORKERS = 20

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

        if sha1 and not file.verify_sha1(sha1):
            raise HashMismatchException(
                "sha1",
                file.sha1,
                sha1,
                file.posix_path
            )

        return json.loads(data.decode("utf-8"))
    except Exception as e:
        logger.exception(e)
        raise AssetManifestSaveException(
            "Error saving version manifest:\n{}".format(e)
        )

def _check_asset(asset_id: str, asset_data: dict, relative_path: str, assets_dir: Path, launcher_root: Path, virtual: bool,
                 map_to_resources: bool, no_hash_check: bool=False)\
        -> tuple[FileObject | None, dict | None]:
    """
    Check if asset exists.
    :param asset_data:
    :param relative_path:
    :param assets_dir:
    :param launcher_root:
    :param virtual:
    :param map_to_resources:
    :return:
        asset_file: FileObject
        legacy_context: dict
    """
    hash_raw = asset_data.get("hash", "")
    expected_size = asset_data.get("size")

    if not hash_raw:
        raise AssetDataKeyNotFoundException(
            "Asset that inside assets section (objects) missing hash."
        )

    beginning = hash_raw[:2]

    full_path = Path(assets_dir, "objects", beginning, hash_raw)  # For newer assets
    full_url = MOJANG_RESOURCE_ENDPOINT.format(beginning=beginning, hash=hash_raw)
    file = FileObject(path=full_path, sha1=hash_raw, url=full_url)

    needs_download = True

    if full_path.exists() and full_path.is_file():
        if no_hash_check and expected_size is not None:
            needs_download = full_path.stat().st_size != expected_size
        else:
            needs_download = not file.verify_sha1(hash_raw)

        if not needs_download:
            suffix = " (no_hash_check=True)" if no_hash_check else ""
            logger.debug(
                "Asset hash {} (Aka {}) already exists.{}".format(
                    hash_raw,
                    relative_path,
                    suffix,
                )
            )

    legacy_context = None
    if virtual:
        legacy_context = {
            "file": file,
            "target": full_path,
            "sha1": hash_raw,
            "destination": Path(assets_dir, "virtual", asset_id, relative_path),
            "size": expected_size,
        }
    elif map_to_resources:
        legacy_context = {
            "file": file,
            "target": full_path,
            "sha1": hash_raw,
            "destination": Path(launcher_root, "resources", relative_path),
            "size": expected_size,
        }

    return file if needs_download else None, legacy_context

def collect_assets_from_manifest(manifest: dict, asset_id: str, assets_dir: Path, launcher_root: Path,
                                 max_workers=ASSET_CHECK_MAX_WORKERS,
                                 no_hash_check=False) -> tuple[list[FileObject], list[dict]]:
    """
    Collect assets from asset manifest. (Only return items that does not exist)
    :param no_hash_check:
    :param manifest:
    :param asset_id:
    :param assets_dir:
    :param launcher_root:
    :param max_workers:
    :return:
        assets: list[FileObject]
        legacy_assets: list[dict] (Contains target and destination of the legacy asset)
    """
    objects = manifest.get("objects", [])
    virtual = manifest.get("virtual", False)
    map_to_resources = manifest.get("map_to_resources", False)

    files = []
    legacy_assets = []

    if not objects:
        raise AssetDataKeyNotFoundException(
            "Assets section (objects) not found in asset manifest."
        )

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(
                _check_asset,
                asset_id, objects[relative_path], relative_path, assets_dir, launcher_root, virtual, map_to_resources,
                no_hash_check=no_hash_check
            )
            for relative_path in objects
        ]

        for future in as_completed(futures):
            asset_file, legacy_context = future.result()

            if asset_file:
                files.append(asset_file)

            # Also copy the asset into legacy directory if needed.
            if legacy_context:
                legacy_assets.append(legacy_context)

    return files, legacy_assets


def download_assets_and_copy(assets: list[FileObject], legacy_assets: list[dict],
                             no_hash_check: bool=False, allow_missing=False,
                             progress_callback: Callable[[str], None]=None,
                             redownload_callback: Callable[[list[FileObject]], tuple[bool, list[FileObject]]]=None) -> list[FileObject]:
    """
    Download assets from target version's asset manifest. (Not sure why this function exist, may for compatibly)
    Also, this function will copy
    :param assets:
    :param legacy_assets:
    :param no_hash_check:
    :param allow_missing:
    :param progress_callback:
    :param redownload_callback:
    :return:
        files: list[FileObject] (files that download failed)
    """

    def __worker(asset: dict):
        target = asset.get("target")
        destination = asset.get("destination")
        sha1 = asset.get("sha1")
        size = asset.get("size")

        if not target or not destination:
            raise ValueError(
                "Legacy asset missing target or destination key."
            )

        # Check source file
        source_asset = FileObject(path=target)

        if (not source_asset.exists or
            (not no_hash_check and sha1 and not source_asset.verify("sha1", sha1))):
            logger.warning("Target asset {} not found.".format(target))
            return False, None

        destination.parent.mkdir(parents=True, exist_ok=True)

        # Check destination file
        old_asset = FileObject(path=destination)
        if old_asset.exists:
            if no_hash_check and size is not None:
                if old_asset.path.stat().st_size == size:
                    logger.debug("Asset {} already exists. (no_hash_check=True)".format(target))
                    return True, None
            elif sha1 and old_asset.verify("sha1", sha1):
                logger.debug("Asset {} already exists.".format(target))
                return True, None

        shutil.copyfile(target, destination)
        return True, destination

    fails , _ = download_multiple_files(assets, progress_callback=progress_callback,
                                        max_workers=ASSET_DOWNLOAD_MAX_WORKERS)


    download_ok = len(fails) == 0

    if fails and callable(redownload_callback):
        download_ok, fails = redownload_callback(fails)

    if not download_ok:
        logger.warning(
            "Download failed for assets: \n"
            +"\n".join([asset.posix_path for asset in fails])
        )
        if not allow_missing:
            return fails

    # Use thread pool to handle copy file process
    with ThreadPoolExecutor(max_workers=ASSET_DOWNLOAD_MAX_WORKERS) as executor:
        futures = [
            executor.submit(
                __worker,
                asset
            )
            for asset in legacy_assets
        ]

        for future in as_completed(futures):
            result, dest = future.result()

            if result and dest:
                logger.debug("Created: {}".format(dest))

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

def download_assets(manifest: dict, assets_dir: Path, launcher_root: Path, no_hash_check: bool=False,
                    progress_callback:  Callable[[str, float], None]=None,
                    redownload_callback: Callable[[list[FileObject]], tuple[bool, list[FileObject]]]=None) -> list[FileObject]:
    _, asset_index, _, _, _, _, _ = find_useful_part_in_specific_version_manifest(manifest)

    asset_id = asset_index.get("id")

    if not asset_id:
        raise VersionDataKeyNotFoundException(
            "Asset ID is missing."
        )

    index_path = Path(assets_dir, "indexes", f"{asset_id}.json")

    # Download and save asset manifest
    asset_manifest = fetch_and_save_asset_manifest(
        manifest,
        index_path,
    )

    # Download assets files
    assets, legacy_assets = collect_assets_from_manifest(
        asset_manifest,
        asset_id,
        assets_dir,
        launcher_root,
        no_hash_check=no_hash_check,
    )

    fails = download_assets_and_copy(
        assets,
        legacy_assets,
        progress_callback=progress_callback,
        no_hash_check=no_hash_check,
        redownload_callback=redownload_callback,
    )

    return fails

def check_assets_exist(manifest: dict, assets_dir: Path, launcher_root: Path, no_hash_check: bool=False) -> bool:
    _, asset_index, _, _, _, _, _ = find_useful_part_in_specific_version_manifest(manifest)

    asset_id = asset_index.get("id")

    if not asset_id:
        raise VersionDataKeyNotFoundException(
            "Asset ID is missing."
        )

    index_path = Path(assets_dir, "indexes", f"{asset_id}.json")

    asset_manifest = None
    if not (index_path.exists() and index_path.is_file()):
        fetch_and_save_asset_manifest(
            manifest,
            index_path,
        )

    with index_path.open() as f:
        asset_manifest = json.load(f)

    # Download assets files
    assets, legacy_assets = collect_assets_from_manifest(
        asset_manifest,
        asset_id,
        assets_dir,
        launcher_root,
        no_hash_check=no_hash_check,
    )

    if not assets and not legacy_assets:
        return True

    return False

def read_exist_assets_indexes(asset_id: str, assets_dir: Path):
    return json.loads(Path(assets_dir, "indexes", f"{asset_id}.json").open().read())


def find_correct_assets_dir(asset_id: str, assets_dir: Path, launcher_root: Path, asset_manifest: dict | None=None) -> Path:
    try:
        if not asset_manifest:
            asset_manifest = read_exist_assets_indexes(asset_id, assets_dir)
    except FileNotFoundError:
        raise AssetManifestException(
            "Asset manifest not found in: {} (Index: {})".format(assets_dir, asset_id),
        )

    virtual = asset_manifest.get("virtual")
    map_to_resources = asset_manifest.get("map_to_resources")

    if virtual:
        return assets_dir / "virtual" / asset_id

    if map_to_resources:
        return launcher_root / "resources"

    return assets_dir