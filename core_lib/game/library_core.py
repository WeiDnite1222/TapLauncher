import logging
import re
import zipfile
from pathlib import Path, PureWindowsPath
from typing import Callable, Literal

from .argument import convert_argument_to_multiple_string, find_game_and_jvm_args, is_argument_allowed
from .library import get_natives_platform_info, is_library_allowed, generate_formatted_artifact_with_name, \
    is_native_allowed, is_legacy_native_allowed, remove_duplicate_artifacts
from .libraryx import normalize_library_to_common_struct
from ..common.common import get_platform_info, FileObject, download_multiple_files, unzip, is_valid_zipfile, \
    SUPPORTED_HASH_ALGORITHMS
from .version_info import find_useful_part_in_specific_version_manifest
from ..common.exception import UnsupportedPlatformException, NativeResolveException, DependencyException, \
    VersionDataKeyNotFoundException, DownloadException, HashMismatchException

logger = logging.getLogger("Launcher.CoreLib")

def _is_native_only_library(library: dict) -> bool:
    name = library.get("name", "")
    if re.search(r":natives-[^:@]+(?:@[^:]+)?$", name):
        return True
    downloads = library.get("downloads") or {}
    has_natives = library.get("natives") or any(
        key.startswith("natives-") for key in (downloads.get("classifiers") or {})
    )
    return bool(has_natives and not downloads.get("artifact"))


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
        # Mixed entries also contain a Java JAR needed on the classpath.
        if _is_native_only_library(library):
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

def locate_natives_extract_dir(jvm_args: list[str | dict], default_extract_dir: Path,
                               features: dict | None = None) -> Path:
    property_prefix = "-Djava.library.path="
    placeholder = "${natives_directory}"

    path_value = None
    for argument in jvm_args:
        if not is_argument_allowed(argument, allow_features=features):
            continue
        for arg in convert_argument_to_multiple_string(argument):
            if arg.startswith(property_prefix):
                path_value = arg[len(property_prefix):]

    if path_value is None or path_value == placeholder:
        return default_extract_dir

    if not path_value.startswith(placeholder + "/") and not path_value.startswith(placeholder + "\\"):
        raise ValueError("Unsupported java.library.path extraction layout")

    suffix = path_value[len(placeholder) + 1:].replace("\\", "/")
    parts = suffix.split("/")

    if (
        any(part in ("", ".", "..") for part in parts)
        or any(char in suffix for char in ":;${}")
        or PureWindowsPath(suffix).drive
    ):
        raise ValueError("Invalid native extraction subdirectory")

    root = default_extract_dir.resolve()
    destination = root.joinpath(*parts).resolve()

    if not destination.is_relative_to(root):
        raise ValueError("Native extraction directory escapes its root")

    return destination

def locate_natives_extract_dir_by_manifest(manifest: dict, default_extract_dir: Path,
                                           features: dict | None = None) -> Path:
    _, jvm = find_game_and_jvm_args(manifest.get("arguments") or {})
    return locate_natives_extract_dir(jvm, default_extract_dir, features=features)

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


def download_libraries(artifacts, output_dir, progress_callback: Callable[[str, float], None] = None, *, verify_hash=True) \
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
            sha256=sha256,
            sha512=sha512,
        )

        if sha1 is None:
            logger.warning(f"File {full_path} has no SHA1 hash.")

        if file.exists:
            if not verify_hash:
                valid = full_path.is_file()
            elif sha1 is not None:
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

    fails, finished = download_multiple_files(files, progress_callback=progress_callback, verify_hash=verify_hash)
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


def check_libraries_exists_and_verify(manifest, libraries_dir, verify_hash=True,
    allow_algorithms=None, *, throw_error_if_missing_hash=False):
    """
    Check if libraries are present in the libraries directory and verify their hash (if required)
    :param manifest:
    :param libraries_dir:
    :param verify_hash: Whether to verify the hash of the library. Defaults to True.
    :param throw_error_if_missing_hash: Whether to throw an error if a library is missing a hash. Defaults to False.
    (Only working when verify_hash is True)
    :param allow_algorithms: The allowed algorithms to use for hash verification. Defaults to SUPPORTED_HASH_ALGORITHMS
    (in corelib.common.common)
    :return:
        not_found: list
    """
    libraries = manifest.get("libraries", [])

    if allow_algorithms is None:
        allow_algorithms = SUPPORTED_HASH_ALGORITHMS

    if verify_hash and not allow_algorithms:
        raise ValueError("algorithm must be provided if verify_hash is True")

    for alog in allow_algorithms or []:
        if alog not in SUPPORTED_HASH_ALGORITHMS:
            raise ValueError(f"Unsupported algorithm: {alog}")

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
        # Mixed entries also contain a Java JAR needed on the classpath.
        if _is_native_only_library(library):
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

        relative_path = artifact["path"] # Is safe because generate_formatted_artifact_with_name will check
        # the "path" key.
        full_path = libraries_dir / Path(relative_path)

        if not full_path.is_file() or not full_path.exists():
            logger.debug(f"Artifact {name} missing.")
            not_found.append(full_path)
            continue

        if verify_hash:
            expected = None
            used_alog = None

            # Get expected hash
            for alog in allow_algorithms or []:
                expected = artifact.get(alog, None)
                if expected:
                    used_alog = alog
                    break

            # Verify hash
            if used_alog:
                f = FileObject(full_path)
                if not f.verify(used_alog, expected):
                    logger.debug(f"Hash mismatch for {full_path} with algorithm {used_alog}")
                    not_found.append(full_path)
                    continue
                else:
                    logger.debug(f"Hash match for {full_path} with algorithm {used_alog}")
            else:
                if throw_error_if_missing_hash:
                    raise VersionDataKeyNotFoundException(
                        f"Library {name} does not provide any hash that type is allowed in {allow_algorithms}"
                    )

                # Show warning if there's no support algorithm in the artifact
                logger.warning(f"Library {name} does not provide any hash that type is allowed in {allow_algorithms}")

    return not_found


def check_natives_exists(manifest: dict, libraries_dir: Path, natives_dir: Path, *,
                         features: dict | None = None):
    extract_dir = locate_natives_extract_dir_by_manifest(manifest, natives_dir, features=features)
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
        if not (extract_dir / target).is_file():
            return False

    return True


def check_full_libraries_exists(manifest: dict, libraries_dir: Path, natives_dir: Path, *,
                                features=None, verify_hash=True,) -> bool:
    natives_exist = check_natives_exists(
        manifest,
        libraries_dir,
        natives_dir,
        features=features,
    )
    missing_libraries = check_libraries_exists_and_verify(
        manifest,
        libraries_dir,
        verify_hash=verify_hash,
    )

    return natives_exist and not missing_libraries


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
        # Mixed entries also contain a Java JAR needed on the classpath.
        if _is_native_only_library(library):
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


def download_full_libraries(manifest: dict, libraries_dir: Path, default_natives_dir: Path,
                            progress_callback: Callable[[str, float], None] = None,
                            redownload_callback: Callable[
                                [list[FileObject]], tuple[bool, list[FileObject]]] = None, *,
                            features: dict | None = None, verify_hash=True) -> None:
    natives_dir = locate_natives_extract_dir_by_manifest(manifest, default_natives_dir, features=features)
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
    fails, successes = download_libraries(full, libraries_dir, progress_callback=progress_callback, verify_hash=verify_hash)

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
