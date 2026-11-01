import json
import hashlib
import logging
import os
import re
import shutil
import stat
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from tempfile import NamedTemporaryFile, mkdtemp
from typing import Literal, Callable
from urllib.parse import urlsplit
from collections.abc import Mapping
import requests

from core_lib.common.common import FileObject, download_file
from core_lib.common.exception import VersionManifestFetchException, NoSpecifiedVersionKeyException, \
    LoaderUnsupportedSpecificVersion, LoaderInstallError
from core_lib.game.library import (
    generate_repo_url, parse_maven_coordinate,
    generate_filename_from_maven_coordinate, generate_repo_path,
    filter_platform_libraries,
)
from core_lib.game.mod.rules import FORGE_LIKE_LOADERS, MOD_LOADER_RULES

FORGE_MAVEN_URL = "https://maven.minecraftforge.net/"
FORGE_METADATA_URL = FORGE_MAVEN_URL + "net/minecraftforge/forge/maven-metadata.xml"
NEOFORGE_MAVEN_URL = "https://maven.neoforged.net/"
NEOFORGE_MAVEN_RELEASE_URL = NEOFORGE_MAVEN_URL + "releases/"
NEOFORGE_METADATA_URL = NEOFORGE_MAVEN_URL + "releases/net/neoforged/neoforge/maven-metadata.xml"
FORGE_INSTALLER_URL = FORGE_MAVEN_URL + "net/minecraftforge/forge/{version}/forge-{version}-installer.jar"
NEOFORGE_INSTALLER_URL = NEOFORGE_MAVEN_URL + "releases/net/neoforged/neoforge/{version}/neoforge-{version}-installer.jar"

logger = logging.getLogger("Launcher.CoreLib")


def fetch_forge_versions(forge_metadata_url: str = FORGE_METADATA_URL, timeout: int = 5) -> list[str]:
    """
    Fetch Forge maven metadata and return a list of version IDs.
    :param forge_metadata_url: URL to fetch Forge maven metadata from
    :param timeout:
    :return:
        found: list[str]
    """
    try:
        r = requests.get(forge_metadata_url, timeout=timeout)
        r.raise_for_status()
    except requests.exceptions.Timeout as e:
        raise VersionManifestFetchException(
            "Timeout while fetch from {}".format(forge_metadata_url)
        ) from e
    except requests.exceptions.ConnectionError as e:
        raise VersionManifestFetchException(
            "Connection error while fetch from {}: {}".format(forge_metadata_url, e)
        ) from e
    except requests.exceptions.HTTPError as e:
        status_code = e.response.status_code if e.response is not None else "unknown"
        raise VersionManifestFetchException(
            "HTTP error while fetch from {}: HTTP Status: {}".format(forge_metadata_url, status_code)
        ) from e
    except requests.exceptions.RequestException as e:
        raise VersionManifestFetchException(
            "Request error while fetch from {}: {}".format(forge_metadata_url, e)
        ) from e

    try:
        root = ET.fromstring(r.content)
    except ET.ParseError as e:
        raise VersionManifestFetchException(
            "XML decode error while fetch from {}: {}".format(forge_metadata_url, e)
        ) from e

    versioning = root.find("versioning")

    if versioning is None:
        raise NoSpecifiedVersionKeyException(
            "Key \"Versioning\" not found in forge metadata"
        )

    versions = versioning.find("versions")
    if versions is None:
        raise NoSpecifiedVersionKeyException(
            "Key \"Versions\" not found or is empty in forge metadata"
        )

    found = []
    for version in versions.findall("version"):
        ver_id = (version.text or "").strip()

        if not ver_id:
            raise NoSpecifiedVersionKeyException(
                "Found empty version ID in forge metadata"
            )

        found.append(ver_id)

    if not found:
        raise NoSpecifiedVersionKeyException(
            "No version entries found in forge metadata"
        )

    return found


def split_forge_like_version(version: str, loader_name: Literal["forge", "neoforge"] = "forge") -> tuple[str, str]:
    """
    Split forge and minecraft version from the loader version
    :param version:
    :param loader_name:
    :return:
    """
    version = version.strip()

    if loader_name not in FORGE_LIKE_LOADERS:
        raise ValueError(f"Unsupported loader: {loader_name!r}")

    # For forge and old neoforge version
    if loader_name == "forge" or version.startswith("1."):
        minecraft_version, separator, loader_version = version.partition("-")

        if not separator or not loader_version:
            raise ValueError(f"Invalid loader version: {version!r}")

        return minecraft_version, loader_version
    elif loader_name == "neoforge" and version.startswith("0."):
        # For special NeoForge version such as 0.25w14craftmine.3-beta
        match = re.fullmatch(
            r"0\.(?P<minecraft>[^.\s]+)\.(?P<build>\d+)"
            r"(?:-[0-9A-Za-z.-]+)?",
            version,
        )
        if match is None:
            raise ValueError(f"Unsupported special NeoForge version: {version!r}")

        return match["minecraft"], version

    if loader_name == "forge":
        raise ValueError(f"Invalid Forge version: {version!r}")

    match = re.fullmatch(
        r"(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)"
        r"(?:\.(?P<build>\d+))?"
        r"(?:-[0-9A-Za-z.-]+)?"
        r"(?:\+(?P<preview>(?:snapshot|pre|rc)-\d+))?",
        version,
    )
    if match is None:
        raise ValueError(f"Unsupported NeoForge version: {version!r}")

    major = int(match["major"])
    minor = int(match["minor"])
    patch = int(match["patch"])

    if match["build"] is None:
        if major >= 26:
            raise ValueError("Calendar-based NeoForge requires four components")

        # Convert such as 21.1.x to 1.21.1 (x is loader patch version)
        minecraft_version = f"1.{major}"
        if minor:
            minecraft_version += f".{minor}"
    else:
        minecraft_version = f"{major}.{minor}"
        if patch:
            minecraft_version += f".{patch}"

    if match["preview"]:
        minecraft_version += f"-{match['preview']}"

    return minecraft_version, version


