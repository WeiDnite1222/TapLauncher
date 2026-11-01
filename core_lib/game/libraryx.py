"""
This module provides some advanced function for library parse/download process use.
"""
import logging
import re
from copy import deepcopy
from enum import StrEnum

from .library import (convert_maven_version, parse_maven_coordinate, is_complete_maven_url,
                      generate_repo_url, generate_filename_from_maven_coordinate,
                      generate_repo_path)
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


def normalize_library_to_common_struct(library: dict, default_maven_url: str | None = MOJANG_LIBRARIES_ENDPOINT,
                                       default_extension: str = "jar",
                                       ignore_missing_url=False) ->  dict:
    result = deepcopy(library)
    name: str | None = library.get("name")

    if name is None:
        raise VersionDataKeyNotFoundException(
            "Provided mod loader version manifest library does not contain key \"name\"."
        )

    group, artifact, version, classifier, extension = parse_maven_coordinate(name,
                                                                             default_extension=default_extension)

    downloads_raw = result.setdefault("downloads", {})

    if isinstance(downloads_raw, dict):
        downloads = downloads_raw
    else:
        downloads = {}

    artifact_raw = dict(downloads.get("artifact") or {})

    # Legacy native-only entries have classifiers, not a Java artifact.
    # Do not invent a base JAR that may not exist in the repository.
    if not artifact_raw and (result.get("natives") or any(
            key.startswith("natives-") for key in (downloads.get("classifiers") or {}))):
        result["downloads"] = downloads
        return result

    # Generate new relative path and put back
    if not artifact_raw.get("path"):
        filename = generate_filename_from_maven_coordinate(
            artifact,
            version,
            classifier=classifier,
            extension=extension,
        )
        artifact_raw["path"] = generate_repo_path(
            group,
            artifact,
            version,
            filename,
        )

    if not artifact_raw.get("url") and not ignore_missing_url:
        top_level_url: str | None = result.get("url")

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
            if not default_maven_url:
                raise DependencyException(
                    f"No download source for library {name!r}."
                )

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

class LibraryPreference(StrEnum):
    HIGHER_VERSION = "higher_version"
    LOWER_VERSION = "lower_version"
    MOD_LIBRARY = "mod_library"
    INHERITS_LIBRARY = "inherits_library"


PREFER_BY_HIGHER_VERSION = LibraryPreference.HIGHER_VERSION
PREFER_BY_LOWER_VERSION = LibraryPreference.LOWER_VERSION
PREFER_MOD_LIBRARY = LibraryPreference.MOD_LIBRARY
PREFER_INHERITS_LIBRARY = LibraryPreference.INHERITS_LIBRARY

LIBRARY_PREFER_OPTIONS = (PREFER_BY_HIGHER_VERSION, PREFER_BY_LOWER_VERSION, PREFER_MOD_LIBRARY, PREFER_INHERITS_LIBRARY,)


def compare_library_versions(left: str, right: str) -> int:
    """
    Compare two library version string.
    :param left:
    :param right:
    :return:
        result: -1 if left < right, 0 if left == right, 1 if left > right. If parse failed, throw DependencyException.
    """
    if left == right:
        return 0

    numeric_version = r"[0-9]+(?:\.[0-9]+)*"

    if not (re.fullmatch(numeric_version, left) and re.fullmatch(numeric_version, right)):
        raise DependencyException(f"Cannot compare library versions {left!r} and {right!r}."
                                  f" Use PREFER_MOD_LIBRARY or PREFER_INHERITS_LIBRARY may solve this issue.")

    left_parts = tuple(map(int, left.split(".")))
    right_parts = tuple(map(int, right.split(".")))

    length = max(len(left_parts), len(right_parts))
    left_parts += (0,) * (length - len(left_parts))
    right_parts += (0,) * (length - len(right_parts))

    return (left_parts > right_parts) - (left_parts < right_parts)

def deduplicate_libraries(libraries: list[dict], preference: LibraryPreference,
                          default_extension: str = "jar") -> list[dict]:
    indexed = {}

    preference = LibraryPreference(preference)

    for library in libraries:
        name: str | None = library.get("name")
        if not name:
            raise DependencyException("Library is missing its name.")

        group, artifact, version, classifier, extension = parse_maven_coordinate(name,
                                                                                 default_extension=default_extension)
        key = generate_unique_library_key(
            group=group,
            artifact=artifact,
            classifier=classifier,
            extension=extension,
        )

        previous = indexed.get(key)

        if previous is not None:
            logger.warning(
                "Duplicate library: %s / %s",
                previous["name"],
                name,
            )

            # Skip/Replace library depend by the library preference
            if preference in (PREFER_BY_HIGHER_VERSION, PREFER_BY_LOWER_VERSION,):
                previous_version = parse_maven_coordinate(previous["name"], default_extension=default_extension)[2]

                comparison = compare_library_versions(previous_version, version,)

                keep_previous = (
                    comparison > 0
                    if preference == PREFER_BY_HIGHER_VERSION
                    else comparison < 0
                )

                if keep_previous:
                    continue

        indexed[key] = library

    return list(indexed.values())
