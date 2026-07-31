import glob
import logging
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

from core_lib.common.exception import JavaRuntimeException, JavaRuntimeParseException

logger = logging.getLogger("Launcher.CoreLib")

def get_java_version(java_executable_path: str | Path) -> tuple[int, str]:
    """
    Get java version by executing `java -version`
    :param java_executable_path:
    :return:
    """
    if isinstance(java_executable_path, Path):
        java_executable_path = java_executable_path.as_posix()

    try:
        process = subprocess.run(
            [java_executable_path, "-version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
    except subprocess.TimeoutExpired:
        raise JavaRuntimeException(
            "Java runtime timed out.",
        )
    except subprocess.CalledProcessError as e:
        raise JavaRuntimeException(
            "Unable to run Java runtime: {}".format(e.stderr),
        )
    except Exception as e:
        raise JavaRuntimeException(
            "An error occurred while executing Java runtime: {}".format(e),
        )

    output = (process.stderr or "") + "\n" + (process.stdout or "")

    match = re.search(r'version "([^"]+)"', output)
    if not match:
        raise JavaRuntimeParseException(
            f"Unable to parse Java version:\n{output}"
        )

    raw_version = match.group(1)

    if raw_version.startswith("1."):
        major = int(raw_version.split(".")[1])
    else:
        major = int(raw_version.split(".")[0])

    return major, raw_version

def find_java_installations(extra_install_patterns: list | None=None) -> tuple[list[dict], list[Path]]:
    """
    Find Java installations
    :param extra_install_patterns:
    :return:
        installations: List[dict]
        errors: List[Path]
    """
    candidates_paths = []
    installations = []

    java_executable_name = "java.exe" if sys.platform == "win32" else "java"

    # Check (system) environment
    path_java = shutil.which("java")
    if path_java:
        candidates_paths.append(Path(path_java))

    java_home = os.environ.get("JAVA_HOME")
    if java_home:
        candidates_paths.append(Path(java_home) / "bin" / java_executable_name)

    system = platform.system().lower()

    if system == "windows":
        patterns = [
            r"C:\Program Files\Java\*\bin\java.exe",
            r"C:\Program Files\Eclipse Adoptium\*\bin\java.exe",
            r"C:\Program Files\Microsoft\jdk-*\bin\java.exe",
            r"C:\Program Files (x86)\Java\*\bin\java.exe",
        ]
    elif system == "darwin":
        patterns = [
            "/Library/Java/JavaVirtualMachines/*/Contents/Home/bin/java",
            "/System/Library/Java/JavaVirtualMachines/*/Contents/Home/bin/java",
            "/opt/homebrew/opt/openjdk*/bin/java",
            "/usr/local/opt/openjdk*/bin/java",
            "/Applications/*/Contents/jbr/Contents/Home/bin/java",
        ]

    else:
        patterns = [
            "/usr/bin/java",
            "/bin/java",
            "/usr/local/bin/java",
            "/usr/lib/jvm/*/bin/java",
            "/opt/java/*/bin/java",
            "/opt/jdk*/bin/java",
            "/snap/*/current/bin/java",
        ]

    if isinstance(extra_install_patterns, list):
        patterns.extend(extra_install_patterns)

    for pattern in patterns:
        candidates_paths.extend(Path(p) for p in glob.glob(pattern))

    seen = set()
    errors = []

    for candidate_path in candidates_paths:
        try:
            converted_path = candidate_path.resolve().absolute()
        except OSError:
            continue

        if converted_path in seen:
            continue

        ver = None
        raw = None

        try:
            ver, raw = get_java_version(converted_path)
        except JavaRuntimeParseException:
            logger.debug(f"Unable to parse java version: {converted_path}")
        except JavaRuntimeException:
            logger.debug(f"Unable to run java executable: {converted_path}")
        except Exception as e:
            logger.exception(f"Unhandled exception: {e} (For path: {converted_path})")

        if not ver:
            errors.append(converted_path)
            continue

        logger.debug(f"Detected java version {ver} for path: {converted_path}")

        installations.append(
            {
                "major": ver,
                "raw": raw,
                "homeDir": converted_path.parent.parent.as_posix(),
                "executable": converted_path.as_posix(),
            }
        )

    installations.sort(key=lambda item: item["major"], reverse=True)

    return installations, errors