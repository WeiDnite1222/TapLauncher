from pathlib import Path
from typing import Mapping

from pydantic import ValidationError


class LauncherException(Exception):
    user_message = "Launcher error occurred."

    def __init__(self, message=None, *, user_message=None):
        super().__init__(message or user_message or self.user_message)
        if user_message is not None:
            self.user_message = user_message

class LauncherHTTPException(LauncherException):
    user_message = "Launcher error occurred."

    def __init__(self, message=None, status_code=None,*, user_message=None):
        super().__init__(message or user_message or self.user_message)
        if user_message is not None:
            self.user_message = user_message
        self.status_code = status_code

class HashMismatchException(Exception):
    def __init__(self, hash_name, got_hash, expected_hash, filepath: str | Path):
        if type(filepath) == Path: filepath = Path(filepath).absolute().as_posix()
        self.message = "File {} hash mismatch. Expected hash {}. Got hash {} ({})".format(filepath, got_hash,
                                                                                          expected_hash, hash_name)
        super().__init__(self.message)

class UnsupportedPlatformException(LauncherException):
    user_message = "Current platform or architecture is not supported."

class VersionNotSelectedException(LauncherException):
    user_message = "Select a version before continuing."

class VersionManifestFetchException(LauncherException):
    user_message = "Unable to fetch version manifest."

class VersionManifestSaveException(LauncherException):
    user_message = "Unable to save version manifest."

class NoVersionFoundException(LauncherException):
    user_message = "No version found. (This should never happen)"

class NoSpecifiedVersionKeyException(LauncherException):
    user_message = "Specified version or type not found."

class VersionDataKeyNotFoundException(LauncherException):
    user_message = "Specified version data section (key) not found."

class VersionManifestException(LauncherException):
    user_message = "Unable to load version manifest."

class DependencyException(LauncherException):
    user_message = "Unable to find dependency."

class NativeResolveException(LauncherException):
    user_message = "Unable to resolve native libraries."

class DownloadException(LauncherException):
    user_message = "Some files failed to download."

class ExtractException(LauncherException):
    user_message = "Unable to extract native libraries."

class AssetManifestFetchException(LauncherException):
    user_message = "Unable to fetch asset manifest."

class AssetManifestSaveException(LauncherException):
    user_message = "Unable to save asset manifest."

class AssetManifestException(LauncherException):
    user_message = "Unable to load asset manifest."

class AssetDataKeyNotFoundException(LauncherException):
    user_message = "Specified asset data section (key) not found."

class JavaRuntimeException(LauncherException):
    user_message = "An error occurred while executing Java runtime."

class JavaRuntimeParseException(JavaRuntimeException):
    user_message = "Unable to parse Java runtime details."

class RuntimeManifestFetchException(LauncherException):
    user_message = "Unable to fetch runtime manifest."

class RuntimeManifestDataException(LauncherException):
    user_message = "Runtime manifest is missing or corrupted."

class ProfileException(LauncherException):
    user_message = "An error occurred while processing profile."

class ProfileSaveException(LauncherException):
    user_message = "Unable to save profile. Try again later."

class ProfileLoadException(LauncherException):
    user_message = "Unable to load profile. Profile may corrupted"

class ProfileKeyNotFoundException(LauncherException):
    user_message = "Specified profile key not found. Profile may corrupted."

class AccountException(LauncherException):
    user_message = "An error occurred while processing account data."

class AccountSaveException(AccountException):
    user_message = "Unable to save account data. Try again later."

class AccountLoadException(AccountException):
    user_message = "Unable to load account data. The account file may be corrupted."

class AccountKeyNotFoundException(AccountException):
    user_message = "Specified account was not found."

class AuthenticationException(LauncherException):
    user_message = "Authentication failed."

class AuthenticationConnectException(LauncherException):
    user_message = "An error occurred while connecting to authentication server."

class AuthenticationSessionException(LauncherHTTPException):
    user_message = "Authentication failed. Session may expire."

class ThirdPartyAPIException(LauncherException):
    user_message = "An error occurred while fetching third party API."

class SettingsError(LauncherException):
    user_message = "An settings error occurred."

class ModelRegistrationError(SettingsError):
    user_message = "Settings section could not be registered."

class ConfigValidationError(SettingsError):
    user_message = "Settings section could not be validated."

    def __init__(self, errors: Mapping[str, ValidationError]) -> None:
        self.errors = dict(errors)
        details = "\n".join(
            f"[{section}]\n{error}" for section, error in self.errors.items()
        )
        super().__init__(f"Invalid settings configuration:\n{details}")