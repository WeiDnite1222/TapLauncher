from pathlib import Path
from enum import Enum
from typing import Literal

import pytest
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from manager.settings import (
    ConfigValidationError,
    ModelRegistrationError,
    SettingsError,
    SettingsManager,
)
from manager.settings_models import AccountSettings


class AppSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    workers: int = Field(ge=1, le=8)


def write_toml(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def test_load_registered_model(tmp_path: Path) -> None:
    path = write_toml(tmp_path / "settings.toml", '[app]\nname = "demo"\nworkers = 4\n')
    manager = SettingsManager(path)
    manager.register("app", AppSettings)
    manager.load()

    settings = manager.get("app", AppSettings)
    assert settings.name == "demo"
    assert settings.workers == 4


def test_decorator_registration_and_validation(tmp_path: Path) -> None:
    manager = SettingsManager()

    @manager.model("plugin")
    class PluginSettings(BaseModel):
        enabled: bool

    manager.validate({"plugin": {"enabled": True}})
    assert manager.registered_sections == ("plugin",)


def test_invalid_config_reports_section(tmp_path: Path) -> None:
    path = write_toml(tmp_path / "settings.toml", '[app]\nname = "demo"\nworkers = 99\n')
    manager = SettingsManager(path)
    manager.register("app", AppSettings)

    with pytest.raises(ConfigValidationError) as error:
        manager.load()

    assert "app" in error.value.errors


def test_unknown_section_is_rejected(tmp_path: Path) -> None:
    path = write_toml(tmp_path / "settings.toml", "[unknown]\nvalue = 1\n")
    manager = SettingsManager(path)

    with pytest.raises(SettingsError, match="unknown"):
        manager.load()


def test_duplicate_registration_is_rejected() -> None:
    manager = SettingsManager()
    manager.register("app", AppSettings)

    with pytest.raises(ModelRegistrationError):
        manager.register("app", AppSettings)


def test_literal_choices_are_exposed_and_validated() -> None:
    class UiSettings(BaseModel):
        theme: Literal["light", "dark", "system"]

    manager = SettingsManager()
    manager.register("ui", UiSettings)

    assert manager.choices("ui", "theme") == ("light", "dark", "system")
    with pytest.raises(ConfigValidationError):
        manager.validate({"ui": {"theme": "unknown"}})


def test_enum_choices_use_toml_values() -> None:
    class LogLevel(str, Enum):
        DEBUG = "debug"
        INFO = "info"

    class LogSettings(BaseModel):
        level: LogLevel

    manager = SettingsManager()
    manager.register("log", LogSettings)

    assert manager.choices("log", "level") == ("debug", "info")
    manager.validate({"log": {"level": "debug"}})


def test_nested_model_and_nested_choices(tmp_path: Path) -> None:
    class WindowSettings(BaseModel):
        mode: Literal["windowed", "fullscreen"]
        width: int = Field(ge=640)

    class UiSettings(BaseModel):
        window: WindowSettings

    path = write_toml(
        tmp_path / "settings.toml",
        '[ui.window]\nmode = "fullscreen"\nwidth = 1920\n',
    )
    manager = SettingsManager(path)
    manager.register("ui", UiSettings)
    manager.load()

    ui = manager.get("ui", UiSettings)
    assert ui.window.width == 1920
    assert manager.choices("ui", "window.mode") == ("windowed", "fullscreen")


def test_invalid_nested_model_is_rejected() -> None:
    class ChildSettings(BaseModel):
        count: int = Field(ge=1)

    class ParentSettings(BaseModel):
        child: ChildSettings

    manager = SettingsManager()
    manager.register("parent", ParentSettings)

    with pytest.raises(ConfigValidationError) as error:
        manager.validate({"parent": {"child": {"count": 0}}})

    assert error.value.errors["parent"].errors()[0]["loc"] == ("child", "count")


def test_defaults_set_save_and_reload(tmp_path: Path) -> None:
    class GeneralSettings(BaseModel):
        language: Literal["en", "zh-TW"] = "zh-TW"

    path = tmp_path / "data" / "settings.toml"
    manager = SettingsManager(path)
    manager.register("general", GeneralSettings)
    manager.load_defaults()
    manager.set("general", {"language": "en"})

    assert manager.save() == path
    assert 'language = "en"' in path.read_text(encoding="utf-8")

    reloaded = SettingsManager(path)
    reloaded.register("general", GeneralSettings)
    reloaded.load()
    assert reloaded.get("general", GeneralSettings).language == "en"


def test_account_client_id_is_a_valid_uuid() -> None:
    manager = SettingsManager()
    manager.register("account", AccountSettings)
    manager.load_defaults()

    custom_id = "12345678-1234-5678-9abc-123456789abc"
    updated = manager.set("account", {"client_id": custom_id})
    assert str(updated.client_id) == custom_id

    with pytest.raises(ValidationError):
        manager.set("account", {"client_id": "not-a-client-id"})
