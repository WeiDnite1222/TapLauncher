import json
import logging
import re
import shlex

from core_lib.common.common import get_platform_info
from core_lib.common.exception import LauncherException
from core_lib.game.library import get_natives_platform_info

logger = logging.getLogger("Launcher.CoreLib")

def compare_versions(left: str, right: str) -> int:
    left_parts = tuple(map(int, left.split(".")))
    right_parts = tuple(map(int, right.split(".")))
    length = max(len(left_parts), len(right_parts))
    left_parts += (0,) * (length - len(left_parts))
    right_parts += (0,) * (length - len(right_parts))
    return (left_parts > right_parts) - (left_parts < right_parts)

def is_argument_allowed(argument: dict | str, allow_features: dict | None = None) -> bool:
    """
    Check if argument is allowed or not.
    :param argument:
    :param allow_features: Should be like {key: value}
    :return:
        allowed: bool
    """
    if isinstance(argument, str):
        return True

    if allow_features is None:
        allow_features = {}

    rules = argument.get('rules', {})

    _, platform_rule_name, platform_arch_type = get_natives_platform_info()
    _, _, platform_version = get_platform_info()

    allowed = False

    if not rules:
        return True

    for rule in rules:
        if not isinstance(rule, dict):
            logger.warning("Ignoring invalid argument rule: {}".format(rule))
            continue

        rule_action = rule.get("action", None)
        os_rule = rule.get("os") or {}
        rule_os = os_rule.get("name", None)
        feature_rule = rule.get("features") or {}
        rule_arch = os_rule.get("arch")
        rule_version = os_rule.get("version")
        rule_version_range = os_rule.get("versionRange")

        # Check platform
        if rule_os is not None and platform_rule_name != rule_os:
            continue

        # Check architecture
        if rule_arch is not None and rule_arch != platform_arch_type:
            continue

        # Check platform version
        if rule_version is not None:
            try:
                if re.search(
                        rule_version,
                        str(platform_version),
                ) is None:
                    continue
            except re.error as exc:
                logger.warning(
                    "Unsupported argument OS version regex %r: %s",
                    rule_version,
                    exc,
                )
                continue

        # Check version range
        if rule_version_range is not None:
            min_value = rule_version_range.get("min")
            max_value = rule_version_range.get("max")

            try:
                if min_value is not None and compare_versions(platform_version, min_value) < 0:
                    continue
                if max_value is not None and compare_versions(platform_version, max_value) > 0:
                    continue
            except ValueError:
                raise LauncherException("Unable to compare versions: SYS_VER: {} MIN: {} MAX: {}".format(platform_version, min_value, max_value))

        # Check feature rule
        if any(allow_features.get(key, False) != expected for key, expected in feature_rule.items()):
            continue

        if rule_action == "allow":
            allowed = True
        elif rule_action == "disallow":
            allowed = False
        else:
            logger.warning(f"Unknown argument rule action {rule_action}\n")

    return allowed

def replace_placeholders(argument, placeholders: dict) -> str:
    if argument:
        for key, value in placeholders.items():
            argument = argument.replace("${" + key + "}", "" if value is None else str(value))

    return argument


class ArgumentMappings:
    def __init__(self, player_name="Player", version_name="unknown",
                 game_directory=None, assets_root=None, legacy_assets_root=None, assets_index_name=None,
                 auth_uuid="00000001-0002-0003-0004-000000000005",
                 auth_access_token="", clientid=None, auth_xuid=None,
                 user_type=None, user_properties=None, version_type=None, natives_directory=None,
                 launcher_name=None, launcher_version=None,
                 classpath=None, classpath_separator=None, library_directory=None,
                 resolution: tuple[int, int] | None = None):
        self.player_name = player_name
        self.version_name = version_name
        self.game_directory = game_directory
        self.assets_root = assets_root
        self.game_assets = legacy_assets_root
        self.assets_index_name = assets_index_name
        self.auth_uuid = auth_uuid
        self.auth_access_token = auth_access_token
        self.clientid = clientid
        self.auth_xuid = auth_xuid
        self.user_type = user_type
        self.user_properties = user_properties
        self.resolution = resolution
        if isinstance(user_properties, dict):
            self.user_properties = json.dumps(
                user_properties,
                separators=(",", ":"),
            )
        else:
            if user_properties is not None:
                logger.warning(f"User properties should be a dictionary.")
            self.user_properties = "{}"
        self.version_type = version_type
        self.natives_directory = natives_directory
        self.launcher_name = launcher_name
        self.launcher_version = launcher_version
        self.classpath = classpath
        self.classpath_separator = classpath_separator
        self.library_directory = library_directory

    def generate_placeholders(self):
        return {
            "player_name": self.player_name,
            "version_name": self.version_name,
            "game_directory": self.game_directory,
            "assets_root": self.assets_root,
            "game_assets": self.game_assets,
            "assets_index_name": self.assets_index_name,
            "auth_uuid": self.auth_uuid,
            "auth_session": self.auth_access_token,
            "auth_access_token": self.auth_access_token,
            "auth_player_name": self.player_name,
            "clientid": self.clientid,
            "auth_xuid": self.auth_xuid,
            "user_type": self.user_type,
            "user_properties": self.user_properties,
            "version_type": self.version_type,
            "natives_directory": self.natives_directory,
            "launcher_name": self.launcher_name,
            "launcher_version": self.launcher_version,
            "classpath": self.classpath,
            "classpath_separator": self.classpath_separator,
            "library_directory": self.library_directory
        }


