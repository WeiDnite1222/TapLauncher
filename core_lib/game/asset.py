

MOJANG_RESOURCE_ENDPOINT = "https://resources.download.minecraft.net/{}/{}"


def fetch_asset_manifest(target_version_manifest: dict) -> dict:
    """
    Fetch the asset manifest from target version's manifest.
    :param target_version_manifest:
    :return:
        asset_manifest: dict
    """

    assetIndex = target_version_manifest.get("assetIndex")

    if assetIndex is None:
        pass