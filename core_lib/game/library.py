import json
import logging
import re
import zipfile
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit, unquote

from ..common.common import get_platform_info, FileObject, download_multiple_files, unzip
from .version_info import (
    MOJANG_LIBRARIES_ENDPOINT,
    NATIVE_OS_KEY_MAP,
    NATIVE_OS_RULE_MAP,
    NATIVE_ARCH_KEY_MAP,
    NATIVE_NEW_TO_OLD_ARCH,
    NATIVE_OLD_TO_NEW_ARCH, find_useful_part_in_specific_version_manifest,
)
from ..common.exception import UnsupportedPlatformException, NativeResolveException, DependencyException, \
    VersionDataKeyNotFoundException, DownloadException

logger = logging.getLogger("Launcher.CoreLib")

def parse_maven_coordinate(value: str, default_extension="jar"):
    value = value.strip()

    coordinate, separator, extension = value.partition("@")
    parts = coordinate.split(":")

    if len(parts) not in (3, 4):
        raise ValueError(f"Invalid maven coordinate {value}")

    group, artifact, version = parts[:3]
    classifier = parts[3] if len(parts) == 4 else None

    if version.count("-") > 0:
        version, extra = version.split("-", 1)

    if not group or not artifact or not version:
        raise ValueError(f"Coordinate key can not be empty: {value!r}")

    if not extension:
        extension = default_extension

    return group, artifact, version, classifier, extension

def convert_maven_version(version: str, failback=None) -> tuple[int, int, int]:
    try:
        print(version)
        items = version.split(".")
        if len(items) >= 3:
            major, minor, patch = items[0], items[1], items[2]
            if len(items) > 3:
                logger.debug(f"Found version tag: {".".join(items)}")
        elif len(items) == 2:
            major, minor, patch = 0, items[0], items[1]
        else:
            raise ValueError(f"Unable to parse version: {version!r}")

        return int(major), int(minor), int(patch)
    except ValueError:
        return failback

def generate_filename_from_maven_coordinate(artifact: str, version, classifier="", extension="jar") -> str:
    classifier = f"-{classifier}" if classifier else ""

    return (
        f"{artifact}-"
        f"{version}"
        f"{classifier}."
        f"{extension}"
    )

def generate_repo_path(group: str, artifact: str, version: str, filename) -> str:
    group_path = group.replace(".", "/")

    return (
        f"{group_path}/"
        f"{artifact}/"
        f"{version}/"
        f"{filename}"
    )

def is_complete_maven_url(url: str, group: str, artifact: str, version: str, classifier: str="", extension: str=".jar") -> bool:
    filename = generate_filename_from_maven_coordinate(artifact, version, classifier=classifier, extension=extension)
    repository_path = generate_repo_path(group, artifact, version, filename)
    parsed = urlsplit(url)

    if parsed.scheme not in ("http", "https"):
        return False

    path = unquote(parsed.path).replace("\\", "/")
    expected_path = "/" + repository_path

    return path.endswith(expected_path)

def generate_repo_url(maven_url: str, group: str, artifact: str, version: str, classifier="", extension=".jar") -> str:
    filename = generate_filename_from_maven_coordinate(artifact, version, classifier=classifier, extension=extension)
    path = generate_repo_path(group, artifact, version, filename)

    if not maven_url.endswith("/"):
        maven_url += "/"

    return f"{maven_url}{path}"

