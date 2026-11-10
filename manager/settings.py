from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from pathlib import Path
from types import UnionType
from typing import Annotated, Any, Literal, TypeVar, Union, cast, get_args, get_origin

from pydantic import BaseModel, ValidationError
import tomli_w

from core_lib.common.exception import ModelRegistrationError, ConfigValidationError, SettingsError

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

ModelT = TypeVar("ModelT", bound=BaseModel)


class SettingsManager:
    """
    A settings manager (Based-on pydantic)

    Vibed!
    """
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else None
        self._models: dict[str, type[BaseModel]] = {}
        self._settings: dict[str, BaseModel] = {}

    @property
    def registered_sections(self) -> tuple[str, ...]:
        return tuple(self._models)

    def register_plugin_apis(self, plugin_manager):
        plugin_manager.register_api("launcher.settings.sections", lambda: self.registered_sections)
        plugin_manager.register_api("launcher.settings.get", lambda section: self.get(section).model_dump(mode="python"))
        plugin_manager.register_api("launcher.settings.choices", self.choices)

    def register(self, section: str, model: type[ModelT], *, replace: bool = False) -> type[ModelT]:
        """
        Register a new model
        :param section:
        :param model:
        :param replace:
        :return:
            model: type[ModelT]
        """
        if not section:
            raise ModelRegistrationError(
                "Section must be a non-empty"
            )
        elif "." in section:
            raise ModelRegistrationError(
                "Top level section cannot contain dots"
            )

        if not isinstance(model, type) or not issubclass(model, BaseModel):
            raise ModelRegistrationError("Model must be a Pydantic BaseModel class")

        if section in self._models and not replace:
            raise ModelRegistrationError(f"Section {section!r} is already registered")

        self._models[section] = model
        self._settings.pop(section, None)
        return model

    def model(self, section: str):
        def decorator(model: type[ModelT]) -> type[ModelT]:
            return self.register(section, model)

        return decorator

    def load(self, path: str | Path | None = None, *, reject_unknown: bool = False) -> SettingsManager:
        """
        Load a toml settings file
        :param reject_unknown: Raise exception if settings file contains unknown section
        :param path: If not set, use default path instead
        """
        config_path = self._resolve_path(path)

        # Check file exist
        if not config_path.exists() or not config_path.is_file():
            raise FileNotFoundError(f"Settings file {config_path} does not exist")

        with config_path.open("rb") as file:
            raw = tomllib.load(file)

        unknown = set(raw).difference(self._models)
        if reject_unknown and unknown:
            names = ", ".join(sorted(unknown))
            raise SettingsError(f"unregistered TOML section(s): {names}")

        loaded: dict[str, BaseModel] = {}
        errors: dict[str, ValidationError] = {}
        for section, model in self._models.items():
            value: Any = raw.get(section, {})
            try:
                # Validate and save section data
                loaded[section] = model.model_validate(value)
            except ValidationError as error:
                errors[section] = error

        if errors:
            raise ConfigValidationError(errors)

        self.path = config_path
        self._settings = loaded
        return self

    def get(self, section: str, model: type[ModelT] | None = None) -> ModelT:
        """
        Get target section model
        :param section:
        :param model:
        :return:
            model: type[ModelT]
        """
        if section not in self._models:
            raise KeyError(f"settings section {section!r} is not registered")
        if section not in self._settings:
            raise SettingsError(f"settings have not been loaded for {section!r}")

        value = self._settings[section]
        if model is not None and not isinstance(value, model):
            raise TypeError(
                f"section {section!r} contains {type(value).__name__}, "
                f"not {model.__name__}"
            )

        return cast(ModelT, value)

    def set(self, section: str, value: BaseModel | Mapping[str, Any]) -> BaseModel:
        """Validate and replace one loaded settings section."""
        try:
            model = self._models[section]
        except KeyError as error:
            raise KeyError(f"settings section {section!r} is not registered") from error

        validated = model.model_validate(value)
        self._settings[section] = validated
        return validated

    def load_defaults(self) -> SettingsManager:
        """Load every registered model using its declared default values."""
        loaded: dict[str, BaseModel] = {}
        errors: dict[str, ValidationError] = {}
        for section, model in self._models.items():
            try:
                loaded[section] = model.model_validate({})
            except ValidationError as error:
                errors[section] = error
        if errors:
            raise ConfigValidationError(errors)
        self._settings = loaded
        return self

    def save(self, path: str | Path | None = None) -> Path:
        """Validate all loaded sections and save them as UTF-8 TOML."""
        config_path = self._resolve_path(path)
        missing = set(self._models).difference(self._settings)
        if missing:
            names = ", ".join(sorted(missing))
            raise SettingsError(f"settings section(s) have not been loaded: {names}")

        data = {
            section: self._models[section]
            .model_validate(self._settings[section])
            .model_dump(mode="json", exclude_none=True) # ignore None keys
            for section in self._models
        }

        config_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = config_path.with_suffix(config_path.suffix + ".tmp")
        temporary_path.write_bytes(tomli_w.dumps(data).encode("utf-8"))
        temporary_path.replace(config_path)
        self.path = config_path
        return config_path

    def choices(self, section: str, field: str) -> tuple[Any, ...]:
        """
        Return choices for a field, accepting paths such as ``window.mode``.

        This can be used by a settings page to populate a combo box. Pydantic
        uses the same annotation to validate values read from TOML.
        :param section:
        :param field:
        """
        try:
            model = self._models[section]
        except KeyError as error:
            raise KeyError(f"settings section {section!r} is not registered") from error

        annotation: Any = model
        for part in field.split("."):
            nested_model = _model_type(annotation)
            if nested_model is None:
                raise KeyError(
                    f"{part!r} cannot be resolved in field path {section}.{field}"
                )
            try:
                annotation = nested_model.model_fields[part].annotation
            except KeyError as error:
                raise KeyError(f"field path {section}.{field} does not exist") from error

        values = _choice_values(annotation)
        if values is None:
            raise SettingsError(
                f"field {section}.{field} is not declared with Literal or Enum"
            )
        return values

    def validate(self, data: Mapping[str, Any], *, reject_unknown: bool = True) -> None:
        """
        Validate an in-memory mapping without changing loaded settings.
        :param data:
        :param reject_unknown:
        :return:
        """
        unknown = set(data).difference(self._models)
        if reject_unknown and unknown:
            names = ", ".join(sorted(unknown))
            raise SettingsError(f"unregistered settings section(s): {names}")

        errors: dict[str, ValidationError] = {}
        for section, model in self._models.items():
            try:
                model.model_validate(data.get(section, {}))
            except ValidationError as error:
                errors[section] = error
        if errors:
            raise ConfigValidationError(errors)

    def _resolve_path(self, path: str | Path | None) -> Path:
        resolved = Path(path) if path is not None else self.path

        if resolved is None:
            raise SettingsError("no TOML configuration path was provided")

        return resolved

def _choice_values(annotation: Any) -> tuple[Any, ...] | None:
    """Extract choices from a field annotation, including Annotated/Optional."""
    origin = get_origin(annotation)
    if origin is Literal:
        return get_args(annotation)
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        return tuple(member.value for member in annotation)
    if origin is Annotated:
        return _choice_values(get_args(annotation)[0])
    if origin in (Union, UnionType):
        choices: list[Any] = []
        found = False
        for member in get_args(annotation):
            values = _choice_values(member)
            if values is not None:
                choices.extend(values)
                found = True
        return tuple(choices) if found else None
    return None


def _model_type(annotation: Any) -> type[BaseModel] | None:
    """Find a nested BaseModel type inside Annotated or Optional."""
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation
    origin = get_origin(annotation)
    if origin is Annotated:
        return _model_type(get_args(annotation)[0])
    if origin in (Union, UnionType):
        for member in get_args(annotation):
            model = _model_type(member)
            if model is not None:
                return model
    return None