def get_version_support_loader_list(target_version: str,
                                    forge_metadata_url: str = FORGE_METADATA_URL,
                                    loader_name: Literal["forge", "neoforge"] = "forge",
                                    version_splitter: Callable[[str], tuple[str, str]] = split_forge_like_version,
                                    timeout: int = 5) \
        -> list[dict]:
    versions = fetch_forge_versions(forge_metadata_url, timeout)
    loaders = []

    for version in versions:
        ver_id, _ = version_splitter(version, loader_name=loader_name)

        if ver_id == target_version:
            loaders.append(version)

    if not loaders:
        raise LoaderUnsupportedSpecificVersion(loader_name, target_version)

    return loaders


def get_installer_coordinate(loader_version: str,
                             group: str = "net.minecraftforge",
                             name: str = "forge") -> str:
    """
    Convert forge (maven) version to installer coordinate
    For example: net.minecraftforge:forge:1.20.1-47.2.0:installer.
    :param loader_version:
    :param group: Group ID of the loader (usually is "net.minecraftforge", for neoforge is "net.neoforged")
    :param name:
    :return:
    """
    version = loader_version.strip()

    if not version:
        raise ValueError("Forge loader version must not be empty")

    if any(char.isspace() or char in ":@/\\"
           for char in version):
        raise ValueError(f"Invalid Forge loader version: {loader_version!r}")

    return f"{group}:{name}:{version}:installer"


def get_installer_url(loader_version: str, maven_url: str = FORGE_MAVEN_URL, *,
                      group: str = "net.minecraftforge", name: str = "forge") -> str:
    """
    Generate installer URL for the loader version
    :param loader_version:
    :param maven_url: Maven URL of the loader
    :param group:
    :param name:
    :return:
    """
    coordinate = get_installer_coordinate(loader_version, group=group, name=name)
    group_id, artifact, version, classifier, extension = parse_maven_coordinate(coordinate)
    return generate_repo_url(
        maven_url, group_id, artifact, version,
        classifier=classifier, extension=extension,
    )


@dataclass
class LoaderInstallPlan:
    loader_name: Literal["forge", "neoforge"]
    loader_version: str
    minecraft_version: str
    version_manifest: dict
    installer_path: Path
    extracted_dir: Path
    install_profile: dict | None = None

    @property
    def version_id(self) -> str:
        return self.version_manifest["id"]


def _read_json_object(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"Unable to read installer JSON: {path}") from exc

    if not isinstance(data, dict):
        raise ValueError(f"Installer JSON must contain an object: {path}")
    return data


def parse_installer_metadata(extracted_dir: Path, *,
                             installer_path: Path,
                             loader_version: str,
                             loader_name: Literal["forge", "neoforge"] = "forge",
                             support_loader_list: list[str] | None = None) -> LoaderInstallPlan:
    """Read version JSON or legacy versionInfo, with an optional install profile.

    The caller supplies the loader identity; profile is a display name.
    Installers without usable launch metadata are explicitly unsupported.
    """
    supported = FORGE_LIKE_LOADERS if support_loader_list is None else support_loader_list
    if loader_name not in supported or loader_name not in ("forge", "neoforge"):
        raise ValueError(f"Unsupported loader name: {loader_name!r}")

    # Validate the full Maven version. (If not supported, this will raise.)
    get_installer_coordinate(loader_version)

    extracted_dir = Path(extracted_dir).resolve()
    install_profile_path = extracted_dir / "install_profile.json"

    if install_profile_path.is_file():
        install_profile = _read_json_object(install_profile_path)
    else:
        install_profile = None

    profile = install_profile if install_profile is not None else {}

    manifest_entry = profile.get("json", "/version.json")
    if not isinstance(manifest_entry, str) or not manifest_entry.strip():
        raise ValueError("Installer version JSON path must be a non-empty string")

    # Leading slashes denote installer resources, not filesystem roots.
    manifest_path = (extracted_dir / manifest_entry.replace("\\", "/").lstrip("/")).resolve()
    if not manifest_path.is_relative_to(extracted_dir):
        raise ValueError("Installer version JSON path escapes the extracted directory")

    if manifest_path.is_file():
        version_manifest = _read_json_object(manifest_path)
    elif isinstance(profile.get("versionInfo"), dict):
        version_manifest = dict(profile["versionInfo"])
    else:
        raise ValueError("Unsupported installer: no version JSON or versionInfo found")

    # Check necessary key exists
    for key in ("id", "mainClass"):
        if not isinstance(version_manifest.get(key), str) or not version_manifest[key].strip():
            raise ValueError(f"Installer version manifest is missing {key!r}")

    minecraft_version = version_manifest.get("inheritsFrom") or profile.get("minecraft")

    if not isinstance(minecraft_version, str) or not minecraft_version.strip():
        raise ValueError("Installer does not declare its Minecraft version")
    if profile.get("minecraft") and profile["minecraft"] != minecraft_version:
        raise ValueError("Installer and version manifest declare different Minecraft versions")

    version_manifest["inheritsFrom"] = minecraft_version
    return LoaderInstallPlan(
        loader_name=loader_name,
        loader_version=loader_version.strip(),
        minecraft_version=minecraft_version,
        version_manifest=version_manifest,
        installer_path=Path(installer_path).resolve(),
        extracted_dir=extracted_dir,
        install_profile=install_profile,
    )


