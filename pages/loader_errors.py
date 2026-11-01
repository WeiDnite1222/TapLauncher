"""Presentation of structured loader errors shared by loader selection views."""

from collections.abc import Callable

from core_lib.common.exception import LoaderUnsupportedSpecificVersion


def format_unsupported_loader_version(
    error: LoaderUnsupportedSpecificVersion, translate: Callable[..., str],
) -> str:
    loader = {
        "fabric": "Fabric",
        "forge": "Forge",
        "neoforge": "NeoForge",
        "quilt": "Quilt"
    }.get(error.loader_name, error.loader_name)
    return translate(
        "{loader} does not support Minecraft {version}.",
        loader=loader, version=error.target_version,
    )
