import sys
from types import SimpleNamespace, ModuleType
from importlib.machinery import ModuleSpec
from unittest.mock import Mock

import pytest

from manager.plugins import PluginManager
from manager.settings import SettingsManager
from manager.settings_models import PluginSettings
from manager.widgets import WidgetManager


@pytest.fixture
def plugin_manager(tmp_path):
    settings = SettingsManager(tmp_path.parent / (tmp_path.name + "-settings.toml"))
    settings.register("plugins", PluginSettings)
    settings.load_defaults()
    widget_manager = WidgetManager()
    messages = []
    contexts = []
    widget_manager.signal.show_and_print_error_message.connect(contexts.append)
    widget_manager.signal.show_and_print_error_message.connect(lambda context: messages.append(context["message"]))
    app = SimpleNamespace(
        plugins_dir=tmp_path,
        data_dir=tmp_path.parent / (tmp_path.name + "-data"),
        aboutToQuit=Mock(),
        internal_plugins_dir=tmp_path.parent / (tmp_path.name + "-builtin"),
        widget_manager=widget_manager,
        logger=Mock(),
        error_contexts=contexts,
        settings_manager=settings,
    )
    previous_modules = set(sys.modules)
    manager = PluginManager(app)
    yield manager, messages
    manager.shutdown_plugins()
    for name in set(sys.modules) - previous_modules:
        if name.startswith("_wheel_plugin_"):
            sys.modules.pop(name, None)


def write_plugin(path, **values):
    path.mkdir(exist_ok=True)
    config = dict(
        group="net.test", id="sample", name="Sample", version="1.0.0",
        api_version=">=0.0.1", entrypoint="main.py:entry",
    )
    config.update(values)
    (path / "plugin.toml").write_text(
        "\n".join(f'{key} = {value!r}' for key, value in config.items()),
        encoding="utf-8",
    )
    (path / "main.py").write_text("def entry(context):\n    pass\n", encoding="utf-8")


def test_load_plugins_continues_after_error_and_reloads(plugin_manager):
    manager, messages = plugin_manager
    invalid = manager.app.plugins_dir / "invalid"
    invalid.mkdir()
    write_plugin(manager.app.plugins_dir / "valid")

    manager.load_plugins()

    assert [plugin.id for plugin in manager.plugins] == ["sample"]
    assert len(messages) == 1
    assert str(invalid) in messages[0]
    manager.app.logger.error.assert_not_called()
    assert len(manager.app.error_contexts) == 1

    manager.load_plugins()

    assert len(manager.plugins) == 1


@pytest.mark.parametrize("values, error", [
    ({"version": "1.0.0junk"}, "Plugin version is invalid"),
    ({"group": 123}, "Plugin group must be a string"),
    ({"icon": 123}, "Plugin icon must be a string"),
    ({"api_version": "invalid"}, "version range is invalid"),
    ({"api_version": ">=999.0.0"}, "does not support"),
    ({"entrypoint": "missing.py:entry"}, "Python file"),
    ({"entrypoint": "main.py:missing"}, "does not exist in file"),
    ({"entrypoint": "main.py:"}, "valid identifier"),
    ({"entrypoint": "..:main.py:entry"}, "Invalid path part"),
    ({"entrypoint": "main.py"}, "At least two parts"),
])
def test_invalid_config_emits_error(plugin_manager, values, error):
    manager, messages = plugin_manager
    plugin_dir = manager.app.plugins_dir / "sample"
    write_plugin(plugin_dir, **values)

    assert manager._load_plugin_config(plugin_dir) is None
    assert len(messages) == 1
    assert str(plugin_dir / "plugin.toml") in messages[0]
    assert error in messages[0]


def test_nested_entrypoint(plugin_manager):
    manager, messages = plugin_manager
    plugin_dir = manager.app.plugins_dir / "sample"
    write_plugin(plugin_dir, entrypoint="nested:main.py:entry")
    (plugin_dir / "nested").mkdir()
    (plugin_dir / "main.py").rename(plugin_dir / "nested" / "main.py")

    assert manager._load_plugin_config(plugin_dir) is not None
    assert messages == []


