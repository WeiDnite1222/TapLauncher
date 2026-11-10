from __future__ import annotations

import base64
import copy
import hashlib
import logging
import os
import platform
import random
import string
import zipfile
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List, Type, Literal

import requests

from .exception import HashMismatchException, DownloadException

DEFAULT_HASH_CHUNK_SIZE = 4096
DEFAULT_DOWNLOAD_CHUNK_SIZE = 4096
THREADED_DOWNLOAD_MAX_WORKERS = 10

logger = logging.getLogger("Launcher.CoreLib")

SUPPORTED_HASH_ALGORITHMS = ["sha1", "sha256", "sha512", "md5"]

class FileObject:
    def __init__(self, path: Path, url=None, sha1=None, sha256=None, sha512=None, md5=None, size=None):
        self.__path = path

        self.expected_sha1 = sha1
        self.expected_sha256 = sha256
        self.expected_sha512 = sha512
        self.expected_md5 = md5
        self.expected_size = size

        self.__sha1 = None
        self.__sha256 = None
        self.__sha512 = None
        self.__md5 = None

        self.url = url

    def __eq__(self, other):
        """
        THIS OPERATION ONLY COMPARE AND FILE SIZE! Use
        :param other:
        :return:
        """
        if self.path == other.path:
            return True

        if self.size == other.size:
            return True

        return False

    def replace_path(self, path: Path):
        """
        Replace the target file path
        This operation will invalidate the hash cache
        :param path:
        :return:
        """
        self.__path = path
        self.invalidate_hash_cache()

    def is_same(self, file: FileObject, hash_name="sha256") -> bool:
        if hash_name == "sha1":
            return self.sha1 == file.sha1

        if hash_name == "md5":
            return self.md5 == file.md5

        if hash_name != "sha256":
            logger.warning("Unsupported hash_name {}. Ignored and use sha256 instead.".format(hash_name))

        return self.sha256 == file.sha256

    @property
    def sha1(self):
        if self.__sha1 is None:
            self.__sha1 = self._calculate_hash("sha1")

        return self.__sha1

    @property
    def sha256(self):
        if self.__sha256 is None:
            self.__sha256 = self._calculate_hash("sha256")

        return self.__sha256

    @property
    def sha512(self):
        if self.__sha512 is None:
            self.__sha512 = self._calculate_hash("sha512")

        return self.__sha512

    @property
    def md5(self):
        if self.__md5 is None:
            self.__md5 = self._calculate_hash("md5")

        return self.__md5

    def verify_sha1(self, expected_hash=None):
        return self.sha1 == expected_hash if expected_hash else self.expected_sha1 == self.sha1

    def verify_sha256(self, expected_hash=None):
        return self.sha256 == expected_hash if expected_hash else self.expected_sha256 == self.sha256

    def verify_sha512(self, expected_hash=None):
        return self.sha512 == expected_hash if expected_hash else self.expected_sha512 == self.sha512

    def verify_md5(self, expected_hash=None):
        return self.md5 == expected_hash if expected_hash else self.expected_md5 == self.md5

    def verify(self, algorithm: Literal["sha1", "sha256", "sha512", "md5"], expected_hash=None):
        if algorithm == "sha1":
            return self.verify_sha1(expected_hash if expected_hash else self.expected_sha1)

        if algorithm == "sha256":
            return self.verify_sha256(expected_hash if expected_hash else self.expected_sha256)

        if algorithm == "sha512":
            return self.verify_sha512(expected_hash if expected_hash else self.expected_sha512)

        if algorithm == "md5":
            return self.verify_md5(expected_hash if expected_hash else self.expected_md5)

        if algorithm == "size":
            return self.verify_size(expected_hash if expected_hash else self.expected_size)

        raise Exception("Unsupported algorithm: {}".format(algorithm))

    def verify_size(self, expected_size):
        return self.size == expected_size if expected_size else self.expected_size == self.size

    def _calculate_hash(self, algorithm):
        h = hashlib.new(algorithm)

        with self.__path.open("rb") as f:
            for chunk in iter(lambda: f.read(DEFAULT_HASH_CHUNK_SIZE), b""):
                h.update(chunk)

        return h.hexdigest()

    @property
    def path(self):
        return self.__path

    @property
    def posix_path(self):
        return self.__path.absolute().as_posix()

    @property
    def size(self):
        return self.__path.stat().st_size

    @property
    def name(self):
        return self.__path.name

    @property
    def extension(self):
        return self.__path.suffix

    def __hash__(self):
        return hash(self.__path)

    @property
    def exists(self):
        return self.__path.exists()

    def invalidate_hash_cache(self):
        self.__sha1 = None
        self.__sha256 = None
        self.__sha512 = None
        self.__md5 = None