def add_missing_url_flag_to_generated_after_install_libraries(install_plan: LoaderInstallPlan) -> None:
    """
    Mark URL-less libraries in both installer manifests in place.

    Such artifacts must be supplied by the installer or its processors rather
    than downloaded from an inferred Maven URL. This flag does not verify that
    the artifact has actually been installed.
    :param install_plan:
    """
    manifests = (install_plan.version_manifest, install_plan.install_profile)
    for manifest in manifests:
        if manifest is None:
            continue

        for library in manifest.get("libraries") or []:
            downloads = library.get("downloads") or {}
            artifact = downloads.get("artifact") or {}
            if not library.get("url") and not artifact.get("url"):
                library["ignoreMissingURL"] = True


def _extract_installer(installer_path: Path, extracted_dir: Path) -> None:
    """
    Validate archive paths before extracting; reading each file checks its CRC.
    :param installer_path:
    :param extracted_dir:
    :return:
    """
    with zipfile.ZipFile(installer_path) as archive:
        entries = []

        for member in archive.infolist():
            name = member.filename.replace("\\", "/")
            parts = name.rstrip("/").split("/")
            destination = (extracted_dir / name).resolve()
            if (
                    name.startswith("/")
                    or PureWindowsPath(name).drive
                    or any(part in ("", ".", "..") or ":" in part for part in parts)
                    or not destination.is_relative_to(extracted_dir)
                    or stat.S_ISLNK(member.external_attr >> 16)
            ):
                raise ValueError(f"Unsafe installer archive entry: {member.filename!r}")

            entries.append((member, destination))

        for member, destination in entries:
            if member.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, destination.open("wb") as output:
                    shutil.copyfileobj(source, output)


def _get_neoforge_artifact(loader_version: str):
    return "forge" if loader_version.startswith("1.") else "neoforge"


def prepare_installer(loader_name: Literal["forge", "neoforge"],
                      loader_version: str, working_dir: Path,
                      *, maven_url: str | None = None,
                      minecraft_version: str,
                      expected_sha1: str | None = None,
                      progress_callback: Callable[[str, float], None] | None = None) -> LoaderInstallPlan:
    """
    Prepare the forge-like installer
    :param loader_name: Loader name.
    :param loader_version: Loader version.
    :param working_dir: Working directory.
    :param maven_url: Maven URL override; defaults to the loader's repository.
    :param minecraft_version: Minecraft version.
    :param expected_sha1: Expected SHA1 hash of the installer. (Optional because most loaders don't provide it)
    :param progress_callback: Progress callback.
    :return: Loader install plan.
    """
    temp_dir: Path | None = None
    stage = "validate installer request"

    try:
        if loader_name not in FORGE_LIKE_LOADERS:
            raise ValueError(f"Unsupported loader: {loader_name!r}")

        # Validate version
        loader_version = loader_version.strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+\-]*", loader_version):
            raise ValueError(f"Invalid loader Maven version: {loader_version!r}")

        if not isinstance(minecraft_version, str) or not minecraft_version.strip():
            raise ValueError("Minecraft version must not be empty")

        # maven and install url
        if loader_name == "forge":
            repository = FORGE_MAVEN_URL
            group, artifact = "net.minecraftforge", "forge"
        else:
            repository = NEOFORGE_MAVEN_RELEASE_URL
            group = "net.neoforged"
            artifact = _get_neoforge_artifact(loader_version)

        url = get_installer_url(
            loader_version, maven_url=repository if maven_url is None else maven_url,
            group=group, name=artifact,
        )

        # Prepare working directory and installer download path
        stage = "create installer workspace"
        working_dir = Path(working_dir).resolve()
        working_dir.mkdir(parents=True, exist_ok=True)
        temp_dir = Path(mkdtemp(prefix=f"{loader_name}-{loader_version}-", dir=working_dir)).resolve()

        installer_path = temp_dir / "installer.jar"
        extracted_dir = temp_dir / "extracted"
        extracted_dir.mkdir()

        # Download and extract installer
        stage = "download installer"
        file = FileObject(path=installer_path, url=url, sha1=expected_sha1)
        download_file(file, progress_callback=progress_callback, overwrite=True)

        stage = "extract installer"
        _extract_installer(installer_path, extracted_dir)

        # Parse installer metadata and create plan
        stage = "parse installer metadata"
        plan = parse_installer_metadata(
            extracted_dir, installer_path=installer_path,
            loader_version=loader_version, loader_name=loader_name,
        )

        # Check version
        if plan.minecraft_version != minecraft_version:
            raise ValueError(
                f"Expected Minecraft version {minecraft_version}, but got {plan.minecraft_version} "
                f"in {installer_path}."
            )

        # Add flag to libraries that will be generated by forge processor
        add_missing_url_flag_to_generated_after_install_libraries(plan)
        return plan
    except Exception as e:
        if temp_dir is not None and temp_dir.is_relative_to(working_dir) and temp_dir != working_dir:
            try:
                shutil.rmtree(temp_dir.as_posix())
            except OSError:
                logger.warning("Unable to clean installer workspace %s", temp_dir, exc_info=True)

        raise LoaderInstallError(f"Failed to {stage} for {loader_name}: {e}") from e


