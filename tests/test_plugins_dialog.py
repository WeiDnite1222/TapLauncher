import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from packaging.specifiers import SpecifierSet
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QImage, QColor, QMovie
from PySide6.QtWidgets import QApplication

from core_lib.i18n import TranslationManager
from manager.plugins import Plugin, PluginManager
from manager.settings import SettingsManager
from manager.settings_models import PluginSettings
from manager.widgets import WidgetManager
from pages.plugins import PluginsDialog


@pytest.fixture
def plugin_dialog(tmp_path):
    qt_app = QApplication.instance() or QApplication([])
    root = Path(__file__).resolve().parents[1]
    i18n = TranslationManager(root / "resources/translations", "en")
    settings = SettingsManager(tmp_path.parent / (tmp_path.name + "-settings.toml"))
    settings.register("plugins", PluginSettings)
    settings.load_defaults()
    app = SimpleNamespace(
        plugins_dir=tmp_path, i18n=i18n, tr_text=i18n.translate,
        data_dir=tmp_path.parent / (tmp_path.name + "-data"), aboutToQuit=qt_app.aboutToQuit,
        icon_dir=root / "resources/icons", get_icon=lambda path: QIcon(str(path)),
        internal_plugins_dir=tmp_path.parent / (tmp_path.name + "-builtin"),
        widget_manager=WidgetManager(), logger=logging.getLogger(__name__),
        settings_manager=settings,
        apply_qss=lambda path, callback: callback((root / "resources/styles" / path).read_text(encoding="utf-8")),
    )
    manager = PluginManager(app)
    for name, enabled in (("Zulu Tools", False), ("Alpha Tools", True)):
        plugin = Plugin(name.lower().replace(" ", "-"), name, "net.test", "1.0.0",
                        SpecifierSet(">=0.0.1"), "main.py:entry", tmp_path / name)
        plugin.enabled = enabled
        manager.plugins.append(plugin)
    dialog = PluginsDialog(app, manager)
    yield dialog
    manager.shutdown_plugins()
    app.aboutToQuit.disconnect(manager.shutdown_plugins)
    dialog.close()
    dialog.deleteLater()
    qt_app.processEvents()


def test_plugin_warning_is_translated_and_saved_once(plugin_dialog):
    dialog = plugin_dialog
    dialog.app.i18n.set_language("zh-TW")
    messages = []
    dialog.app.widget_manager.signal.show_warning_message.connect(messages.append)
    dialog._show_plugin_warning()
    dialog._show_plugin_warning()
    assert len(messages) == 1
    assert "可信來源" in messages[0]
    dialog.app.settings_manager.load()
    assert dialog.app.settings_manager.get("plugins", PluginSettings).is_plugin_warning_shown
    dialog._show_plugin_warning()
    assert len(messages) == 1


def test_plugin_warning_save_failure_does_not_repeat(plugin_dialog, monkeypatch):
    dialog = plugin_dialog
    monkeypatch.setattr(dialog.app.settings_manager, "save", Mock(side_effect=OSError("read only")))
    messages = []
    dialog.app.widget_manager.signal.show_warning_message.connect(messages.append)
    dialog._show_plugin_warning()
    dialog._show_plugin_warning()
    assert len(messages) == 1


def test_search_filter_and_selection(plugin_dialog):
    dialog = plugin_dialog
    assert dialog.plugin_list.count() == 2
    assert dialog.name_label.text() == "Alpha Tools"
    dialog.plugin_list.setCurrentRow(1)
    dialog.refresh_plugins()
    assert dialog.name_label.text() == "Zulu Tools"
    dialog.search_edit.setText("NET.TEST")
    assert dialog.plugin_list.count() == 2
    dialog.filter_combo.setCurrentIndex(1)
    assert dialog.plugin_list.count() == 1
    assert dialog.name_label.text() == "Alpha Tools"
    dialog.search_edit.setText("no match")
    assert dialog.plugin_list.count() == 0
    assert dialog.details_stack.currentIndex() == 0
    assert dialog.empty_title.text() == "No matching plugins"
    dialog.search_edit.clear()
    dialog.filter_combo.setCurrentIndex(2)
    assert dialog.name_label.text() == "Zulu Tools"


