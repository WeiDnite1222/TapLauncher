"""
Wheel plugin API

My simple plugin API for "all" Python-based applications
"""
import importlib
import re
import sys
import traceback
from dataclasses import dataclass
from hashlib import sha256
from importlib.machinery import ModuleSpec
from importlib.util import spec_from_file_location
from logging import Logger
from pathlib import Path
from typing import Callable, Any

from PySide6.QtCore import QObject, Signal

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

from packaging.specifiers import SpecifierSet, InvalidSpecifier

from constant import WHEEL_PLUGIN_API_VERSION
from core_lib.common.python import is_function_in_file
from manager.settings_models import PluginSettings

OPERATORS = {
    "==": "equal",
    "!=": "not equal",
    ">": "higher than",
    ">=": "not lower than",
    "<": "lower than",
    "<=": "not higher than",
    "~=": "compatible with",
    "===": "same",
}

def describe_specifier(spec: SpecifierSet) -> str:
    if not spec:
        return "No version limit"

    return ", and ".join(
        f"{OPERATORS[item.operator]} {item.version}"
        for item in sorted(spec, key=str)
    )

class Plugin:
    def __init__(self, plugin_id: str, name: str, group: str, version: str, api_version_range: SpecifierSet, entrypoint: str, path: Path,
                 icon_path: Path | None = None, module_spec: ModuleSpec | None = None, description: str = ""):
        self.id: str = plugin_id
        self.name: str = name
        self.group: str = group
        self.version: str = version
        self.description: str = description

        self.enabled: bool = False
        self._changing_state = False
        self._cleanup_callbacks: list[Callable[[], None]] = []
        self.api_version_range: SpecifierSet = api_version_range

        self.entrypoint = entrypoint
        self.entry: Callable[[PluginContext], None] | None = None
        self.path = path
        self.icon_path: Path | None = icon_path
        self.module_spec: ModuleSpec | None = module_spec

    def get_support_api_range_string(self):
        return describe_specifier(self.api_version_range)

    @property
    def is_changing_state(self) -> bool:
        return self._changing_state

    def get_entrypoint_name(self):
        """
        Get entrypoint name
        IMPORTANT: The entrypoint should be verified.
        :return:
        """
        return self.entrypoint.rsplit(":", 1)[-1]

@dataclass(frozen=True)
class PluginContext:
    api_version: str
    plugin_id: str
    plugin_dir: Path
    data_dir: Path
    logger: Logger

    # callback
    get_api: Callable[[str], Callable]
    show_info: Callable[[str], None]
    show_error: Callable[[str], None]
    on_cleanup: Callable[[Callable[[], None]], None]
    override_api: Callable[[str, Callable], Callable[[], None]]

class PluginHook:
    """
    A callable instance that used by plugin to calling the target API.
    """
    def __init__(self, name: str, target: Callable[..., Any]):
        self.name = name
        self._target = target
        self._original_target = target
        self._overrides: list[tuple[object, Callable]] = []

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return self._target(*args, **kwargs)

    def set_target(self, target: Callable[..., Any]) -> Callable[[], None]:
        """Set/Override the target API."""
        if not callable(target):
            raise TypeError(f'Plugin API "{self.name}" must be callable.')

        token = object()
        self._overrides.append((token, target))
        self._target = target

        return lambda: self.restore(token)

    def restore(self, token: object | None = None) -> None:
        """Remove an override and restore the latest remaining target."""
        if token is None:
            if not self._overrides:
                return

            token = self._overrides[-1][0]

        self._overrides = [entry for entry in self._overrides if entry[0] is not token]
        self._target = self._overrides[-1][1] if self._overrides else self._original_target

