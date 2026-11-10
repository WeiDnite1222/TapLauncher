"""
Profile Manager

A Minecraft profile manager that completely support official Minecraft Launcher.
"""
import base64
import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, Signal
from datetime import datetime, timezone

from PySide6.QtGui import QIcon

from core_lib.common.exception import ProfileException, ProfileLoadException, ProfileSaveException
from core_lib.game.profile import read_profile_file, is_profiles_valid, \
    get_profile_sample, create_or_save_profile_file, list_profiles as list_profiles_raw, convert_profile_data_to_object, \
    is_profile_exists, create_profile as create_profile_raw, update_profile as update_profile_raw, \
    get_current_profile_id, set_current_profile_id, remove_profile, duplicate_profile,  \
    set_last_used_time
from core_lib.game.version_info import LATEST_VERSION_ALIASES
from core_lib.qt.hack import is_qt_supported_image, image_to_data_url, base64_to_qicon, prepare_profile_icon
from manager.widgets import AskForRequest

DEFAuLT_PROFILE_RELATIVE_PATH = Path("launcher_profiles.json")

@dataclass(frozen=True)
class ProfileSummary:
    display_name: str
    id: str
    name: str
    version_id: str
    version_type: str
    icon: str
    last_used: datetime | None


@dataclass(frozen=True)
class ProfileDetail(ProfileSummary):
    game_dir: Path | None
    java_args: str
    resolution: tuple[int, int] | None
    created: datetime


@dataclass(frozen=True)
class CreateProfileRequest:
    name: str
    version_id: str
    version_type: str = "custom"
    game_dir: Path | None = None
    java_args: str = ""
    icon: str = ""
    resolution: tuple[int, int] | None = None
class _Profile_UnsetType:
    pass

_UNSET = _Profile_UnsetType()

@dataclass(frozen=True)
class UpdateProfileRequest:
    name: str | None = None
    version_id: str | None = None
    version_type: str | None = None
    game_dir: Path | None | _Profile_UnsetType = _UNSET
    java_args: str | None | _Profile_UnsetType = _UNSET
    icon: str | None = None
    resolution: tuple[int, int] | None | _Profile_UnsetType = _UNSET

@dataclass(frozen=True)
class LaunchProfile:
    display_name: str
    name: str
    profile_id: str
    version_id: str
    version_type: str
    game_dir: Path
    java_args: str
    resolution: tuple[int, int] | None

@dataclass(frozen=True)
class ValidationResult:
    errors: dict[str, str]

    @property
    def is_valid(self) -> bool:
        return not self.errors

