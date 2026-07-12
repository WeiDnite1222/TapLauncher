import logging
import shlex

from core_lib.game.library import get_natives_platform_info

logger = logging.getLogger("Launcher.CoreLib")

def is_argument_allowed(argument: dict | str, allow_features: dict | None=None) -> bool:
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

    _, platform_rule_name, _ = get_natives_platform_info()

    allowed = False

    if not rules:
        return True

    for rule in rules:
        rule_action = rule.get("action", None)
        os_section = rule.get("os", {})
        rule_os = os_section.get("name", None)
        features_rule = rule.get("features", None)

        if rule_os is not None and platform_rule_name != rule_os:
            continue

        matched = True

        # Check feature dict
        if features_rule:
            for key, expected in features_rule.items():
                if allow_features.get(key, False) != expected:
                    matched = False
                    break

        if not matched:
            continue


        if rule_action == "allow":
            allowed = True
        elif rule_action == "disallow":
            allowed = False
        else:
            logger.warning(f"Unknown action {rule_action}\n")

    return allowed

def replace_placeholders(argument, placeholders: dict) -> str:
    if argument:
        for key, value in placeholders.items():
            argument = argument.replace("${" + key + "}", "" if value is None else str(value))

    return argument

class ArgumentMappings:
    def __init__(self, player_name="Player", version_name="unknown",
                 game_directory=None, assets_root=None, assets_index_name=None,
                 auth_uuid="00000001-0002-0003-0004-000000000005",
                 auth_access_token="", clientid=None, auth_xuid=None,
                 user_type=None, version_type=None, natives_directory=None,
                 launcher_name=None, launcher_version=None,
                 classpath=None, classpath_separator=None, library_directory=None):
        self.player_name = player_name
        self.version_name = version_name
        self.game_directory = game_directory
        self.assets_root = assets_root
        self.assets_index_name = assets_index_name
        self.auth_uuid = auth_uuid
        self.auth_access_token = auth_access_token
        self.clientid = clientid
        self.auth_xuid = auth_xuid
        self.user_type = user_type
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
            "assets_index_name": self.assets_index_name,
            "auth_uuid": self.auth_uuid,
            "auth_access_token": self.auth_access_token,
            "auth_player_name": self.player_name,
            "clientid": self.clientid,
            "auth_xuid": self.auth_xuid,
            "user_type": self.user_type,
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
            return [str(item) for item in value] # ensure all item are string
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

REMAPPING_ARGUMENTS = {
    # For some (I don't know) reason, in 26.2, Mojang include some
    "-Djava.library.path=${natives_directory}/java": "-Djava.library.path=${natives_directory}"
}

def hard_remapping_special_arguments(argument: str) -> str:
    for arg in REMAPPING_ARGUMENTS:
        new_value = REMAPPING_ARGUMENTS[arg]

        if arg == argument:
            return new_value

    return argument

def parse_and_generate_arguments(arguments: list | str, mappings: ArgumentMappings, features: dict | None=None) -> list[str]:
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

        # Replace some special arguments
        new_argument = hard_remapping_special_arguments(argument)

        # Each argument (section) may contain multiple items, convert it to list before replace placeholder
        converted = convert_argument_to_multiple_string(new_argument)

        for item in converted:
            parsed = replace_placeholders(item, placeholders)
            parsed_arguments.append(parsed)

    return parsed_arguments


def generate_launch_command(arg_maps: ArgumentMappings, main_class: str, java_path: str, full_args: dict | str
                            ) -> list[str]:
    cmd = [java_path]
    game_args, jvm_args = find_game_and_jvm_args(full_args)
    parsed_jvm_args = parse_and_generate_arguments(
        jvm_args,
        arg_maps
    )
    parsed_game_args = parse_and_generate_arguments(
        game_args,
        arg_maps
    )

    # Legacy Minecraft don't have jvm arguments exist in the version library. We need to generate by ourselves
    if len(parsed_jvm_args) == 0:
        cmd.extend([
            f"-Djava.library.path={arg_maps.natives_directory}",
            "-cp",
            arg_maps.classpath,
        ])
    else:
        cmd.extend(parsed_jvm_args)

    cmd.append(main_class)
    cmd.extend(parsed_game_args)

    return cmd