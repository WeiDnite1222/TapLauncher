import hashlib
import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List

import requests

from core_lib.common.exception import HashMismatchException

DEFAULT_HASH_CHUNK_SIZE = 4096
DEFAULT_DOWNLOAD_CHUNK_SIZE = 4096
THREADED_DOWNLOAD_MAX_WORKERS = 10

logger = logging.getLogger("Launcher.CoreLib")

class FileObject:
    def __init__(self, path: Path, url=None, sha1=None, sha256=None, md5=None):
        self.__path = path

        self.expected_sha1 = sha1
        self.expected_sha256 = sha256
        self.expected_md5 = md5

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

        raise Exception("Unsupported algorithm: {}".format(algorithm))

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


def download_file(file: FileObject, overwrite=True) -> FileObject | Exception:
    """
    Download file from url
    :param file: File (Objected)
    :param overwrite: Overwrite existing file
    :return:
    """

    file.path.parent.mkdir(parents=True, exist_ok=True)

    if file.exists and not overwrite:
        raise Exception("File {} already exists. Use overwrite=True to overwrite.".format(file))

    if file.url is None:
        raise Exception("Target file {} URL cannot be None.".format(file))

    logger.debug("Downloading file {} to {}".format(file.url, file))

    with requests.get(file.url, stream=True) as r:
        logger.debug("URL: {}".format(file.url))
        logger.debug("Response code: {}".format(r.status_code))

        with file.path.open("wb") as f:
            for chunk in r.iter_content(chunk_size=DEFAULT_DOWNLOAD_CHUNK_SIZE):
                if not chunk:
                    break

                f.write(chunk)

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

def download_multiple_files(files: List[FileObject], download_callback: Callable[str]=None,
                            max_workers=THREADED_DOWNLOAD_MAX_WORKERS) \
        -> List[FileObject]:
    """
    Download multiple files
    :param download_callback:
    :param files:
    :param max_workers:
    :return: List of file objects that download failed.
    """

    fails = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_file = {executor.submit(download_file, file): file for file in files}

        for future in as_completed(future_to_file):
            file = future_to_file[future]

            try:
                future.result()
                if callable(download_callback):
                    download_callback(file.posix_path)
            except Exception as exc:
                logger.error("Unable to download file {}: {}".format(file.posix_path, exc))
                fails.append(file)

    return fails