def _is_artifact_link(path: Path) -> bool:
    return path.is_symlink() or getattr(path, "is_junction", lambda: False)()


def _checked_artifact_path(root: Path, relative: str) -> Path:
    """Resolve a relative artifact path without following links or junctions."""
    relative = relative.replace("\\", "/")
    parts = relative.split("/")

    if (
            relative.startswith("/") or PureWindowsPath(relative).drive
            or any(part in ("", ".", "..") or part.rstrip(". ") != part
                   or any(char in part for char in ':<>"|?*\0') for part in parts)
    ):
        raise ValueError(f"Invalid artifact path: {relative!r}")

    path = root
    for part in parts:
        path = path / part
        if _is_artifact_link(path):
            raise ValueError(f"Artifact path contains a link: {path}")

    if not path.resolve().is_relative_to(root):
        raise ValueError(f"Artifact path escapes its root: {path}")

    return path


def _artifact_sha256(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest()


def copy_embedded_artifacts(install_plan: LoaderInstallPlan,
                            output_libraries_dir: Path) -> list[Path]:
    """
    Copy maven and libraries trees/files from extracted dir to output dir.

    Conflicting embedded sources are rejected before copying. Existing identical
    files are skipped; differing files are replaced atomically. Returns only the
    destinations actually copied. Patch data stays in the extracted directory.
    """
    source = Path(install_plan.extracted_dir)
    destination = Path(output_libraries_dir)

    try:
        if _is_artifact_link(source) or _is_artifact_link(destination):
            raise ValueError("Artifact roots must not be links")

        root = source.resolve()
        output_root = destination.resolve()

        if not root.is_dir():
            raise ValueError(f"Installer extraction directory does not exist: {root}")

        if output_root.is_relative_to(root) or root.is_relative_to(output_root):
            raise ValueError("Artifact source and destination roots must not overlap")

        # Build and validate the entire copy plan before changing any artifacts.
        artifacts: dict[Path, tuple[Path, str]] = {}

        def add_artifact(relative_source: str, relative_destination: str) -> None:
            nonlocal source, destination

            source = _checked_artifact_path(root, relative_source)
            destination = _checked_artifact_path(output_root, relative_destination)

            if not source.is_file():
                raise ValueError(f"Declared embedded artifact is missing or not a file: {source}")

            digest = _artifact_sha256(source)
            previous = artifacts.get(destination)

            if previous is not None and previous[1] != digest:
                raise ValueError(f"Conflicting embedded artifacts: {previous[0]} and {source}")

            artifacts.setdefault(destination, (source, digest))

        def collect_tree(directory: Path, tree_root: Path) -> None:
            for item in sorted(directory.iterdir()):
                _checked_artifact_path(root, item.relative_to(root).as_posix())
                if item.is_dir():
                    collect_tree(item, tree_root)
                else:
                    add_artifact(
                        item.relative_to(root).as_posix(), item.relative_to(tree_root).as_posix(),
                    )

        for directory_name in ("maven", "libraries"):
            tree_root = _checked_artifact_path(root, directory_name)

            if tree_root.exists():
                if not tree_root.is_dir():
                    raise ValueError(f"Embedded Maven root is not a directory: {tree_root}")

                collect_tree(tree_root, tree_root)

        profile = install_plan.install_profile or {}
        if "install" in profile:
            legacy = profile["install"]

            if not isinstance(legacy, dict):
                raise ValueError("Legacy install metadata must be an object")

            file_path, coordinate = legacy.get("filePath"), legacy.get("path")
            if not isinstance(file_path, str) or not isinstance(coordinate, str):
                raise ValueError("Legacy install metadata requires filePath and path")

            group, artifact, version, classifier, extension = parse_maven_coordinate(coordinate)

            # The shared Maven parser checks structure; also validate its path components.
            for component in (group, artifact, version, classifier, extension):
                if component is not None:
                    if not component or any(char.isspace() or char in "/\\:@" for char in component):
                        raise ValueError(f"Invalid legacy Maven coordinate: {coordinate!r}")

            filename = generate_filename_from_maven_coordinate(
                artifact, version, classifier=classifier, extension=extension,
            )
            add_artifact(file_path, generate_repo_path(group, artifact, version, filename))

        output_root.mkdir(parents=True, exist_ok=True)
        copied = []
        for destination, (source, digest) in artifacts.items():
            _checked_artifact_path(root, source.relative_to(root).as_posix())
            _checked_artifact_path(output_root, destination.relative_to(output_root).as_posix())

            if destination.is_file() and _artifact_sha256(destination) == digest:
                continue

            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = None
            try:
                with NamedTemporaryFile(dir=destination.parent, prefix=f".{destination.name}.",
                                        suffix=".tmp", delete=False) as stream:
                    temporary = Path(stream.name)

                shutil.copy2(source, temporary)
                if _artifact_sha256(temporary) != digest:
                    raise ValueError(f"Copied artifact hash does not match source: {source}")

                temporary.replace(destination)
                copied.append(destination)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
        return copied
    except Exception as exc:
        raise LoaderInstallError(
            f"Failed to copy embedded artifact from {source} to {destination}: {exc}"
        ) from exc


def collect_install_dependencies(install_plan: LoaderInstallPlan, libraries_dir: Path) -> list[FileObject]:
    """
    Collect install dependencies from manifest and install profile.
    :param install_plan:
    :param libraries_dir:

    Missing SHA-1 is allowed, but a supplied hash must be valid. Local/generated
    artifacts marked ignoreMissingURL are excluded. No files are created here.
    Contains many checks to deal with the issue that forge install profile or manifest may contain invalid paths, missing
    url...
    :return:
    """
    context = "libraries root"
    try:
        # Check libraries dir
        libraries_dir = Path(libraries_dir)
        if _is_artifact_link(libraries_dir):
            raise ValueError("Libraries root must not be a link")

        root = libraries_dir.resolve()
        if root.exists() and not root.is_dir():
            raise ValueError("Libraries root must be a directory")

        files: dict[Path, FileObject] = {}

        for source_name, manifest in (
                ("version manifest", install_plan.version_manifest),
                ("install profile", install_plan.install_profile),
        ):
            if manifest is None:
                continue

            if not isinstance(manifest, dict):  # ignore invalid manifest
                raise ValueError(f"{source_name} must be an object")

            libraries = manifest.get("libraries")
            # Ignore invalid or empty
            if libraries is None:
                continue
            elif not libraries:
                continue

            if not isinstance(libraries, list):
                raise ValueError(f"{source_name} libraries must be a list")

            for index, library in enumerate(libraries):
                context = f"{source_name} library #{index}"
                if not isinstance(library, dict):
                    raise ValueError("Library must be an object")

                context += f" ({library.get('name', 'unnamed')})"

                # Get flag that sat by add_missing_url_flag_to_generated_after_install_libraries
                ignore_missing_url = library.get(
                    "ignoreMissingURL",
                    library.get("ignoreMissingUrl", False),
                )
                if not isinstance(ignore_missing_url, bool):
                    raise ValueError("ignoreMissingURL must be a boolean")

                # Skip libraries that will be generated after installation
                if ignore_missing_url:
                    continue

                downloads = library.get("downloads")
                if not isinstance(downloads, dict):
                    raise ValueError("Library downloads must be an object")

                artifact = downloads.get("artifact")
                if not isinstance(artifact, dict):
                    raise ValueError("Library downloads.artifact must be an object")

                url = artifact.get("url")
                if (
                        not isinstance(url, str) or not url
                        or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in url)
                        or "\\" in url
                ):
                    raise ValueError("Artifact URL must be a non-empty HTTP(S) URL without whitespace")

                # Not sure if this will be triggered in the daily use?
                # Check protocol, fragment, credentials, path
                parsed = urlsplit(url)
                if (
                        parsed.scheme.lower() not in ("http", "https") or not parsed.hostname
                        or parsed.username is not None or parsed.password is not None
                        or parsed.fragment
                ):
                    raise ValueError("Artifact URL requires an HTTP(S) host and no credentials or fragment")

                # Accessing port also rejects non-numeric and out-of-range values.
                if parsed.port is not None and parsed.port == 0:
                    raise ValueError("Artifact URL port must be between 1 and 65535")

                # Check sha1
                sha1 = artifact.get("sha1")
                if sha1 is not None:
                    if not isinstance(sha1, str) or not re.fullmatch(r"[0-9a-fA-F]{40}", sha1):
                        raise ValueError("Artifact SHA-1 must contain exactly 40 hexadecimal characters")

                    sha1 = sha1.lower()

                # Check path
                path = artifact.get("path")
                if not isinstance(path, str) or not path:
                    raise ValueError("Artifact path must be a non-empty relative string")

                if any(ord(char) < 32 or ord(char) == 127 for char in path):
                    raise ValueError("Artifact path must not contain control characters")

                reserved_names = {"CON", "PRN", "AUX", "NUL"} | {
                    f"{prefix}{number}" for prefix in ("COM", "LPT") for number in range(1, 10)
                }
                if any(part.split(".", 1)[0].upper() in reserved_names
                       for part in path.replace("\\", "/").split("/")):
                    raise ValueError("Artifact path must not use Windows device names")

                # Check destination
                destination = _checked_artifact_path(root, path)
                if destination.exists() and not destination.is_file():
                    raise ValueError(f"Artifact destination is not a file: {destination}")

                previous = files.get(destination)
                if previous is not None:
                    if previous.url != url or (
                            previous.expected_sha1 is not None and sha1 is not None
                            and previous.expected_sha1 != sha1
                    ):
                        raise ValueError(f"Conflicting download metadata for {destination}")

                    if previous.expected_sha1 is None:
                        previous.expected_sha1 = sha1

                    continue

                files[destination] = FileObject(url=url, sha1=sha1, path=destination)
        return list(files.values())
    except Exception as exc:
        raise LoaderInstallError(f"Invalid install dependency in {context}: {exc}") from exc

