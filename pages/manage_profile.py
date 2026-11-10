import shutil
from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QImageReader
from PySide6.QtWidgets import (
    QFileDialog, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QScrollArea, QSizePolicy, QSpinBox,
    QVBoxLayout, QWidget, QMenu, QComboBox, QTabWidget,
)

from core_lib.qt.hack import base64_to_qicon, prepare_profile_icon
from core_lib.qt.item_button import ItemButton
from manager.profile import ProfileDetail, ProfileManager, ProfileSummary, UpdateProfileRequest, _profile_icon
from manager.game import AvailableVersion
from pages.add_modded_version import AddModdedVersionDialog


class ManageProfileItem(ItemButton):
    selected = Signal(object)

    def __init__(self, app, profile: ProfileSummary,
                 parent=None,
                 delete_callback=None,
                 duplicate_callback=None):
        super().__init__(parent)
        self.app = app
        self.profile = profile
        self.setObjectName("manageProfileItem")
        # Custom row backgrounds cover the full widget, including native macOS margins.
        self.setAttribute(Qt.WidgetAttribute.WA_LayoutUsesWidgetRect)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(64)

        # Callback
        self.delete_callback = delete_callback
        self.duplicate_callback = duplicate_callback

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(12)

        icon = QLabel()
        icon.setFixedSize(40, 40)
        icon.setPixmap(_profile_icon(profile.icon, app.icon_dir).pixmap(36, 36))
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)

        texts = QVBoxLayout()
        texts.setSpacing(1)
        name = QLabel(profile.display_name)
        name.setObjectName("itemName")
        version = QLabel(profile.version_id)
        version.setObjectName("itemVersion")
        texts.addWidget(name)
        texts.addWidget(version)

        layout.addWidget(icon)
        layout.addLayout(texts, 1)
        self.clicked.connect(lambda: self.selected.emit(self.profile))

        # Enable right click menu
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_right_click_menu)

    def show_right_click_menu(self, position):
        menu = QMenu(self)

        duplicate_action = menu.addAction(self.app.tr_text("Duplicate"))
        remove_action = menu.addAction(self.app.tr_text("Delete"))

        menu.addAction(duplicate_action)
        menu.addAction(remove_action)

        def duplicate_callback():
            self.duplicate_callback(self.profile)

        def delete_callback():
            self.delete_callback(self.profile)

        if callable(self.duplicate_callback):
            duplicate_action.triggered.connect(duplicate_callback)

        if callable(self.delete_callback):
            remove_action.triggered.connect(delete_callback)

        global_position = self.mapToGlobal(position)
        menu.exec(global_position)



