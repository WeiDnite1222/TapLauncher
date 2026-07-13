from pathlib import Path


class LauncherException(Exception):
    user_message = "Launcher error occurred."

    def __init__(self, message=None, *, user_message=None):
        super().__init__(message or user_message or self.user_message)
        if user_message is not None:
            self.user_message = user_message

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