def resolve_processor_value(value: str, *, variables: Mapping[str, str], libraries_dir: Path) -> str:
    """
    Resolve one processor argument, output path, or output hash.
    """
    if not isinstance(value, str):
        raise LoaderInstallError("Processor value must be a string")

    # Quoted values are literals, not paths.
    if value.startswith("'") and value.endswith("'") and len(value) >= 2:
        return value[1:-1]

    def replace_variable(match: re.Match) -> str:
        key = match.group(1)
        if key not in variables:
            raise LoaderInstallError(f"Unknown processor variable: {key}")

        replacement = variables[key]
        if not isinstance(replacement, str):
            raise LoaderInstallError(f"Invalid processor variable: {key}")

        return replacement

    token_pattern = re.compile(r"\{([^{}]+)\}")
    unmatched = token_pattern.sub("", value)
    if "{" in unmatched or "}" in unmatched:
        raise LoaderInstallError(
            f"Malformed processor value: {value!r}"
        )
    resolved = token_pattern.sub(replace_variable, value)

    # Variables already contain final values. Do not reinterpret a substituted
    # literal (which may itself contain brackets or braces) as installer syntax.
    if value.startswith("[") and value.endswith("]"):
        coordinate = resolved[1:-1]
        try:
            group, artifact, version, classifier, extension = (
                parse_maven_coordinate(coordinate)
            )
            filename = generate_filename_from_maven_coordinate(
                artifact,
                version,
                classifier=classifier,
                extension=extension,
            )
            relative_path = generate_repo_path(
                group, artifact, version, filename,
            )
            root = Path(libraries_dir)
            if _is_artifact_link(root):
                raise ValueError("Libraries root must not be a link")

            return str(_checked_artifact_path(root.resolve(), relative_path))
        except (ValueError, OSError) as exc:
            raise LoaderInstallError(
                f"Invalid processor artifact: {coordinate!r}"
            ) from exc

    return resolved

