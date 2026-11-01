import logging
from copy import deepcopy
import shlex

from core_lib.common.exception import VersionDataKeyNotFoundException, DependencyException
from core_lib.game.library import parse_maven_coordinate, generate_repo_url, \
    is_complete_maven_url, filter_platform_libraries
from core_lib.game.libraryx import convert_maven_version_with_extra, generate_unique_library_key, \
    normalize_library_to_common_struct, compare_library_versions, LibraryPreference, PREFER_MOD_LIBRARY, \
    PREFER_INHERITS_LIBRARY, PREFER_BY_HIGHER_VERSION, deduplicate_libraries
from core_lib.game.version_info import MOJANG_LIBRARIES_ENDPOINT

logger = logging.getLogger("Launcher.CoreLib")

LOADER_LIBRARY_MARKERS = {
    ("net.fabricmc", "fabric-loader"): "fabric",
    ("org.quiltmc", "quilt-loader"): "quilt",
    ("net.minecraftforge", "forge"): "forge",
    ("net.neoforged", "neoforge"): "neoforge",
    ("net.neoforged", "forge"): "neoforge",
}


def detect_loader_name(manifest: dict) -> str | None:
    """Read the recorded loader identity without inferring it from dependencies."""
    loader_name = manifest.get("loader")
    if isinstance(loader_name, str) and loader_name:
        return loader_name

    # Older Forge installations already record the identity in their receipt.
    receipt = manifest.get("forgeInstall")
    if isinstance(receipt, dict):
        loader_name = receipt.get("loader")
        if isinstance(loader_name, str) and loader_name:
            return loader_name

    return None

def find_useful_part_in_mod_version_manifest(mod_version_manifest: dict):
    ver_id = mod_version_manifest.get("id", None)
    inherits_from = mod_version_manifest.get("inheritsFrom", None)
    ver_type = mod_version_manifest.get("type", None)
    main_class = mod_version_manifest.get("mainClass", None)
    arguments = mod_version_manifest.get("arguments", {})
    old_arguments = mod_version_manifest.get("minecraftArguments", None)
    libraries = mod_version_manifest.get("libraries", [])

    if not ver_id:
        raise VersionDataKeyNotFoundException(
            "Provided mod loader version manifest does not contain key \"id\"."
        )

    if not ver_type:
        raise VersionDataKeyNotFoundException(
            "Provided mod loader version manifest does not contain key \"type\"."
        )

    if not inherits_from:
        raise VersionDataKeyNotFoundException(
            "Provided mod loader version manifest does not contain key \"inheritsFrom\"."
        )

    if not main_class:
        raise VersionDataKeyNotFoundException(
            "Provided mod loader version manifest does not contain key \"mainClass\"."
        )

    if not arguments and not old_arguments:
        raise VersionDataKeyNotFoundException(
            "Provided mod loader version manifest does not contain key \"arguments\" or \"minecraftArguments\"."
        )

    if not libraries:
        raise VersionDataKeyNotFoundException(
            "Provided mod loader version manifest does not contain key \"libraries\"."
        )

    return {
        "id": ver_id,
        "type": ver_type,
        "inheritsFrom": inherits_from,
        "minecraftArguments": old_arguments,
        "libraries": libraries,
        "arguments": arguments,
        "mainClass": main_class,
    }