def test_invalid_toml_emits_error(plugin_manager):
    manager, messages = plugin_manager
    (manager.app.plugins_dir / "plugin.toml").write_text("id = [", encoding="utf-8")

    assert manager._load_plugin_config(manager.app.plugins_dir) is None
    assert len(messages) == 1
    assert "Failed to load plugin config" in messages[0]


def test_missing_plugins_directory_is_empty(plugin_manager):
    manager, messages = plugin_manager
    manager.app.plugins_dir /= "missing"

    manager.load_plugins()

    assert manager.plugins == []
    assert messages == []


def test_plugins_directory_error_emits_error(plugin_manager):
    manager, messages = plugin_manager
    manager.app.plugins_dir /= "file"
    manager.app.plugins_dir.write_text("", encoding="utf-8")

    manager.load_plugins()

    assert len(messages) == 1
    assert str(manager.app.plugins_dir) in messages[0]


@pytest.mark.parametrize("filename", ["main.py", "__init__.py"])
def test_endpoint_returns_spec_without_executing_plugin(plugin_manager, filename):
    manager, messages = plugin_manager
    plugin_dir = manager.app.plugins_dir / "sample"
    write_plugin(plugin_dir, entrypoint=f"{filename}:entry")
    source = plugin_dir / filename
    source.write_text(
        'raise RuntimeError("Must not execute during validation")\n'
        'def entry(context):\n    pass\n',
        encoding="utf-8",
    )

    plugin = manager._load_plugin_config(plugin_dir)

    assert plugin is not None
    assert isinstance(plugin.module_spec, ModuleSpec)
    assert plugin.module_spec.origin == str(source.resolve())
    assert plugin.module_spec.loader is not None
    if filename == "__init__.py":
        assert plugin.module_spec.submodule_search_locations == [str(plugin_dir.resolve())]
    assert messages == []


def test_specs_for_same_filename_in_different_plugins_have_distinct_names(plugin_manager):
    manager, _ = plugin_manager
    specs = []
    for name in ("first", "second"):
        plugin_dir = manager.app.plugins_dir / name
        write_plugin(plugin_dir)
        specs.append(manager._check_and_return_plugin_endpoint_spec("main.py:entry", plugin_dir))

    assert specs[0].name != specs[1].name


def test_init_registers_spec_name_and_supports_relative_imports(plugin_manager):
    manager, messages = plugin_manager
    plugin_dir = manager.app.plugins_dir / "sample"
    write_plugin(plugin_dir, entrypoint="__init__.py:entry")
    (plugin_dir / "__init__.py").write_text(
        "from .helper import value\ndef entry(context):\n    return value\n",
        encoding="utf-8",
    )
    (plugin_dir / "helper.py").write_text("value = 42\n", encoding="utf-8")
    plugin = manager._load_plugin_config(plugin_dir)
    assert plugin is not None
    assert plugin.module_spec is not None

    assert manager._init_plugin_entry(plugin)
    module = sys.modules[plugin.module_spec.name]
    assert module.entry({}) == 42
    assert module.__name__ == plugin.module_spec.name
    assert messages == []


@pytest.mark.parametrize("source, error", [
    ('raise RuntimeError("broken plugin")\n', "broken plugin"),
    ('raise SystemExit("plugin exit")\n', "plugin exit"),
    ('entry = None\n', "not callable"),
    ('del entry\n', "missing"),
])
def test_init_failure_reports_once_and_cleans_module(plugin_manager, source, error):
    manager, messages = plugin_manager
    plugin_dir = manager.app.plugins_dir / "sample"
    write_plugin(plugin_dir)
    plugin = manager._load_plugin_config(plugin_dir)
    assert plugin is not None
    assert plugin.module_spec is not None
    (plugin_dir / "main.py").write_text(
        "def entry(context):\n    pass\n" + source, encoding="utf-8",
    )

    assert not manager._init_plugin_entry(plugin)
    assert plugin.module_spec.name not in sys.modules
    assert len(messages) == 1
    assert plugin.id in messages[0]
    assert error in messages[0]
    context = manager.app.error_contexts[0]
    assert context["title"] == "Plugin Error"
    assert "Traceback" in context["error"]
    if source.startswith("raise "):
        assert str(plugin_dir / "main.py") in context["error"]