def is_library_allowed(rules, platform_rule_name, platform_arch_type, platform_version):
    """
    Checks if the given rule is allowed for the given platform to use it.
    :param rules: Rules from library data
    The following parameters can get from get_natives_platform_info
    :param platform_rule_name: Platform rule name
    :param platform_arch_type: Platform arch type
    :param platform_version: Platform version
    :return:
    """
    allowed = False

    if not rules:
        return True

    for rule in rules:
        rule_action = rule.get("action", None)
        os_section = rule.get("os", {})
        rule_os = os_section.get("name", None)
        rule_arch = os_section.get("arch")  # Not sure if is available in official source
        rule_version = os_section.get("version", None)

        if rule_os is not None and platform_rule_name != rule_os:
            continue

        if rule_arch is not None and platform_arch_type != rule_arch:
            continue

        if rule_version is not None:
            try:
                if re.search(rule_version, platform_version) is None:
                    continue
            except re.error as exc:
                logger.warning(
                    f"Unsupported OS version regex {rule_version!r}: {exc}"
                )
                continue

        if rule_action == "allow":
            allowed = True
        elif rule_action == "disallow":
            allowed = False
        else:
            logger.warning(f"Unknown action {rule_action}\n")

    return allowed


def get_natives_platform_info():
    """
    Get platform information that converted to natives supported formula type
    :return:
        platform_key_name: str, platform_rule_name: str, platform_arch_type: str
    """
    platform_name, arch, os_version = get_platform_info()

    platform_key_name = NATIVE_OS_KEY_MAP.get(platform_name, None)
    platform_rule_name = NATIVE_OS_RULE_MAP.get(platform_name, None)
    platform_arch_type = NATIVE_ARCH_KEY_MAP.get(arch, None)

    return platform_key_name, platform_rule_name, platform_arch_type


def is_native_allowed(lib_name, platform_key_name, platform_arch_type, unspecified_arch_policy: str = "x86_64") -> bool:
    # Parse native key
    match = re.search(r":(natives-[^:]+)$", lib_name)

    if match:
        native_key = match.group(1)
        logger.debug(f"Found native key {native_key} in {lib_name}")

        try:
            parts = native_key.split("-")

            if len(parts) == 2:  # Only os name exists
                native_os_name = parts[1]
                if unspecified_arch_policy == "universal":
                    arch_type = platform_arch_type
                    logger.debug(
                        f"This native may for platform \"{native_os_name}\" (\"May\" for all architecture type)")
                else:
                    arch_type = unspecified_arch_policy
                    logger.debug(
                        f"This native may for platform \"{native_os_name}\" and specific architecture type {unspecified_arch_policy}")

            elif len(parts) == 3:  # With architecture type
                native_os_name, arch_type = parts[1], parts[2]
                logger.debug(f"This native may for platform \"{native_os_name}\" and architecture type \"{arch_type}\"")
            else:
                logger.warning("Unsupported native key '{}'".format(native_key))
                return False

            arch_type_converted = NATIVE_ARCH_KEY_MAP.get(arch_type, arch_type)

            if platform_key_name == native_os_name and arch_type_converted == platform_arch_type:
                return True

        except ValueError:
            logger.warning(
                "Unsupported native key '{}'".format(native_key)
            )

    return False


