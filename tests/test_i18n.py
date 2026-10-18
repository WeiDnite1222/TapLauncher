import json
from pathlib import Path
from string import Formatter

from core_lib.i18n import TranslationManager


def test_empty_catalog_uses_english_source_strings(tmp_path):
    (tmp_path / "zh-TW.json").write_text("{}", encoding="utf-8")
    translations = TranslationManager(tmp_path, "zh-TW")

    assert translations.language == "zh-TW"
    assert translations.translate("Settings") == "Settings"
    assert translations.translate("Version: {version}", version="1.0") == "Version: 1.0"


def test_catalog_translation_and_unknown_language_fallback(tmp_path):
    (tmp_path / "zh-TW.json").write_text(
        json.dumps({"Settings": "設定"}), encoding="utf-8"
    )
    translations = TranslationManager(tmp_path, "zh-TW")
    assert translations.translate("Settings") == "設定"

    translations.set_language("unsupported")
    assert translations.language == "en"
    assert translations.translate("Settings") == "Settings"


def test_bundled_catalogs_have_matching_english_entries():
    catalog_dir = Path(__file__).parents[1] / "resources" / "translations"
    english = json.loads((catalog_dir / "en.json").read_text(encoding="utf-8"))
    traditional_chinese = json.loads(
        (catalog_dir / "zh-TW.json").read_text(encoding="utf-8")
    )

    assert english
    assert set(traditional_chinese) == set(english)
    assert traditional_chinese["Settings"] == "設定"
    untranslated_names = {"English", "Fabric"}
    assert {
        key
        for key, value in traditional_chinese.items()
        if key == value
    } == untranslated_names

    formatter = Formatter()
    for key, translated in traditional_chinese.items():
        source_fields = {
            field for _, field, _, _ in formatter.parse(key) if field is not None
        }
        translated_fields = {
            field
            for _, field, _, _ in formatter.parse(translated)
            if field is not None
        }
        assert translated_fields == source_fields, key
