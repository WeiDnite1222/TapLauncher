import threading

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QPushButton,
    QVBoxLayout,
)

from core_lib.game.mod import fabric
from core_lib.game.mod.mod_core import find_useful_part_in_mod_version_manifest
from core_lib.game.version_info import get_available_version_types


class AddModdedVersionDialog(QDialog):
    """
    Create a local mod-loader manifest without creating a profile.

    This dialog is vibed.
    """

    version_created = Signal(str)

    class WorkerSignals(QObject):
        manifest_loaded = Signal(object, object)
        loader_versions_loaded = Signal(str, object, object)
        version_installed = Signal(object, object)

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.manifest_manager = app.game_manager.manifest
        self.root_manifest: dict = {}
        self.worker_signals = self.WorkerSignals(self)

        self.setWindowTitle(self.app.tr_text("Add Modded Version"))
        self.setMinimumWidth(480)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(14)

        title = QLabel(self.app.tr_text("Add Modded Version"))
        title.setObjectName("dialogTitle")
        description = QLabel(self.app.tr_text(
            "Create a local mod-loader version manifest without creating a profile."
        ))
        description.setWordWrap(True)

        form = QFormLayout()
        form.setVerticalSpacing(10)

        self.loader_dropdown = QComboBox()
        self.loader_dropdown.setObjectName("Dropdown")
        self.loader_dropdown.addItem(self.app.tr_text("Fabric"), "fabric")

        self.minecraft_type_dropdown = QComboBox()
        self.minecraft_type_dropdown.setObjectName("Dropdown")
        self.minecraft_version_dropdown = QComboBox()
        self.minecraft_version_dropdown.setObjectName("Dropdown")
        self.loader_version_dropdown = QComboBox()
        self.loader_version_dropdown.setObjectName("Dropdown")

        form.addRow(self.app.tr_text("Mod loader"), self.loader_dropdown)
        form.addRow(self.app.tr_text("Minecraft type"), self.minecraft_type_dropdown)
        form.addRow(self.app.tr_text("Minecraft version"), self.minecraft_version_dropdown)
        form.addRow(self.app.tr_text("Loader version"), self.loader_version_dropdown)

        self.status_label = QLabel()
        self.status_label.setWordWrap(True)

        buttons = QHBoxLayout()
        self.refresh_button = QPushButton(self.app.tr_text("Refresh"))
        self.cancel_button = QPushButton(self.app.tr_text("Cancel"))
        self.add_button = QPushButton(self.app.tr_text("Add Version"))
        self.add_button.setObjectName("saveProfileButton")
        buttons.addWidget(self.refresh_button)
        buttons.addStretch()
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.add_button)

        root.addWidget(title)
        root.addWidget(description)
        root.addLayout(form)
        root.addWidget(self.status_label)
        root.addLayout(buttons)

        self.minecraft_type_dropdown.currentIndexChanged.connect(
            self._update_minecraft_versions
        )
        self.minecraft_version_dropdown.currentIndexChanged.connect(
            self._start_load_loader_versions
        )
        self.refresh_button.clicked.connect(self.load_versions)
        self.cancel_button.clicked.connect(self.reject)
        self.add_button.clicked.connect(self.install_selected_version)

        self.worker_signals.manifest_loaded.connect(self._manifest_loaded)
        self.worker_signals.loader_versions_loaded.connect(
            self._loader_versions_loaded
        )
        self.worker_signals.version_installed.connect(self._version_installed)

        self.load_versions()

    @staticmethod
    def _error_text(error: Exception) -> str:
        return str(getattr(error, "user_message", None) or error)

    def _set_loading(self, loading: bool, status: str = "") -> None:
        self.refresh_button.setEnabled(not loading)
        self.add_button.setEnabled(not loading)
        self.status_label.setText(status)

    def load_versions(self) -> None:
        self._set_loading(True, self.app.tr_text("Loading Minecraft versions..."))
        self.minecraft_type_dropdown.setEnabled(False)
        self.minecraft_version_dropdown.setEnabled(False)
        self.loader_version_dropdown.setEnabled(False)

        def worker():
            try:
                manifest = self.manifest_manager.get_cached_version_manifest()
                if not manifest:
                    raise RuntimeError("Unable to load the Minecraft version manifest.")
                self.worker_signals.manifest_loaded.emit(manifest, None)
            except Exception as error:
                self.worker_signals.manifest_loaded.emit(None, error)

        threading.Thread(target=worker, daemon=True).start()

    def _manifest_loaded(self, manifest, error) -> None:
        if error is not None:
            self._set_loading(False, self.app.tr_text(
                "Unable to load versions: {error}", error=self._error_text(error)
            ))
            return

        self.root_manifest = manifest
        try:
            types = get_available_version_types(manifest)
        except Exception as exc:
            self._set_loading(False, self.app.tr_text(
                "Unable to read version types: {error}", error=self._error_text(exc)
            ))
            return

        types = [item for item in types if isinstance(item, str) and item]
        if "release" in types:
            types.remove("release")
            types.insert(0, "release")

        self.minecraft_type_dropdown.blockSignals(True)
        self.minecraft_type_dropdown.clear()
        self.minecraft_type_dropdown.addItems(types)
        self.minecraft_type_dropdown.blockSignals(False)
        self.minecraft_type_dropdown.setEnabled(True)
        self.minecraft_version_dropdown.setEnabled(True)
        self._update_minecraft_versions()

    def _update_minecraft_versions(self, _index: int = -1) -> None:
        version_type = self.minecraft_type_dropdown.currentText()
        self.minecraft_version_dropdown.blockSignals(True)
        self.minecraft_version_dropdown.clear()

        for version in self.root_manifest.get("versions", []):
            if version.get("type") != version_type:
                continue
            version_id = version.get("id")
            if version_id:
                self.minecraft_version_dropdown.addItem(version_id, version_id)

        self.minecraft_version_dropdown.blockSignals(False)
        self._start_load_loader_versions()

    def _start_load_loader_versions(self, _index: int = -1) -> None:
        minecraft_version = self.minecraft_version_dropdown.currentData()
        self.loader_version_dropdown.clear()
        self.loader_version_dropdown.setEnabled(False)

        if not minecraft_version:
            self._set_loading(False, self.app.tr_text("No Minecraft version is available for this type."))
            return

        self._set_loading(True, self.app.tr_text(
            "Loading Fabric versions for {version}...", version=minecraft_version
        ))

        def worker():
            try:
                loaders = fabric.get_version_support_loader_list(minecraft_version)
                self.worker_signals.loader_versions_loaded.emit(
                    minecraft_version, loaders, None
                )
            except Exception as error:
                self.worker_signals.loader_versions_loaded.emit(
                    minecraft_version, None, error
                )

        threading.Thread(target=worker, daemon=True).start()

    def _loader_versions_loaded(self, minecraft_version, loaders, error) -> None:
        # Ignore an obsolete response after the user selected another version.
        if minecraft_version != self.minecraft_version_dropdown.currentData():
            return

        if error is not None:
            self._set_loading(
                False,
                self.app.tr_text(
                    "Unable to load Fabric versions: {error}",
                    error=self._error_text(error),
                ),
            )
            return

        self.loader_version_dropdown.clear()
        for loader in loaders:
            loader_version = loader.get("version")
            if not loader_version:
                continue
            display_name = loader_version
            if loader.get("stable") is True:
                display_name += " (stable)"
            self.loader_version_dropdown.addItem(display_name, loader)

        self.loader_version_dropdown.setEnabled(
            self.loader_version_dropdown.count() > 0
        )
        self._set_loading(False, self.app.tr_text("Select a loader version to continue."))

    def install_selected_version(self) -> None:
        minecraft_version = self.minecraft_version_dropdown.currentData()
        loader_data = self.loader_version_dropdown.currentData()

        if not minecraft_version or not isinstance(loader_data, dict):
            self.status_label.setText(self.app.tr_text("Select a Minecraft and loader version."))
            return

        loader_version = loader_data.get("version")
        if not loader_version:
            self.status_label.setText(self.app.tr_text("The selected loader version is invalid."))
            return

        self._set_loading(True, self.app.tr_text("Creating the Fabric version manifest..."))
        self.loader_dropdown.setEnabled(False)
        self.minecraft_type_dropdown.setEnabled(False)
        self.minecraft_version_dropdown.setEnabled(False)
        self.loader_version_dropdown.setEnabled(False)

        def worker():
            try:
                # Cache the parent manifest as well, so the new modded version
                # can be resolved immediately when it is selected for launch.
                parent = self.manifest_manager.get_cached_version_manifest(
                    minecraft_version
                )
                if not parent:
                    raise RuntimeError(
                        f"Unable to cache Minecraft {minecraft_version}."
                    )

                version_id = fabric.get_full_version_string(
                    version=minecraft_version,
                    loader_version=loader_version,
                )

                def fetch_manifest(_version_id: str):
                    return (
                        fabric.get_loader_manifest_from_loader_data(
                            minecraft_version, loader_data
                        ),
                        None,
                    )

                manifest = self.manifest_manager.get_cached_custom_version_manifest(
                    version_id,
                    fetch_manifest_handler=fetch_manifest,
                )
                if not manifest:
                    raise RuntimeError("Unable to create the Fabric version manifest.")

                loader_info = find_useful_part_in_mod_version_manifest(manifest)
                if loader_info["id"] != version_id:
                    raise ValueError(
                        f"Manifest ID mismatch: expected {version_id}, "
                        f"got {loader_info['id']}."
                    )
                if loader_info["inheritsFrom"] != minecraft_version:
                    raise ValueError(
                        "The created manifest inherits from an unexpected "
                        "Minecraft version."
                    )

                self.worker_signals.version_installed.emit(version_id, None)
            except Exception as error:
                self.worker_signals.version_installed.emit(None, error)

        threading.Thread(target=worker, daemon=True).start()

    def _version_installed(self, version_id, error) -> None:
        if error is not None:
            self.loader_dropdown.setEnabled(True)
            self.minecraft_type_dropdown.setEnabled(True)
            self.minecraft_version_dropdown.setEnabled(True)
            self.loader_version_dropdown.setEnabled(True)
            self._set_loading(False, self.app.tr_text(
                "Unable to add version: {error}", error=self._error_text(error)
            ))
            return

        self.status_label.setText(self.app.tr_text(
            "Added version {version_id}.", version_id=version_id
        ))
        self.version_created.emit(version_id)
        self.accept()
