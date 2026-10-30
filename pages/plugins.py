from pathlib import Path

from PySide6.QtCore import Qt, QSize, QUrl, QTimer
from PySide6.QtGui import QDesktopServices, QIcon, QPixmap, QMovie
from PySide6.QtWidgets import (
    QWidget, QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QPushButton, QComboBox, QSplitter,
    QStackedWidget, QScrollArea, QFormLayout, QDialogButtonBox, QSizePolicy, QTextBrowser, QFrame,
)

from manager.plugins import Plugin
from manager.settings_models import PluginSettings


class PluginsDialog(QDialog):
    def __init__(self, app, plugin_manager, parent=None):
        super().__init__(parent)
        self.app = app
        self.plugin_manager = plugin_manager
        self.icon_movies: list[QMovie] = []
        self.default_plugin_icon = self.app.get_icon(Path(self.app.icon_dir, "plugin.png"))
        self.setWindowIcon(self.default_plugin_icon)
        self.setObjectName("pluginsDialog")
        self.resize(960, 620)
        self.setMinimumSize(720, 480)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(14)

        header = QHBoxLayout()
        self.title_label = QLabel()
        self.title_label.setObjectName("pluginsTitle")
        self.reload_button = QPushButton()
        self.reload_button.setIcon(self.app.get_icon(Path(self.app.icon_dir, "refresh.png")))
        self.folder_button = QPushButton()
        self.folder_button.setIcon(self.app.get_icon(Path(self.app.icon_dir, "file.png")))

        header.addWidget(self.title_label)
        header.addStretch()
        header.addWidget(self.folder_button)
        header.addWidget(self.reload_button)
        layout.addLayout(header)

        # Split plugin list and details
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        sidebar = QWidget()
        sidebar.setMinimumWidth(260)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 0, 12, 0)
        sidebar_layout.setSpacing(10)

        # Label
        self.installed_label = QLabel()
        self.installed_label.setObjectName("pluginsSectionTitle")

        self.search_edit = QLineEdit()
        self.search_edit.setClearButtonEnabled(True)
        self.filter_combo = QComboBox()
        # Plugin state filter
        for state in ("all", "enabled", "disabled"):
            self.filter_combo.addItem("", state)

        # Plugin list
        self.plugin_list = QListWidget()
        self.plugin_list.setObjectName("pluginList")
        self.plugin_list.setIconSize(QSize(32, 32))
        self.plugin_list.setSpacing(3)
        self.plugin_list.setWordWrap(True)
        self.plugin_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.count_label = QLabel()
        self.count_label.setObjectName("pluginsMuted")

        # Bind widgets
        sidebar_layout.addWidget(self.installed_label)
        sidebar_layout.addWidget(self.search_edit)
        sidebar_layout.addWidget(self.filter_combo)
        sidebar_layout.addWidget(self.plugin_list, 1)
        sidebar_layout.addWidget(self.count_label)
        splitter.addWidget(sidebar)

        # Stack widget (For plugin details)
        self.details_stack = QStackedWidget()

        empty_page = QWidget()
        empty_layout = QVBoxLayout(empty_page)
        empty_layout.addStretch()

        self.empty_title = QLabel()
        self.empty_title.setObjectName("pluginsEmptyTitle")
        self.empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_text = QLabel()
        self.empty_text.setObjectName("pluginsMuted")
        self.empty_text.setWordWrap(True)
        self.empty_text.setAlignment(Qt.AlignmentFlag.AlignCenter)

        empty_layout.addWidget(self.empty_title)
        empty_layout.addWidget(self.empty_text)
        empty_layout.addStretch()
        self.details_stack.addWidget(empty_page)

        # Scroll area for plugin details
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)

        details = QWidget()
        details_layout = QVBoxLayout(details)
        details_layout.setContentsMargins(24, 20, 20, 20)
        details_layout.setSpacing(18)

        # Plugin identity inside the details layout
        identity = QHBoxLayout()
        self.plugin_icon = QLabel()
        self.plugin_icon.setObjectName("pluginIcon")
        self.plugin_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.plugin_icon.setFixedSize(56, 56)
        self.plugin_icon.setPixmap(self.default_plugin_icon.pixmap(QSize(48, 48)))

        identity.addWidget(self.plugin_icon)
        identity_text = QVBoxLayout()

        self.name_label = QLabel()
        self.name_label.setObjectName("pluginName")
        self.name_label.setWordWrap(True)
        self.group_label = QLabel()
        self.group_label.setObjectName("pluginsMuted")
        self.group_label.setWordWrap(True)

        identity_text.addWidget(self.name_label)
        identity_text.addWidget(self.group_label)
        identity.addLayout(identity_text, 1)
        details_layout.addLayout(identity)

        # Status of the plugin
        self.status_label = QLabel()
        self.status_label.setObjectName("pluginsMuted")
        details_layout.addWidget(self.status_label)

        # Plugin description
        self.overview_label = QLabel()
        self.overview_label.setObjectName("pluginsSectionTitle")
        self.description_browser = QTextBrowser() # use QTextBrowser for Markdown support
        self.description_browser.setFrameShape(QFrame.Shape.NoFrame)
        details_layout.addWidget(self.overview_label)
        details_layout.addWidget(self.description_browser)

        # Metadata
        metadata = QFormLayout()
        metadata.setHorizontalSpacing(24)
        metadata.setVerticalSpacing(14)
        metadata.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        metadata.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)

        self.field_labels = {}
        self.field_values = {}

        for key in ("Version", "Plugin ID", "Group", "Required API version", "Location"):
            title = QLabel()
            title.setObjectName("pluginsMuted")
            value = QLabel()
            value.setWordWrap(True)
            value.setMinimumWidth(0)
            value.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            value.setTextFormat(Qt.TextFormat.PlainText)
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            metadata.addRow(title, value)
            self.field_labels[key] = title
            self.field_values[key] = value

        details_layout.addLayout(metadata)

        # Buttons
        self.open_plugin_button = QPushButton()
        self.open_plugin_button.setIcon(self.app.get_icon(Path(self.app.icon_dir, "file.png")))
        self.toggle_plugin_button = QPushButton()

        details_layout.addWidget(self.open_plugin_button, 0, Qt.AlignmentFlag.AlignLeft)
        details_layout.addWidget(self.toggle_plugin_button, 0, Qt.AlignmentFlag.AlignLeft)
        details_layout.addStretch()

        scroll.setWidget(details)
        self.details_stack.addWidget(scroll)

        splitter.addWidget(self.details_stack)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([310, 610])
        layout.addWidget(splitter, 1)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        # Plugin metadata is plain text, never HTML.
        for label in (self.name_label, self.group_label, self.plugin_icon):
            label.setTextFormat(Qt.TextFormat.PlainText)

        # Bind events
        self.search_edit.textChanged.connect(self.refresh_plugins)
        self.filter_combo.currentIndexChanged.connect(self.refresh_plugins)
        self.plugin_list.currentItemChanged.connect(self._show_plugin_details)
        self.reload_button.clicked.connect(self.reload_plugins)
        self.folder_button.clicked.connect(self._open_plugins_directory)
        self.open_plugin_button.clicked.connect(self._open_selected_directory)
        self.toggle_plugin_button.clicked.connect(self._toggle_selected_plugin)
        self.plugin_manager.signals.plugins_loaded.connect(self.refresh_plugins)
        self.plugin_manager.signals.plugin_state_changed.connect(self.refresh_plugins)
        self.app.i18n.language_changed.connect(self.retranslate_ui)

        # Apply qss
        self.app.apply_qss(Path("plugins.qss"), self.setStyleSheet)

        # Apply translations
        self.retranslate_ui()

    def retranslate_ui(self, *_args):
        tr = self.app.tr_text

        self.setWindowTitle(tr("Plugins"))

        self.title_label.setText(tr("Plugins"))
        self.installed_label.setText(tr("Installed"))
        self.reload_button.setText(tr("Reload plugins"))
        self.folder_button.setText(tr("Plugins folder"))

        self.search_edit.setPlaceholderText(tr("Search plugins…"))
        self.search_edit.setAccessibleName(tr("Search plugins…"))
        self.filter_combo.setAccessibleName(tr("Filter plugins"))

        for index, text in enumerate(("All plugins", "Enabled", "Disabled")):
            self.filter_combo.setItemText(index, tr(text))

        self.overview_label.setText(tr("Overview"))
        self.description_browser.setText(tr("This plugin does not provide a description."))

        self.open_plugin_button.setText(tr("Open plugin folder"))
        self.buttons.button(QDialogButtonBox.StandardButton.Close).setText(tr("Close"))

        for key, label in self.field_labels.items():
            label.setText(tr(key))

        self.refresh_plugins()

    def refresh_plugins(self, *_args):
        current = self.plugin_list.currentItem()

        selected_path = current.data(Qt.ItemDataRole.UserRole).path if current else None
        query = self.search_edit.text().strip().casefold()
        state = self.filter_combo.currentData()

        plugins = sorted(self.plugin_manager.plugins, key=lambda entry: entry.name.casefold())
        for movie in self.icon_movies:
            movie.stop()
            movie.frameChanged.disconnect()
            movie.error.disconnect()
            movie.deleteLater()
        self.icon_movies.clear()
        self.plugin_list.blockSignals(True)
        self.plugin_list.clear()

        selected_item = None
        for plugin in plugins:
            if query and query not in f"{plugin.name} {plugin.group} {plugin.id}".casefold():
                continue
            if (state == "enabled" and not plugin.enabled) or (state == "disabled" and plugin.enabled):
                continue
            item = QListWidgetItem(f"{plugin.name}\n{plugin.group} · {plugin.version}")
            item.setIcon(self.default_plugin_icon)
            item.setSizeHint(QSize(240, 70))
            item.setData(Qt.ItemDataRole.UserRole, plugin)
            self.plugin_list.addItem(item)
            self._load_plugin_icon(item, plugin)
            if plugin.path == selected_path:
                selected_item = item

        if self.plugin_list.count():
            self.plugin_list.setCurrentItem(selected_item or self.plugin_list.item(0))

        self.plugin_list.blockSignals(False)
        self.count_label.setText(self.app.tr_text(
            "{visible} of {total} plugins", visible=self.plugin_list.count(), total=len(plugins),
        ))
        self._show_plugin_details(self.plugin_list.currentItem())

    def _show_plugin_details(self, item, _previous=None):
        tr = self.app.tr_text
        if item is None:
            self.toggle_plugin_button.setEnabled(False)
            self.details_stack.setCurrentIndex(0)
            if self.plugin_manager.plugins:
                self.empty_title.setText(tr("No matching plugins"))
                self.empty_text.setText(tr("Try another search or change the filter."))
            else:
                self.empty_title.setText(tr("No plugins loaded"))
                self.empty_text.setText(tr("Add plugins to your plugins folder, then click Reload plugins."))
            return

        plugin: Plugin = item.data(Qt.ItemDataRole.UserRole)

        if plugin.description:
            self.description_browser.setMarkdown(plugin.description)
        else:
            self.description_browser.setText(tr("This plugin does not provide a description."))

        self.toggle_plugin_button.setText(tr("Disable plugin") if plugin.enabled else tr("Enable plugin"))
        self.toggle_plugin_button.setEnabled(not plugin.is_changing_state)
        self.details_stack.setCurrentIndex(1)
        self.plugin_icon.setPixmap(item.icon().pixmap(QSize(48, 48)))
        self.name_label.setText(plugin.name)
        self.group_label.setText(plugin.group)
        self.status_label.setText(tr("Enabled") if plugin.enabled else tr("Disabled"))
        values = {
            "Version": plugin.version,
            "Plugin ID": plugin.id,
            "Group": plugin.group,
            "Required API version": str(plugin.api_version_range),
            "Location": str(plugin.path),
        }

        for key, value in values.items():
            self.field_values[key].setText(value)

    def _toggle_selected_plugin(self):
        item: QListWidgetItem | None = self.plugin_list.currentItem()
        if item is None:
            return
        plugin: Plugin = item.data(Qt.ItemDataRole.UserRole)
        self.toggle_plugin_button.setEnabled(False)
        try:
            self.plugin_manager.set_plugin_enabled(plugin, not plugin.enabled)
        finally:
            self._show_plugin_details(self.plugin_list.currentItem())

    def _load_plugin_icon(self, item: QListWidgetItem, plugin: Plugin):
        path = plugin.icon_path
        if path is None or path.suffix.lower() not in (".gif", ".png", ".jpg", ".jpeg", ".bmp"):
            return

        # Load custom artwork directly to preserve its original colors.
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            return
        item.setIcon(QIcon(pixmap))
        if path.suffix.lower() != ".gif":
            return

        movie = QMovie(str(path), parent=self)
        if not movie.isValid():
            movie.deleteLater()
            return
        movie.setScaledSize(pixmap.size().scaled(QSize(48, 48), Qt.AspectRatioMode.KeepAspectRatio))
        movie.frameChanged.connect(lambda _frame, target=item, animation=movie:
                                   self._update_plugin_movie(target, animation))
        movie.error.connect(lambda _error, target=item, animation=movie:
                            self._stop_plugin_movie(target, animation))
        self.icon_movies.append(movie)
        movie.jumpToFrame(0)
        if self.isVisible():
            movie.start()

    def _update_plugin_movie(self, item: QListWidgetItem, movie: QMovie):
        pixmap = movie.currentPixmap()
        if pixmap.isNull():
            return
        item.setIcon(QIcon(pixmap))
        if self.plugin_list.currentItem() is item:
            self.plugin_icon.setPixmap(pixmap)

    def _stop_plugin_movie(self, item: QListWidgetItem, movie: QMovie):
        movie.stop()
        item.setIcon(self.default_plugin_icon)
        if self.plugin_list.currentItem() is item:
            self.plugin_icon.setPixmap(self.default_plugin_icon.pixmap(QSize(48, 48)))

    def showEvent(self, event):
        super().showEvent(event)
        for movie in self.icon_movies:
            movie.start()
        QTimer.singleShot(0, self._show_plugin_warning)

    def _show_plugin_warning(self):
        settings_manager = self.app.settings_manager
        settings = settings_manager.get("plugins", PluginSettings)
        if settings.is_plugin_warning_shown:
            return

        settings_manager.set("plugins", settings.model_copy(update={"is_plugin_warning_shown": True}))
        self.app.widget_manager.signal.show_warning_message.emit(self.app.tr_text(
            "Plugins can run code on your computer and access your files and account data. "
            "Only enable plugins from sources you trust."
        ))
        try:
            settings_manager.save()
        except OSError as error:
            self.app.logger.warning("Failed to save plugin warning preference: %s", error)

    def hideEvent(self, event):
        for movie in self.icon_movies:
            movie.stop()
        super().hideEvent(event)

    def reload_plugins(self):
        self.reload_button.setEnabled(False)
        try:
            self.plugin_manager.signals.reload_plugins.emit()
        finally:
            self.reload_button.setEnabled(True)

    def _open_directory(self, path: Path):
        try:
            path.mkdir(parents=True, exist_ok=True)
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve()))):
                raise OSError(self.app.tr_text("Unable to open folder: {path}", path=path))
        except OSError as e:
            self.app.widget_manager.signal.show_and_print_error_message.emit({
                "title": self.app.tr_text("Plugin Error"),
                "message": str(e),
                "error": str(e),
            })

    def _open_plugins_directory(self):
        self._open_directory(self.app.plugins_dir)

    def _open_selected_directory(self):
        item = self.plugin_list.currentItem()
        if item:
            self._open_directory(item.data(Qt.ItemDataRole.UserRole).path)