def is_legacy_native_allowed(natives, classifiers, platform_rule_name, platform_arch_type,
                             unspecified_arch_policy: str = "x86_64") -> tuple[bool, dict | None, str | None]:
    valid_non_arch_values = {
        "universal",
        "x86",
        "x86_64",
        "arm64",
    }

    if unspecified_arch_policy not in valid_non_arch_values:
        raise ValueError(
            f"Unsupported considered_non_arch: "
            f"{unspecified_arch_policy!r}"
        )

    classifier = natives.get(platform_rule_name)

    if classifier:
        if "${arch}" in classifier:
            legacy_arch = NATIVE_NEW_TO_OLD_ARCH.get(platform_arch_type)

            if legacy_arch is None:
                logger.warning(
                    f"No legacy architecture mapping for {platform_arch_type}"
                )
                classifier = None
            else:
                classifier = classifier.replace("${arch}", legacy_arch)

        if classifier:
            native_artifact = classifiers.get(classifier)

            if native_artifact:
                return True, native_artifact, classifier

    # classifiers-rule use NATIVE_OS_RULE_MAP
    if classifiers:
        logger.debug(
            f"\nClassifiers: {json.dumps(classifiers, indent=4)}\n"
        )

        for native in classifiers.keys():
            data_raw = classifiers[native]
            data = json.dumps(classifiers[native], indent=4)
            logger.debug(f"Contains native: {data}\n")

            parts = native.split("-")

            universal = False

            if len(parts) == 2:
                native_os_name = parts[1].lower()
                if unspecified_arch_policy == "universal":
                    universal = True
                    arch_type = platform_arch_type
                    logger.debug(
                        f"This native may for platform \"{native_os_name}\" (\"May\" for all architecture type)")
                else:
                    arch_type = unspecified_arch_policy
                    logger.debug(
                        f"This native may for platform \"{native_os_name}\" and specific architecture type {unspecified_arch_policy}")
            elif len(parts) == 3:
                native_os_name, arch_type = parts[1].lower(), parts[2].lower()
                logger.debug(f"This native may for platform \"{native_os_name}\" and architecture type \"{arch_type}\"")
            else:
                logger.warning("Unsupported legacy native key '{}'".format(native))
                continue

            arch_type_converted = NATIVE_OLD_TO_NEW_ARCH.get(str(arch_type), None) if not universal else None
            if not universal and arch_type_converted != platform_arch_type:
                logger.warning("Unsupported legacy native architecture '{}'".format(native))
                continue

            if native_os_name == platform_rule_name and (arch_type_converted == platform_arch_type or universal):
                return True, data_raw, native

    return False, None, None


def generate_relative_path_by_maven_coordinate(maven_coordinate: str, extra=None) -> str | None:
    parts = maven_coordinate.split(":")

    if len(parts) not in (3, 4):
        logger.warning("Unsupported maven coordinate '{}'".format(maven_coordinate))
        return None

    group, artifact, version = parts[:3]
    classifier = extra or (parts[3] if len(parts) == 4 else None)

    base_path = group.replace(".", "/")
    filename = f"{artifact}-{version}"

    if classifier:
        filename += f"-{classifier}"

    return f"{base_path}/{artifact}/{version}/{filename}.jar"


def remove_duplicate_artifacts(artifacts: list[dict], ignore_null=False, compare_by_name=False) -> list[dict]:
    seen = set()
    result = []

    for artifact in artifacts:
        path = artifact.get("path")
        name = artifact.get("name")

        if name in seen and compare_by_name:
            continue
        elif path in seen:
            continue

        if name is None or path is None:
            logger.warning("Artifact '{}' has no name or path.".format(artifact))

        if (not ignore_null or name is not None) and compare_by_name:
            result.append(artifact)
            seen.add(name)
        elif not ignore_null or path is not None:
            result.append(artifact)
            seen.add(path)

    return result


def generate_formatted_artifact_with_name(lib_name, lib_artifact, libraries_endpoint=MOJANG_LIBRARIES_ENDPOINT,
                                          extra: dict | None = None, relative_args: dict | None = None) -> dict | None:
    """
    Generates a formatted artifact
    :param lib_name: Library name
    :param lib_artifact: Type should be a dict, and it must contain the key "path" (relative path)
    :param libraries_endpoint: The function will use it and relative path to generate a new URL if artifact does not contain it.
    Default value is MOJANG_LIBRARIES_ENDPOINT
    :param extra: Extra part of the artifact (Will be included if exists)
    :param relative_args: Arguments of the generate_relative_path_by_maven_coordinate (Will be called when relative path
    is missing)
    :return: artifact_new: dict
    """
    artifact_new = dict(lib_artifact)
    artifact_new["name"] = lib_name

    if not artifact_new.get("path"):
        logger.warning(f"Artifact {lib_name} missing relative path. Trying to generate new relative path...")
        if relative_args is None: relative_args = {}
        relative_path = generate_relative_path_by_maven_coordinate(lib_name, **relative_args)
        if relative_path:
            artifact_new["path"] = relative_path
            logger.debug(f"Artifact {lib_name} relative path: {relative_path}")
        else:
            logger.error(f"Unable to generate new relative path for artifact {lib_name}")
            return None

    if not artifact_new.get("url") and artifact_new.get("path"):
        artifact_new["url"] = (
                libraries_endpoint.rstrip("/")
                + "/"
                + artifact_new["path"].lstrip("/")
        )

    if extra:
        artifact_new.update(extra)

    return artifact_new