def run_processors(install_plan: LoaderInstallPlan, libraries_dir: Path, *,
                   java_path: Path, minecraft_jar: Path, minecraft_root: Path,
                    progress_callback: Callable[[str, float], None] | None = None,
                    timeout: float | None = None) -> None:
    """
    Run forge-like processors in order and record verified outputs in the manifest.

    The caller supplies downloaded dependencies and a compatible Java executable.
    Save version_manifest after success, including forgeInstall, for launch-time
    checks. No manifest is written to disk and no downloads are performed here.

    :param install_plan: Loader install plan
    :param libraries_dir: Path to the libraries directory
    :param java_path: Path to the Java executable
    :param minecraft_jar: Path to the Minecraft JAR file
    :param minecraft_root: Path to the Minecraft root directory (Libraries should be in this directory)
    :param progress_callback: Optional callback for progress updates
    :param timeout: Optional timeout for the processor run
    """
    context = "processor configuration"

    try:
        if not isinstance(install_plan.version_manifest, dict):
            raise ValueError("Version manifest must be an object")

        install_plan.version_manifest.pop("forgeInstall", None)
        libraries_dir = _processor_root(libraries_dir)
        minecraft_root = _processor_root(minecraft_root)
        minecraft_jar = Path(minecraft_jar).resolve()
        java_path = Path(java_path).resolve()
        processors = _client_processors(install_plan.install_profile)
        variables = build_processor_variables(
            install_plan, libraries_dir, minecraft_jar=minecraft_jar,
            minecraft_root=minecraft_root,
        ) if processors else {} # 1.12.2 and older don't have processors or is empty

        tracked: dict[Path, str | None] = {}
        for index, processor in enumerate(processors, start=1):
            context = f"client processor {index}/{len(processors)} ({processor.get('jar')})"
            outputs = _processor_outputs(processor, variables, libraries_dir)

            # Later processors may overwrite earlier intermediates.
            tracked.update(outputs)

            # Only declared, hash-verified outputs provide a safe cache hit.
            if outputs and all(sha1 is not None and _valid_installed_file(path, sha1)
                               for path, sha1 in outputs.items()):
                logger.info("Skipping cached %s", context)
            else:
                if not java_path.is_file():
                    raise ValueError(f"Java executable does not exist: {java_path}")

                if not _valid_installed_file(minecraft_jar):
                    raise ValueError(f"Minecraft client JAR is missing or invalid: {minecraft_jar}")

                jar_raw: str | None = processor.get("jar") # processor maven address

                if not jar_raw:
                    raise ValueError("Processor missing key \"jar\" (Aka processor maven address)")

                jar = _processor_artifact(jar_raw, libraries_dir)
                classpath = processor.get("classpath", [])
                if not isinstance(classpath, list):
                    raise ValueError("Processor classpath must be a list")

                # Append processor dependencies (including itself)
                dependencies = [jar] + [_processor_artifact(item, libraries_dir) for item in classpath]
                dependencies = list(dict.fromkeys(dependencies))
                for dependency in dependencies:
                    if not _valid_installed_file(dependency):
                        raise ValueError(f"Processor dependency is missing or invalid: {dependency}")

                # Get processor arguments
                args = _processor_args(processor, variables, libraries_dir)
                for output in outputs:
                    output.parent.mkdir(parents=True, exist_ok=True)

                minecraft_root.mkdir(parents=True, exist_ok=True)

                # Generate processor command
                command = [str(java_path), "-cp", os.pathsep.join(map(str, dependencies)),
                           _jar_main_class(jar), *args]

                # Run processor
                logger.info("Running %s: %s", context, command)
                completed = subprocess.run(
                    command, cwd=minecraft_root, capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=timeout,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                )

                if completed.stdout:
                    logger.info("%s stdout:\n%s", context, completed.stdout)

                if completed.stderr:
                    logger.warning("%s stderr:\n%s", context, completed.stderr)

                if completed.returncode != 0:
                    raise ValueError(
                        f"Processor exited with code {completed.returncode}: "
                        f"{(completed.stderr or completed.stdout or '')[-2000:]}"
                    )

                # Check output files
                for output, sha1 in outputs.items():
                    _checked_artifact_path(libraries_dir, output.relative_to(libraries_dir).as_posix())
                    if not _valid_installed_file(output, sha1):
                        raise ValueError(f"Processor output is missing, corrupt or has the wrong hash: {output}")

            if progress_callback is not None:
                progress_callback(context, index / len(processors) * 100)

        # Includes embedded/legacy artifacts and generated runtime libraries.
        for path, sha1, size in _generated_libraries(install_plan.version_manifest, libraries_dir):
            if not _valid_installed_file(path, sha1, size):
                raise ValueError(f"Required installed artifact is missing or invalid: {path}")
            tracked[path] = sha1

        records = []
        for path in tracked:
            _checked_artifact_path(libraries_dir, path.relative_to(libraries_dir).as_posix())

            if not _valid_installed_file(path, tracked[path]):
                raise ValueError(f"Installed processor artifact is missing or invalid: {path}")

            records.append({
                "path": path.relative_to(libraries_dir).as_posix(),
                "sha1": FileObject(path).sha1, "size": path.stat().st_size,
            })

        install_plan.version_manifest["forgeInstall"] = {
            "schema": 1, "versionId": install_plan.version_id,
            "loader": install_plan.loader_name, "loaderVersion": install_plan.loader_version,
            "minecraftVersion": install_plan.minecraft_version, "outputs": records,
        }
    except Exception as exc:
        raise LoaderInstallError(f"Failed to run {context}: {exc}") from exc


