import logging
import re
import zipfile
from pathlib import Path
from typing import Callable

from .library import get_natives_platform_info, is_library_allowed, generate_formatted_artifact_with_name, \
    is_native_allowed, is_legacy_native_allowed, remove_duplicate_artifacts
from .libraryx import normalize_library_to_common_struct
from ..common.common import get_platform_info, FileObject, download_multiple_files, unzip, is_valid_zipfile
from .version_info import find_useful_part_in_specific_version_manifest
from ..common.exception import UnsupportedPlatformException, NativeResolveException, DependencyException, \
    VersionDataKeyNotFoundException, DownloadException

logger = logging.getLogger("Launcher.CoreLib")

def collect_library_artifacts(specific_version_manifest):
    _, _, _, _, libraries, _, _ = find_useful_part_in_specific_version_manifest(specific_version_manifest)

    items = []

    # Same as natives
    _, _, os_version = get_platform_info()
    platform_key_name, platform_rule_name, platform_arch_type = get_natives_platform_info()

    for library_raw in libraries:
        library = normalize_library_to_common_struct(
            library_raw
        )

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

    for library_raw in libraries:
        library = normalize_library_to_common_struct(
            library_raw
        )

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
        sha256 = artifact.get("sha256")
        sha512 = artifact.get("sha512")
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

        if file.exists:
            if sha1 is not None:
                valid = file.verify("sha1", sha1)
            elif sha256 is not None:
                valid = file.verify("sha256", sha256)
            elif sha512 is not None:
                valid = file.verify("sha512", sha512)
            elif full_path.suffix.lower() == ".jar":
                valid = is_valid_zipfile(file.path)
            else:
                valid = full_path.stat().st_size > 0

            if valid:
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

    for library_raw in libraries:
        library = normalize_library_to_common_struct(
            library_raw
        )

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

    for library_raw in libraries:
        library = normalize_library_to_common_struct(
            library_raw
        )

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

    for library_raw in libraries:
        library = normalize_library_to_common_struct(
            library_raw
        )

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