def collect_library_artifacts(specific_version_manifest):
    _, _, _, _, libraries, _, _ = find_useful_part_in_specific_version_manifest(specific_version_manifest)

    items = []

    # Same as natives
    _, _, os_version = get_platform_info()
    platform_key_name, platform_rule_name, platform_arch_type = get_natives_platform_info()

    for library in libraries:
        name = library.get("name", "")
        artifact_raw = library.get("downloads", {}).get("artifact", {})
        rules = library.get("rules", [])
        classifiers = library.get("downloads", {}).get("classifiers", {})
        natives = library.get("natives", {})

        # Ignore natives
        if (len(natives) > 0 or bool(re.search(r":natives-[^:]+$", name)) or
                any(native.startswith("natives-") for native in classifiers)):
            logger.info(f"Skipping {name} because its a native library.")
            continue

        if not is_library_allowed(
                rules,
                platform_rule_name,
                platform_arch_type,
                os_version,
        ):
            logger.debug(f"Library {name} can't pass library rules.")
            continue

        artifact = generate_formatted_artifact_with_name(
            name,
            artifact_raw
        )

        if artifact:
            items.append(artifact)

    if not items:
        raise DependencyException(
            "Could not find any artifact in any of the libraries."
        )

    return items


def collect_native_artifacts(specific_version_manifest):
    """
    Collects native artifacts that support current platform
    :param specific_version_manifest:
    :return:
        filtered_natives_artifacts: list[dict]
    """
    filtered = []

    # Convert current platform and architecture type to same formula
    _, _, os_version = get_platform_info()
    platform_key_name, platform_rule_name, platform_arch_type = get_natives_platform_info()

    if platform_key_name is None or platform_arch_type is None or platform_rule_name is None:
        raise UnsupportedPlatformException(
            f"Unsupported platform: key={platform_key_name}, "
            f"rule={platform_rule_name}, arch={platform_arch_type}"
        )

    _, _, _, _, libraries, _, _ = find_useful_part_in_specific_version_manifest(specific_version_manifest)

    for library in libraries:
        name = library.get("name", "")
        artifact = library.get("downloads", {}).get("artifact", {})
        # For newer Minecraft (VER>1.7.10)
        rules = library.get("rules", [])
        # For legacy version (VER<1.8)
        classifiers = library.get("downloads", {}).get("classifiers", {})
        natives = library.get("natives", {})
        exclude = library.get("extract", {}).get("exclude", ["META-INF/"])  # For extract use

        is_natives = False

        # Check if library is a native
        if (len(natives) > 0 or bool(re.search(r":natives-[^:]+$", name)) or
                any(native.startswith("natives-") for native in classifiers)):
            is_natives = True

        if not is_natives:
            continue

        if rules and classifiers:
            logger.debug(f"Found newer and legacy (classifier) native rules for {name}")
        elif rules:
            logger.debug(f"Found newer native rules for {name}")
        elif classifiers:
            logger.debug(f"Found legacy native rules (classifier) for {name}")

        # =============== New rules ===============

        # Parse action section
        if not is_library_allowed(
                rules,
                platform_rule_name,
                platform_arch_type,
                os_version,
        ):
            logger.debug(f"Library {name} can't pass library rules.")
            continue

        if is_native_allowed(
                name,
                platform_key_name,
                platform_arch_type,
        ):
            result_artifact = generate_formatted_artifact_with_name(name, artifact, extra={"exclude": exclude,
                                                                                           "flatten": True})
            if result_artifact:
                filtered.append(result_artifact)
            # For some reason, we still need to continue process because some version use multiple type of
            # classifier. (Such as 1.14.2)
        else:
            logger.debug(f"Library {name} can't pass native rules.")

        # =============== Old rules ===============
        logger.debug(
            "Library {} doesn't have native key. This library may use old rule.".format(name)
        )

        result, result_artifact, classifier = is_legacy_native_allowed(
            natives,
            classifiers,
            platform_rule_name,
            platform_arch_type,
        )

        if not result:
            logger.debug(f"Library {name} can't pass legacy native rules.")
            continue
        else:
            result_artifact = generate_formatted_artifact_with_name(name,
                                                                    result_artifact,
                                                                    extra={"exclude": exclude, "flatten": True},
                                                                    relative_args={
                                                                        "extra": classifier
                                                                    })
        if result_artifact:
            filtered.append(result_artifact)

    # Remove duplicate items
    items = remove_duplicate_artifacts(filtered)

    if not filtered:
        raise NativeResolveException(
            "No compatible native artifact found.",
            user_message="No compatible native library was found for this platform.",
        )
    elif not items:
        raise NativeResolveException(
            "No compatible native artifact found. Report developer because this may be a issue"
            " at function \"remove_duplicate_artifacts\"",
        )

    return items


