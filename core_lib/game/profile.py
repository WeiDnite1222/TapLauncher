"""
This profile module also compatible with official launcher profile format
"""
import datetime
import json
import logging
import os
import uuid
from copy import deepcopy
from pathlib import Path

from PySide6.QtGui import QImage

from core_lib.common.exception import ProfileKeyNotFoundException, ProfileException, ProfileSaveException, \
    ProfileLoadException

logger = logging.getLogger("Launcher.CoreLib")

def get_profile_sample() -> dict:
    return {
        "lastPlayedProfileID": None,
        "profiles": {},
        "settings": {
            # Not all settings are included
            "profileSorting": "ByLastPlayed",
            "showGameLog": True,
        },
        "version": 6
    }

class Profile:
    def __init__(self, version_id: str, created: datetime.datetime,
                 last_used: datetime.datetime | None, name: str="", icon: str | Path="",
                 game_dir: str | Path="", java_args: str="", resolution_raw: dict | None = None, type_raw="custom"):
        self.version_id = version_id
        self.created = created
        self.last_used = last_used
        self.name = name
        self.icon: str | Path = icon
        self.game_dir: Path | str = game_dir
        self.java_args: str = java_args
        self.resolution: dict | None = resolution_raw
        self.type: str = type_raw

def _get_current_datetime_string() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")

def _create_profile_data(version_id: str, version_type: str, java_args: str= "", game_dir: str= "", icon: str= "", name: str= "", resolution: dict=None) -> dict:
    content = {
        "name": name,
        "created": _get_current_datetime_string(),
        "gameDir": game_dir,
        "lastVersionId": version_id,
        "lastUsed": "",
        "type": version_type,
        "javaArgs": java_args,
        "icon": icon,
    }

    if isinstance(resolution, dict):
        content["resolution"] = resolution

    return content

def create_profile_data_from_object(p: Profile):
    created: datetime.datetime | str = p.created
    last_used: datetime.datetime | str | None = p.last_used

    if isinstance(created, datetime.datetime):
        created = created.isoformat().replace("+00:00", "Z")
    elif not isinstance(created, str):
        raise TypeError("\"created\" key  must be a datetime.datetime or str")

    game_dir: str | Path = p.game_dir

    if isinstance(game_dir, Path):
        game_dir = game_dir.as_posix()

    icon: str | Path = p.icon

    if isinstance(icon, Path):
        icon = icon.as_posix()

    content = {
        "name": p.name,
        "created": created,
        "gameDir": game_dir,
        "lastVersionId": p.version_id,
        "type": p.type,
        "javaArgs": p.java_args,
        "icon": icon,
    }

    if isinstance(last_used, datetime.datetime):
        last_used = last_used.isoformat().replace("+00:00", "Z")
    elif isinstance(last_used, str):
        pass
    elif last_used is not None:
        raise TypeError("\"last_used\" key  must be a datetime.datetime or str")

    if last_used:
        content["lastUsed"] = last_used

    if isinstance(p.resolution, dict):
        content["resolution"] = p.resolution

    return content



def create_profile(version_id: str, version_type: str, java_args: str="", game_dir: str="",
                   icon: str="", name: str="", resolution: dict=None, profiles: dict | None=None,
                   max_generate_retry=10) -> tuple[dict, str]:
    """
    Create a new profile with the given arguments
    :param version_id:
    :param version_type:
    :param java_args:
    :param game_dir:
    :param icon:
    :param name:
    :param resolution:
    :param profiles: If not given, this function will create a new profiles dict instead
    :param max_generate_retry:
    :return:
        profile: dict
        new_profile_id: str
    """
    if profiles is None:
        profiles = get_profile_sample()

    profile = _create_profile_data(version_id, version_type, java_args, game_dir, icon, name, resolution)

    for _ in range(max_generate_retry):
        profile_id = str(uuid.uuid4().hex)

        if profile_id not in profiles["profiles"]:
            break
    else:
        raise ProfileException(
            "Unable to generate a unique profile ID."
        )

    profiles["profiles"][profile_id] = profile

    return profile, profile_id

