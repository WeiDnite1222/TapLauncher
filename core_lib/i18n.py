"""Small, dependency-free translation catalog used by the launcher UI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal


SUPPORTED_LANGUAGES = ("en", "zh-TW")


class TranslationManager(QObject):
    """Load JSON catalogs and notify widgets when the language changes."""

    language_changed = Signal(str)

    def __init__(self, catalog_dir: Path, language: str = "en") -> None:
        super().__init__()
        self.catalog_dir = Path(catalog_dir)
        self._language = "en"
        self._catalog: dict[str, str] = {}
        self.set_language(language, emit=False)

    @property
    def language(self) -> str:
        return self._language

    def set_language(self, language: str, *, emit: bool = True) -> None:
        if language not in SUPPORTED_LANGUAGES:
            language = "en"

        catalog: dict[str, str] = {}
        path = self.catalog_dir / f"{language}.json"
        if path.is_file():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                catalog = {
                    str(key): str(value)
                    for key, value in raw.items()
                    if isinstance(value, str)
                }
            except (OSError, json.JSONDecodeError):
                # An invalid optional catalog must not prevent the launcher starting.
                catalog = {}

        changed = language != self._language or catalog != self._catalog
        self._language = language
        self._catalog = catalog
        if emit and changed:
            self.language_changed.emit(language)

    def translate(self, key: str, /, **values: Any) -> str:
        text = self._catalog.get(key, key)
        return text.format(**values) if values else text

