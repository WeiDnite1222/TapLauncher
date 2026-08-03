"""Launcher settings schemas persisted by SettingsManager."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from constant import CLIENT_ID


class GeneralSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    language: Literal["en", "zh-TW"] = "zh-TW"


class AppearanceSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    theme: Literal["system", "light", "dark"] = "system"


class AccountSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_id: UUID = UUID(CLIENT_ID)
