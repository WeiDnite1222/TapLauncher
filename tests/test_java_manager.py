import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from core_lib.common.exception import JavaRuntimeException
from manager.game import JavaManager, JavaRuntime


@pytest.fixture
def java_manager(tmp_path):
    app = SimpleNamespace(
        work_dir=tmp_path,
        logger=logging.getLogger(__name__),
        widget_manager=SimpleNamespace(signal=SimpleNamespace(show_plain_error_text=Mock())),
    )
    return JavaManager(app)


def add_runtime(manager, name="java", *, source="custom", major=21):
    executable = Path(manager.app.work_dir) / name / "bin" / "java"
    executable.parent.mkdir(parents=True)
    executable.touch()
    runtime = JavaRuntime(name, major, str(major), executable, executable.parent.parent, source)
    manager.runtimes.append(runtime)
    return runtime


def test_runtime_major_version_from_modern_version():
    assert JavaManager._runtime_major_version("21.0.8") == 21


def test_runtime_major_version_from_legacy_version():
    assert JavaManager._runtime_major_version("1.8.0_51") == 8
    assert JavaManager._runtime_major_version("8u51") == 8


def test_runtime_major_version_rejects_unknown_value():
    assert JavaManager._runtime_major_version(None) is None
    assert JavaManager._runtime_major_version("unknown") is None


def test_runtime_list_tracks_removal_and_restoration(java_manager):
    runtime = add_runtime(java_manager)
    runtime.executable.unlink()
    assert not java_manager.list_runtimes()[0].valid
    runtime.executable.touch()
    assert java_manager.list_runtimes()[0].valid


@pytest.mark.parametrize("source", ["custom", "managed"])
def test_refresh_does_not_resolve_missing_retained_runtime(java_manager, monkeypatch, source):
    runtime = add_runtime(java_manager, source=source)
    runtime.executable.unlink()
    monkeypatch.setattr("manager.game.find_java_installations", lambda _: ([], []))
    assert java_manager.resolve_runtime(major_version=21) is None
    assert not java_manager.runtimes[0].valid
    # Availability is also correct after restarting the launcher.
    assert not JavaManager(java_manager.app).list_runtimes()[0].valid


def test_resolve_uses_available_runtime_when_managed_one_disappears(java_manager, monkeypatch):
    missing = add_runtime(java_manager, "managed", source="managed")
    available = add_runtime(java_manager, "custom")
    missing.executable.unlink()
    monkeypatch.setattr("manager.game.find_java_installations", lambda _: ([], []))
    assert java_manager.resolve_runtime(major_version=21).id == available.id


def test_directory_is_not_a_java_executable(java_manager):
    runtime = add_runtime(java_manager)
    runtime.executable.unlink()
    runtime.executable.mkdir()
    assert JavaManager.check_runtimes([runtime]) == [runtime]
    assert not java_manager.list_runtimes()[0].valid


def test_register_existing_runtime_rechecks_version_and_preserves_identity(java_manager, monkeypatch):
    runtime = add_runtime(java_manager, source="managed")
    monkeypatch.setattr("manager.game.get_java_version", lambda _: (25, "25.0.1"))
    updated = java_manager.register_runtime(runtime.executable)
    assert updated.major_version == 25
    assert updated.id == runtime.id
    assert updated.source == "managed"
    assert java_manager.list_runtimes() == [updated]


def test_register_existing_missing_runtime_is_rejected(java_manager):
    runtime = add_runtime(java_manager)
    runtime.executable.unlink()
    with pytest.raises(JavaRuntimeException):
        java_manager.register_runtime(runtime.executable)


def test_resolve_discovers_required_version_even_with_other_cached_runtimes(java_manager, monkeypatch):
    add_runtime(java_manager, "old", major=8)
    executable = Path(java_manager.app.work_dir) / "new-java"
    executable.touch()
    monkeypatch.setattr("manager.game.find_java_installations", lambda _: ([{
        "major": 21, "raw": "21.0.8", "executable": str(executable),
    }], []))
    assert java_manager.resolve_runtime(major_version=21).executable == executable


def test_legacy_selector_excludes_missing_runtimes(java_manager):
    runtime = add_runtime(java_manager)
    runtime.executable.unlink()
    assert java_manager.get_or_cache_jvm_settings() == []


@pytest.mark.parametrize("manifest", [{}, {"javaVersion": None}])
def test_legacy_manifest_resolves_java_8(java_manager, manifest):
    add_runtime(java_manager, "modern", major=21)
    legacy = add_runtime(java_manager, "legacy", major=8)
    assert java_manager.resolve_runtime(manifest=manifest) == legacy
    assert java_manager.ensure_runtime(manifest) == legacy


@pytest.mark.parametrize("manifest", [{}, {"javaVersion": None}])
def test_legacy_manifest_installs_java_8(java_manager, monkeypatch, manifest):
    monkeypatch.setattr("manager.game.find_java_installations", lambda _: ([], []))
    runtime = JavaRuntime("legacy", 8, "1.8.0", Path("java"), Path("jre"), "managed")
    install = Mock(return_value=runtime)
    monkeypatch.setattr(java_manager, "install_runtime", install)

    assert java_manager.ensure_runtime(manifest, auto_install=True) == runtime
    install.assert_called_once_with("jre-legacy", progress_callback=None, redownload_callback=None)


def test_resolve_without_requirement_returns_none(java_manager):
    add_runtime(java_manager, "legacy", major=8)
    assert java_manager.resolve_runtime() is None
