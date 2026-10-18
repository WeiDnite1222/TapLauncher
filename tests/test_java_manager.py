from manager.game import JavaManager


def test_runtime_major_version_from_modern_version():
    assert JavaManager._runtime_major_version("21.0.8") == 21


def test_runtime_major_version_from_legacy_version():
    assert JavaManager._runtime_major_version("1.8.0_51") == 8
    assert JavaManager._runtime_major_version("8u51") == 8


def test_runtime_major_version_rejects_unknown_value():
    assert JavaManager._runtime_major_version(None) is None
    assert JavaManager._runtime_major_version("unknown") is None
