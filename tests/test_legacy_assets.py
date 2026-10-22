import hashlib
import json

import pytest

from core_lib.game import asset


@pytest.fixture
def legacy_assets(tmp_path, monkeypatch, request):
    kind = request.param
    assets_dir = tmp_path / "assets"
    content = b"legacy asset payload"
    digest = hashlib.sha1(content).hexdigest()
    source = assets_dir / "objects" / digest[:2] / digest
    source.parent.mkdir(parents=True)
    source.write_bytes(content)
    destination = (
        assets_dir / "virtual" / "fixture" / "sound.ogg"
        if kind == "virtual" else tmp_path / "resources" / "sound.ogg"
    )
    index_data = {kind: True, "objects": {"sound.ogg": {"hash": digest, "size": len(content)}}}
    index_bytes = json.dumps(index_data).encode("utf-8")
    index = assets_dir / "indexes" / "fixture.json"
    index.parent.mkdir(parents=True)
    index.write_bytes(index_bytes)
    manifest = {"assetIndex": {"id": "fixture", "sha1": hashlib.sha1(index_bytes).hexdigest()}}
    monkeypatch.setattr(asset, "find_useful_part_in_specific_version_manifest",
                        lambda value: (None, value["assetIndex"], None, None, None, None, None))

    def deny_network(*args, **kwargs):
        pytest.fail("Local legacy asset repair must not access the network")

    monkeypatch.setattr(asset.requests, "get", deny_network)
    return manifest, assets_dir, tmp_path, source, destination, content


@pytest.mark.parametrize("legacy_assets", ["virtual", "map_to_resources"], indirect=True)
def test_complete_legacy_assets_pass_without_network(legacy_assets):
    manifest, assets_dir, root, source, destination, content = legacy_assets
    destination.parent.mkdir(parents=True)
    destination.write_bytes(content)
    assert asset.check_assets_exist(manifest, assets_dir, root)
    assert asset.download_assets(manifest, assets_dir, root) == []


@pytest.mark.parametrize("legacy_assets", ["virtual", "map_to_resources"], indirect=True)
@pytest.mark.parametrize("damaged", [False, True])
def test_legacy_copy_repaired_from_objects_without_network(legacy_assets, damaged):
    manifest, assets_dir, root, source, destination, content = legacy_assets
    if damaged:
        destination.parent.mkdir(parents=True)
        # Same size, different content: the default check must verify SHA-1.
        destination.write_bytes(b"x" * len(content))
    assert not asset.check_assets_exist(manifest, assets_dir, root)
    assert asset.download_assets(manifest, assets_dir, root) == []
    assert destination.read_bytes() == content
    assert asset.check_assets_exist(manifest, assets_dir, root)


@pytest.mark.parametrize("legacy_assets", ["virtual", "map_to_resources"], indirect=True)
def test_missing_object_is_still_reported(legacy_assets):
    manifest, assets_dir, root, source, destination, content = legacy_assets
    destination.parent.mkdir(parents=True)
    destination.write_bytes(content)
    source.unlink()
    assert not asset.check_assets_exist(manifest, assets_dir, root)


@pytest.mark.parametrize("legacy_assets", ["virtual", "map_to_resources"], indirect=True)
def test_corrupt_cached_index_is_not_trusted(legacy_assets, monkeypatch):
    manifest, assets_dir, root, source, destination, content = legacy_assets
    index = assets_dir / "indexes" / "fixture.json"
    original = json.loads(index.read_text(encoding="utf-8"))
    index.write_text("{}", encoding="utf-8")
    fetched = []

    def fetch(version, path):
        fetched.append(path)
        return original

    monkeypatch.setattr(asset, "fetch_and_save_asset_manifest", fetch)
    assert asset.download_assets(manifest, assets_dir, root) == []
    assert fetched == [index]
    assert destination.read_bytes() == content
