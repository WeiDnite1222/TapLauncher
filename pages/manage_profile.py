import shutil
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import (
    QFileDialog, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QScrollArea, QSizePolicy, QSpinBox,
    QVBoxLayout, QWidget,
)

from manager.profile import ProfileDetail, ProfileManager, ProfileSummary, UpdateProfileRequest


class ManageProfileItem(QPushButton):
    selected = Signal(object)

    def __init__(self, app, profile: ProfileSummary, parent=None):
        super().__init__(parent)
        self.profile = profile
        self.setObjectName("manageProfileItem")
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(64)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(12)

        icon_path = Path(profile.icon)
        if not icon_path.is_file():
            icon_path = Path(app.icon_dir, "profile_default.png")
        icon = QLabel()
        icon.setFixedSize(40, 40)
        icon.setPixmap(QIcon(icon_path.as_posix()).pixmap(36, 36))
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


class ManageProfilePage(QWidget):
    """Select a profile on the left and edit its launcher settings on the right."""

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.profile_manager: ProfileManager = app.profile_manager
        self.selected_profile_id: str | None = None
        self.profile_items: dict[str, ManageProfileItem] = {}

        root = QVBoxLayout(self)
        title = QLabel("Manage Profiles (Experimental)")
        title.setObjectName("manageTitle")
        root.addWidget(title)

        columns = QHBoxLayout()
        columns.setSpacing(12)
        root.addLayout(columns, 1)

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
        columns.addWidget(self.options_scroll, 3)

        self.empty_label = QLabel("Select a profile from the list to edit its settings.")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setWordWrap(True)
        self.options_layout.addWidget(self.empty_label, 1)

        self.editor = QFrame()
        self.editor.setObjectName("profileEditor")
        editor_layout = QVBoxLayout(self.editor)
        editor_layout.setSpacing(14)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        form.setVerticalSpacing(12)

        self.name_edit = QLineEdit()
        self.version_edit = QLineEdit()
        self.type_edit = QLineEdit()
        self.game_dir_edit = QLineEdit()
        self.java_args_edit = QLineEdit()
        self.icon_edit = QLineEdit()
        self.width_spin = self._dimension_spin()
        self.height_spin = self._dimension_spin()

        form.addRow("Profile name", self.name_edit)
        form.addRow("Version ID", self.version_edit)
        form.addRow("Profile type", self.type_edit)
        form.addRow("Game directory", self.game_dir_edit)
        form.addRow("Java arguments", self.java_args_edit)
        form.addRow("Icon", self.icon_edit)

        resolution = QHBoxLayout()
        resolution.addWidget(self.width_spin)
        resolution.addWidget(QLabel("×"))
        resolution.addWidget(self.height_spin)
        form.addRow("Resolution", resolution)
        editor_layout.addLayout(form)

        file_actions = QHBoxLayout()
        open_button = QPushButton("Open Profile Folder")
        open_button.clicked.connect(self.open_profile_folder)
        import_button = QPushButton("Import Mods…")
        import_button.clicked.connect(self.import_mods)
        file_actions.addWidget(open_button)
        file_actions.addWidget(import_button)
        file_actions.addStretch()
        editor_layout.addLayout(file_actions)

        actions = QHBoxLayout()
        duplicate_button = QPushButton("Duplicate")
        duplicate_button.clicked.connect(self.duplicate_profile)
        delete_button = QPushButton("Delete")
        delete_button.setObjectName("dangerButton")
        delete_button.clicked.connect(self.delete_profile)
        save_button = QPushButton("Save Changes")
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

        self.profile_manager.profiles_changed.connect(self.load_profiles)
        self.app.apply_qss(Path("manage_profile.qss"), self.setStyleSheet)
        self.load_profiles()

    @staticmethod
    def _scroll_area(name: str) -> QScrollArea:
        area = QScrollArea()
        area.setObjectName(name)
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        return area

    @staticmethod
    def _dimension_spin() -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(0, 16384)
        spin.setSpecialValueText("Default")
        spin.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        return spin

    def load_profiles(self) -> None:
        while self.list_layout.count():
            item = self.list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.profile_items.clear()

        profiles = self.profile_manager.list_profiles()
        for profile in profiles:
            item = ManageProfileItem(self.app, profile, self.list_content)
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

    def _set_detail(self, profile: ProfileDetail) -> None:
        self.name_edit.setText(profile.name)
        self.version_edit.setText(profile.version_id)
        self.type_edit.setText(profile.version_type)
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
                "Set both resolution values, or set both to Default."
            )
            return
        game_dir_text = self.game_dir_edit.text().strip()
        request = UpdateProfileRequest(
            name=self.name_edit.text().strip(),
            version_id=self.version_edit.text().strip(),
            version_type=self.type_edit.text().strip(),
            game_dir=Path(game_dir_text) if game_dir_text else None,
            java_args=self.java_args_edit.text(),
            icon=self.icon_edit.text().strip(),
            resolution=(width, height) if width and height else None,
        )
        if self.profile_manager.validate_update(request).is_valid and self.profile_manager.update_profile(
            self.selected_profile_id, request
        ):
            self.profile_manager.save()
            self.app.widget_manager.signal.show_info_message.emit("Profile settings saved.")
        else:
            errors = self.profile_manager.validate_update(request).errors
            if errors:
                self.app.widget_manager.signal.show_warning_message.emit("\n".join(errors.values()))

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
            self, "Import Mods", "", "Minecraft mods (*.jar *.zip);;All files (*)"
        )
        if not files:
            return
        mods_dir = profile_dir / "mods"
        mods_dir.mkdir(parents=True, exist_ok=True)
        try:
            for source in files:
                shutil.copy2(source, mods_dir / Path(source).name)
        except OSError as error:
            self.app.widget_manager.signal.show_error_message.emit(f"Unable to import mod: {error}")
            return
        self.app.widget_manager.signal.show_info_message.emit(
            f"Imported {len(files)} mod(s) into {mods_dir}."
        )

    def duplicate_profile(self) -> None:
        if self.selected_profile_id is None:
            return
        new_id = self.profile_manager.duplicate_profile(self.selected_profile_id)
        if new_id:
            self.selected_profile_id = new_id
            self.load_profiles()
            self.profile_manager.save()

    def delete_profile(self) -> None:
        if self.selected_profile_id is None:
            return
        answer = QMessageBox.question(
            self, "Delete Profile", "Delete this profile? Game files will not be removed.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            profile_id = self.selected_profile_id
            self.selected_profile_id = None
            if self.profile_manager.remove_profile(profile_id):
                self.profile_manager.save()