def merge_necessary_dependencies(inherits_libraries: list, mod_libraries: list, inherits_maven_url=MOJANG_LIBRARIES_ENDPOINT,
                                 mod_maven_url=None, default_extension="jar",
                                 prefer_libraries_by: LibraryPreference = PREFER_MOD_LIBRARY,
                                 ignore_missing_url_libraries=False) -> list[dict]:
    """
    Merge necessary dependencies
    :param inherits_libraries:
    :param mod_libraries:
    :param inherits_maven_url:
    :param mod_maven_url:
    :param default_extension:
    :param prefer_libraries_by:
    :param ignore_missing_url_libraries: Skip url regeneration if library url is missing and contains the key
     "ignoreMissingURL": true
    :return:
    """

    inherits = {}
    result_pre = []
    result = []

    # ensure below step won't modify original data
    inherits_libraries = deepcopy(inherits_libraries)
    mod_libraries = deepcopy(mod_libraries)

    # Filter platform (natives) libraries
    inherits_libraries = filter_platform_libraries(inherits_libraries)
    mod_libraries = filter_platform_libraries(mod_libraries)

    preference = LibraryPreference(prefer_libraries_by)

    # Remove duplicate libraries
    inherits_libraries = deduplicate_libraries(
        inherits_libraries,
        preference,
        default_extension,
    )
    mod_libraries = deduplicate_libraries(
        mod_libraries,
        preference,
        default_extension,
    )

    # def check_lib(lib: dict):
    #     url: str = lib.get("url", "")
    #     source_from = lib["sourceFrom"]
    #     lib_group=lib["parsed"]["group"]
    #     lib_artifact=lib["parsed"]["artifact"]
    #     lib_version=lib["parsed"]["versionRaw"]
    #     lib_classifier=lib["parsed"]["classifier"]
    #     lib_extension=lib["parsed"]["extension"]
    #     lib_downloads = lib["downloads"]
    #
    #     recreated = False
    #
    #     if not url:
    #         artifact_url = lib_downloads.get("artifact", {}).get("url", "")
    #         is_completed = is_complete_maven_url(artifact_url, lib_group, lib_artifact, lib_version, lib_classifier, lib_extension)
    #
    #         if is_completed:
    #             lib["url"] = artifact_url
    #         else:
    #             if source_from == "official":
    #                 new_url = generate_repo_url(inherits_maven_url, lib_group, lib_artifact, lib_version,
    #                                             lib_classifier,
    #                                             lib_extension)
    #             else:
    #                 new_url = generate_repo_url(mod_maven_url, lib_group, lib_artifact, lib_version, lib_classifier,
    #                                             lib_extension)
    #
    #             lib["url"] = new_url
    #
    #         recreated = True
    #
    #     if not recreated:
    #         url_result = is_complete_maven_url(url, lib_group, lib_artifact, lib_version, lib_classifier, lib_extension)
    #
    #         if not url_result:
    #             # deal with some weird maven url that don't contain srepo path
    #             # Some mod loader (such as fabric), did not contain a full path inside the library. We will need to
    #             # generate it from maven coordinate (aka lib_name)
    #             target_maven = url or mod_maven_url
    #             repo_url = generate_repo_url(target_maven, lib_group, lib_artifact, lib_version, lib_classifier,
    #                                         lib_extension)
    #             lib["url"] = repo_url

    for library in inherits_libraries:
        name: str | None = library.get("name", None)
        downloads = library.get("downloads", {})

        if not name:
            raise DependencyException(
                "Provided inherited library does not contain key \"name\"."
            )

        group, artifact, version_raw, classifier, extension = parse_maven_coordinate(name, default_extension=default_extension)

        # ver_converted, extra = convert_maven_version_with_extra(version_raw)
        #
        # if extra:
        #     logger.debug("Found extra version \"{}\" for library {}".format(extra, name))
        #
        # if not ver_converted:
        #     raise DependencyException(
        #         f"Unable to convert provided inherited library name {name}'s version {version_raw} to tuple."
        #     )

        lib_key = generate_unique_library_key(
            group=group,
            artifact=artifact,
            classifier=classifier,
            extension=extension,
        )

        # Save into dict for next step to check if library is existing
        if not lib_key in inherits:
            inherits[lib_key] = library
            inherits[lib_key]["parsed"] = {
                "group": group,
                "artifact": artifact,
                "version": version_raw,
                "versionRaw": version_raw,
                "classifier": classifier,
                "extension": extension,
                "endpoint": inherits_maven_url,
                "downloads": downloads,
            }
            inherits[lib_key]["sourceFrom"] = "official"
        else:
            logger.warning("Duplicate library: {}".format(name))

    for mod_library in mod_libraries:
        name = mod_library.get("name", None)
        downloads = mod_library.get("downloads", {})

        if not name:
            raise DependencyException(
                "Provided mod library does not contain key \"name\"."
            )

        # ver_converted, extra = convert_maven_version_with_extra(version_raw)
        #
        # if extra:
        #     logger.debug("Found extra version \"{}\" for library {}".format(extra, name))
        #
        # if ver_converted is None:
        #     raise DependencyException(
        #         "Unable to convert mod library version {} to tuple".format(version_raw),
        #     )

        group, artifact, version_raw, classifier, extension = parse_maven_coordinate(name, default_extension=default_extension)
        lib_key = generate_unique_library_key(
            group=group,
            artifact=artifact,
            classifier=classifier,
            extension=extension,
        )

        mod_library["sourceFrom"] = "mod"
        mod_library["parsed"] = {
            "group": group,
            "artifact": artifact,
            # "version": {"raw": version, "converted": ver_converted, "extra": extra},
            "version": version_raw,
            "versionRaw": version_raw,
            "classifier": classifier,
            "extension": extension,
            "endpoint": mod_maven_url,
            "downloads": downloads,
        }

        if lib_key in inherits:
            found_lib = inherits.pop(lib_key)
            found_lib_ver = found_lib["parsed"]["version"]

            if found_lib_ver is None:
                raise DependencyException(
                    "Unable to convert mod library version {} to tuple".format(found_lib["versionRaw"])
                )

            if preference  in (PREFER_MOD_LIBRARY, PREFER_INHERITS_LIBRARY,):
                selected = mod_library if preference  == PREFER_MOD_LIBRARY else found_lib
            else:
                comparison = compare_library_versions(
                    found_lib["parsed"]["versionRaw"],
                    mod_library["parsed"]["versionRaw"],
                )

                if preference == PREFER_BY_HIGHER_VERSION:
                    selected = found_lib if comparison > 0 else mod_library
                else:  # PREFER_BY_LOWER_VERSION
                    selected = found_lib if comparison < 0 else mod_library

            result_pre.append(selected)
        else:
            result_pre.append(mod_library)

    # Add the remaining dependencies back to result
    for key in inherits:
        value = inherits[key]
        result_pre.append(value)

    for library in result_pre:
        # Check library download url
        endpoint = library["parsed"]["endpoint"] # maven url
        artifact_url = ((library.get("downloads") or {}).get("artifact") or {}).get("url")
        ignore_missing_url = library.get("ignoreMissingURL", False)

        if not artifact_url and not library.get("url") and not endpoint and not ignore_missing_url:
            raise DependencyException(
                f"No download source for library {library['name']!r}."
            )

        library_normalized = normalize_library_to_common_struct(
            library,
            default_maven_url=endpoint,
            default_extension=default_extension,
            ignore_missing_url=ignore_missing_url
        )

        # Cleanup and append
        library_normalized.pop("parsed", None)
        library_normalized.pop("sourceFrom", None)
        result.append(library_normalized)

    return result

