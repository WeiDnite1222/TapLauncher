"""
This module provide some advanced function for library parse/download process use.
"""
import logging
import re
from copy import deepcopy

from .library import (convert_maven_version, parse_maven_coordinate, generate_relative_path_by_maven_coordinate,
                      is_complete_maven_url, generate_repo_url)
from .version_info import MOJANG_LIBRARIES_ENDPOINT
from ..common.exception import VersionDataKeyNotFoundException, DependencyException

logger = logging.getLogger("Launcher.CoreLib")


def convert_maven_version_with_extra(version: str, failback=None) -> tuple[tuple[int, int, int] | None, str | None]:
    match = re.fullmatch(
        r"(\d+(?:\.\d+){1,2})(.*)",
        version,
    )

    if match is None:
        return failback, None

    base_ver = match.group(1)
    extra_ver = match.group(2) or None

    base_ver_converted = convert_maven_version(base_ver, failback=None)

    if base_ver_converted is None:
        return failback, extra_ver

    return base_ver_converted, extra_ver

def generate_unique_library_key(group: str, artifact: str, classifier: str | None=None, extension: str | None=None, version: str | None=None) -> str:
    key = f"{group}:{artifact}"
    if version is not None:
        key += f":{version}"

    if classifier is not None:
        key += f":{classifier}"

    if extension is not None:
        key += f":{extension}"

    return key


def normalize_library_to_common_struct(library: dict, default_maven_url: str = MOJANG_LIBRARIES_ENDPOINT) ->  dict:
    result = deepcopy(library)
    name: str = library.get("name")

    if name is None:
        raise VersionDataKeyNotFoundException(
            "Provided mod loader version manifest library does not contain key \"name\"."
        )

    group, artifact, version, classifier, extension = parse_maven_coordinate(name)

    downloads_raw = result.setdefault("downloads", {})

    if isinstance(downloads_raw, dict):
        downloads = downloads_raw
    else:
        downloads = {}

    artifact_raw = dict(downloads.get("artifact") or {})

    # Generate new relative path and put back
    if not artifact_raw.get("path"):
        path = generate_relative_path_by_maven_coordinate(name)
        if not path:
            raise DependencyException(
                f"Unable to generate artifact path for {name}"
            )
        artifact_raw["path"] = path

    if not artifact_raw.get("url"):
        top_level_url = result.get("url")

        if top_level_url:
            if is_complete_maven_url(
                    top_level_url,
                    group,
                    artifact,
                    version,
                    classifier,
                    extension,
            ):
                # Put existing url to downloads.artifact
                artifact_raw["url"] = top_level_url
            else:
                # Replace broken url
                artifact_raw["url"] = generate_repo_url(
                    top_level_url,
                    group,
                    artifact,
                    version,
                    classifier,
                    extension,
                )
        else:
            # Generate missing url
            artifact_raw["url"] = generate_repo_url(
                default_maven_url,
                group,
                artifact,
                version,
                classifier,
                extension,
            )

    # Put hash information to artifact
    for key in (
            "sha1",
            "sha256",
            "sha512",
            "md5",
            "size",
    ):
        if artifact_raw.get(key) is None:
            value = result.get(key)
            if value is not None:
                artifact_raw[key] = value

    # Put updated data back to result
    downloads["artifact"] = artifact_raw
    result["downloads"] = downloads

    return result
