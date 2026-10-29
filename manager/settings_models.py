"""Launcher settings schemas persisted by SettingsManager."""
import warnings
from typing import Literal, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator, model_validator, Field

from constant import CLIENT_ID

class WarnExtraModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    @model_validator(mode="before")
    @classmethod
    def warn_extra_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            extra = set(data) - set(cls.model_fields)
            if extra:
                warnings.warn(
                    f"{cls.__name__}: ignored extra fields: {sorted(extra)}",
                    UserWarning,
                    stacklevel=2,
                )
        return data

class GeneralSettings(WarnExtraModel):
    model_config = ConfigDict()

    language: Literal["en", "zh-TW"] = "zh-TW"


class AppearanceSettings(WarnExtraModel):
    model_config = ConfigDict()

    theme: str = "system"

    @field_validator("theme")
    @classmethod
    def validate_theme_name(cls, value: str) -> str:
        value = value.strip()
        if not value or "/" in value or "\\" in value or ".." in value:
            raise ValueError("invalid theme name")
        return value


class AccountSettings(WarnExtraModel):
    model_config = ConfigDict()

    credentials_save_method: Literal["system-keyring", "file"] = "system-keyring"
    custom_client_id: UUID | None = None
    token_refresh_interval: int = 600
    @field_validator("custom_client_id", mode="before")
    @classmethod
    def validate_custom_client_id(cls, value: str | None | UUID) -> UUID | None:
        if value is None:
            return None

        if isinstance(value, UUID):
            return value

        if isinstance(value, str):
            value = value.strip()

            if not value:
                return None

        try:
            return UUID(value)
        except (TypeError, ValueError, AttributeError) as error:
            raise ValueError("invalid client ID") from error

    @field_validator("token_refresh_interval", mode="before")
    @classmethod
    def validate_token_refresh_interval(cls, value: int) -> int:
        if value < 60 or value > 86400:
            raise ValueError("token refresh interval must be at least 60 seconds and at most 1 day")
        return value

class PluginSettings(WarnExtraModel):
    enabled: list[str] = Field(default_factory=list)