def create_or_save_profile_file(profiles: dict, profile_filepath: Path, profile_file_bak_filepath: Path | None=None,
                        overwrite=True, create_backup=True) -> None:
    """
    Create or save a new profile
    :param profiles:
    :param profile_filepath:
    :param profile_file_bak_filepath:
    :param overwrite:
    :param create_backup:
    :return:
    """
    profile_filepath.parent.mkdir(parents=True, exist_ok=True)

    if profile_filepath.exists() and not overwrite:
        raise ProfileSaveException(
            f"Profile file already exists: {profile_filepath}"
        )

    # Create backup path
    if create_backup and profile_file_bak_filepath is None:
        profile_file_bak_filepath = profile_filepath.with_suffix(
            profile_filepath.suffix + ".bak"
        )

    temporary_path = profile_filepath.with_suffix(
        profile_filepath.suffix + ".tmp"
    )

    try:
        # Write temp profile file first
        temporary_path.write_text(
            json.dumps(profiles, indent=4, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception as e:
        raise ProfileSaveException(
            "Unable to create profile file: {}".format(e)
        )

    try:
        if create_backup and profile_filepath.exists():
            if profile_file_bak_filepath.exists():
                profile_file_bak_filepath.unlink()

            # Rename old profile with an ".bak" extension
            os.replace(
                profile_filepath,
                profile_file_bak_filepath,
            )

        # Rename new profile file
        os.replace(temporary_path, profile_filepath)
    except OSError as exc:
        if (create_backup and profile_file_bak_filepath is not None and profile_file_bak_filepath.exists()
            and not profile_filepath.exists()):
            os.replace(
                profile_file_bak_filepath,
                profile_filepath,
            )
        raise ProfileSaveException(
            f"Unable to save profile file: {exc}"
        ) from exc
    except Exception as e:
        raise ProfileSaveException(
            "Unable to replace path from old to new profile: {}".format(e)
        )

def read_profile_file(profile_filepath: Path) -> dict:
    """
    Read profile from existing file
    :param profile_filepath:
    :return:
        profiles: dict
    """
    if not profile_filepath.exists():
        raise ProfileException(
            "Profile file does not exist: {}".format(profile_filepath)
        )

    try:
        with open(str(profile_filepath), "r", encoding="utf-8") as f:
            return json.loads(f.read())
    except Exception as e:
        raise ProfileLoadException(
            "Unable to read profile file: {}".format(e)
        )

def _check_profile(profile: dict, fix_wrong=False) -> bool:
    if not isinstance(profile, dict):
        return False

    profile_name = profile.get("name")
    last_version_id = profile.get("lastVersionId", None)

    if not last_version_id or not isinstance(last_version_id, str):
        return False
    elif profile_name is None or not isinstance(profile_name, str):
        return False

    resolution = profile.get("resolution", None)

    if resolution is None:
        return True

    if not isinstance(resolution, dict):
        if fix_wrong:
            profile.pop("resolution", None)
            return True
        return False

    width = resolution.get("width")
    height = resolution.get("height")

    if not isinstance(width, int) or isinstance(width, bool) or width <= 0:
        return False

    if not isinstance(height, int) or isinstance(height, bool) or height <= 0:
        return False

    return True

def is_profiles_valid(profiles: dict, fix_wrong=False, ignore_invalid_profile=False) -> bool:
    """
    Check if a profiles dictionary is valid
    :param profiles:
    :param fix_wrong:
    :param ignore_invalid_profile:
    :return:
        filtered_profiles: dict
    """
    if not isinstance(profiles, dict):
        return False

    profiles_map = profiles.get("profiles", None)
    settings = profiles.get("settings", None)

    if not isinstance(profiles_map, dict):
        return False

    if not isinstance(settings, dict):
        return False

    invalid_ids = []

    for profile_id, profile in profiles_map.items():
        if not _check_profile(profile, fix_wrong=fix_wrong):
            invalid_ids.append(profile_id)

    if ignore_invalid_profile:
        for profile_id in invalid_ids:
            del profiles_map[profile_id]
        return True

    return not invalid_ids

def is_profile_valid(profile_data: dict, fix_wrong=False):
    return _check_profile(profile_data, fix_wrong=fix_wrong)

def is_profile_exists(profiles: dict, profile_id: str) -> bool:
    if not isinstance(profiles, dict):
        logger.warning("Profile type is not valid: {}".format(type(profiles)))
        return False

    profiles_map: dict = profiles.get("profiles")

    if not isinstance(profiles_map, dict):
        logger.warning("Profile map type is not valid: {}".format(type(profiles_map)))
        return False

    return profile_id in profiles_map

def list_profiles(profiles: dict) -> dict:
    """
    List all profiles that inside profiles data
    :param profiles:
    :return:
    """
    return profiles.get("profiles", {})

def get_profile(profiles: dict, profile_id: str) -> dict:
    profile_map = list_profiles(profiles)

    try:
        return profile_map[profile_id]
    except KeyError as exc:
        raise ProfileKeyNotFoundException(
            f"Specified profile id {profile_id} not found."
        ) from exc

def set_current_profile_id(profiles: dict, profile_id: str):
    """
    Set current profile id
    INFO: You should ensure profile id is existing in profiles before calling this function.
    :param profiles:
    :param profile_id:
    :return:
    """
    profiles["lastPlayedProfileID"] = profile_id

def get_current_profile_id(profiles: dict) -> str | None:
    return profiles.get("lastPlayedProfileID", None)

get_last_played_profile_id = get_current_profile_id

def add_profile(profiles: dict, profile: dict, max_generate_retry=10) -> tuple[dict, str]:
    """
    Add a new profile
    :param profiles:
    :param profile:
    :param max_generate_retry:
    :return:
        profiles: dict
        new_profile_id: str
    """
    for _ in range(max_generate_retry):
        profile_id = str(uuid.uuid4().hex)

        if profile_id not in profiles["profiles"]:
            break
    else:
        raise ProfileException(
            "Unable to generate a unique profile ID."
        )

    profiles["profiles"][profile_id] = profile

    return profiles, profile_id

def remove_profile(profiles: dict, profile_id: str):
    """
    Remove a profile
    :param profiles:
    :param profile_id:
    :return:
    """
    profiles_map = list_profiles(profiles)

    if not profiles_map:
        raise ProfileException(
            "No profiles exists"
        )

    try:
        del profiles_map[profile_id]
    except KeyError:
        raise ProfileKeyNotFoundException("Specified profile id {} not found.".format(profile_id))

def duplicate_profile(profiles: dict, profile_id: str, new_name: str | None=None, max_generate_retry: int=10) -> str:
    """
    Duplicate a profile
    :param profiles:
    :param profile_id:
    :param new_name:
    :param max_generate_retry:
    :return:
        new_profile_id: str
    """
    profiles_map = list_profiles(profiles)

    if not profiles_map:
        raise ProfileException(
            "No profiles exists"
        )

    for _ in range(max_generate_retry):
        new_profile_id = str(uuid.uuid4().hex)

        if new_profile_id not in profiles_map:
            break
    else:
        raise ProfileException(
            "Unable to generate a unique profile ID."
        )

    for p_id in profiles_map:
        if p_id == profile_id:
            new_profile = deepcopy(profiles_map[profile_id])

            if new_name is not None:
                new_profile["name"] = new_name
            else:
                new_profile["name"] = f'{new_profile.get("name", "")} Copy'

            profiles["profiles"][new_profile_id] = new_profile
            return new_profile_id

    raise ProfileKeyNotFoundException(
        "Specified profile id {} not found.".format(profile_id)
    )

def convert_profile_data_to_object(profiles: dict, profile_id: str) -> Profile:
    """
    Convert profiles data to object
    :param profiles:
    :param profile_id:
    :return:
        profiles: dict
        profile_id: str
    """
    profile = get_profile(profiles, profile_id)

    created: str | datetime.datetime = profile.get("created", datetime.datetime.now())
    last_used: None | str | datetime.datetime = profile.get("lastUsed", None)

    if not isinstance(created, datetime.datetime):
        try:
            created = datetime.datetime.fromisoformat(created)
        except ValueError:
            created = datetime.datetime.now()

    if isinstance(last_used, str):
        try:
            last_used = datetime.datetime.fromisoformat(last_used)
        except ValueError:
            last_used = None

    item = Profile(
        version_id=profile.get("lastVersionId", ""),
        created=created,
        last_used=last_used,
        name=profile.get("name", ""),
        icon=profile.get("icon", ""),
        game_dir=profile.get("gameDir", ""),
        java_args=profile.get("javaArgs", ""),
        resolution_raw=profile.get("resolution", {}),
        type_raw=profile.get("type", "custom"),
    )

    return item

def update_profile(profiles: dict, profile_id: str, profile_data: dict, fix_wrong: bool=False) -> tuple[dict, str]:
    if not is_profile_exists(profiles, profile_id):
        raise ProfileException(
            "Specified profile id {} not found.".format(profile_id)
        )

    if not is_profile_valid(profile_data, fix_wrong=fix_wrong):
        raise ProfileException(
            "Provided profile data is not valid."
        )

    profiles["profiles"][profile_id] = profile_data

    return profiles, profile_id