class ProfileManager(QObject):
    profile_load = Signal()
    profiles_changed = Signal()
    profile_created = Signal(str)
    profile_updated = Signal(str)
    profile_removed = Signal(str)
    current_profile_changed = Signal(object)  # str | None
    error_occurred = Signal(str, str)  # error_code, message
    replace_relative_path = Signal(str)

    def __init__(self, app, widget_manager):
        QObject.__init__(self, app)
        self.app = app
        self.widget_manager = widget_manager
        self.profiles = {}


        self._path: Path | None = None
        self._is_modified = False

        self.profile_load.connect(
            self.load,
        )

        self.load()

    @property
    def default_profile_path(self):
        return Path(self.app.work_dir, DEFAuLT_PROFILE_RELATIVE_PATH)

    def register_plugin_apis(self, plugin_manager):
        plugin_manager.register_api("launcher.profiles.list", self.list_profiles)
        plugin_manager.register_api("launcher.profiles.get", self.get_profile)
        plugin_manager.register_api("launcher.profiles.contains", self.contains)
        plugin_manager.register_api("launcher.profiles.current_id", self.get_current_profile_id)
        plugin_manager.register_api("launcher.profiles.set_current", self.set_current_profile)
        plugin_manager.register_api("launcher.profiles.reload", self.reload)

    # File lifetime
    def create_profiles(self, path: str | Path | None=None) -> bool:
        path = Path(path) if path is not None else self.default_profile_path

        try:
            new_profiles = get_profile_sample()
            create_or_save_profile_file(new_profiles, path, create_backup=False)
            return True
        except ProfileSaveException as e:
            self.widget_manager.signal.show_error_message.emit(
                "Unable to create profile file: {}".format(e.user_message),
            )
            return False
        except Exception as e:
            self.widget_manager.signal.show_error_message.emit(
                "Unable to create profile file. An unexpected error occurred: {}".format(e),
            )
            return False

    def load(self, path: str | Path | None=None, return_value: bool=False) -> tuple[bool, None | dict]:
        """
        Load profiles
        :param path: If provided, this path becomes the current profile path after loading succeeds.
        :param return_value:
        :return:
        """
        path = Path(path) if path is not None else self.default_profile_path

        try:
            # Prevent existing data from being overwritten
            if self._is_modified:
                request = AskForRequest("ProfileManager", "Would you like to save the existing profile"
                                                          " before reload? (If not existing data will be overwritten)")

                self.widget_manager.signal.askyesno.emit(request)

                if not request.wait(60):
                    self.widget_manager.signal.show_error_message.emit(
                        "Timed out while waiting for confirmation. Please try again."
                    )
                    return False, None

                result = request.result()

                if result:
                    save_result = self.save()

                    if not save_result:
                        self.widget_manager.signal.show_error_message.emit(
                            "Unable to load profile due to saving error."
                        )
                        return False, None

            # Create new profile if the target profile file does not exist
            if not path.exists() and not self.create_profiles(path):
                return False, None

            result = read_profile_file(path)

            # Profile validation
            if not is_profiles_valid(result):
                self.widget_manager.signal.show_error_message.emit(
                    "Invalid profile file. Try restarting the profile in settings page.",
                )
                return False, None

            self.profiles = result
            self._path = path
            self._is_modified = False

            self.profiles_changed.emit()

            if return_value:
                return True, copy.deepcopy(result)

            return True, None
        except (ProfileException, ProfileLoadException) as e:
            self.widget_manager.signal.show_error_message.emit(
                "Unable to load profile file: {}".format(e.user_message),
            )
            return False, None
        except Exception as e:
            self.widget_manager.signal.show_error_message.emit(
                "Unable to load profile file. An unexpected error occurred: {}".format(e),
            )
            return False, None

    def save(self, path: str | Path | None=None, create_backup: bool=True) -> bool:
        path = Path(path) if path is not None else self.path

        try:
            if not is_profiles_valid(self.profiles):
                self.widget_manager.signal.show_error_message.emit(
                    "Current profile store in memory is not a valid profile.",
                )
                return False

            create_or_save_profile_file(
                self.profiles,
                path,
                create_backup=create_backup,
            )

            self._path = path
            self._is_modified = False
            return True
        except (ProfileException, ProfileSaveException) as e:
            self.widget_manager.signal.show_error_message.emit(
                "Unable to save profile file: {}".format(e.user_message),
            )
            return False
        except Exception as e:
            self.widget_manager.signal.show_error_message.emit(
                "Unable to save profile file. An unexpected error occurred: {}".format(e),
            )
            return False

    def _commit_profiles(self, updated_profiles: dict) -> bool:
        """Persist an updated profile document and roll back memory on failure."""
        previous_profiles = self.profiles
        previous_modified = self._is_modified

        self.profiles = updated_profiles
        self._is_modified = True

        if self.save():
            return True

        self.profiles = previous_profiles
        self._is_modified = previous_modified
        return False

    def reload(self) -> tuple[bool, dict | None]:
        return self.load(path=self.path)

    # Profile search
    def list_profiles(self) -> list[ProfileSummary]:
        result = []
        profiles = list_profiles_raw(self.profiles)

        for profile_id in profiles:
            profile = convert_profile_data_to_object(self.profiles, profile_id)
            profile_summary = ProfileSummary(
                display_name=self._get_profile_display_name(profile.name, profile.version_id),
                icon=str(profile.icon),
                id=profile_id,
                last_used=profile.last_used,
                name=profile.name,
                version_id=profile.version_id,
                version_type=profile.type
            )
            result.append(profile_summary)

        settings = self.profiles.get("settings", {})
        sorting = settings.get("profileSorting", "ByLastPlayed")
        current_id = get_current_profile_id(self.profiles)
        return sort_profile_summaries(result, sorting, current_id)

    def get_profile(self, profile_id: str) -> ProfileDetail | None:
        if not self.contains(profile_id, show_error=True):
            return None

        profile = convert_profile_data_to_object(
            self.profiles,
            profile_id,
        )

        resolution = None

        if profile.resolution:
            # Put resolution data to profile detail
            resolution = (
                profile.resolution["width"],
                profile.resolution["height"],
            )

        return ProfileDetail(
            display_name=self._get_profile_display_name(profile.name, profile.version_id),
            id=profile_id,
            name=profile.name,
            version_id=profile.version_id,
            version_type=profile.type,
            icon=str(profile.icon),
            last_used=profile.last_used,
            game_dir=Path(profile.game_dir) if profile.game_dir else None,
            java_args=profile.java_args,
            resolution=resolution,
            created=profile.created,
        )

    def contains(self, profile_id: str, show_error: bool=False) -> bool:
        result =  is_profile_exists(self.profiles, profile_id)

        if not result and show_error:
            self.widget_manager.signal.show_error_message.emit(
                "Profile ID {} does not exist.".format(profile_id),
            )

        return result

    # CRUD
    def create_profile(self, request: CreateProfileRequest) -> str | None:
        if not self.is_loaded:
            result, _ = self.load()

            if not result:
                return None

        validation: ValidationResult = self.validate(request)

        if not validation.is_valid:
            message = "\n".join(validation.errors.values())

            self.widget_manager.signal.show_error_message.emit(message)
            return None

        # Check game dir
        if request.game_dir is not None:
            game_dir = Path(request.game_dir).as_posix()
        else:
            default_game_dir = self.app.default_game_dir
            game_dir = default_game_dir.as_posix()

        try:
            # Apply resolution
            resolution = None
            if request.resolution is not None:
                width, height = request.resolution
                resolution = {
                    "width": width,
                    "height": height,
                }

            # Copy profiles before update
            updated_profiles = copy.deepcopy(self.profiles)

            _, profile_id = create_profile_raw(
                version_id=request.version_id,
                version_type=request.version_type,
                java_args=request.java_args,
                game_dir=game_dir,
                icon=request.icon,
                name=request.name,
                resolution=resolution,
                profiles=updated_profiles,
            )

            if not is_profiles_valid(updated_profiles):
                raise ProfileException("Created profile data is invalid.")

            if not self._commit_profiles(updated_profiles):
                return None

            # Update change events after the data is persisted.
            self.profile_created.emit(profile_id)
            self.profiles_changed.emit()

            return profile_id

        except ProfileException as e:
            self.widget_manager.signal.show_error_message.emit(
                f"Unable to create profile: {e.user_message}"
            )
            return None
        except (TypeError, ValueError) as e:
            self.widget_manager.signal.show_error_message.emit(
                f"Invalid profile request: {e}"
            )
            return None


    def _get_profile_display_name(self, existing_name: str, version_id: str) -> str:
        if existing_name.strip():
            return existing_name.strip()

        return self._get_profile_alias_display_name(version_id)

    @staticmethod
    def _get_profile_alias_display_name(version_id: str) -> str:
        alias = LATEST_VERSION_ALIASES.get(version_id)

        if alias:
            return alias.get("displayName", version_id)

        return "Unnamed Profile"

    def update_profile(self, profile_id: str, changes: UpdateProfileRequest) -> bool:
        # Check profile exists
        if not self.contains(profile_id, show_error=True):
            return False

        try:
            # Copy before the actual update.
            updated_profiles = copy.deepcopy(self.profiles)
            profile_data = copy.deepcopy(
                list_profiles_raw(updated_profiles)[profile_id]
            )

            # Check profile value change
            if changes.name is not None:
                profile_data["name"] = changes.name

            if changes.version_id is not None:
                profile_data["lastVersionId"] = changes.version_id

            if changes.version_type is not None:
                profile_data["type"] = changes.version_type

            if changes.game_dir is not _UNSET:
                if changes.game_dir is None:
                    profile_data["gameDir"] = ""
                else:
                    profile_data["gameDir"] = Path(
                        changes.game_dir
                    ).as_posix()

            if changes.java_args is not _UNSET:
                profile_data["javaArgs"] = (
                    "" if changes.java_args is None
                    else changes.java_args
                )

            if changes.icon is not None:
                profile_data["icon"] = changes.icon

            if changes.resolution is not _UNSET:
                if changes.resolution is None:
                    profile_data.pop("resolution", None)
                else:
                    width, height = changes.resolution
                    profile_data["resolution"] = {
                        "width": width,
                        "height": height,
                    }

            update_profile_raw(
                updated_profiles,
                profile_id,
                profile_data,
            )

            if profile_data == list_profiles_raw(self.profiles)[profile_id]:
                return True

            if not self._commit_profiles(updated_profiles):
                return False

            self.profile_updated.emit(profile_id)
            self.profiles_changed.emit()

            return True

        except (ProfileException, TypeError, ValueError) as e:
            self.widget_manager.signal.show_error_message.emit(
                f"Unable to update profile: {e}"
            )
            return False

    def remove_profile(self, profile_id: str) -> bool:
        if not self.contains(profile_id, show_error=True):
            return False

        try:
            updated_profiles = copy.deepcopy(self.profiles)
            is_current_changed = get_current_profile_id(self.profiles) == profile_id

            # !!!COPY BEFORE REMOVE!!!
            remove_profile(updated_profiles, profile_id)

            # Unset current profile id if is same as removed profile's id
            if is_current_changed:
                updated_profiles["lastPlayedProfileID"] = None

            if not self._commit_profiles(updated_profiles):
                return False

            self.profile_removed.emit(profile_id)

            if is_current_changed:
                self.current_profile_changed.emit(None)

            self.profiles_changed.emit()

            return True
        except ProfileException as e:
            self.widget_manager.signal.show_error_message.emit(
                f"Unable to remove profile: {e.user_message}"
            )
            return False
        except Exception as e:
            self.widget_manager.signal.show_error_message.emit(
                f"Unable to remove profile. An unknown error occurred: {e}"
            )
            return False

    def duplicate_profile(self, profile_id: str, new_name: str | None = None) -> str | None:
        if not self.contains(profile_id, show_error=True):
            return None

        try:
            updated_profiles = copy.deepcopy(self.profiles)
            new_profile_id = duplicate_profile(
                updated_profiles,
                profile_id,
                new_name,
            )

            if not self._commit_profiles(updated_profiles):
                return None

            self.profile_created.emit(new_profile_id)
            self.profiles_changed.emit()

            return new_profile_id
        except ProfileException as e:
            self.widget_manager.signal.show_error_message.emit(
                f"Unable to duplicate profile: {e.user_message}"
            )
        except Exception as e:
            self.widget_manager.signal.show_error_message.emit(
                f"Unable to duplicate profile. An unknown error occurred: {e}"
            )

    # Profile switch
    def set_current_profile(self, profile_id: str | None) -> bool:
        """
        Set the current profile ID.
        :param profile_id: INFO: Set the current profile ID to None if you want to unset it
        :return:
        """
        if not self.is_loaded:
            success, _ = self.load()

            if not success:
                return False

        if profile_id is not None and not self.contains(profile_id, show_error=True):
            return False

        try:
            existing_id = get_current_profile_id(self.profiles)

            # ignore same id request
            if profile_id == existing_id:
                return True

            if existing_id is not None:
                self.app.logger.debug(
                    "Replacing current profile ID {} to {}".format(existing_id, profile_id)
                )

            updated_profiles = copy.deepcopy(self.profiles)
            set_current_profile_id(updated_profiles, profile_id)

            if not self._commit_profiles(updated_profiles):
                return False

            self.current_profile_changed.emit(profile_id)
            self.profiles_changed.emit()
            return True
        except ProfileException as e:
            self.widget_manager.signal.show_error_message.emit(
                f"Unable to set current profile ID: {e.user_message}"
            )
            return False
        except Exception as e:
            self.widget_manager.signal.show_error_message.emit(
                "Unable to set current profile ID. An unknown error occurred {}".format(str(e))
            )
            return False

    def update_profile_icon(self, profile_id: str, filepath: Path, format_checker: Callable[[Path], *
        tuple[bool, str | None]]=is_qt_supported_image):
        if not self.is_loaded:
            success, _ = self.load()

            if not success:
                return False

        if profile_id is not None and not self.contains(profile_id, show_error=True):
            return False

        if not filepath.exists() or not filepath.is_file():
            self.widget_manager.show_error(self.app.tr_text("Image file does not exist or is not a file"))
            return False

        try:
            result = None
            file_format: str | None = None
            if callable(format_checker):
                result, file_format = format_checker(filepath)
                if not result:
                    self.widget_manager.show_error(self.app.tr_text("Image format is not supported."))
                    return False

            if file_format is None:
                raise ValueError(self.app.tr_text("Image format is not supported."))

            new_icon, resized = prepare_profile_icon(filepath)
            if resized:
                self.widget_manager.signal.show_info_message.emit(self.app.tr_text(
                    "This image exceeds 128 x 128 pixels and will be resized to 128 x 128."
                ))
            request = UpdateProfileRequest(
                icon=new_icon
            )

            if not self.update_profile(profile_id, request):
                return False

            self.profiles_changed.emit()
            return True
        except Exception as e:
            self.widget_manager.signal.show_error_message.emit(self.app.tr_text(str(e)))
            return False

    def update_last_used_time(
        self,
        profile_id: str,
        time: datetime | None = None,
    ) -> bool:
        """
        Update profile last used time
        :param profile_id:
        :param time:
        :return:
        """
        if time is None:
            time = datetime.now(timezone.utc)

        if not self.is_loaded:
            success, _ = self.load()

            if not success:
                return False

        if profile_id is not None and not self.contains(profile_id, show_error=True):
            return False

        try:
            updated_profiles = copy.deepcopy(self.profiles)
            set_last_used_time(updated_profiles, profile_id, time)

            if not self._commit_profiles(updated_profiles):
                return False

            self.profiles_changed.emit()
            return True
        except ProfileException as e:
            self.widget_manager.signal.show_error_message.emit(
                f"Unable to set last used time for profile ID: {e.user_message}"
            )
            return False
        except Exception as e:
            self.widget_manager.signal.show_error_message.emit(
                f"Unable to set last used time for profile with ID {profile_id}. An unknown error occurred {str(e)}"
            )
            return False

    def get_current_profile_id(self) -> str | None:
        if not self.is_loaded:
            success, _ = self.load()

            if not success:
                return None

        return get_current_profile_id(self.profiles)

    def get_launch_profile(self, profile_id: str) -> LaunchProfile | None:
        profile = self.get_profile(profile_id)

        if profile is None:
            return None

        # Use default game_dir if is unset
        game_dir = (
            profile.game_dir
            if profile.game_dir is not None
            else self.app.default_game_dir
        )

        return LaunchProfile(
            display_name=self._get_profile_display_name(
                profile.name,
                profile.version_id,
            ),
            name=profile.name,
            profile_id=profile.id,
            version_id=profile.version_id,
            version_type=profile.version_type,
            game_dir=game_dir,
            java_args=profile.java_args,
            resolution=profile.resolution,
        )

    # Validation
    @staticmethod
    def validate(request: CreateProfileRequest) -> ValidationResult:
        errors = {}

        if not isinstance(request.name, str) or not request.name.strip():
            errors["name"] = "Profile name cannot be empty."

        if not isinstance(request.version_id, str)  or not request.version_id.strip():
            errors["version_id"] = "Version ID cannot be empty."

        if not isinstance(request.version_type, str) or not request.version_type.strip():
            errors["version_type"] = "Version type cannot be empty."

        if not isinstance(request.java_args, str):
            errors["java_args"] = "Java arguments must be a string."

        if not isinstance(request.icon, str):
            errors["icon"] = "Icon must be a string."

        if request.game_dir is not None:
            try:
                Path(request.game_dir)
            except (TypeError, ValueError):
                errors["game_dir"] = "Game directory is invalid."

        if request.resolution is not None:
            if not isinstance(request.resolution, tuple) or len(request.resolution) != 2:
                errors["resolution"] = (
                    "Resolution must contain width and height."
                )
            else:
                width, height = request.resolution

                if (not isinstance(width, int) or isinstance(width, bool) or width <= 0 or
                    not isinstance(height, int) or isinstance(height, bool) or height <= 0):
                    errors["resolution"] = (
                        "Resolution width and height must be positive integers."
                    )

        return ValidationResult(errors=errors)

    @staticmethod
    def validate_update(request: UpdateProfileRequest) -> ValidationResult:
        errors = {}

        if not isinstance(request.name, str) or not request.name.strip():
            errors["name"] = "Profile name cannot be empty."

        if not isinstance(request.version_id, str) or not request.version_id.strip():
            errors["version_id"] = "Version ID cannot be empty."

        if not isinstance(request.version_type, str) or not request.version_type.strip():
            errors["version_type"] = "Version type cannot be empty."

        if not isinstance(request.java_args, str):
            errors["java_args"] = "Java arguments must be a string."

        if not isinstance(request.icon, str):
            errors["icon"] = "Icon must be a string."

        if request.game_dir is not _UNSET and request.game_dir is not None:
            try:
                Path(request.game_dir)
            except (TypeError, ValueError):
                errors["game_dir"] = "Game directory is invalid."

        if request.resolution is not _UNSET and request.resolution is not None:
            if not isinstance(request.resolution, tuple) or len(request.resolution) != 2:
                errors["resolution"] = (
                    "Resolution must contain width and height."
                )
            else:
                width, height = request.resolution

                if (not isinstance(width, int) or isinstance(width, bool) or width <= 0 or
                        not isinstance(height, int) or isinstance(height, bool) or height <= 0):
                    errors["resolution"] = (
                        "Resolution width and height must be positive integers."
                    )

        return ValidationResult(errors=errors)

    # Property
    @property
    def path(self) -> Path | None:
        if self._path is None:
            self._path = Path(self.app.work_dir, DEFAuLT_PROFILE_RELATIVE_PATH)

        return self._path

    @property
    def is_loaded(self) -> bool:
        return bool(self.profiles) and is_profiles_valid(self.profiles)

    @property
    def is_modified(self) -> bool:
        return self._is_modified