def convert_argument_to_multiple_string(argument: str | dict) -> list[str]:
    if isinstance(argument, str):
        return [argument]

    if isinstance(argument, dict):
        value = argument.get("value", None)

        if isinstance(value, list):
            return [str(item) for item in value]  # ensure all item are string
        elif isinstance(value, str):
            return [value]

    raise TypeError("Argument must be of type str or dict")


def find_game_and_jvm_args(arguments: dict | str) -> tuple[list, list]:
    game_args = []
    jvm_args = []

    if isinstance(arguments, dict):
        game = arguments.get("game", [])
        jvm = arguments.get("jvm", [])

        if isinstance(game, list):
            game_args.extend(game)
        elif isinstance(game, str):
            game_args.append(game)

        if isinstance(jvm, list):
            jvm_args.extend(jvm)
        elif isinstance(jvm, str):
            jvm_args.append(jvm)

    if isinstance(arguments, str):
        # Convert legacy argument into a list type
        game_args = shlex.split(arguments)

    return game_args, jvm_args


def parse_and_generate_arguments(arguments: list | str, mappings: ArgumentMappings, features: dict | None = None) -> \
    list[str]:
    if features is None:
        features = {}

    parsed_arguments = []

    if isinstance(arguments, str):
        # Convert legacy argument into a list type
        arguments = shlex.split(arguments)

    placeholders = mappings.generate_placeholders()

    for argument in arguments:
        # Check rules
        if not is_argument_allowed(argument, allow_features=features):
            continue

        # Each argument (section) may contain multiple items, convert it to list before replace placeholder
        for item in convert_argument_to_multiple_string(argument):
            parsed = replace_placeholders(item, placeholders)
            parsed_arguments.append(parsed)

    return parsed_arguments


def append_missing_necessary_jvm_arguments(arguments: list, arg_maps: ArgumentMappings) -> list[str]:
    result = []
    has_classpath = any(
        argument in ("-cp", "-classpath", "--class-path")
        for argument in arguments
    )

    has_native_path = any(
        argument.startswith("-Djava.library.path=")
        for argument in arguments
    )

    if not has_native_path:
        result.append(f"-Djava.library.path={arg_maps.natives_directory}")

    if not has_classpath:
        result.extend(["-cp", arg_maps.classpath])

    result.extend(arguments)

    return result

def add_feature_arguments(arguments: dict, arg_maps: ArgumentMappings, features: dict | None = None) -> list[str]:
    result = []

    if features is None:
        return result

    if features.get("has_custom_resolution"):
        result.append(f"-Dminecraft.overrideResolution={features['resolution']}")

    return result

def generate_launch_command(arg_maps: ArgumentMappings, main_class: str, java_path: str, full_args: dict | str
                            , features: dict | None = None, user_jvm_args: list[str] | None | str = None) -> list[str]:
    cmd = [java_path]
    game_args, jvm_args = find_game_and_jvm_args(full_args)

    if isinstance(user_jvm_args, str):
        user_jvm_args = shlex.split(user_jvm_args)

    if user_jvm_args is None:
        # Use manifest recommended user jvm arguments
        default_args = (
            full_args.get("default-user-jvm", [])
            if isinstance(full_args, dict)
            else []
        )

        parsed_user_jvm_args = parse_and_generate_arguments(
            default_args,
            arg_maps,
            features=features,
        )
    else:
        # Use jvm arguments that provided by user
        parsed_user_jvm_args = list(user_jvm_args)

    parsed_manifest_jvm_args = parse_and_generate_arguments(
        jvm_args,
        arg_maps,
        features=features,
    )

    parsed_game_args = parse_and_generate_arguments(
        game_args,
        arg_maps,
        features=features,
    )

    # Legacy Minecraft don't have jvm arguments exist in the version library. We need to generate by ourselves
    parsed_jvm_args = append_missing_necessary_jvm_arguments(
        parsed_user_jvm_args + parsed_manifest_jvm_args, # Combine manifest and user jvm arguments together
        arg_maps,
    )

    cmd.extend(parsed_jvm_args)
    cmd.append(main_class)
    cmd.extend(parsed_game_args)

    return cmd


def is_a_argument(arg: str, startswith="--"):
    pattern = re.compile(rf"{startswith}(.+)")
    return pattern.match(arg) is not None


def generate_argument_details(arguments: list[str | dict], startswith="--") -> list[dict]:
    items = []

    for index, arg in enumerate(arguments):
        if isinstance(arg, str) and is_a_argument(arg, startswith):
            items.append({
                "value": arg,
                "type": "argument",
                "dataType": "string",
            })

            if index > 0:
                previous = items[index - 1]
                if previous["type"] == "argument":
                    previous["isFlag"] = True
        elif isinstance(arg, str):
            items.append({
                "value": arg,
                "type": "value",
            })
        elif isinstance(arg, dict):
            value = arg.get("value", None)

            if not value:
                raise ValueError("Dictionary argument must contain a value")

            items.append({
                "value": value,
                "type": "argument",
                "dataType": "dictionary",
                "dictValue": arg,
            })

    return items


def is_same_argument(item: dict, another: dict) -> bool:
    pass