@pytest.mark.parametrize("missing_loader", [False, True])
def test_init_missing_spec_or_loader_reports_error(plugin_manager, missing_loader):
    manager, messages = plugin_manager
    plugin_dir = manager.app.plugins_dir / "sample"
    write_plugin(plugin_dir)
    plugin = manager._load_plugin_config(plugin_dir)
    assert plugin is not None
    assert plugin.module_spec is not None
    if missing_loader:
        plugin.module_spec.loader = None
    else:
        plugin.module_spec = None

    assert not manager._init_plugin_entry(plugin)
    assert len(messages) == 1
    assert "Module spec or loader is missing" in messages[0]


def test_failed_reload_restores_modules(plugin_manager, monkeypatch):
    manager, messages = plugin_manager
    plugin_dir = manager.app.plugins_dir / "sample"
    write_plugin(plugin_dir, entrypoint="__init__.py:entry")
    (plugin_dir / "__init__.py").write_text(
        'from . import helper\nraise RuntimeError("broken reload")\n'
        'def entry(context):\n    pass\n', encoding="utf-8",
    )
    (plugin_dir / "helper.py").write_text("value = 42\n", encoding="utf-8")
    plugin = manager._load_plugin_config(plugin_dir)
    assert plugin is not None
    assert plugin.module_spec is not None
    previous = ModuleType(plugin.module_spec.name)
    monkeypatch.setitem(sys.modules, plugin.module_spec.name, previous)

    assert not manager._init_plugin_entry(plugin)
    assert sys.modules[plugin.module_spec.name] is previous
    assert plugin.module_spec.name + ".helper" not in sys.modules
    assert len(messages) == 1


def test_load_skips_failed_initialization_and_continues(plugin_manager):
    manager, messages = plugin_manager
    write_plugin(manager.app.plugins_dir / "valid")
    broken_dir = manager.app.plugins_dir / "broken"
    write_plugin(broken_dir, id="broken")
    (broken_dir / "main.py").write_text(
        'raise RuntimeError("broken plugin")\ndef entry(context):\n    pass\n',
        encoding="utf-8",
    )

    manager.load_plugins()

    assert [plugin.id for plugin in manager.plugins] == ["sample"]
    assert len(messages) == 1
    assert "broken plugin" in messages[0]


def test_incompatible_api_range_is_valid(plugin_manager):
    manager, _ = plugin_manager

    valid, supported, required = manager._check_plugin_support_api_version(">=999.0.0")

    assert valid
    assert not supported
    assert str(required) == ">=999.0.0"


@pytest.mark.parametrize("user_plugins", ["missing", "empty", "installed"])
def test_load_preserves_builtin_plugins(plugin_manager, user_plugins):
    manager, messages = plugin_manager
    root = manager.app.plugins_dir
    manager.app.internal_plugins_dir = root / "builtin"
    manager.app.plugins_dir = root / "user"
    manager.app.internal_plugins_dir.mkdir()
    write_plugin(manager.app.internal_plugins_dir / "internal", id="internal")
    if user_plugins != "missing":
        manager.app.plugins_dir.mkdir()
    if user_plugins == "installed":
        write_plugin(manager.app.plugins_dir / "external", id="external")
    completed = []
    manager.signals.plugins_loaded.connect(lambda: completed.append(True))

    manager.load_plugins()

    expected = ["internal", "external"] if user_plugins == "installed" else ["internal"]
    assert [plugin.id for plugin in manager.plugins] == expected
    assert completed == [True]
    assert messages == []
    manager.load_plugins()
    assert [plugin.id for plugin in manager.plugins] == expected


