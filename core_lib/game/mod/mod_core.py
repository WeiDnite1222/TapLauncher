import logging
from copy import deepcopy
import shlex

from core_lib.common.exception import VersionDataKeyNotFoundException, DependencyException
from core_lib.game.library import parse_maven_coordinate, convert_maven_version, generate_repo_url, \
    is_complete_maven_url
from core_lib.game.version_info import MOJANG_LIBRARIES_ENDPOINT

logger = logging.getLogger("Launcher.CoreLib")

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

def merge_necessary_dependencies(inherits_libraries: list, mod_libraries: list, mod_maven_url=None,
                                 inherits_maven_url=MOJANG_LIBRARIES_ENDPOINT, default_extension="jar") -> list[dict]:

    inherits = {}
    result = []

    # ensure below step won't modify original data
    inherits_libraries = deepcopy(inherits_libraries)
    mod_libraries = deepcopy(mod_libraries)

    def check_lib(lib: dict):
        url: str = lib.get("url", "")
        source_from = lib["sourceFrom"]
        lib_group=lib["parsed"]["group"]
        lib_artifact=lib["parsed"]["artifact"]
        lib_version=lib["parsed"]["version"]
        lib_classifier=lib["parsed"]["classifier"]
        lib_extension=lib["parsed"]["extension"]

        recreated = False

        if not url:
            if source_from == "official":
                new_url = generate_repo_url(inherits_maven_url, lib_group, lib_artifact, lib_version, lib_classifier,
                                            lib_extension)
            else:
                new_url = generate_repo_url(mod_maven_url, lib_group, lib_artifact, lib_version, lib_classifier,
                                            lib_extension)

            lib["url"] = new_url

            recreated = True

        if not recreated:
            url_result = is_complete_maven_url(url, lib_group, lib_artifact, lib_version, lib_classifier, lib_extension)

            if not url_result:
                # deal with some weird maven url that don't contain repo path
                # Some mod loader (such as fabric), did not contain a full path inside the library. We will need to
                # generate it from maven coordinate (aka lib_name)
                target_maven = mod_maven_url or url
                repo_url = generate_repo_url(target_maven, lib_group, lib_artifact, lib_version, lib_classifier,
                                            lib_extension)
                lib["url"] = repo_url

    for library in inherits_libraries:
        name = library.get("name", None)

        if not name:
            raise DependencyException(
                "Provided inherited library does not contain key \"name\"."
            )

        group, artifact, version, classifier, extension = parse_maven_coordinate(name,
                                                                                 default_extension=default_extension)

        # Save into dict for next step to check if library is existing
        if not f"{group}:{artifact}" in inherits:
            inherits[f"{group}:{artifact}"] = library
            inherits[f"{group}:{artifact}"]["parsed"] = {
                "group": group,
                "artifact": artifact,
                "version": version,
                "classifier": classifier,
                "extension": extension,
            }
            inherits[f"{group}:{artifact}"]["sourceFrom"] = "official"
        else:
            logger.warning("Duplicate library: {}".format(name))

    for mod_library in mod_libraries:
        name = mod_library.get("name", None)
        group, artifact, version, classifier, extension = parse_maven_coordinate(name, default_extension=default_extension)

        ver_converted = convert_maven_version(version)

        if not name:
            raise DependencyException(
                "Provided mod library does not contain key \"name\"."
            )

        if ver_converted is None:
            raise DependencyException(
                "Unable to convert inherits library version {} to tuple".format(version),
            )

        group, artifact, version, classifier, extension = parse_maven_coordinate(name, default_extension=default_extension)

        mod_library["sourceFrom"] = "mod"
        mod_library["parsed"] = {
            "group": group,
            "artifact": artifact,
            "version": version,
            "classifier": classifier,
            "extension": extension,
        }

        if f"{group}:{artifact}" in inherits:
            found_lib = inherits.pop(f"{group}:{artifact}")
            found_lib_ver = convert_maven_version(found_lib["parsed"]["version"], None)

            if found_lib_ver is None:
                raise DependencyException(
                    "Unable to convert mod library version {} to tuple".format(found_lib["version"])
                )

            if found_lib_ver > ver_converted or found_lib_ver == ver_converted:
                result.append(found_lib)
            elif found_lib_ver < ver_converted:
                result.append(mod_library)
        else:
            result.append(mod_library)

    # Add the remaining dependencies back to result
    for key in inherits:
        value = inherits[key]
        result.append(value)

    for library in result:
        check_lib(library)

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

def merge_manifest(inherits_version_manifest: dict, mod_version_manifest: dict, mod_maven_url=None) -> dict:
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

    merged_manifest["libraries"] = merge_necessary_dependencies(inherits_libraries, mod_libraries,
                                                                mod_maven_url=mod_maven_url)

    # arguments
    inherits_arguments = inherits_version_manifest.get("arguments", []) or inherits_version_manifest.get("minecraftArguments", "")
    mod_arguments = mod_version_manifest.get("arguments", {}) or mod_version_manifest.get("minecraftArguments", {})

    merged_manifest["arguments"] = merge_game_and_jvm_args(inherits_arguments, mod_arguments)

    return merged_manifest