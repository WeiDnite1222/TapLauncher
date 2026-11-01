import json
import logging
import re
import shlex
from dataclasses import dataclass
from typing import Callable
from core_lib.common.common import get_platform_info
from core_lib.common.exception import LauncherException, ArgumentValueError
from core_lib.game.library import get_natives_platform_info

logger = logging.getLogger("Launcher.CoreLib")

# =============== Features ===============
@dataclass(frozen=True)
class FeatureSpec:
    required_placeholders: tuple[str, ...] = ()
    validate: Callable[[dict], None] | None = None


def validate_resolution(values: dict) -> None:
    for key in ("resolution_width", "resolution_height"):
        value = values[key]
        if type(value) is not int or value <= 0:
            raise ArgumentValueError(
                f"{key} must be a positive integer."
            )


FEATURE_SPECS = {
    "has_custom_resolution": FeatureSpec(
        required_placeholders=(
            "resolution_width",
            "resolution_height",
        ),
        validate=validate_resolution,
    ),
    "is_demo_user": FeatureSpec(),
    "has_quick_plays_support": FeatureSpec(
        required_placeholders=("quickPlayPath",),
    ),
    "is_quick_play_singleplayer": FeatureSpec(
        required_placeholders=("quickPlaySingleplayer",),
    ),
    "is_quick_play_multiplayer": FeatureSpec(
        required_placeholders=("quickPlayMultiplayer",),
    ),
    "is_quick_play_realms": FeatureSpec(
        required_placeholders=("quickPlayRealms",),
    ),
}
# =============== Features end ===============

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

PLACEHOLDER_PATTERN = re.compile(r"\$\{([^{}]+)\}")

def replace_placeholders(argument, placeholders: dict, *, strict: bool = False,) -> str:
    def replace(match: re.Match) -> str:
        key = match.group(1)

        if key not in placeholders or placeholders[key] is None:
            if not strict:
                return match.group(0)

            reason = "unknown" if key not in placeholders else "has no value"
            raise ArgumentValueError(
                f"Argument placeholder {reason}: {key}"
            )

        return str(placeholders[key])

    return PLACEHOLDER_PATTERN.sub(replace, argument)


class ArgumentMappings:
    def __init__(self, player_name="Player", version_name="unknown",
                 game_directory=None, assets_root=None, legacy_assets_root=None, assets_index_name=None,
                 auth_uuid="00000001-0002-0003-0004-000000000005",
                 auth_access_token="", clientid=None, auth_xuid=None,
                 user_type=None, user_properties=None, version_type=None, natives_directory=None,
                 launcher_name=None, launcher_version=None,
                 classpath=None, classpath_separator=None, library_directory=None,
                 resolution: tuple[int, int] | None = None, client_jar_name: str | None = None):
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
        self.client_jar_name = client_jar_name
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


def parse_and_generate_arguments(arguments: list | str, mappings: ArgumentMappings,
                                 features: dict | None = None, *, extra_placeholders: dict | None = None,
                                 strict_placeholders: bool = False) -> \
    list[str]:
    if features is None:
        features = {}

    parsed_arguments = []

    if isinstance(arguments, str):
        # Convert legacy argument into a list type
        arguments = shlex.split(arguments)

    placeholders = mappings.generate_placeholders()

    if extra_placeholders:
        placeholders.update(extra_placeholders)

    for argument in arguments:
        # Check rules
        if not is_argument_allowed(argument, allow_features=features):
            continue

        # Each argument (section) may contain multiple items, convert it to list before replace placeholder
        for item in convert_argument_to_multiple_string(argument):
            parsed = replace_placeholders(item, placeholders, strict=strict_placeholders)
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

def find_match_feature_argument(arguments: list | str, feature) -> dict | None:
    if isinstance(arguments, str):
        arguments = shlex.split(arguments)

    for argument in arguments:
        # Check rules
        if not is_argument_allowed(argument, allow_features=feature):
            continue

        # Only dict argument has feature rule
        if not isinstance(argument, dict):
            continue

        return argument

    return None

def generate_enabled_feature_arguments(arguments: list | str, arg_maps: ArgumentMappings,
                                       features: dict | None = None, feature_placeholders: dict | None=None,
                                       strict_placeholders=False) -> list[str]:
    enabled_features = dict(features or {})
    extra_values = dict(feature_placeholders or {})

    values = arg_maps.generate_placeholders()
    values.update(extra_values)

    for name, enabled in enabled_features.items():
        if type(enabled) is not bool:
            raise ArgumentValueError(
                f"Feature {name} must be a boolean."
            )

        if not enabled:
            continue

        spec = FEATURE_SPECS.get(name)

        # Ignore unknown feature flag, hand it to parse_and_generate_arguments
        if spec is None:
            continue

        for key in spec.required_placeholders:
            if key not in values or values[key] is None or values[key] == "":
                raise ArgumentValueError(
                    f"Feature {name} requires placeholder {key}."
                )

        if spec.validate:
            spec.validate(values)

    return parse_and_generate_arguments(
        arguments,
        arg_maps,
        features=enabled_features,
        extra_placeholders=extra_values,
        strict_placeholders=strict_placeholders,
    )

def generate_feature_placeholders(maps: ArgumentMappings):
    if not isinstance(maps.resolution, tuple):
        width, height = None, None
    else:
        width = maps.resolution[0]
        height = maps.resolution[1] or None

    return {
        "resolution_width": width,
        "resolution_height": height,
    }


def generate_launch_command(arg_maps: ArgumentMappings, main_class: str, java_path: str, full_args: dict | str
                            , features: dict | None = None, user_jvm_args: list[str] | None | str = None,
                            strict_placeholders=False, *, extra_jvm_args: list[str] | None = None,
                            extra_game_args: list[str] | None = None) -> list[str]:
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
            strict_placeholders=strict_placeholders,
        )
    else:
        # Use jvm arguments that provided by user
        parsed_user_jvm_args = list(user_jvm_args)

    parsed_manifest_jvm_args = parse_and_generate_arguments(
        jvm_args,
        arg_maps,
        features=features,
        strict_placeholders=strict_placeholders,
    )

    feature_placeholders = generate_feature_placeholders(arg_maps)
    parsed_game_args = generate_enabled_feature_arguments(
        game_args,
        arg_maps,
        features=features,
        feature_placeholders=feature_placeholders,
        strict_placeholders=strict_placeholders,
    ) # Generate arguments that enabled by features and necessary arguments that from manifest

    # Legacy Minecraft don't have jvm arguments exist in the version library. We need to generate by ourselves
    parsed_jvm_args = append_missing_necessary_jvm_arguments(
        parsed_user_jvm_args + parsed_manifest_jvm_args, # Combine manifest and user jvm arguments together
        arg_maps,
    )

    # BootstrapLauncher must ignore the original client when the loader supplies
    # its patched Minecraft module. The client filename can differ from the
    # profile's version_name because manifests inherit the vanilla client JAR.
    if arg_maps.client_jar_name:
        prefix = "-DignoreList="
        for index, argument in enumerate(parsed_jvm_args):
            if argument.startswith(prefix):
                ignored = [item for item in argument[len(prefix):].split(",") if item]
                if not any(arg_maps.client_jar_name.startswith(item) for item in ignored):
                    ignored.append(arg_maps.client_jar_name)
                    parsed_jvm_args[index] = prefix + ",".join(ignored)

    cmd.extend(parsed_jvm_args)
    cmd.extend(extra_jvm_args or [])
    cmd.append(main_class)
    cmd.extend(parsed_game_args)
    cmd.extend(extra_game_args or [])
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