@pytest.mark.parametrize("filename", ["icon.gif", "icon.png", "icon.jpg", "icon.bmp", "ICON.PNG", "icon.jpeg"])
def test_custom_icon_path_is_relative_to_plugin(plugin_manager, filename):
    manager, messages = plugin_manager
    plugin_dir = manager.app.plugins_dir / "sample"
    write_plugin(plugin_dir, icon=f"images/{filename}")
    (plugin_dir / "images").mkdir()
    path = plugin_dir / "images" / filename
    path.write_bytes(b"image validation happens in the UI")

    plugin = manager._load_plugin_config(plugin_dir)

    assert plugin is not None
    assert plugin.icon_path == path.resolve()
    assert messages == []


@pytest.mark.parametrize("icon", ["", "missing.png", "icon.txt", "../outside.png"])
def test_invalid_optional_icon_keeps_plugin_loadable(plugin_manager, icon):
    manager, messages = plugin_manager
    plugin_dir = manager.app.plugins_dir / "sample"
    write_plugin(plugin_dir, icon=icon)
    (plugin_dir / "icon.txt").write_text("not an image", encoding="utf-8")
    (manager.app.plugins_dir / "outside.png").write_bytes(b"outside plugin")

    plugin = manager._load_plugin_config(plugin_dir)

    assert plugin is not None
    assert plugin.icon_path is None
    assert messages == []


@pytest.fixture
def loaded_plugin(plugin_manager):
    manager, _ = plugin_manager
    plugin_dir = manager.app.plugins_dir / "sample"
    write_plugin(plugin_dir)
    manager.load_plugins()
    return manager.plugins[0]


def test_enable_provides_context_and_runs_entry_once(plugin_manager, loaded_plugin):
    manager, messages = plugin_manager
    plugin = loaded_plugin
    entry = Mock()
    plugin.entry = entry

    assert manager.enable_plugin(plugin)
    assert manager.enable_plugin(plugin)

    entry.assert_called_once()
    context = entry.call_args.args[0]
    assert context.plugin_id == "net.test:sample"
    assert context.plugin_dir == plugin.path
    assert context.data_dir == (manager.app.data_dir / "plugins/net.test/sample").resolve()
    assert context.data_dir.is_dir()
    manager.app.logger.getChild.assert_called_once_with("plugins.net.test.sample")
    info = []
    manager.widget_manager.signal.show_info_message.connect(info.append)
    context.show_info("hello")
    context.show_error("problem")
    assert info == ["[net.test:sample] hello"]
    assert messages == ["[net.test:sample] problem"]
    assert plugin.enabled


def test_disable_runs_cleanup_in_reverse_order_once(plugin_manager, loaded_plugin):
    manager, messages = plugin_manager
    calls = []
    def entry(context):
        context.on_cleanup(lambda: calls.append("first"))
        context.on_cleanup(lambda: calls.append("second"))
    loaded_plugin.entry = entry

    assert manager.enable_plugin(loaded_plugin)
    assert manager.disable_plugin(loaded_plugin)
    assert manager.disable_plugin(loaded_plugin)

    assert calls == ["second", "first"]
    assert not loaded_plugin.enabled
    assert messages == []


@pytest.mark.parametrize("error", [RuntimeError("entry failed"), SystemExit("entry exited")])
def test_entry_failure_cleans_partial_initialization(plugin_manager, loaded_plugin, error):
    manager, messages = plugin_manager
    cleanup = Mock()
    def entry(context):
        context.on_cleanup(cleanup)
        raise error
    loaded_plugin.entry = entry

    assert not manager.enable_plugin(loaded_plugin)

    cleanup.assert_called_once()
    assert not loaded_plugin.enabled
    assert not loaded_plugin._changing_state
    assert len(messages) == 1
    assert str(error) in messages[0]
    assert "Traceback" in manager.app.error_contexts[0]["error"]


