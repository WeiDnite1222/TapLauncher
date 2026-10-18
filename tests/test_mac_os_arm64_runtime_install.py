import logging
import sys
import tempfile
from pathlib import Path

from core_lib.common.exception import JavaRuntimeException
from core_lib.runtime.mojang import download_java_runtimes, get_support_runtime_manifest


def test_mac_os_runtime_install(tmp_path):
    destination = tmp_path / "java-runtime-epsilon"
    logger = logging.getLogger("Launcher.CoreLib")
    logger.setLevel(logging.DEBUG)
    print("Installing runtime...")

    component = "java-runtime-epsilon"

    download_java_runtimes(
        component,
        destination
    )

    executable_name = "java"
    candidates = sorted(destination.rglob(executable_name))

    print(f"{candidates=}")

    assert any(path.is_file() for path in candidates), (
        f"Installed runtime has no {executable_name}: {destination}"
    )