class ManageProfilePage(QWidget):
    """
    Profile manage page
    """

    selected_profile_changed = Signal(object)

    VERSION_CATEGORIES = (
        ("Vanilla", "vanilla"),
        ("Modded", "modded"),
        ("Custom", "custom"),
    )

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.profile_manager: ProfileManager = app.profile_manager
        self.manifest_manager = app.game_manager.manifest
        self.widget_manager = app.widget_manager
        self.selected_profile_id: str | None = None
        self.profile_items: dict[str, ManageProfileItem] = {}
        self.version_options: list[AvailableVersion] = []

        root = QVBoxLayout(self)
        title = QLabel(self.app.tr_text("Manage Profiles"))
        title.setObjectName("manageTitle")
        root.addWidget(title)

        columns = QHBoxLayout()
        columns.setSpacing(12)
        root.addLayout(columns, 1)

        # Widgets
        self.list_scroll = self._scroll_area("manageProfileListScroll")
        self.list_content = QWidget()
        self.list_layout = QVBoxLayout(self.list_content)
        self.list_layout.setContentsMargins(6, 6, 6, 6)
        self.list_layout.setSpacing(4)
        self.list_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.list_scroll.setWidget(self.list_content)
        self.list_scroll.setMinimumWidth(260)
        self.list_scroll.setMaximumWidth(380)
        columns.addWidget(self.list_scroll, 2)

        self.options_scroll = self._scroll_area("manageProfileOptionsScroll")
        self.options_content = QWidget()
        self.options_layout = QVBoxLayout(self.options_content)
        self.options_layout.setContentsMargins(20, 16, 20, 20)
        self.options_layout.setSpacing(14)
        self.options_scroll.setWidget(self.options_content)

        # Tabs
        self.profile_tabs = QTabWidget()
        self.empty_label = QLabel(self.app.tr_text("Select a profile from the list to edit its settings."))
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setWordWrap(True)
        self.options_layout.addWidget(self.empty_label, 1)
        columns.addWidget(self.profile_tabs, 3)

        self.editor = QFrame()
        self.editor.setObjectName("profileEditor")
        editor_layout = QVBoxLayout(self.editor)
        editor_layout.setSpacing(14)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        form.setVerticalSpacing(12)

        # Icon & Name
        self.profile_icon = QLabel()
        self.profile_icon.setFixedSize(64, 64)
        self.profile_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.name_edit = QLineEdit()
        self.replace_icon_btn = QPushButton(self.app.tr_text("Replace Icon"))
        self.reset_icon_btn = QPushButton(self.app.tr_text("Reset Icon"))
        self.reset_icon_btn.clicked.connect(self._reset_icon)

        profile_head_h_layout = QHBoxLayout()
        profile_head_v_layout = QVBoxLayout()

        profile_head_v_layout.addWidget(self.name_edit)
        icon_actions = QHBoxLayout()
        icon_actions.addWidget(self.replace_icon_btn)
        icon_actions.addWidget(self.reset_icon_btn)
        profile_head_v_layout.addLayout(icon_actions)
        profile_head_h_layout.addWidget(self.profile_icon)
        profile_head_h_layout.addLayout(profile_head_v_layout)

        self.version_dropdown = QComboBox()
        self.version_dropdown.setObjectName("Dropdown")
        self.version_dropdown.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        self.version_dropdown.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.version_dropdown.setMinimumContentsLength(24)
        self.type_dropdown = QComboBox()
        self.type_dropdown.setObjectName("Dropdown")
        self.game_dir_edit = QLineEdit()
        self.java_args_edit = QLineEdit()
        self.icon_edit = QLineEdit(self.editor)
        self.icon_edit.hide()
        self.width_spin = self._dimension_spin()
        self.height_spin = self._dimension_spin()

        form.addRow(self.app.tr_text("Type"), self.type_dropdown)
        form.addRow(self.app.tr_text("Version"), self.version_dropdown)
        form.addRow(self.app.tr_text("Game directory"), self.game_dir_edit)
        form.addRow(self.app.tr_text("Java arguments"), self.java_args_edit)

        resolution = QHBoxLayout()
        resolution.addWidget(self.width_spin)
        resolution.addWidget(QLabel("×"))
        resolution.addWidget(self.height_spin)
        form.addRow(self.app.tr_text("Resolution"), resolution)
        editor_layout.addLayout(profile_head_h_layout)
        editor_layout.addLayout(form)

        file_actions = QHBoxLayout()
        add_version_button = QPushButton(self.app.tr_text("Add Modded Version"))
        add_version_button.clicked.connect(self.open_add_modded_version_dialog)
        open_button = QPushButton(self.app.tr_text("Open Profile Folder"))
        open_button.clicked.connect(self.open_profile_folder)
        import_button = QPushButton(self.app.tr_text("Import Mods…"))
        import_button.clicked.connect(self.import_mods)
        file_actions.addWidget(add_version_button)
        file_actions.addWidget(open_button)
        file_actions.addWidget(import_button)
        file_actions.addStretch()
        editor_layout.addLayout(file_actions)

        self.plugin_actions = QHBoxLayout()
        self.plugin_actions.addStretch()
        editor_layout.addLayout(self.plugin_actions)

        actions = QHBoxLayout()
        duplicate_button = QPushButton(self.app.tr_text("Duplicate"))
        duplicate_button.clicked.connect(self.duplicate_profile)
        delete_button = QPushButton(self.app.tr_text("Delete"))
        delete_button.setObjectName("dangerButton")
        delete_button.clicked.connect(self.delete_profile)
        save_button = QPushButton(self.app.tr_text("Save Changes"))
        save_button.setObjectName("saveProfileButton")
        save_button.clicked.connect(self.save_profile)
        actions.addWidget(duplicate_button)
        actions.addWidget(delete_button)
        actions.addStretch()
        actions.addWidget(save_button)
        editor_layout.addLayout(actions)

        self.options_layout.addWidget(self.editor)
        self.options_layout.addStretch()
        self.editor.hide()

        self.type_dropdown.currentIndexChanged.connect(self._filter_versions)
        self.profile_manager.profiles_changed.connect(self.refresh_profiles)
        self.replace_icon_btn.clicked.connect(self._replace_icon)
        self.app.apply_qss(Path("manage_profile.qss"), self.setStyleSheet)
        self._load_type_dropdown()
        self.refresh_profiles()

        self._tabs = {
            "Profile settings": self.options_scroll
        }

        self.app.i18n.language_changed.connect(self.load_profile_page_for_tabs)
        self.load_profile_page_for_tabs()

    def load_profile_page_for_tabs(self, *_args):
        for tab_name, page in self._tabs.items():
            index = self.profile_tabs.indexOf(page)
            if index < 0:
                self.profile_tabs.addTab(page, self.app.tr_text(tab_name))
            else:
                self.profile_tabs.setTabText(index, self.app.tr_text(tab_name))

    @staticmethod
    def _scroll_area(name: str) -> QScrollArea:
        area = QScrollArea()
        area.setObjectName(name)
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        return area

    def _dimension_spin(self) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(0, 16384)
        spin.setSpecialValueText(self.app.tr_text("Default"))
        spin.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        return spin

    def _load_type_dropdown(self) -> None:
        self.type_dropdown.blockSignals(True)
        self.type_dropdown.clear()
        for display_name, category in self.VERSION_CATEGORIES:
            self.type_dropdown.addItem(self.app.tr_text(display_name), category)
        self.type_dropdown.blockSignals(False)

    def refresh_profiles(self) -> None:
        self.version_options = self.manifest_manager.list_available_profile_versions()
        self.load_profiles()

    def _filter_versions(self, _index: int = -1) -> None:
        selected_category = self.type_dropdown.currentData()
        selected_option = self.version_dropdown.currentData()
        selected_id = (
            selected_option.id
            if isinstance(selected_option, AvailableVersion)
            else None
        )

        self.version_dropdown.blockSignals(True)
        self.version_dropdown.clear()

        for option in self.version_options:
            if option.source == selected_category:
                self.version_dropdown.addItem(option.display_name, option)

        if selected_id is not None:
            self._select_version(selected_id)

        self.version_dropdown.blockSignals(False)

    def load_profiles(self) -> None:
        while self.list_layout.count():
            item = self.list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self.profile_items.clear()

        profiles = self.profile_manager.list_profiles()
        for profile in profiles:
            item = ManageProfileItem(self.app, profile,
                                     self.list_content,
                                     duplicate_callback=self.duplicate_profile,
                                     delete_callback=self.delete_profile)
            item.selected.connect(self.select_profile)
            self.profile_items[profile.id] = item
            self.list_layout.addWidget(item)

        available_ids = {profile.id for profile in profiles}

        if self.selected_profile_id not in available_ids:
            self.selected_profile_id = None

        if self.selected_profile_id is None and profiles:
            current = self.profile_manager.get_current_profile_id()
            selected = next((p for p in profiles if p.id == current), profiles[0])
            self.select_profile(selected)
        elif self.selected_profile_id:
            profile = next(p for p in profiles if p.id == self.selected_profile_id)
            self.select_profile(profile)
        else:
            self.editor.hide()
            self.empty_label.show()
            self.selected_profile_changed.emit(None)

    def select_profile(self, profile: ProfileSummary) -> None:
        detail = self.profile_manager.get_profile(profile.id)

        if detail is None:
            return

        self.selected_profile_id = profile.id

        for profile_id, item in self.profile_items.items():
            item.setChecked(profile_id == profile.id)

        self._set_detail(detail)
        self.empty_label.hide()
        self.editor.show()
        self.selected_profile_changed.emit(detail)

    def _select_version(self, version_id: str) -> None:
        for index in range(self.version_dropdown.count()):
            data = self.version_dropdown.itemData(index)

            if isinstance(data, AvailableVersion) and data.id == version_id:
                self.version_dropdown.setCurrentIndex(index)
                return

    def _select_type(self, category: str) -> None:
        index = self.type_dropdown.findData(category)
        if index >= 0:
            self.type_dropdown.setCurrentIndex(index)

    def _set_detail(self, profile: ProfileDetail) -> None:
        self.name_edit.setText(profile.name)
        profile_icon = _profile_icon(profile.icon, self.app.icon_dir)
        self.profile_icon.setPixmap(profile_icon.pixmap(64, 64))

        option = next(
            (item for item in self.version_options if item.id == profile.version_id),
            None,
        )

        # Preserve profiles imported from another launcher, even when their
        # version manifest is not available locally anymore.
        if option is None:
            option = AvailableVersion(
                id=profile.version_id,
                display_name=f"{profile.version_id} (Unavailable)",
                version_type=profile.version_type or "custom",
                source="custom",
            )
            self.version_options.append(option)

        self._select_type(option.source)
        self._filter_versions()
        self._select_version(profile.version_id)
        self.game_dir_edit.setText(str(profile.game_dir or ""))
        self.java_args_edit.setText(profile.java_args)
        self.icon_edit.setText(profile.icon)
        width, height = profile.resolution or (0, 0)
        self.width_spin.setValue(width)
        self.height_spin.setValue(height)

    def _profile_dir(self) -> Path | None:
        if self.selected_profile_id is None:
            return None

        detail = self.profile_manager.get_profile(self.selected_profile_id)

        if detail is None:
            return None

        return detail.game_dir or Path(self.app.default_game_dir)

    def save_profile(self) -> None:
        if self.selected_profile_id is None:
            return

        width, height = self.width_spin.value(), self.height_spin.value()

        if (width == 0) != (height == 0):
            self.app.widget_manager.signal.show_warning_message.emit(
                self.app.tr_text("Set both resolution values, or set both to Default.")
            )
            return

        game_dir_text = self.game_dir_edit.text().strip()
        version = self.version_dropdown.currentData()

        if not isinstance(version, AvailableVersion):
            self.app.widget_manager.signal.show_warning_message.emit(
                self.app.tr_text("Select a version.")
            )
            return

        request = UpdateProfileRequest(
            name=self.name_edit.text().strip(),
            version_id=version.id,
            version_type=version.version_type,
            game_dir=Path(game_dir_text) if game_dir_text else None,
            java_args=self.java_args_edit.text(),
            icon=self.icon_edit.text().strip(),
            resolution=(width, height) if width and height else None,
        )

        if self.profile_manager.validate_update(request).is_valid and self.profile_manager.update_profile(
            self.selected_profile_id, request
        ):
            self.app.widget_manager.signal.show_info_message.emit(
                self.app.tr_text("Profile settings saved.")
            )
        else:
            errors = self.profile_manager.validate_update(request).errors
            if errors:
                self.app.widget_manager.signal.show_warning_message.emit("\n".join(errors.values()))

    def open_add_modded_version_dialog(self) -> None:
        dialog = AddModdedVersionDialog(self.app, self)
        dialog.version_created.connect(self._modded_version_created)
        dialog.exec()

    def _modded_version_created(self, version_id: str) -> None:
        self.version_options = self.manifest_manager.list_available_profile_versions()
        # self._select_type("modded")
        # self._filter_versions()
        # self._select_version(version_id)
        self.app.widget_manager.signal.show_info_message.emit(
            self.app.tr_text("Modded version {version_id} added.", version_id=version_id)
        )

    def open_profile_folder(self) -> None:
        profile_dir = self._profile_dir()

        if profile_dir is None:
            return

        profile_dir.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(profile_dir.resolve())))

    def import_mods(self) -> None:
        profile_dir = self._profile_dir()

        if profile_dir is None:
            return

        files, _ = QFileDialog.getOpenFileNames(
            self, self.app.tr_text("Import Mods"), "", "Minecraft mods (*.jar *.zip);;All files (*)"
        )

        if not files:
            return

        mods_dir = profile_dir / "mods"
        mods_dir.mkdir(parents=True, exist_ok=True)

        try:
            for source in files:
                shutil.copy2(source, mods_dir / Path(source).name)
        except OSError as error:
            self.app.widget_manager.signal.show_error_message.emit(
                self.app.tr_text("Unable to import mod: {error}", error=error)
            )
            return

        self.app.widget_manager.signal.show_info_message.emit(
            self.app.tr_text(
                "Imported {count} mod(s) into {directory}.",
                count=len(files), directory=mods_dir,
            )
        )

    def duplicate_profile(self, profile: ProfileSummary | None=None) -> None:
        if self.selected_profile_id is None and profile is None:
            return

        profile_id = self.selected_profile_id

        new_id = self.profile_manager.duplicate_profile(profile_id)

        if new_id:
            self.selected_profile_id = new_id
            self.load_profiles()

    def delete_profile(self, profile: ProfileSummary | None=None) -> None:
        if self.selected_profile_id is None and profile is None:
            return

        profile_id = self.selected_profile_id

        answer = QMessageBox.question(
            self,
            self.app.tr_text("Delete Profile"),
            self.app.tr_text("Delete this profile? Game files will not be removed."),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            if self.profile_manager.remove_profile(profile_id):
                self.selected_profile_id = None

    def add_page(self, page_name: str, page: QScrollArea) -> Callable[[], None]:
        """Add a plugin tab and return an idempotent cleanup callback."""
        if not isinstance(page_name, str) or not page_name.strip():
            raise ValueError("Invalid page name")

        if not isinstance(page, QScrollArea):
            raise ValueError("Page must be a QScrollArea")

        if page_name in self._tabs:
            raise ValueError("Page name already exists")
        if page in self._tabs.values():
            raise ValueError("Page is already registered")

        self._tabs[page_name] = page
        self.load_profile_page_for_tabs()

        def remove_page():
            # An old cleanup callback must not remove a replacement tab.
            if self._tabs.get(page_name) is page:
                self.remove_page(page_name)

        return remove_page

    def remove_page(self, page_name: str) -> bool:
        if page_name == "Profile settings":
            raise ValueError("The profile settings page cannot be removed")
        page = self._tabs.pop(page_name, None)
        if page is None:
            return False
        index = self.profile_tabs.indexOf(page)
        if index >= 0:
            self.profile_tabs.removeTab(index)
        page.hide()
        page.deleteLater()
        return True

    def register_plugin_apis(self, plugin_manager):
        plugin_manager.register_api("launcher.manage_profile_page.add_page", self.add_page)
        plugin_manager.register_api("launcher.manage_profile_page.remove_page", self.remove_page)
        plugin_manager.register_api("launcher.manage_profile_page.subscribe_profile", self.subscribe_profile)
        plugin_manager.register_api("launcher.manage_profile_page.add_action", self.add_plugin_action)

    def add_plugin_action(self, text: str, callback: Callable) -> Callable[[], None]:
        """Add an editor action and return an idempotent cleanup callback."""
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Invalid action text")
        if not callable(callback):
            raise TypeError("Action callback must be callable")
        button = QPushButton(text, self.editor)
        button.clicked.connect(lambda: callback())
        self.plugin_actions.insertWidget(self.plugin_actions.count() - 1, button)
        removed = False

        def cleanup():
            nonlocal removed
            if removed:
                return
            removed = True
            self.plugin_actions.removeWidget(button)
            button.hide()
            button.setEnabled(False)
            button.clicked.disconnect()
            button.deleteLater()

        return cleanup

    def subscribe_profile(self, callback: Callable) -> Callable[[], None]:
        """Send saved details for the editor selection, including the initial state."""
        if not callable(callback):
            raise TypeError("Profile callback must be callable")
        self.selected_profile_changed.connect(callback)
        connected = True

        def cleanup():
            nonlocal connected
            if connected:
                self.selected_profile_changed.disconnect(callback)
                connected = False

        try:
            detail = (self.profile_manager.get_profile(self.selected_profile_id)
                      if self.selected_profile_id is not None else None)
            callback(detail)
        except BaseException:
            cleanup()
            raise
        return cleanup

    def _reset_icon(self):
        if self.selected_profile_id is None:
            return
        self.icon_edit.clear()
        self.profile_icon.setPixmap(_profile_icon("", self.app.icon_dir).pixmap(64, 64))

    def _replace_icon(self):
        profile_id = self.selected_profile_id

        if not profile_id or self.profile_manager.get_profile(profile_id) is None:
            self.widget_manager.signal.show_warning_message.emit(
                self.app.tr_text("Select a profile before replacing the icon")
            )
            return

        formats = " ".join(
            "*." + bytes(fmt).decode("ascii")
            for fmt in QImageReader.supportedImageFormats()
        )
        filename, _ = QFileDialog.getOpenFileName(
            self, self.app.tr_text("Replace Icon"), "",
            self.app.tr_text("Images") + f" ({formats});;" + self.app.tr_text("All files") + " (*)",
        )
        if not filename:
            return
        try:
            path = Path(filename)
            value, resized = prepare_profile_icon(path)
            icon = base64_to_qicon(value)
            if icon.isNull():
                raise ValueError(self.app.tr_text("Image format is not supported."))
        except (OSError, ValueError) as error:
            self.widget_manager.signal.show_error_message.emit(self.app.tr_text(str(error)))
            return
        if resized:
            self.widget_manager.signal.show_info_message.emit(self.app.tr_text(
                "This image exceeds 128 x 128 pixels and will be resized to 128 x 128."
            ))
        self.icon_edit.setText(value)
        self.profile_icon.setPixmap(icon.pixmap(64, 64))