def _processor_root(path: Path) -> Path:
    path = Path(path)

    if _is_artifact_link(path):
        raise ValueError(f"Processor root must not be a link: {path}")

    return path.resolve()


def _client_processors(profile: dict | None) -> list[dict]:
    if profile is None:
        return []

    if not isinstance(profile, dict):
        raise ValueError("Install profile must be an object")

    processors = profile.get("processors", [])
    if not isinstance(processors, list):
        raise ValueError("Processors must be a list")

    selected = []
    for processor in processors:
        if not isinstance(processor, dict):
            raise ValueError("Processor must be an object")

        sides = processor.get("sides")
        if sides is not None and (not isinstance(sides, list) or
                                  not all(isinstance(side, str) for side in sides)):
            raise ValueError("Processor sides must be a list of strings")

        if sides is None or "client" in sides:
            selected.append(processor)

    return selected


def build_processor_variables(install_plan: LoaderInstallPlan, libraries_dir: Path, *,
                             minecraft_jar: Path, minecraft_root: Path) -> dict[str, str]:
    """Resolve client data entries, then inject the six reserved installer tokens."""
    libraries_dir = _processor_root(libraries_dir)
    variables = {}
    data = (install_plan.install_profile or {}).get("data", {})

    if not isinstance(data, dict):
        raise LoaderInstallError("Processor data must be an object")

    reserved = {"SIDE", "MINECRAFT_JAR", "MINECRAFT_VERSION", "ROOT", "INSTALLER", "LIBRARY_DIR"} # necessary variable
    # that used by processor

    for key, entry in data.items():
        if key in reserved:
            continue

        if not isinstance(key, str) or not isinstance(entry, dict):
            raise LoaderInstallError(f"Invalid processor data entry: {key!r}")

        value = entry.get("client")
        if not isinstance(value, str) or not value:
            raise LoaderInstallError(f"Processor data has no client value: {key}")
        if (value.startswith("[") and value.endswith("]")) or (
            value.startswith("'") and value.endswith("'")
        ):
            variables[key] = resolve_processor_value(value, variables={}, libraries_dir=libraries_dir)
        else:
            root = _processor_root(install_plan.extracted_dir)
            resource = _checked_artifact_path(root, value.lstrip("/"))
            if not resource.is_file():
                raise LoaderInstallError(f"Installer data resource is missing: {resource}")
            variables[key] = str(resource)

    variables.update({
        "SIDE": "client", "MINECRAFT_JAR": str(Path(minecraft_jar).resolve()),
        "MINECRAFT_VERSION": install_plan.minecraft_version,
        "ROOT": str(_processor_root(minecraft_root)),
        "INSTALLER": str(Path(install_plan.installer_path).resolve()),
        "LIBRARY_DIR": str(libraries_dir),
    })
    return variables


def _processor_artifact(coordinate: str, libraries_dir: Path) -> Path:
    if not isinstance(coordinate, str) or not coordinate or any(char in coordinate for char in "[]{}"):
        raise ValueError(f"Invalid processor artifact: {coordinate!r}")

    return Path(resolve_processor_value(f"[{coordinate}]", variables={}, libraries_dir=libraries_dir))


def _processor_args(processor: dict, variables: Mapping[str, str], libraries_dir: Path) -> list[str]:
    args = processor.get("args", [])
    if not isinstance(args, list):
        raise ValueError("Processor args must be a list")

    result = [resolve_processor_value(arg, variables=variables, libraries_dir=libraries_dir) for arg in args]
    if any("\0" in arg for arg in result):
        raise ValueError("Processor args must not contain NUL")

    return result


def _processor_output_path(value: str, libraries_dir: Path) -> Path:
    path = Path(value)
    if not path.is_absolute() or not path.is_relative_to(libraries_dir):
        raise ValueError(f"Processor output must be under libraries: {value}")

    return _checked_artifact_path(libraries_dir, path.relative_to(libraries_dir).as_posix())