def test_cleanup_failure_can_be_retried_without_repeating_successful_callbacks(plugin_manager, loaded_plugin):
    manager, messages = plugin_manager
    success = Mock()
    failure = Mock(side_effect=[RuntimeError("cleanup failed"), None])
    def entry(context):
        context.on_cleanup(success)
        context.on_cleanup(failure)
    loaded_plugin.entry = entry
    assert manager.enable_plugin(loaded_plugin)

    assert not manager.disable_plugin(loaded_plugin)
    assert loaded_plugin.enabled
    success.assert_called_once()
    assert len(messages) == 1
    assert manager.disable_plugin(loaded_plugin)
    assert not loaded_plugin.enabled
    success.assert_called_once()
    assert failure.call_count == 2


def test_reload_cleans_old_entry_and_restarts_only_enabled_plugin(plugin_manager):
    manager, messages = plugin_manager
    plugin_dir = manager.app.plugins_dir / "sample"
    write_plugin(plugin_dir)
    (plugin_dir / "main.py").write_text(
        'def entry(context):\n'
        '    path = context.data_dir / "events.txt"\n'
        '    def record(text):\n'
        '        with path.open("a", encoding="utf-8") as f:\n'
        '            f.write(text + "\\n")\n'
        '    record("start")\n'
        '    context.on_cleanup(lambda: record("stop"))\n', encoding="utf-8",
    )
    write_plugin(manager.app.plugins_dir / "inactive", id="inactive")
    manager.load_plugins()
    old = next(plugin for plugin in manager.plugins if plugin.id == "sample")
    assert manager.enable_plugin(old)

    manager.load_plugins()

    current = next(plugin for plugin in manager.plugins if plugin.id == "sample")
    assert current is not old
    assert not old.enabled
    assert current.enabled
    assert not next(plugin for plugin in manager.plugins if plugin.id == "inactive").enabled
    path = manager.app.data_dir / "plugins/net.test/sample/events.txt"
    assert path.read_text(encoding="utf-8").splitlines() == ["start", "stop", "start"]
    assert manager.shutdown_plugins()
    assert path.read_text(encoding="utf-8").splitlines() == ["start", "stop", "start", "stop"]
    assert messages == []


def test_enable_missing_entry_reports_error(plugin_manager, loaded_plugin):
    manager, messages = plugin_manager
    loaded_plugin.entry = None

    assert not manager.enable_plugin(loaded_plugin)
    assert not loaded_plugin.enabled
    assert len(messages) == 1
    assert "not been initialized" in messages[0]


def test_reload_does_not_replace_plugin_when_cleanup_fails(plugin_manager, loaded_plugin):
    manager, messages = plugin_manager
    cleanup = Mock(side_effect=RuntimeError("still running"))
    loaded_plugin.entry = lambda context: context.on_cleanup(cleanup)
    assert manager.enable_plugin(loaded_plugin)

    manager.load_plugins()

    assert manager.plugins == [loaded_plugin]
    assert loaded_plugin.enabled
    assert len(messages) == 1
    cleanup.side_effect = None


def test_set_plugin_enabled_persists_and_restores_after_restart(plugin_manager, loaded_plugin):
    manager, messages = plugin_manager
    settings = manager.app.settings_manager
    settings.set("plugins", PluginSettings(enabled=["missing:plugin"]))
    entry = Mock()
    loaded_plugin.entry = entry
    assert manager.set_plugin_enabled(loaded_plugin, True)
    assert manager.set_plugin_enabled(loaded_plugin, True)
    entry.assert_called_once()
    assert settings.get("plugins", PluginSettings).enabled == ["missing:plugin", "net.test:sample"]
    saved = settings.path.read_bytes()
    assert manager.shutdown_plugins()
    assert settings.path.read_bytes() == saved

    restored_settings = SettingsManager(settings.path)
    restored_settings.register("plugins", PluginSettings)
    restored_settings.load()
    manager.app.settings_manager = restored_settings
    restarted = PluginManager(manager.app)
    try:
        restarted.load_plugins()
        plugin = restarted.plugins[0]
        assert plugin.enabled
        assert restarted.set_plugin_enabled(plugin, False)
        restored_settings.load()
        assert restored_settings.get("plugins", PluginSettings).enabled == ["missing:plugin"]
        restarted.load_plugins()
        assert not restarted.plugins[0].enabled
        assert messages == []
    finally:
        restarted.shutdown_plugins()