def generate_random_suffix():
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=8))

def download_file(file: FileObject, overwrite=True, progress_callback: Callable[int]=None,
                  safe_download=True, max_temp_suffix_retry=5,
                  *, timeout=5, verify_hash=True) -> FileObject | Exception:
    """
    Download the file from url
    :param file: File (Objected)
    :param overwrite: Overwrites existing file
    :param progress_callback: Callback function called with progress information
    :param safe_download: Download the file at temp location. If hash matches, Replace the old one with the new one
    :param max_temp_suffix_retry: Maximum number of retries for generating a unique temp file suffix
    :param timeout: Timeout for the download request
    :return:
    """

    def gen_random(path: Path):
        suffix = generate_random_suffix()
        new = path.with_suffix(path.suffix + "." + suffix)

        if new.exists():
            raise Exception("File already exists")

        return new

    if safe_download:
        temp_path: Path | None = attempt(lambda: gen_random(file.path), Exception, max_temp_suffix_retry, logger)

        if not temp_path:
            raise DownloadException("Failed to generate unique temp file suffix")

        target_file = copy.copy(file)
        target_file.replace_path(temp_path)
    else:
        target_file = file

    target_file.path.parent.mkdir(parents=True, exist_ok=True)

    if file.exists and not overwrite:
        raise FileExistsError("File {} already exists. Use overwrite=True to overwrite.".format(target_file))

    if target_file.url is None:
        raise ValueError("Target file {} URL cannot be None.".format(target_file))

    logger.debug("Downloading file {} to {}".format(target_file.url, target_file))

    try:
        target_file.invalidate_hash_cache()  # Clean cache hash
        try:
            with requests.get(target_file.url, stream=True, timeout=timeout) as r:
                r.raise_for_status()
                current_chunk = 0
                total_bytes = r.headers.get("content-length", None)
                logger.debug("URL: {}".format(target_file.url))
                logger.debug("Response code: {}".format(r.status_code))

                with target_file.path.open("wb") as f:
                    for chunk in r.iter_content(chunk_size=DEFAULT_DOWNLOAD_CHUNK_SIZE):
                        if not chunk:
                            break

                        f.write(chunk)
                        current_chunk += 1

                        if callable(progress_callback) and total_bytes is not None:
                            current_progress = ((current_chunk * DEFAULT_DOWNLOAD_CHUNK_SIZE) / int(total_bytes)) * 100
                            progress_callback(target_file.name, current_progress)
        except Exception as e:
            raise DownloadException(
                "An error occurred while downloading file {}. {}".format(target_file.url, e)
            )
        finally:
            target_file.invalidate_hash_cache()

        if verify_hash and target_file.expected_sha256 and not target_file.verify_sha256():
            raise HashMismatchException("sha256", target_file.sha256, target_file.expected_sha256,
                                        target_file.posix_path)
        elif verify_hash and target_file.expected_sha1 and not target_file.verify_sha1():
            raise HashMismatchException("sha1", target_file.sha1, target_file.expected_sha1, target_file.posix_path)
        elif verify_hash and target_file.expected_md5 and not target_file.verify_md5():
            raise HashMismatchException("md5", target_file.md5, target_file.expected_md5, target_file.posix_path)
        elif verify_hash and target_file.expected_sha512 and not target_file.verify_sha512():
            raise HashMismatchException("sha512", target_file.sha512, target_file.expected_sha512,
                                        target_file.posix_path)

        if verify_hash and any([target_file.expected_sha1, target_file.expected_md5, target_file.expected_sha256, target_file.expected_sha512]):
            logger.debug("File hash is match as the expected hash.")
        else:
            logger.warning("Hash is not checked for file: {}".format(target_file.posix_path))

        if safe_download:
            try:
                os.replace(target_file.path, file.path)
            except Exception as e:
                logger.error(f"Failed to replace file: {target_file.posix_path}. Error: {str(e)}")

                if target_file.exists:
                    try:
                        os.remove(target_file.path)
                    except Exception as second_exc:
                        logger.error(f"Failed to remove temp file: {target_file.posix_path}. Error: {str(second_exc)}")

                raise DownloadException(f"Failed to replace temp file {target_file.path} as {file.path}")
    finally:
        # Cleanup
        file.invalidate_hash_cache()

        if safe_download:
            try:
                target_file.path.unlink(missing_ok=True)
            except OSError as exc:
                logger.warning("Unable to remove temporary download: %s", exc)

    return file