def download_libraries(artifacts, output_dir, progress_callback: Callable[[str, float], None] = None) \
        -> tuple[list[FileObject], list[FileObject]]:
    """
    Download libraries from a list that contains artifacts
    :param artifacts:
    :param output_dir:
    :param progress_callback:
    :return:
        fails: list (List of artifacts that download failed)
        successes: list (artifacts that were downloaded)
    """
    files = []
    successes = []

    for artifact in artifacts:
        sha1 = artifact.get("sha1")
        relative_path = artifact.get("path")
        url = artifact.get("url")

        if not relative_path or not url:
            logger.warning(
                "Artifact {} has no path or url. Skipping.".format(artifact["name"])
            )
            continue
        else:
            full_path = output_dir / Path(relative_path)

        file = FileObject(
            full_path,
            url=url,
            sha1=sha1,
        )

        if sha1 is None:
            logger.warning(f"File {full_path} has no SHA1 hash.")

        if file.exists and (sha1 is None or file.verify("sha1", sha1)):
            logger.debug(f"File {full_path} exists.")
            successes.append(file)
            continue

        files.append(file)

    fails, finished = download_multiple_files(files, progress_callback=progress_callback)
    successes.extend(finished)

    return fails, successes


def unzip_natives(filtered, libraries_dir, destination: Path):
    """
    Unzip native libraries from a list that contains artifacts
    :param filtered:
    :param libraries_dir:
    :param destination:
    :return:

    IMPORTANT:
    Please put "exclude" key inside the artifact (from the version data). If not, some unnecessary file will be also
    included when unzipping the native library.
    """
    destination.mkdir(parents=True, exist_ok=True)

    for result_artifact in filtered:
        exclude = result_artifact.get("exclude", [])
        flatten = result_artifact.get("flatten", False)
        relative_path = result_artifact.get("path")

        if not relative_path:
            logger.warning(
                "Artifact {} has no relative path. Skipping.".format(result_artifact["name"])
            )
            continue
        else:
            full_path = libraries_dir / Path(relative_path)

        unzip(full_path, destination, exclude=exclude, flatten=flatten)

        logger.debug(f"Unzipped {full_path}.")