def test_reload_signal_refreshes_empty_state(plugin_dialog):
    dialog = plugin_dialog
    dialog.reload_button.click()
    assert dialog.plugin_manager.plugins == []
    assert dialog.plugin_list.count() == 0
    assert dialog.empty_title.text() == "No plugins loaded"
    assert dialog.reload_button.isEnabled()


def test_language_change_preserves_selection(plugin_dialog):
    dialog = plugin_dialog
    dialog.plugin_list.setCurrentRow(1)
    dialog.app.i18n.set_language("zh-TW")
    assert dialog.windowTitle() == "插件"
    assert dialog.name_label.text() == "Zulu Tools"
    assert dialog.reload_button.text() == "重新載入插件"


def test_open_folder_failure_uses_widget_signal(plugin_dialog, monkeypatch):
    dialog = plugin_dialog
    messages = []
    urls = []
    dialog.app.widget_manager.signal.show_and_print_error_message.connect(messages.append)
    monkeypatch.setattr("pages.plugins.QDesktopServices.openUrl", lambda url: urls.append(url) or False)
    dialog.open_plugin_button.click()
    assert len(urls) == 1
    assert urls[0].isLocalFile()
    assert len(messages) == 1
    assert "Unable to open folder" in messages[0]["message"]


def test_metadata_is_plain_text(plugin_dialog):
    dialog = plugin_dialog
    plugin = dialog.plugin_manager.plugins[0]
    plugin.name = "<b>Plugin name</b>"
    dialog.refresh_plugins()
    item = next(dialog.plugin_list.item(i) for i in range(dialog.plugin_list.count())
                if dialog.plugin_list.item(i).data(Qt.ItemDataRole.UserRole) is plugin)
    dialog.plugin_list.setCurrentItem(item)
    assert dialog.name_label.textFormat() == Qt.TextFormat.PlainText
    assert dialog.name_label.text() == plugin.name


def test_reload_displays_builtin_plugin_when_user_directory_is_missing(plugin_dialog):
    dialog = plugin_dialog
    dialog.app.internal_plugins_dir = Path(__file__).resolve().parents[1] / "resources/builtin_plugins"
    dialog.app.plugins_dir /= "missing-user-plugins"
    errors = []
    dialog.app.widget_manager.signal.show_and_print_error_message.connect(errors.append)

    dialog.reload_button.click()

    assert errors == []
    plugin_ids = [dialog.plugin_list.item(i).data(Qt.ItemDataRole.UserRole).id
             for i in range(dialog.plugin_list.count())]
    assert "experimentalfarm" in plugin_ids
    assert dialog.details_stack.currentIndex() == 1


@pytest.mark.parametrize("extension", ["png", "jpg", "bmp"])
def test_custom_icon_preserves_color_and_aspect_ratio(plugin_dialog, extension):
    dialog = plugin_dialog
    plugin = dialog.plugin_manager.plugins[1]
    path = dialog.app.plugins_dir / f"custom.{extension}"
    image = QImage(80, 40, QImage.Format.Format_RGB32)
    image.fill(QColor("red"))
    assert image.save(str(path))
    plugin.icon_path = path

    dialog.refresh_plugins()

    pixmap = dialog.plugin_icon.pixmap()
    assert pixmap.width() == 48
    assert pixmap.height() == 24
    assert pixmap.toImage().pixelColor(24, 12).red() > 240
    assert dialog.icon_movies == []


@pytest.mark.parametrize("filename", ["missing.png", "broken.png", "broken.gif"])
def test_unreadable_custom_icon_uses_default(plugin_dialog, filename):
    dialog = plugin_dialog
    plugin = dialog.plugin_manager.plugins[1]
    plugin.icon_path = dialog.app.plugins_dir / filename
    if filename != "missing.png":
        plugin.icon_path.write_bytes(b"not an image")

    dialog.refresh_plugins()

    assert dialog.plugin_list.currentItem().icon().cacheKey() == dialog.default_plugin_icon.cacheKey()
    assert not dialog.plugin_icon.pixmap().isNull()
    assert dialog.icon_movies == []


