import zipfile

import pytest

from core_lib.game import argument, library_core
from core_lib.game.argument import ArgumentMappings, generate_launch_command


@pytest.fixture(autouse=True)
def windows_platform(monkeypatch):
    for module in (argument, library_core):
        monkeypatch.setattr(module, "get_natives_platform_info", lambda: ("windows", "windows", "x86_64"))
        monkeypatch.setattr(module, "get_platform_info", lambda: ("windows", "amd64", "10.0.26100"))


@pytest.mark.parametrize("path_argument, subdirectory", [
    (None, ""),
    ("-Djava.library.path=${natives_directory}", ""),
    ("-Djava.library.path=${natives_directory}/java", "java"),
    ({"value": ["-Djava.library.path=${natives_directory}/java"]}, "java"),
    ({"rules": [{"action": "allow", "os": {"name": "osx"}}],
      "value": "-Djava.library.path=${natives_directory}/java"}, ""),
])
def test_download_check_and_command_share_native_directory(tmp_path, monkeypatch, path_argument, subdirectory):
    libraries_dir = tmp_path / "libraries"
    natives_root = tmp_path / "natives"
    archive = libraries_dir / "native.jar"
    libraries_dir.mkdir()
    with zipfile.ZipFile(archive, "w") as jar:
        jar.writestr("windows/example.dll", b"native fixture")
        jar.writestr("META-INF/MANIFEST.MF", "excluded")

    manifest = {
        "assetIndex": {"id": "fixture"},
        "downloads": {"client": {}},
        "mainClass": "example.Main",
        "arguments": {"jvm": [] if path_argument is None else [path_argument], "game": ["--demo"]},
        "libraries": [{
            "name": "example:native:1:natives-windows",
            "downloads": {"artifact": {"path": "native.jar"}},
        }],
    }
    # Downloads are stubbed; native selection, extraction and checking use real code.
    monkeypatch.setattr(library_core, "collect_library_artifacts", lambda _: [])
    monkeypatch.setattr(library_core, "download_libraries", lambda *args, **kwargs: ([], []))

    assert not library_core.check_natives_exists(manifest, libraries_dir, natives_root)
    library_core.download_full_libraries(manifest, libraries_dir, natives_root)

    extract_dir = natives_root / subdirectory
    native_file = extract_dir / "example.dll"
    assert native_file.read_bytes() == b"native fixture"
    assert not (extract_dir / "META-INF").exists()
    assert not (natives_root / "java" / "java").exists()
    assert library_core.check_full_libraries_exists(manifest, libraries_dir, natives_root)

    command = generate_launch_command(
        ArgumentMappings(natives_directory=natives_root.as_posix(), classpath="client.jar"),
        "example.Main", "java", manifest["arguments"],
    )
    assert f"-Djava.library.path={extract_dir.as_posix()}" in command
    assert command[-2:] == ["example.Main", "--demo"]

    native_file.unlink()
    assert not library_core.check_natives_exists(manifest, libraries_dir, natives_root)


def test_feature_rules_and_last_applicable_property(tmp_path):
    manifest = {"arguments": {"jvm": [
        "-Djava.library.path=${natives_directory}",
        {"rules": [{"action": "allow", "features": {"new_layout": True}}],
         "value": "-Djava.library.path=${natives_directory}/java"},
    ]}}
    locate = library_core.locate_natives_extract_dir_by_manifest
    assert locate(manifest, tmp_path) == tmp_path
    assert locate(manifest, tmp_path, features={"new_layout": True}) == tmp_path / "java"
    assert locate({"minecraftArguments": "--demo"}, tmp_path) == tmp_path


@pytest.mark.parametrize("suffix", ["/../outside", "//absolute", "/C:/outside", "/java;other", "other"])
def test_unsupported_native_layout_is_rejected(tmp_path, suffix):
    with pytest.raises(ValueError):
        library_core.locate_natives_extract_dir(
            ["-Djava.library.path=${natives_directory}" + suffix], tmp_path,
        )