class PluginManager(QObject):
    def __init__(self, app):
        QObject.__init__(self)
        self.app = app
        self.widget_manager = app.widget_manager
        self.plugins: list[Plugin] = []
        self._apis: dict[str, Callable] = {}
        self._updating_plugin_state = False
        self._hooks: dict[str, PluginHook] = {}
        self.register_api("launcher.apis.list", self.list_apis)

        self.signals = PluginManager.Signals()

        self.signals.load_plugins.connect(self.load_plugins)
        self.signals.reload_plugins.connect(self.load_plugins)
        self.app.aboutToQuit.connect(self.shutdown_plugins)

    class Signals(QObject):
        load_plugins = Signal()
        reload_plugins = Signal()
        plugins_loaded = Signal() # For gui
        plugin_state_changed = Signal(object)

    def _show_error(self, message: str, error: BaseException | None = None):
        details = message
        if error is not None:
            details += "\n" + "".join(traceback.format_exception(type(error), error, error.__traceback__))

        self.widget_manager.signal.show_and_print_error_message.emit({
            "title": "Plugin Error",
            "message": message,
            "error": details,
        })

    def load_plugins_from_path(self, plugins_dir: Path):
        try:
            plugins = [d for d in plugins_dir.iterdir() if d.is_dir()]
        except FileNotFoundError:
            return
        except OSError as e:
            message = f"Failed to load plugins from {plugins_dir}: {e}"
            self._show_error(message, e)
            return

        for plugin_dir in plugins:
            plugin = self._load_plugin_config(plugin_dir)

            if plugin:
                self.app.logger.debug(f"Loading plugin: {plugin.id}")
                if self._init_plugin_entry(plugin):
                    self.plugins.append(plugin)

    def load_plugins(self):
        if self._updating_plugin_state:
            return
        try:
            settings = self.app.settings_manager.get("plugins", PluginSettings)
            enabled_ids = set(settings.enabled)
        except Exception as e:
            self._show_error(f"Failed to read plugin enabled states: {e}", e)
            self.signals.plugins_loaded.emit()
            return

        plugins_dir: Path = self.app.plugins_dir
        internal_dir: Path = self.app.internal_plugins_dir
        enabled_ids.update(f"{plugin.group}:{plugin.id}" for plugin in self.plugins if plugin.enabled)

        if not self.shutdown_plugins():
            self.signals.plugins_loaded.emit()
            return

        self.plugins.clear()
        self.load_plugins_from_path(internal_dir)
        self.load_plugins_from_path(plugins_dir)
        for plugin in self.plugins:
            if f"{plugin.group}:{plugin.id}" in enabled_ids:
                self.enable_plugin(plugin)
        self.signals.plugins_loaded.emit()

    def _init_plugin_entry(self, plugin: Plugin) -> bool:
        # For current state, the plugin manager only supports init plugin entry in main thread
        spec = plugin.module_spec
        if spec is None or spec.loader is None:
            self._show_error(f"Failed to initialize plugin entry: {plugin.id}. Module spec or loader is missing.")
            return False

        # Keep existing modules so a failed reload can restore them.
        previous_modules = {
            name: module for name, module in sys.modules.copy().items()
            if name == spec.name or name.startswith(spec.name + ".")
        }

        try:
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)

            entry_name = plugin.get_entrypoint_name()
            entry: Callable[[PluginContext], None] | None = getattr(module, entry_name, None)
            if not callable(entry):
                raise ValueError(f'Plugin entry "{entry_name}" is missing or is not callable.')

            plugin.entry = entry
        except (Exception, SystemExit) as e:
            for name in list(sys.modules):
                if name == spec.name or name.startswith(spec.name + "."):
                    sys.modules.pop(name, None)
            sys.modules.update(previous_modules)

            message = f"Failed to initialize plugin entry: {plugin.id}\n{e}"
            self._show_error(message, e)
            return False

        return True

    def set_plugin_enabled(self, plugin: Plugin, enabled: bool) -> bool:
        """Change runtime state and persist the user's preference after success."""
        if not isinstance(enabled, bool):
            raise TypeError("Plugin enabled state must be a bool.")
        if self._updating_plugin_state or plugin.is_changing_state:
            return False

        self._updating_plugin_state = True
        was_enabled = plugin.enabled
        previous_settings = None
        settings_changed = False
        try:
            settings_manager = self.app.settings_manager
            previous_settings = settings_manager.get("plugins", PluginSettings).model_copy(deep=True)
            plugin_id = f"{plugin.group}:{plugin.id}"
            success = self.enable_plugin(plugin) if enabled else self.disable_plugin(plugin)
            if not success:
                return False
            if (plugin_id in previous_settings.enabled) == enabled:
                return True

            enabled_ids = [value for value in previous_settings.enabled if value != plugin_id]
            if enabled:
                enabled_ids.append(plugin_id)
            updated_settings = previous_settings.model_copy(update={"enabled": enabled_ids})
            settings_manager.set("plugins", updated_settings)
            settings_changed = True
            settings_manager.save()
            return True
        except Exception as e:
            if settings_changed:
                self.app.settings_manager.set("plugins", previous_settings)
            # Keep runtime and stored preference consistent if writing fails.
            if plugin.enabled != was_enabled:
                if was_enabled:
                    self.enable_plugin(plugin)
                else:
                    self.disable_plugin(plugin)
            self._show_error(f"Failed to save enabled state for plugin: {plugin.id}\n{e}", e)
            return False
        finally:
            self._updating_plugin_state = False
            self.signals.plugin_state_changed.emit(plugin)

    def enable_plugin(self, plugin: Plugin) -> bool:
        if plugin._changing_state:
            return False
        if plugin.enabled:
            return True

        plugin._changing_state = True
        try:
            if not self._cleanup_plugin(plugin):
                return False
            entry: Callable[[PluginContext], None] | None = plugin.entry
            if not entry or not callable(entry):
                raise ValueError("Plugin entry has not been initialized.")

            context = self._create_plugin_context(plugin)
            entry(context)
            plugin.enabled = True
            return True
        except (Exception, SystemExit) as e:
            self._cleanup_plugin(plugin)
            self._show_error(f"Failed to enable plugin: {plugin.id}\n{e}", e)
            return False
        finally:
            plugin._changing_state = False
            self.signals.plugin_state_changed.emit(plugin)

    def disable_plugin(self, plugin: Plugin) -> bool:
        if plugin._changing_state:
            return False

        plugin._changing_state = True
        try:
            if not self._cleanup_plugin(plugin):
                return False
            plugin.enabled = False
            return True
        finally:
            plugin._changing_state = False
            self.signals.plugin_state_changed.emit(plugin)

    def shutdown_plugins(self) -> bool:
        success = True
        for plugin in reversed(self.plugins):
            if plugin.enabled or plugin._cleanup_callbacks:
                success = self.disable_plugin(plugin) and success

        return success

    def _create_plugin_context(self, plugin: Plugin) -> PluginContext:
        plugin_id = f"{plugin.group}:{plugin.id}"
        data_root = (self.app.data_dir / "plugins").resolve()
        data_dir = (data_root / plugin.group / plugin.id).resolve()
        if data_dir == data_root or not data_dir.is_relative_to(data_root):
            raise ValueError(f"Invalid plugin data directory: {plugin_id}")
        data_dir.mkdir(parents=True, exist_ok=True)
        return PluginContext(
            plugin_id=plugin_id,
            plugin_dir=plugin.path,
            data_dir=data_dir,
            logger=self.app.logger.getChild(f"plugins.{plugin.group}.{plugin.id}"),
            api_version=WHEEL_PLUGIN_API_VERSION,
            show_info=lambda message: self.widget_manager.signal.show_info_message.emit(f"[{plugin_id}] {message}"),
            show_error=lambda message: self._show_error(f"[{plugin_id}] {message}"),
            on_cleanup=lambda callback: self._register_plugin_cleanup(plugin, callback),
            get_api=self.get_api,
            override_api=lambda name, callback: self._override_plugin_api(plugin, name, callback),
        )

    def _override_plugin_api(self, plugin: Plugin, name: str, callback: Callable) -> Callable[[], None]:
        restore = self.override_api(name, callback)
        self._register_plugin_cleanup(plugin, restore)
        return restore

    @staticmethod
    def _register_plugin_cleanup(plugin: Plugin, callback: Callable[[], None]):
        if not callable(callback):
            raise TypeError("Plugin cleanup callback must be callable.")

        plugin._cleanup_callbacks.append(callback)

    def _cleanup_plugin(self, plugin: Plugin) -> bool:
        callbacks = plugin._cleanup_callbacks
        plugin._cleanup_callbacks = []
        failed_callbacks = []
        for callback in reversed(callbacks):
            try:
                callback()
            except (Exception, SystemExit) as e:
                failed_callbacks.append(callback)
                self._show_error(f"Failed to clean up plugin: {plugin.id}\n{e}", e)

        # Keep failed callbacks available for retry without repeating successful ones.
        plugin._cleanup_callbacks[:0] = reversed(failed_callbacks)
        return not plugin._cleanup_callbacks

    def _load_plugin_config(self, plugin_dir: Path) -> Plugin | None:
        plugin_config_path = plugin_dir / "plugin.toml"

        try:
            if not plugin_config_path.exists():
                self._show_error(f"Plugin config not found for plugin: {plugin_dir}")
                return None

            with plugin_config_path.open("rb") as f:
                plugin_config = tomllib.load(f)

                for key in ("group", "id", "name", "version", "api_version", "entrypoint", "icon"):
                    if key in plugin_config and not isinstance(plugin_config[key], str):
                        raise ValueError(f"Plugin {key} must be a string.")

                group = plugin_config.get("group", "")
                if not group:
                    raise ValueError("Plugin missing group id.")

                plugin_id = plugin_config.get("id", "")
                if not plugin_id:
                    raise ValueError("Plugin id is missing.")

                name = plugin_config.get("name", "")
                if not name:
                    name = f"UnnamedPlugin.{plugin_id}"

                version: str = plugin_config.get("version", "")
                if not version:
                    raise ValueError("Plugin version is missing.")

                if not self._check_plugin_version(version):
                    raise ValueError("Plugin version is invalid.")

                required_api_version = plugin_config.get("api_version", "")
                if not required_api_version:
                    raise ValueError("Required API version is missing.")

                is_valid, is_support, support_api_ver_range = self._check_plugin_support_api_version(required_api_version)
                if not is_valid or support_api_ver_range is None:
                    raise ValueError("Plugin support api version range is invalid")
                elif not is_support:
                    raise ValueError("Plugin does not support the current API version.")

                entrypoint = plugin_config.get("entrypoint", "")
                if not entrypoint:
                    raise ValueError("Plugin entrypoint is missing.")

                module_spec = self._check_and_return_plugin_endpoint_spec(entrypoint, plugin_dir)

                icon_path = None
                icon = plugin_config.get("icon", "")
                if icon:
                    candidate = (plugin_dir / icon).resolve()
                    if (not Path(icon).is_absolute()
                            and candidate.is_relative_to(plugin_dir.resolve())
                            and candidate.suffix.lower() in (".gif", ".png", ".jpg", ".jpeg", ".bmp")
                            and candidate.is_file()):
                        icon_path = candidate

                description = plugin_config.get("description", None)

                plugin = Plugin(
                    name=name,
                    version=version,
                    entrypoint=entrypoint,
                    api_version_range=support_api_ver_range,
                    group=group,
                    path=plugin_dir,
                    plugin_id=plugin_id,
                    module_spec=module_spec,
                    icon_path=icon_path,
                    description=description
                )

                return plugin
        except Exception as e:
            message = f"Failed to load plugin config: {plugin_config_path}\n{e}"
            self._show_error(message, e)
            return None

    @staticmethod
    def _check_plugin_version(plugin_version: str) -> bool:
        pattern = r"[0-9]+\.[0-9]+\.[0-9]+"

        if isinstance(plugin_version, str) and re.fullmatch(pattern, plugin_version):
            return True

        return False

    @staticmethod
    def _check_plugin_support_api_version(required_api_version: str) -> tuple[bool, bool, SpecifierSet | None]:
        """
        Check plugin support api version
        :param required_api_version:
        :return:
            parse_result: bool
            support_current_api_version: bool
            required_api_version: SpecifierSet
        """
        try:
            required = SpecifierSet(required_api_version)

            if WHEEL_PLUGIN_API_VERSION in required:
                return True, True, required
        except InvalidSpecifier:
            return False, False, None

        return True, False, required

    @staticmethod
    def _check_and_return_plugin_endpoint_spec(endpoint: str, plugin_dir: Path) -> ModuleSpec:
        """
        Check plugin endpoint
        :param endpoint:
        :param plugin_dir:
        :return: Module spec for the validated Python file. Does not execute the module.
        """
        path = plugin_dir

        parts = endpoint.split(":")

        if len(parts) < 2:
            raise ValueError(f"Invalid plugin endpoint \"{endpoint}\". At least two parts are required.")

        for index, part in enumerate(parts[:-1]):
            if not part or part in (".", "..") or "/" in part or "\\" in part:
                raise ValueError(f"Invalid plugin endpoint \"{endpoint}\". Invalid path part \"{part}\".")

            path = path / part

            if not path.resolve().is_relative_to(plugin_dir.resolve()):
                raise ValueError(f"Invalid plugin endpoint \"{endpoint}\". Path must be inside the plugin directory.")

            if index != len(parts) - 2:
                if not path.is_dir():
                    raise ValueError(f"Invalid plugin endpoint \"{endpoint}\". Directory \"{path}\" does not exist.")
                continue

            if not path.is_file() or path.suffix != ".py":
                raise ValueError(f"Invalid plugin endpoint \"{endpoint}\". Python file \"{path}\" does not exist.")

            # dira:dirb:file.py:entry
            entry = parts[-1]

            if not entry.isidentifier():
                raise ValueError(f"Invalid plugin endpoint \"{endpoint}\". Entry must be a valid identifier.")

            # Check if the entry is in file
            is_success, existing = is_function_in_file(path, entry)
            if not is_success:
                raise ValueError(f"Failed to check if function \"{entry}\" exists in file \"{path}\".")

            if not existing:
                raise ValueError(f"Function \"{entry}\" does not exist in file \"{path}\".")

        # Use the resolved path to keep module names distinct across plugins.
        path = path.resolve()
        module_name = "_wheel_plugin_" + sha256(str(path).encode("utf-8")).hexdigest()
        spec = spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise ValueError(f"Failed to create module spec for plugin endpoint \"{endpoint}\".")

        return spec

    #
    # API
    #
    def register_api(self, name: str, callback: Callable, overridable: bool = True):
        if not isinstance(name, str):
            raise TypeError("Plugin API name must be a string.")
        if not name or name != name.strip():
            raise ValueError("Plugin API name must be non-empty and have no surrounding whitespace.")
        if not callable(callback):
            raise TypeError(f'Plugin API "{name}" must be callable.')
        if name in self._apis:
            raise ValueError(f'Plugin API "{name}" is already registered.')

        self._apis[name] = callback

        if overridable:
            self._create_hook(name, callback)

    def _create_hook(self, name: str, callback: Callable):
        if not isinstance(name, str):
            raise TypeError("Plugin API name must be a string.")

        if not name or name != name.strip():
            raise ValueError("Plugin API name must be non-empty and have no surrounding whitespace.")

        if not callable(callback):
            raise TypeError(f'Plugin API "{name}" must be callable.')

        self._hooks[name] = PluginHook(name, callback)

    def override_api(self, name: str, callback: Callable):
        if not isinstance(name, str):
            raise TypeError("Plugin API name must be a string.")

        if name not in self._apis:
            raise ValueError(f'Plugin API "{name}" is not registered.')

        if name not in self._hooks:
            raise ValueError(f'Plugin API "{name}" does not allow overrides.')

        hook = self._hooks[name]
        return hook.set_target(callback)

    def list_apis(self) -> tuple[str, ...]:
        return tuple(sorted(self._apis))

    def get_api(self, name: str) -> Callable:
        try:
            if name in self._hooks:
                return self._hooks[name]

            return self._apis[name]
        except KeyError:
            raise LookupError(f'Plugin API "{name}" is not available.') from None
