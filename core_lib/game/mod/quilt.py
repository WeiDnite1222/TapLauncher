from packaging.version import Version

from core_lib.game.mod.fabric import (fetch_fabric_versions,
                                      is_version_supported_and_stable as is_fabric_version_supported_and_stable,
                                      get_version_support_loader_list as get_fabric_version_support_loader_list,
                                      get_loader_manifest_from_loader_data as get_fabric_loader_manifest_from_loader_data)

QUILT_META_VERSION_ENDPOINT = "https://meta.quiltmc.org/v3/versions"
QUILT_META_GAME_VERSION_ENDPOINT = "https://meta.quiltmc.org/v3/versions/game"
QUILT_META_LOADER_VERSION_ENDPOINT = "https://meta.quiltmc.org/v3/versions/loader/{}"
QUILT_META_LOADER_MANIFEST_ENDPOINT = (
    "https://meta.quiltmc.org/v3/versions/loader/{}/{}/profile/json"
)
QUILT_MAVEN_URL = "https://maven.quiltmc.org/repository/release/"

def get_full_version_string(version: str, loader_version: str, loader_name="quilt") -> str:
    return f"{loader_name}-loader-{loader_version}-{version}"

def fetch_quilt_versions(version_manifest_url: str=QUILT_META_VERSION_ENDPOINT, timeout: int=5) -> list[dict]:
    return fetch_fabric_versions(version_manifest_url, timeout)

is_version_supported_and_stable = is_fabric_version_supported_and_stable

def get_version_support_loader_list(target_version: str, loader_version_url: str=QUILT_META_LOADER_VERSION_ENDPOINT, timeout: int=5):
    loaders = get_fabric_version_support_loader_list(
        target_version, loader_version_url, timeout, loader_name="quilt",
    )
    # Quilt Meta lists older loaders first; show the newest release first.
    return sorted(loaders, key=lambda loader: Version(loader["version"]), reverse=True)

def get_loader_manifest_from_loader_data(target_version: str, loader_data: dict,
                                             loader_manifest_url: str=QUILT_META_LOADER_MANIFEST_ENDPOINT) -> dict:
    return get_fabric_loader_manifest_from_loader_data(target_version, loader_data, loader_manifest_url)
