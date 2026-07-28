"""
IMPORTANT: Still under construction!
"""
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from datetime import datetime

from PySide6.QtWidgets import QApplication

from core_lib.common.exception import ProfileException
from core_lib.game.profile import read_profile_file

DEFAuLT_PROFILE_RELATIVE_PATH = Path("launcher_profiles.json")

@dataclass(frozen=True)
class ProfileSummary:
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


@dataclass(frozen=True)
class UpdateProfileRequest:
    name: str | None = None
    version_id: str | None = None
    version_type: str | None = None
    game_dir: Path | None = None
    java_args: str | None = None
    icon: str | None = None
    resolution: tuple[int, int] | None = None

@dataclass(frozen=True)
class LaunchProfile:
    pass

@dataclass(frozen=True)
class ValidationResult:
    pass

class ProfileManager(QObject):
    profiles_changed = Signal()
    profile_created = Signal(str)
    profile_updated = Signal(str)
    profile_removed = Signal(str)
    current_profile_changed = Signal(object)  # str | None
    error_occurred = Signal(str, str)  # error_code, message
    replace_relative_path = Signal(str)

    def __init__(self, app):
        QObject.__init__(self, app)
        self.app = app
        self.profiles = []

    @property
    def profile_path(self):
        return Path(self.app.work_dir, DEFAuLT_PROFILE_RELATIVE_PATH)

    # File lifetime
    def load(self, path: Path=None, return_value=False) -> None | dict:
        if path is None:
            path = self.profile_path

        try:
            result = read_profile_file(path)
        except ProfileException:
            pass


    # def load(self, path: str | Path) -> None: ...
    def save(self) -> None: ...
    def save_as(self, path: str | Path) -> None: ...
    def reload(self) -> None: ...

    # Profile search
    def list_profiles(self) -> list[ProfileSummary]: ...
    def get_profile(self, profile_id: str) -> ProfileDetail: ...
    def contains(self, profile_id: str) -> bool: ...

    # CRUD
    def create_profile(self, request: CreateProfileRequest) -> str: ...
    def update_profile(
        self, profile_id: str, changes: UpdateProfileRequest
    ) -> None: ...
    def remove_profile(self, profile_id: str) -> None: ...
    def duplicate_profile(
        self, profile_id: str, new_name: str | None = None
    ) -> str: ...

    # Profile switch
    def set_current_profile(self, profile_id: str | None) -> None: ...
    def get_current_profile_id(self) -> str | None: ...
    def get_launch_profile(self, profile_id: str) -> LaunchProfile: ...

    # Validation
    def validate(self, request: CreateProfileRequest) -> ValidationResult: ...

    # Property
    @property
    def path(self) -> Path | None: ...

    @property
    def is_loaded(self) -> bool: ...

    @property
    def is_dirty(self) -> bool: ...