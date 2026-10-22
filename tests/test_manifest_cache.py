import hashlib
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from core_lib.game import version_info
from core_lib.common.exception import VersionManifestSaveException
from manager.game import ManifestManager
from pages.test import TestPage as LauncherTestPage


@pytest.fixture
def cache(tmp_path):
    app = SimpleNamespace(work_dir=tmp_path, widget_manager=MagicMock(), logger=MagicMock())
    return ManifestManager(app)


def write_cache(cache, data, version=None):
    path = cache.switch_between_specific_path(version)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data).encode("utf-8")
    path.write_bytes(payload)
    return path, payload


def reply(cache, answer):
    def respond(request):
        request.result_queue.put(answer)
        request.wait_event.set()
    cache.widget_mgr.signal.askyesno.emit.side_effect = respond


@pytest.mark.parametrize("answer", [True, False])
def test_stale_root_requires_consent_and_only_one_final_notice(cache, monkeypatch, answer):
    data = {"versions": []}
    write_cache(cache, data)
    fetch = MagicMock(side_effect=OSError("offline"))
    monkeypatch.setattr("manager.game.fetch_and_save_version_manifest", fetch)
    reply(cache, answer)
    assert cache.get_cached_version_manifest(max_age=-1) == (data if answer else None)
    assert fetch.call_count == 3
    assert cache.use_expired_manifest is answer
    cache.widget_mgr.signal.askyesno.emit.assert_called_once()
    cache.widget_mgr.signal.show_error_message.emit.assert_not_called()
    assert cache.widget_mgr.signal.show_warning_message.emit.call_count == int(answer)
    if answer:
        assert cache.get_cached_version_manifest(max_age=-1) == data
        assert fetch.call_count == 3
        assert not ManifestManager(cache.app).use_expired_manifest


def test_timeout_does_not_enable_flag(cache, monkeypatch):
    write_cache(cache, {"versions": []})
    monkeypatch.setattr(cache, "_cache_version_manifest", lambda *args, **kwargs: (False, None))
    monkeypatch.setattr("manager.game.AskForRequest.wait", lambda *args: False)
    assert cache.get_cached_version_manifest(max_age=-1) is None
    assert not cache.use_expired_manifest


@pytest.mark.parametrize("payload", [None, b"{broken", b"[]", b"{}", b'{"versions":[{"id":"x"}]}'])
def test_unusable_root_never_asks_or_enables_flag(cache, monkeypatch, payload):
    if payload is not None:
        cache.version_manifest_path.parent.mkdir(parents=True)
        cache.version_manifest_path.write_bytes(payload)
    fetch = MagicMock(return_value=(False, None))
    monkeypatch.setattr(cache, "_cache_version_manifest", fetch)
    assert cache.get_cached_version_manifest(max_age=-1) is None
    assert fetch.call_count == 3
    assert not cache.use_expired_manifest
    cache.widget_mgr.signal.askyesno.emit.assert_not_called()
    cache.widget_mgr.signal.show_error_message.emit.assert_called_once()


@pytest.mark.parametrize("tampered", [False, True])
def test_specific_version_hash_is_checked_even_when_flag_enabled(cache, monkeypatch, tampered):
    data = {"id": "fixture", "mainClass": "Main"}
    path, payload = write_cache(cache, data, "fixture")
    write_cache(cache, {"versions": [{"id": "fixture", "url": "https://example.invalid",
                                    "sha1": hashlib.sha1(payload).hexdigest()}]})
    if tampered:
        path.write_text(json.dumps({**data, "mainClass": "Wrong"}), encoding="utf-8")
    cache.use_expired_manifest = True
    fetch = MagicMock(return_value=(False, None))
    monkeypatch.setattr(cache, "_cache_version_manifest", fetch)
    assert cache.get_cached_version_manifest("fixture", max_age=-1) == (None if tampered else data)
    assert fetch.call_count == (3 if tampered else 0)
    cache.widget_mgr.signal.askyesno.emit.assert_not_called()


def test_custom_manifest_shares_fallback_and_session_flag(cache):
    data = {"id": "loader", "inheritsFrom": "vanilla"}
    write_cache(cache, data, "loader")
    fetch = MagicMock(side_effect=OSError("offline"))
    reply(cache, True)
    assert cache.get_cached_custom_version_manifest("loader", fetch, max_age=-1) == data
    assert fetch.call_count == 3
    assert cache.get_cached_custom_version_manifest("loader", fetch, max_age=-1) == data
    assert fetch.call_count == 3


@pytest.mark.parametrize("payload,sha1", [(b"{broken", None), (b'{"id":"fixture"}', "0" * 40)])
def test_failed_save_preserves_original_and_cleans_temporary_files(tmp_path, payload, sha1):
    path = tmp_path / "manifest.json"
    path.write_bytes(b"previous content")
    with pytest.raises(VersionManifestSaveException):
        version_info.save_version_manifest(payload, path, sha1)
    assert path.read_bytes() == b"previous content"
    assert list(tmp_path.iterdir()) == [path]


def test_failed_download_verification_keeps_valid_specific_cache(cache, monkeypatch):
    data = {"id": "fixture", "mainClass": "Main"}
    path, payload = write_cache(cache, data, "fixture")
    root = {"versions": [{"id": "fixture", "url": "https://example.invalid",
                          "sha1": hashlib.sha1(payload).hexdigest()}]}
    write_cache(cache, root)
    fetched = MagicMock(return_value=(b'{"id":"fixture","mainClass":"Wrong"}', hashlib.sha1(payload).hexdigest()))
    monkeypatch.setattr(version_info, "fetch_specific_version_manifest", fetched)
    reply(cache, True)
    assert cache.get_cached_version_manifest("fixture", max_age=-1) == data
    assert fetched.call_count == 3
    assert path.read_bytes() == payload
    assert not list(path.parent.glob("*.tmp"))


def test_structurally_invalid_refresh_does_not_replace_cache(tmp_path, monkeypatch):
    path = tmp_path / "manifest.json"
    path.write_bytes(b"previous content")
    monkeypatch.setattr(version_info, "fetch_specific_version_manifest", lambda *args: (b"{}", None))
    with pytest.raises(ValueError):
        version_info.fetch_and_save_version_manifest(path, "fixture", {"versions": []})
    assert path.read_bytes() == b"previous content"


def test_successful_save_preserves_downloaded_bytes(tmp_path):
    payload = b'{ "id": "fixture", "mainClass": "Main" }'
    path = tmp_path / "manifest.json"
    assert version_info.save_version_manifest(payload, path, hashlib.sha1(payload).hexdigest())["id"] == "fixture"
    assert path.read_bytes() == payload
    assert list(tmp_path.iterdir()) == [path]


def test_test_page_fetch_runs_in_worker(monkeypatch):
    page = SimpleNamespace(button=MagicMock(), output=MagicMock(), get_selected_version=lambda: "fixture",
                           _fetch_version_data=MagicMock())
    worker = MagicMock()
    monkeypatch.setattr("pages.test.threading.Thread", worker)
    LauncherTestPage.run_test(page)
    worker.assert_called_once_with(target=page._fetch_version_data, args=("fixture",), daemon=True)
    worker.return_value.start.assert_called_once()
    page._fetch_version_data.assert_not_called()