def check_libraries_exists(manifest: dict, libraries_dir: Path):
    """
    Check if libraries are present in the libraries directory
    :param manifest:
    :param libraries_dir:
    :return:
        not_found: list
    """
    libraries = manifest.get("libraries", [])

    if not libraries:
        raise VersionDataKeyNotFoundException(
            "Libraries not found in manifest.",
        )

    not_found = []

    # Same as natives
    _, _, os_version = get_platform_info()
    platform_key_name, platform_rule_name, platform_arch_type = get_natives_platform_info()

    for library in libraries:
        name = library.get("name", "")
        artifact_raw = library.get("downloads", {}).get("artifact", {})
        rules = library.get("rules", [])
        classifiers = library.get("downloads", {}).get("classifiers", {})
        natives = library.get("natives", {})

        # Ignore natives
        if (len(natives) > 0 or bool(re.search(r":natives-[^:]+$", name)) or
                any(native.startswith("natives-") for native in classifiers)):
            logger.info(f"Skipping {name} because its a native library.")
            continue

        if not is_library_allowed(
                rules,
                platform_rule_name,
                platform_arch_type,
                os_version,
        ):
            continue

        artifact = generate_formatted_artifact_with_name(
            name,
            artifact_raw
        )

        if not artifact:
            logger.warning(f"Artifact {name} are not valid. Skipping...")
            continue

        relative_path = artifact.get("path")
        full_path = libraries_dir / Path(relative_path)

        if not full_path.is_file() or not full_path.exists():
            logger.debug(f"Artifact {name} missing.")
            not_found.append(full_path)

    return not_found


def check_natives_exists(manifest: dict, libraries_dir: Path, natives_dir: Path):
    filtered = []

    # Convert current platform and architecture type to same formula
    _, _, os_version = get_platform_info()
    platform_key_name, platform_rule_name, platform_arch_type = get_natives_platform_info()

    if platform_key_name is None or platform_arch_type is None or platform_rule_name is None:
        raise UnsupportedPlatformException(
            f"Unsupported platform: key={platform_key_name}, "
            f"rule={platform_rule_name}, arch={platform_arch_type}"
        )

    _, _, _, _, libraries, _, _ = find_useful_part_in_specific_version_manifest(manifest)

    for library in libraries:
        name = library.get("name", "")
        artifact = library.get("downloads", {}).get("artifact", {})
        # For newer Minecraft (VER>1.7.10)
        rules = library.get("rules", [])
        # For legacy version (VER<1.8)
        classifiers = library.get("downloads", {}).get("classifiers", {})
        natives = library.get("natives", {})
        exclude = library.get("extract", {}).get("exclude", ["META-INF/"])  # For extract use

        is_natives = False

        # Check if library is a native
        if (len(natives) > 0 or bool(re.search(r":natives-[^:]+$", name)) or
                any(native.startswith("natives-") for native in classifiers)):
            is_natives = True

        if not is_natives:
            continue

        # =============== New rules ===============

        # Parse action section
        if not is_library_allowed(
                rules,
                platform_rule_name,
                platform_arch_type,
                os_version,
        ):
            continue

        if is_native_allowed(
                name,
                platform_key_name,
                platform_arch_type,
        ):
            result_artifact = generate_formatted_artifact_with_name(name, artifact, extra={"exclude": exclude,
                                                                                           "flatten": True})
            if result_artifact:
                filtered.append(result_artifact)

        # =============== Old rules ===============
        result, result_artifact, classifier = is_legacy_native_allowed(
            natives,
            classifiers,
            platform_rule_name,
            platform_arch_type,
        )

        if not result:
            continue

        result_artifact = generate_formatted_artifact_with_name(name,
                                                                result_artifact,
                                                                extra={"exclude": exclude, "flatten": True},
                                                                relative_args={
                                                                    "extra": classifier
                                                                })

        if result_artifact:
            filtered.append(result_artifact)

    # Remove duplicate items
    items = remove_duplicate_artifacts(filtered)

    if not filtered:
        raise NativeResolveException(
            "No compatible native artifact found.",
            user_message="No compatible native library was found for this platform.",
        )
    elif not items:
        raise NativeResolveException(
            "No compatible native artifact found. Report developer because this may be a issue"
            " at function \"remove_duplicate_artifacts\"",
        )

    expected = set()

    for result_artifact in items:
        full_path = libraries_dir / Path(result_artifact["path"])
        exclude = result_artifact.get("exclude", []) or []
        flatten = result_artifact.get("flatten", False)

        if not full_path.is_file() or not full_path.exists():
            return False

        with zipfile.ZipFile(full_path) as zf:
            for member in zf.namelist():
                if member.endswith("/"):
                    continue
                if any(member.startswith(item) for item in exclude):
                    continue

                target = Path(member).name if flatten else member
                if target:
                    expected.add(target)

    if not expected:
        return False

    for target in expected:
        if not (natives_dir / target).exists():
            return False

    return True