def test_gif_animates_list_and_details_and_stops_when_hidden(plugin_dialog):
    dialog = plugin_dialog
    dialog.plugin_manager.plugins[1].icon_path = (
        Path(__file__).resolve().parents[1] / "resources/builtin_plugins/experimental_farm/nugget.gif"
    )
    dialog.refresh_plugins()
    assert len(dialog.icon_movies) == 1
    movie = dialog.icon_movies[0]
    dialog.show()
    assert movie.state() == QMovie.MovieState.Running
    first_icon = dialog.plugin_list.currentItem().icon().cacheKey()
    assert movie.jumpToNextFrame()
    assert dialog.plugin_list.currentItem().icon().cacheKey() != first_icon
    assert dialog.plugin_icon.pixmap().toImage() == movie.currentPixmap().toImage()
    dialog.hide()
    assert movie.state() == QMovie.MovieState.NotRunning
    dialog.refresh_plugins()
    assert movie.state() == QMovie.MovieState.NotRunning
    assert len(dialog.icon_movies) == 1


def test_dialog_enables_and_disables_entry_with_context(plugin_dialog):
    dialog = plugin_dialog
    plugin = dialog.plugin_manager.plugins[0]
    contexts = []
    cleanup = Mock()
    def entry(context):
        contexts.append(context)
        context.on_cleanup(cleanup)
    plugin.entry = entry
    dialog.plugin_list.setCurrentRow(1)
    assert dialog.toggle_plugin_button.text() == "Enable plugin"

    dialog.toggle_plugin_button.click()

    assert plugin.enabled
    assert len(contexts) == 1
    assert contexts[0].plugin_id == "net.test:zulu-tools"
    assert dialog.status_label.text() == "Enabled"
    assert dialog.toggle_plugin_button.text() == "Disable plugin"
    assert "net.test:zulu-tools" in dialog.app.settings_manager.get("plugins", PluginSettings).enabled
    dialog.toggle_plugin_button.click()
    assert not plugin.enabled
    cleanup.assert_called_once()
    assert dialog.toggle_plugin_button.text() == "Enable plugin"
    assert "net.test:zulu-tools" not in dialog.app.settings_manager.get("plugins", PluginSettings).enabled


def test_failed_enable_keeps_dialog_disabled_state(plugin_dialog):
    dialog = plugin_dialog
    plugin = dialog.plugin_manager.plugins[0]
    errors = []
    dialog.app.widget_manager.signal.show_and_print_error_message.connect(errors.append)
    plugin.entry = Mock(side_effect=RuntimeError("entry failed"))
    dialog.plugin_list.setCurrentRow(1)

    dialog.toggle_plugin_button.click()

    assert not plugin.enabled
    assert dialog.status_label.text() == "Disabled"
    assert dialog.toggle_plugin_button.text() == "Enable plugin"
    assert dialog.toggle_plugin_button.isEnabled()
    assert len(errors) == 1


def test_toggling_updates_disabled_filter(plugin_dialog):
    dialog = plugin_dialog
    plugin = dialog.plugin_manager.plugins[0]
    plugin.entry = Mock()
    dialog.filter_combo.setCurrentIndex(2)
    assert dialog.plugin_list.count() == 1

    dialog.toggle_plugin_button.click()

    assert plugin.enabled
    assert dialog.plugin_list.count() == 0
    assert dialog.details_stack.currentIndex() == 0
    assert not dialog.toggle_plugin_button.isEnabled()


def test_builtin_entry_is_called_from_dialog(plugin_dialog, caplog):
    dialog = plugin_dialog
    dialog.app.internal_plugins_dir = Path(__file__).resolve().parents[1] / "resources/builtin_plugins"
    dialog.app.plugins_dir /= "missing-user-plugins"
    caplog.set_level(logging.INFO)
    errors = []
    dialog.app.widget_manager.signal.show_and_print_error_message.connect(errors.append)
    dialog.reload_button.click()
    plugin = dialog.plugin_list.currentItem().data(Qt.ItemDataRole.UserRole)

    dialog.toggle_plugin_button.click()

    assert plugin.enabled
    assert "Experimental Farm initialized" in caplog.text
    assert (dialog.app.data_dir / "plugins/net.wei/experimentalfarm").is_dir()
    assert errors == []
    dialog.toggle_plugin_button.click()
    assert not plugin.enabled
