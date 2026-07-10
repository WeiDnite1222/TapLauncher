from pathlib import Path


class LauncherException(Exception):
    def __init__(self, message):
        self.message = message

    def __str__(self):
        return self.message

class HashMismatchException(Exception):
    def __init__(self, hash_name, got_hash, expected_hash, filepath: str | Path):
        if type(filepath) == Path: filepath = Path(filepath).absolute().as_posix()
        self.message = "File {} hash mismatch. Expected hash {}. Got hash {} ({})".format(filepath, got_hash,
                                                                                          expected_hash, hash_name)