def check_full_libraries_exists(manifest: dict, libraries_dir: Path, natives_dir: Path) -> bool:
    if not check_natives_exists(manifest, libraries_dir, natives_dir) or not check_libraries_exists(manifest, libraries_dir):
        return False

    return True


def generate_classpath(manifest: dict, libraries_dir: Path, core_file_path: Path):
    """
    Generate classpath by using specific version's data
    :param manifest:
    :param libraries_dir:
    :param core_file_path:
    :return:
        not_found: list
    """
    libraries = manifest.get("libraries", [])

    if not libraries:
        raise VersionDataKeyNotFoundException(
            "Libraries not found in manifest.",
        )

    # Same as natives
    _, _, os_version = get_platform_info()
    platform_key_name, platform_rule_name, platform_arch_type = get_natives_platform_info()

    separator = ";" if platform_key_name == "windows" else ":"
    classes = []

    for library in libraries:
        name = library.get("name", "")
        artifact_raw = library.get("downloads", {}).get("artifact", {})
        rules = library.get("rules", [])
        classifiers = library.get("downloads", {}).get("classifiers", {})
        natives = library.get("natives", {})

        # Ignore natives
        if (len(natives) > 0 or bool(re.search(r":natives-[^:]+$", name)) or
                any(native.startswith("natives-") for native in classifiers)):
            logger.info(f"Skipping {name} because its a native library.")
            continue

        if not is_library_allowed(
                rules,
                platform_rule_name,
                platform_arch_type,
                os_version,
        ):
            continue

        artifact = generate_formatted_artifact_with_name(
            name,
            artifact_raw
        )

        if not artifact:
            logger.warning(f"Artifact {name} are not valid. Skipping...")
            continue

        relative_path = artifact.get("path")
        full_path = libraries_dir / Path(relative_path)

        if not full_path.is_file() or not full_path.exists():
            raise FileNotFoundError(f"Artifact {name} missing.")

        classes.append(full_path.as_posix())

    # Append core file
    classes.append(core_file_path.as_posix())

    return f"{separator}".join(classes)


def download_full_libraries(manifest: dict, libraries_dir: Path, natives_dir: Path,
                            progress_callback: Callable[[str, float], None] = None,
                            redownload_callback: Callable[
                                [list[FileObject]], tuple[bool, list[FileObject]]] = None) -> None:
    # libraries
    libraries = collect_library_artifacts(manifest)

    # natives
    natives = collect_native_artifacts(manifest)

    # all
    full = list(libraries)
    full.extend(natives)

    logger.info(
        "Supported native count: {}".format(len(natives))
    )

    # Start download
    fails, successes = download_libraries(full, libraries_dir, progress_callback=progress_callback)

    download_ok = len(fails) == 0

    if redownload_callback and not download_ok:
        download_ok, fails = redownload_callback(fails)

        if not download_ok:
            raise DownloadException(
                "Unable to continue process due to certain libraries download failed:\n"
                + "\n".join(file.posix_path for file in fails)
            )

    if download_ok:
        # Start unzip natives
        unzip_natives(natives, libraries_dir, natives_dir)
    else:
        raise DependencyException(
            "Certain libraries download failed. Unable to continue unzip process.\n"
        )