def merge_arguments(inherits_arguments: str | list, mod_arguments: str | list) -> list[str | dict]:
    def str_to_list(args):
        p = shlex.split(args)
        return p

    if isinstance(inherits_arguments, str):
        inherits_arguments = str_to_list(inherits_arguments)

    if isinstance(mod_arguments, str):
        mod_arguments = str_to_list(mod_arguments)

    result = []
    result.extend(inherits_arguments)
    result.extend(mod_arguments)

    return result

def merge_game_and_jvm_args(inherits_args: dict[str, list[str]] | str, mod_args: dict[str, list[str]] | str) -> dict:
    inherits_game = inherits_args.get("game", []) if isinstance(inherits_args, dict) else inherits_args
    inherits_jvm = inherits_args.get("jvm", []) if isinstance(inherits_args, dict) else []

    mod_game = mod_args.get("game", []) if isinstance(mod_args, dict) else mod_args
    mod_jvm = mod_args.get("jvm", []) if isinstance(mod_args, dict) else []

    merged = {
        "game": merge_arguments(inherits_game, mod_game),
        "jvm": merge_arguments(inherits_jvm, mod_jvm),
    }

    return merged

def merge_manifest(inherits_version_manifest: dict, mod_version_manifest: dict, mod_maven_url=None,
    *, prefer_libraries_by: LibraryPreference = PREFER_MOD_LIBRARY) -> dict:
    merged_manifest = deepcopy(inherits_version_manifest)

    # main class
    main_class = mod_version_manifest.get("mainClass", None)

    # Apply main class change
    if main_class:
        merged_manifest["mainClass"] = main_class

    # Libraries
    inherits_libraries = inherits_version_manifest.get("libraries", [])
    mod_libraries = mod_version_manifest.get("libraries", [])

    if not inherits_libraries or not mod_libraries:
        raise VersionDataKeyNotFoundException(
            "Inherited (or mod) version manifest does not contain key \"libraries\"."
        )

    merged_manifest["libraries"] = merge_necessary_dependencies(
        inherits_libraries,
        mod_libraries,
        mod_maven_url=mod_maven_url,
        prefer_libraries_by=prefer_libraries_by
    )

    # Modern argument arrays extend the parent. Legacy minecraftArguments is a
    # complete game command line (including vanilla options), so it replaces it.
    def read_arguments(manifest: dict) -> dict:
        arguments = deepcopy(manifest.get("arguments") or {})
        if "game" not in arguments and manifest.get("minecraftArguments"):
            arguments["game"] = shlex.split(manifest["minecraftArguments"])
        return arguments

    inherits_arguments = read_arguments(inherits_version_manifest)
    mod_arguments = read_arguments(mod_version_manifest)
    if (mod_version_manifest.get("minecraftArguments")
            and "game" not in (mod_version_manifest.get("arguments") or {})):
        inherits_arguments.pop("game", None)

    merged_manifest["arguments"] = merge_game_and_jvm_args(inherits_arguments, mod_arguments)
    # The merged manifest now has a single canonical argument representation.
    merged_manifest.pop("minecraftArguments", None)

    # Update version number
    mod_id = mod_version_manifest.get("id")
    inherits_id = inherits_version_manifest.get("id")

    if mod_id:
        merged_manifest["id"] = mod_id

    if inherits_id:
        merged_manifest["inheritsFrom"] = inherits_id

    # Keep the child's recorded identity instead of inheriting the parent's.
    merged_manifest.pop("loader", None)
    loader_name = detect_loader_name(mod_version_manifest)
    if loader_name is not None:
        merged_manifest["loader"] = loader_name

    # Processor output receipts must survive inheritance for launch-time checks.
    if "forgeInstall" in mod_version_manifest:
        merged_manifest["forgeInstall"] = deepcopy(mod_version_manifest["forgeInstall"])

    return merged_manifest