def _processor_outputs(processor: dict, variables: Mapping[str, str],
                       libraries_dir: Path) -> dict[Path, str | None]:
    """
    Find output paths in processor data.
    :param processor:
    :param variables:
    :param libraries_dir:
    :return:
    """
    raw = processor.get("outputs", {})
    if not isinstance(raw, dict):
        raise ValueError("Processor outputs must be an object")

    outputs = {}
    for key, value in raw.items():
        path = _processor_output_path(
            resolve_processor_value(key, variables=variables, libraries_dir=libraries_dir), libraries_dir,
        )
        sha1 = resolve_processor_value(value, variables=variables, libraries_dir=libraries_dir)

        if re.fullmatch(r"[0-9a-fA-F]{40}", sha1) is None:
            raise ValueError(f"Invalid processor output SHA-1: {sha1!r}")

        if path in outputs and outputs[path] != sha1.lower():
            raise ValueError(f"Conflicting processor output hashes: {path}")

        outputs[path] = sha1.lower()

    # New NeoForge profiles omit outputs. Track explicit output arguments and
    # record their resulting hashes so later launches can validate them offline.
    args = _processor_args(processor, variables, libraries_dir)
    for index, arg in enumerate(args):
        value = None

        if arg in ("--output", "--out-jar"):
            if index + 1 >= len(args):
                raise ValueError(f"Missing value for processor argument {arg}")
            value = args[index + 1]
        elif arg.startswith(("--output=", "--out-jar=")):
            value = arg.partition("=")[2]
        if value is not None:
            outputs.setdefault(_processor_output_path(value, libraries_dir), None)

    return outputs


def _jar_main_class(path: Path) -> str:
    with zipfile.ZipFile(path) as jar:
        text = jar.read("META-INF/MANIFEST.MF").decode("utf-8")

    # JAR manifest attributes may continue on the following space-prefixed line.
    text = re.sub(r"\r?\n ", "", text)
    for line in text.splitlines():
        if not line:
            break  # Named sections must not supply the main entry point.

        key, separator, value = line.partition(":")
        if separator and key.lower() == "main-class":
            value = value.strip()
            if re.fullmatch(r"[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*", value):
                return value

    raise ValueError(f"Processor JAR has no valid Main-Class: {path}")


def _valid_installed_file(path: Path, sha1: str | None = None, size: int | None = None) -> bool:
    if not path.is_file() or path.stat().st_size == 0:
        return False

    if size is not None and (type(size) is not int or size < 0 or path.stat().st_size != size):
        return False

    if sha1 is not None:
        if not isinstance(sha1, str) or re.fullmatch(r"[0-9a-fA-F]{40}", sha1) is None:
            return False

        return FileObject(path).sha1 == sha1.lower()

    if path.suffix.lower() == ".jar":
        try:
            with zipfile.ZipFile(path) as jar:
                return jar.testzip() is None
        except (OSError, zipfile.BadZipFile, RuntimeError):
            return False

    return True


def _generated_libraries(manifest: dict, libraries_dir: Path) -> list[tuple[Path, str | None, int | None]]:
    libraries = manifest.get("libraries", [])
    if not isinstance(libraries, list) or not all(isinstance(item, dict) for item in libraries):
        raise ValueError("Manifest libraries must be a list of objects")

    generated = []
    for library in filter_platform_libraries(libraries):
        artifact = (library.get("downloads") or {}).get("artifact") or {}

        if not isinstance(artifact, dict):
            raise ValueError("Library artifact must be an object")
        if not (library.get("ignoreMissingURL") or library.get("ignoreMissingUrl")) and (
            artifact.get("url") or library.get("url")
        ):
            continue

        relative = artifact.get("path")
        if relative is not None:
            if not isinstance(relative, str):
                raise ValueError("Library path must be a string")
            path = _checked_artifact_path(libraries_dir, relative)
        else:
            name: str | None = library.get("name")

            if not name:
                raise ValueError("Library name is missing: {}".format(library))

            path = _processor_artifact(name, libraries_dir)

        generated.append((path, artifact.get("sha1", library.get("sha1")), artifact.get("size", library.get("size"))))

    return generated


def check_forge_dependencies(version_manifest: dict, libraries_dir: Path) -> bool:
    """
    Check forge dependencies after post-installation.
    :param version_manifest:
    :param libraries_dir:
    :return:
        is_ok: bool (True when installer artifacts are valid; False means rerun the installer)
    """
    try:
        libraries_dir = _processor_root(libraries_dir)
        generated = _generated_libraries(version_manifest, libraries_dir)
        for path, sha1, size in generated:
            if not _valid_installed_file(path, sha1, size):
                logger.info("Forge installation needs repair: %s", path)
                return False

        receipt = version_manifest.get("forgeInstall")
        if receipt is None:
            return bool(generated)
        if (
            not isinstance(receipt, dict) or type(receipt.get("schema")) is not int or receipt.get("schema") != 1
            or receipt.get("versionId") != version_manifest.get("id")
            or receipt.get("loader") not in FORGE_LIKE_LOADERS
            or not isinstance(receipt.get("outputs"), list)
        ):
            return False

        parent = version_manifest.get("inheritsFrom")
        if parent is not None and receipt.get("minecraftVersion") != parent:
            return False

        # Check processor outputs
        for output in receipt["outputs"]:
            if not isinstance(output, dict) or not isinstance(output.get("path"), str):
                return False

            path = _checked_artifact_path(libraries_dir, output["path"])

            # Verify installed file that generated by processor
            if (not isinstance(output.get("sha1"), str) or "size" not in output
                or not _valid_installed_file(path, output["sha1"], output["size"])):
                logger.info("Forge processor output needs repair: %s", path)
                return False

        return True
    except (OSError, ValueError, TypeError, AttributeError, LoaderInstallError) as exc:
        logger.warning("Unable to validate Forge installation: %s", exc)
        return False