def download_multiple_files(files: List[FileObject], download_callback: Callable[[str], None]=None,
                            max_workers=THREADED_DOWNLOAD_MAX_WORKERS, progress_callback: Callable[str]=None, *, verify_hash=True) \
        -> tuple[list[FileObject], list[FileObject]]:
    """
    Download multiple files
    :param download_callback:
    :param files:
    :param max_workers:
    :param progress_callback:
    :return:
        fails: List of file objects that download failed.
        successes: List of file objects that download succeeded.
    """

    fails = []
    successes = []

    files_count = 0
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_file = {executor.submit(download_file, file, verify_hash=verify_hash): file for file in files}

        for future in as_completed(future_to_file):
            file = future_to_file[future]

            try:
                files_count += 1
                future.result()
                successes.append(file)
                if callable(download_callback):
                    download_callback(file.posix_path)

                if callable(progress_callback):
                    progress_callback(f"{len(files)} Files", files_count / len(files) * 100)
            except Exception as exc:
                logger.error("Unable to download file {}: {}".format(file.posix_path, exc))
                fails.append(file)


    return fails, successes

def unzip(filepath: Path, destination: Path, exclude: list[str] | None = None, flatten: bool=False):
    exclude = exclude or []

    with zipfile.ZipFile(filepath.as_posix(), "r") as archive:
        for member in archive.namelist():
            # Ignore exclude file.
            if any(member.startswith(pattern) for pattern in exclude):
                continue

            if flatten:
                member_path = Path(member)

                if member.endswith("/") or not member_path.name:
                    continue

                if any(member.startswith(pattern) for pattern in exclude):
                    continue

                target = destination / member_path.name

                with archive.open(member) as source:
                    with target.open("wb") as output:
                        output.write(source.read())
            else:
                archive.extract(member, path=destination)

def get_platform_info():
    """
    Get information about the current platform.
    IMPORTANT: All return values are lower-case
    :return:
        platform_name: str, architecture: str, os_version: str
    """
    platform_name = platform.system().lower()
    arch = platform.uname().machine.lower()
    os_version = platform.version()

    if platform_name == "darwin":
        os_version = platform.mac_ver()[0]
    elif platform_name == "linux":
        os_version = platform.release()

    return platform_name, arch, os_version

def is_valid_zipfile(path: Path) -> bool:
    try:
        return zipfile.is_zipfile(path)
    except OSError:
        return False

def bytes_to_data_url(image_data: bytes,  mime_type: str = "image/png",) -> str:
    """
    Convert raw image bytes to a Base64 Data URL.
    :param image_data:
    :param mime_type:
    :return:
        data_url: str
    """
    if not isinstance(image_data, bytes):
        raise TypeError("image_data must be bytes")

    if not image_data:
        raise ValueError("image_data cannot be empty")

    if not isinstance(mime_type, str) or not mime_type.startswith("image/"):
        raise ValueError("mime_type must be a valid image MIME type")

    encoded = base64.b64encode(image_data).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"

def attempt(function: Callable, exceptions: Type[Exception],
            retry: int = 10, logger_obj: logging.Logger | None = None):
    """
    Attempt to execute a function with retries and logging.
    :param function: The function to attempt. It should throw the specified exception that has written in exceptions
    if failed.
    :param exceptions: The exception type to catch.
    :param retry: The number of retries.
    :param logger_obj: The logger object for logging.
    :return: The result of the function if successful, None otherwise.
    """
    def log_info(message):
        if logger_obj:
            logger_obj.info(message)
        else:
            print("INFO: {}".format(message))

    def log_error(message):
        if logger_obj:
            logger_obj.error(message)
        else:
            print("ERROR: {}".format(message))

    for i in range(1, retry+1):
        if i > 1:
            log_info(f"Attempt {i-1} failed. Retrying...")

        try:
            return function()
        except exceptions as e:
            log_error(f"Attempt {i} failed: {e}")

    return None