def sort_profile_summaries(
    profiles: list[ProfileSummary],
    sorting: str,
    current_profile_id: str | None = None,
) -> list[ProfileSummary]:
    """Order profiles according to launcher_profiles.json settings."""
    ordered = list(profiles)

    if sorting == "ByName":
        return sorted(
            ordered,
            key=lambda profile: (
                profile.display_name.casefold(),
                profile.version_id.casefold(),
                profile.id,
            ),
        )

    if sorting == "ByLastPlayed":
        def last_used_timestamp(profile: ProfileSummary) -> float:
            if profile.last_used is None:
                return float("-inf")
            try:
                return profile.last_used.timestamp()
            except (OSError, OverflowError, ValueError):
                return float("-inf")

        ordered.sort(key=last_used_timestamp, reverse=True)
        if current_profile_id is not None:
            ordered.sort(key=lambda profile: profile.id != current_profile_id)

    return ordered


def _profile_icon(value: str, icon_dir: Path) -> QIcon:
    icon = base64_to_qicon(value)
    if icon.isNull() and not value.startswith("data:"):
        try:
            if value and Path(value).is_file():
                icon = QIcon(value)
        except (OSError, ValueError):
            pass
    if icon.isNull():
        icon = QIcon(str(Path(icon_dir, "profile_default.png")))
    return icon
