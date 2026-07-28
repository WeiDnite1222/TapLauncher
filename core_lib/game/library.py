import json
import logging
import re
from urllib.parse import urlsplit, unquote

from ..common.common import get_platform_info
from .version_info import (
    MOJANG_LIBRARIES_ENDPOINT,
    NATIVE_OS_KEY_MAP,
    NATIVE_OS_RULE_MAP,
    NATIVE_ARCH_KEY_MAP,
    NATIVE_NEW_TO_OLD_ARCH,
    NATIVE_OLD_TO_NEW_ARCH
)

logger = logging.getLogger("Launcher.CoreLib")

def parse_maven_coordinate(value: str, default_extension="jar"):
    value = value.strip()

    coordinate, separator, extension = value.partition("@")
    parts = coordinate.split(":")

    if len(parts) not in (3, 4):
        raise ValueError(f"Invalid maven coordinate {value}")

    group, artifact, version = parts[:3]
    classifier = parts[3] if len(parts) == 4 else None

    if not group or not artifact or not version:
        raise ValueError(f"Coordinate key can not be empty: {value!r}")

    if not extension:
        extension = default_extension

    return group, artifact, version, classifier, extension

def convert_maven_version(version: str, failback=None) -> tuple[int, int, int]:
    try:
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