def test_failed_entry_does_not_persist_enabled_preference(plugin_manager, loaded_plugin):
    manager, messages = plugin_manager
    settings = manager.app.settings_manager
    settings.save()
    saved = settings.path.read_bytes()
    loaded_plugin.entry = Mock(side_effect=RuntimeError("cannot start"))

    assert not manager.set_plugin_enabled(loaded_plugin, True)

    assert not loaded_plugin.enabled
    assert settings.get("plugins", PluginSettings).enabled == []
    assert settings.path.read_bytes() == saved
    assert len(messages) == 1


def test_failed_cleanup_preserves_enabled_preference(plugin_manager, loaded_plugin):
    manager, messages = plugin_manager
    cleanup = Mock(side_effect=RuntimeError("cannot stop"))
    loaded_plugin.entry = lambda context: context.on_cleanup(cleanup)
    assert manager.set_plugin_enabled(loaded_plugin, True)
    settings = manager.app.settings_manager
    saved = settings.path.read_bytes()

    assert not manager.set_plugin_enabled(loaded_plugin, False)

    assert loaded_plugin.enabled
    assert settings.get("plugins", PluginSettings).enabled == ["net.test:sample"]
    assert settings.path.read_bytes() == saved
    assert len(messages) == 1
    cleanup.side_effect = None


@pytest.mark.parametrize("was_enabled", [False, True])
def test_save_failure_restores_runtime_and_preferences(plugin_manager, loaded_plugin, monkeypatch, was_enabled):
    manager, messages = plugin_manager
    settings = manager.app.settings_manager
    settings.set("plugins", PluginSettings(enabled=["missing:plugin"]))
    settings.save()
    cleanup = Mock()
    loaded_plugin.entry = lambda context: context.on_cleanup(cleanup)
    if was_enabled:
        assert manager.set_plugin_enabled(loaded_plugin, True)
    before = list(settings.get("plugins", PluginSettings).enabled)
    saved = settings.path.read_bytes()
    monkeypatch.setattr(SettingsManager, "save", Mock(side_effect=PermissionError("read only")))

    assert not manager.set_plugin_enabled(loaded_plugin, not was_enabled)

    assert loaded_plugin.enabled == was_enabled
    assert settings.get("plugins", PluginSettings).enabled == before
    assert settings.path.read_bytes() == saved
    cleanup.assert_called_once()
    assert len(messages) == 1
    assert "Failed to save enabled state" in messages[0]


def test_auto_enable_failure_keeps_saved_preference(plugin_manager):
    manager, messages = plugin_manager
    plugin_dir = manager.app.plugins_dir / "sample"
    write_plugin(plugin_dir)
    (plugin_dir / "main.py").write_text(
        'def entry(context):\n    raise RuntimeError("startup failure")\n', encoding="utf-8",
    )
    settings = manager.app.settings_manager
    settings.set("plugins", PluginSettings(enabled=["net.test:sample", "missing:plugin"]))
    settings.save()
    saved = settings.path.read_bytes()

    manager.load_plugins()

    plugin = manager.plugins[0]
    assert not plugin.enabled
    assert settings.get("plugins", PluginSettings).enabled == ["net.test:sample", "missing:plugin"]
    assert settings.path.read_bytes() == saved
    assert len(messages) == 1
    assert manager.set_plugin_enabled(plugin, False)
    assert settings.get("plugins", PluginSettings).enabled == ["missing:plugin"]
