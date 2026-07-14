from __future__ import annotations
import hashlib
import logging
import platform
import zipfile
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List

import requests

from .exception import HashMismatchException, DownloadException

DEFAULT_HASH_CHUNK_SIZE = 4096
DEFAULT_DOWNLOAD_CHUNK_SIZE = 4096
THREADED_DOWNLOAD_MAX_WORKERS = 10

logger = logging.getLogger("Launcher.CoreLib")

class FileObject:
    def __init__(self, path: Path, url=None, sha1=None, sha256=None, md5=None, size=None):
        self.__path = path

        self.expected_sha1 = sha1
        self.expected_sha256 = sha256
        self.expected_md5 = md5
        self.expected_size = size

        self.__sha1 = None
        self.__sha256 = None
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
    def md5(self):
        if self.__md5 is None:
            self.__md5 = self._calculate_hash("md5")

        return self.__md5

    def verify_sha1(self, expected_hash=None):
        return self.sha1 == expected_hash if expected_hash else self.expected_sha1 == self.sha1

    def verify_sha256(self, expected_hash=None):
        return self.sha256 == expected_hash if expected_hash else self.expected_sha256 == self.sha256

    def verify_md5(self, expected_hash=None):
        return self.sha1 == expected_hash if expected_hash else self.expected_sha1 == self.sha1

    def verify(self, algorithm, expected_hash=None):
        if algorithm == "sha1":
            return self.verify_sha1(expected_hash if expected_hash else self.expected_sha1)

        if algorithm == "sha256":
            return self.verify_sha256(expected_hash if expected_hash else self.expected_sha256)

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


def download_file(file: FileObject, overwrite=True, progress_callback: Callable[int]=None) -> FileObject | Exception:
    """
    Download file from url
    :param file: File (Objected)
    :param overwrite: Overwrite existing file
    :param progress_callback: Callback function called with progress information
    :return:
    """

    file.path.parent.mkdir(parents=True, exist_ok=True)

    if file.exists and not overwrite:
        raise FileExistsError("File {} already exists. Use overwrite=True to overwrite.".format(file))

    if file.url is None:
        raise ValueError("Target file {} URL cannot be None.".format(file))

    logger.debug("Downloading file {} to {}".format(file.url, file))

    try:
        with requests.get(file.url, stream=True) as r:
            current_chunk = 0
            total_bytes = r.headers.get("content-length", None)
            logger.debug("URL: {}".format(file.url))
            logger.debug("Response code: {}".format(r.status_code))

            with file.path.open("wb") as f:
                for chunk in r.iter_content(chunk_size=DEFAULT_DOWNLOAD_CHUNK_SIZE):
                    if not chunk:
                        break

                    f.write(chunk)
                    current_chunk += 1

                    if callable(progress_callback) and total_bytes is not None:
                        current_progress = ((current_chunk * DEFAULT_DOWNLOAD_CHUNK_SIZE) / int(total_bytes)) * 100
                        progress_callback(file.name, current_progress)
    except Exception as e:
        raise DownloadException(
            "An error occurred while downloading file {}. {}".format(file.url, e)
        )

    if file.expected_sha256 and not file.verify_sha256():
        raise HashMismatchException("sha256", file.sha256, file.expected_sha256, file.posix_path)
    elif file.expected_sha1 and not file.verify_sha1():
        raise HashMismatchException("sha1", file.sha1, file.expected_sha1, file.posix_path)
    elif file.expected_md5 and not file.verify_md5():
        raise HashMismatchException("md5", file.md5, file.expected_md5, file.posix_path)

    if any([file.expected_sha1, file.expected_md5, file.expected_sha256]):
        logger.debug("File hash is match as the expected hash.")
    else:
        logger.warning("File hash is not checked.")

    return file

def download_multiple_files(files: List[FileObject], download_callback: Callable[[str], None]=None,
                            max_workers=THREADED_DOWNLOAD_MAX_WORKERS, progress_callback: Callable[str]=None) \
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
        future_to_file = {executor.submit(download_file, file): file for file in files}

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

