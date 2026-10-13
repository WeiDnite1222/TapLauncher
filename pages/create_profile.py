import threading
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QObject, Signal, Slot
from PySide6.QtWidgets import QWidget, QVBoxLayout, QComboBox, QListWidget, QPushButton, QLabel, QHBoxLayout, \
    QSizePolicy, QListWidgetItem, QInputDialog

from core_lib.common.exception import VersionManifestFetchException, VersionManifestException
from core_lib.game.mod import fabric
from core_lib.game.mod.mod_core import find_useful_part_in_mod_version_manifest
from core_lib.game.version_info import get_all_versions, get_available_version_types
from manager.game import ManifestManager, GameManager
from manager.profile import CreateProfileRequest
from manager.widgets import SignalTransferItem, WidgetManager
from pages.install_java_dialog import InstallJavaDialog

class CreateProfilePage(QWidget):
    def __init__(self, app, parent=None):
        super(CreateProfilePage, self).__init__(parent)
        self.app = app

        # Manager
        self.widget_mgr: WidgetManager = app.widget_manager
        self.game_mgr: GameManager = app.game_manager
        self.manifest_mgr: ManifestManager = self.game_mgr.manifest

        # Layout
        self.layout = QVBoxLayout()
        self.content_layout = QHBoxLayout()

        self.main_layout = QVBoxLayout()
        self.right_layout = QVBoxLayout()
        self.operate_layout = QHBoxLayout()

        # Some items
        self.version_type_label = QLabel(self.app.tr_text("Version Type"))
        self.version_type_dropdown = QComboBox()
        self.version_type_dropdown.setObjectName("Dropdown")

        # Mod loader
        self.mod_loader_icon_label = QLabel()
        icon = self.app.get_icon(Path(self.app.icon_dir, "mod_loader_temp.png"))
        pixmap = icon.pixmap(QSize(100, 100))
        self.mod_loader_icon_label.setPixmap(pixmap)
        self.mod_loader_label = QLabel(self.app.tr_text("Mod Loader"))
        self.mod_loader_dropdown = QComboBox()
        self.mod_loader_dropdown.setObjectName("Dropdown")

        # Mod loader layout
        self.mod_config_layout = QHBoxLayout()
        self.mod_config_fields_layout = QVBoxLayout()

        self.mod_loader_version_label = QLabel(self.app.tr_text("Mod Loader Version"))

        self.mod_loader_version_list = QListWidget()
        self.mod_loader_version_list.setObjectName(
            "ListWidget"
        )

        # Version list
        self.version_list_type_label = QLabel(self.app.tr_text("Version: Vanilla"))
        self.version_list_label = QLabel(self.app.tr_text("Select a version to continue:"))
        self.version_list = QListWidget()
        self.version_list.setObjectName("ListWidget")

        # Button
        self.create_profile_button = QPushButton(self.app.tr_text("Create Profile"))
        self.create_profile_button.setObjectName("Button")

        self.refresh_button = QPushButton(self.app.tr_text("Refresh"))
        self.refresh_button.setObjectName("Button")

        self.install_java_button = QPushButton(self.app.tr_text("Install Java"))
        self.install_java_button.setObjectName("Button")

        # Bind widget
        self.main_layout.addWidget(self.version_list_label)
        self.main_layout.addWidget(self.version_list)
        self.operate_layout.addWidget(self.version_list_type_label)
        self.operate_layout.addStretch()
        self.operate_layout.addWidget(self.install_java_button)
        self.operate_layout.addWidget(self.refresh_button)
        self.operate_layout.addWidget(self.create_profile_button)

        self.mod_config_fields_layout.addWidget(
            self.mod_loader_label
        )
        self.mod_config_fields_layout.addWidget(
            self.mod_loader_dropdown
        )
        self.mod_config_fields_layout.addWidget(
            self.version_type_label
        )
        self.mod_config_fields_layout.addWidget(
            self.version_type_dropdown
        )
        self.mod_config_fields_layout.addStretch()
        self.mod_config_layout.addWidget(
            self.mod_loader_icon_label,
            alignment=Qt.AlignmentFlag.AlignTop,
        )
        self.mod_config_layout.addLayout(
            self.mod_config_fields_layout
        )
        self.right_layout.addLayout(
            self.mod_config_layout
        )

        self.right_layout.addWidget(self.mod_loader_version_label)
        self.right_layout.addWidget(
            self.mod_loader_version_list,
            1,
        )
        self.mod_loader_version_list.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        self.right_layout.setContentsMargins(0, 20, 0, 0)

        self.setLayout(self.layout)
        self.content_layout.addLayout(
            self.main_layout,
            stretch=2,
        )
        self.content_layout.addLayout(
            self.right_layout,
            stretch=1,
        )

        self.layout.addLayout(
            self.content_layout,
            stretch=1,
        )
        self.layout.addLayout(
            self.operate_layout,
        )

        # Signals
        self.signals = self.PageSignal()

        self.signals.get_selected_item.connect(self.get_selected_item)
        self.signals.update_list.connect(self.update_list)
        self.signals.clean_list.connect(self.clean_list)

        # Button event
        self.create_profile_button.clicked.connect(self.create_profile)
        self.install_java_button.clicked.connect(self.create_install_jvm_dialog)

        # Update version list while current type is changed
        self.version_type_dropdown.currentTextChanged.connect(
            self.start_load_version_list
        )

        self.version_list.currentTextChanged.connect(
            self.start_load_mod_loader_version
        )

        self.mod_loader_dropdown.currentTextChanged.connect(
            self.start_load_mod_loader_version
        )

        self.mod_loader_dropdown.currentTextChanged.connect(
            self.update_mod_loader_icon
        )

        self.loader_list = {
            "Don't Install": {
                "type": "vanilla",
                "icon": Path(self.app.icon_dir, "vanilla.png"),
                "loadVersionMethod": self.load_vanilla_version_list,
                "profileCreateHandler": self.handle_vanilla_profile_create,
            },
            "Fabric": {
                "type": "modded",
                "icon": Path(self.app.icon_dir, "modLoader", "fabric.png"),
                "loadVersionMethod": getattr(self, "load_fabric_version_list", None),
                "profileCreateHandler": self.handle_fabric_profile_create,
            },
            "NeoForge": {
                "type": "modded",
                "icon": Path(self.app.icon_dir, "modLoader", "neoforged.ico"),
                "loadVersionMethod": getattr(self, "load_neoforge_version_list", None),
                "profileCreateHandler": self.handle_neoforge_profile_create,
            }
        }
        self.init_all()

    class PageSignal(QObject):
        mod_loader_dropdown_changed = Signal(str)
        load_version_list = Signal()

        # widget
        update_list = Signal(object)
        clean_list = Signal(object)
        update_mod_loader_icon_label = Signal(object)

        get_selected_item = Signal(object)

    #
    # Signal Handler
    #
    class UpdateListRequest(object):
        def __init__(self, target_list: QListWidget | QComboBox, items: list[str], clean: bool=True,
                     current_index: int | None = None, custom_handler: Callable = None,
                     block_signals: bool = False, complete_callback: Callable = None):
            self.target_list = target_list
            self.items: list[str | dict] = items
            self.clean = clean
            self.current_index = current_index
            self.custom_handler = custom_handler
            self.block_signals = block_signals
            self.complete_callback = complete_callback

    @Slot(object)
    def update_list(self, request: UpdateListRequest):
        target_list = request.target_list
        items = request.items

        if not isinstance(target_list, QListWidget | QComboBox):
            raise TypeError(
                "Target list must be a QListWidget or QComboBox."
            )

        if request.block_signals:
            target_list.blockSignals(True)

        # Handle update
        try:
            if request.clean:
                target_list.clear()

            if callable(request.custom_handler):
                handler = request.custom_handler
                handler(request)
            else:
                target_list.addItems(items)

            index = request.current_index
            if index is None:
                return

            # Check and set current index
            if 0 <= request.current_index < target_list.count():
                if isinstance(target_list, QComboBox):
                    target_list.setCurrentIndex(index)
                elif isinstance(target_list, QListWidget):
                    target_list.setCurrentRow(index)
            else:
                self.app.logger.warning(
                    "Target list index out of range. Current index is {}.".format(
                        request.current_index
                    )
                )
        finally:
            if request.block_signals:
                target_list.blockSignals(False)

        if callable(request.complete_callback):
            request.complete_callback()

    @Slot(str)
    def update_mod_loader_icon(self, loader_name: str):
        loader = self.loader_list.get(loader_name)
        if not loader:
            self.app.logger.warning(
                "Mod Loader {} not found".format(loader_name)
            )
            return

        icon_path = loader.get("icon")
        if not isinstance(icon_path, Path):
            self.app.logger.warning(
                "Mod Loader {} icon path not found or is not Path type".format(loader_name)
            )
            return

        pixmap = self.app.get_picture(
            icon_path,
            QSize(100, 100),
        )

        pixmap = pixmap.scaled(
            QSize(100, 100),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

        self.mod_loader_icon_label.setPixmap(pixmap)

    @staticmethod
    def clean_list(target_list: QListWidget | QComboBox):
        if not isinstance(target_list, QListWidget | QComboBox):
            raise TypeError("Target list is not a QListWidget")

        target_list.clear()

    class GetSelectedItem(SignalTransferItem):
        def __init__(self, target_list: QListWidget | QComboBox):
            SignalTransferItem.__init__(self)
            self.target_list = target_list

    class DisplayListItem(QListWidgetItem):
        def __init__(self, parent: QListWidget=None, display_text: str=None, raw_value: str=None):
            QListWidgetItem.__init__(self, parent)

            self.display_text = display_text
            self.raw_value = raw_value

            self.setText(self.display_text)

    @Slot(object)
    def get_selected_item(self, request: GetSelectedItem):
        if not isinstance(request, self.GetSelectedItem):
            raise TypeError("Item is not a GetSelectedItem")

        target = request.target_list

        if isinstance(target, QComboBox):
            selected_text = target.currentText()
        elif isinstance(target, QListWidget):
            item = target.currentItem()
            if isinstance(item, self.DisplayListItem):
                selected_text = item.raw_value
            else:
                selected_text = None
        else:
            raise TypeError("Target list is not a QListWidget or QComboBox")

        if not selected_text:
            request.result_queue.put(None)
        else:
            request.result_queue.put(selected_text)

        request.wait_event.set()

    def update_type_dropdown(self, types: list):
        # Move release to top
        if "release" in types:
            types.pop(types.index("release"))
            types.insert(0, "release")

        self.version_type_dropdown.addItems(types)

        if len(self.version_type_dropdown.currentText()) == 0:
            self.version_type_dropdown.setCurrentIndex(0)


    def update_version_list(self, request: UpdateListRequest):
        version_list = request.target_list

        if not isinstance(version_list, QListWidget | QComboBox):
            raise TypeError("Target list is not a QListWidget or QComboBox")

        for version in request.items:
            ver_id = version.get("id", None) or version.get("version", None)
            stable = version.get("stable", None)

            if not ver_id:
                self.app.logger.warning("Provided version {} missing ID.".format(version))

            display_text = ver_id

            if stable is not None and isinstance(stable, bool):
                display_text = f"{ver_id}"+(" (stable)" if stable else "")

            item = self.DisplayListItem(
                parent=request.target_list,
                display_text=display_text,
                raw_value=ver_id,
            )

            version_list.addItem(item)

    def update_mod_loader_list(self, loaders: dict):
        for loader_name, value in loaders.items():
            self.mod_loader_version_list.addItem(loader_name)

    #
    # Thread Starter
    #
    def init_all(self):
        self.start_load_type_list()
        self.start_load_mod_loader_list()

    def start_load_type_list(self):
        thread = threading.Thread(target=self.load_type_list)
        thread.start()

    def start_load_version_list(self):
        thread = threading.Thread(target=self.load_version_list)
        thread.start()

    def start_load_mod_loader_list(self):
        thread = threading.Thread(target=self.load_mod_loader_list)
        thread.start()

    def start_load_mod_loader_version(self):
        thread = threading.Thread(target=self.load_mod_loader_version)
        thread.start()

    #
    # Processor
    #
    def create_profile(self):
        request = self.GetSelectedItem(
            target_list=self.version_list,
        )
        self.signals.get_selected_item.emit(request)

        if not request.wait(10):
            self.widget_mgr.signal.show_error_message.emit(
                self.app.tr_text("Timeout while waiting for selected version."),
            )
            return

        minecraft_version = request.result()

        if not minecraft_version:
            self.widget_mgr.signal.show_warning_message.emit(
                self.app.tr_text("Selected a version before creating profile."),
            )
            return

        loader_request = self.GetSelectedItem(
            target_list=self.mod_loader_dropdown,
        )
        self.signals.get_selected_item.emit(loader_request)

        if not loader_request.wait(10):
            self.widget_mgr.signal.show_error_message.emit(
                self.app.tr_text("Timeout while waiting for selected mod loader."),
            )
            return

        loader_name = loader_request.result()

        if loader_name not in self.loader_list:
            self.widget_mgr.signal.show_error_message.emit(
                self.app.tr_text("Loader {loader} not found.", loader=loader_name),
            )
            return

        loader = self.loader_list[loader_name]
        profile_create_handler: Callable[[str, str, str | None], None] = loader.get("profileCreateHandler", None)

        if profile_create_handler is None:
            self.widget_mgr.signal.show_warning_message.emit(
                self.app.tr_text(
                    "Profile creation for loader {loader} is not implemented.",
                    loader=loader_name,
                ),
            )
            return

        loader_version_request = self.GetSelectedItem(
            target_list=self.mod_loader_version_list,
        )
        self.signals.get_selected_item.emit(loader_version_request)

        if not loader_version_request.wait(10):
            self.widget_mgr.signal.show_error_message.emit(
                self.app.tr_text("Timeout while waiting for selected mod loader version."),
            )
            return

        loader_version = loader_version_request.result()

        if not loader_version and loader_version is not None:
            loader_version = None

        profile_name, accepted = QInputDialog.getText(
            self,
            self.app.tr_text("Create Profile"),
            self.app.tr_text("Profile name:"),
            text=f"Minecraft {minecraft_version}",
        )

        if not accepted:
            return

        profile_name = profile_name.strip()
        if not profile_name:
            self.widget_mgr.signal.show_warning_message.emit(
                self.app.tr_text("Profile name cannot be empty."),
            )
            return

        # Call handler
        if callable(profile_create_handler):
            profile_create_handler(profile_name, minecraft_version, loader_version)

    def handle_vanilla_profile_create(self, profile_name: str, version: str, loader_version: None=None, switch_to_current=False):
        """
        Handle vanilla profile creation.
        :param profile_name:
        :param version:
        :param loader_version:
        :param switch_to_current: Switch new profile to current profile.
        :return:
        """
        manifest = self.manifest_mgr.get_cached_version_manifest(version)

        if not manifest:
            self.widget_mgr.signal.show_warning_message.emit(
                self.app.tr_text("Unable to create profile due to manifest fetch failure."),
            )
            return

        version_id: str = manifest.get("id")
        version_type = manifest.get(
            "type",
            self.version_type_dropdown.currentText() or "custom",
        )

        if version_id is None:
            self.widget_mgr.signal.show_error_message.emit(
                self.app.tr_text("Unable to create profile due to version ID is missing in manifest."),
            )
            return

        request = CreateProfileRequest(
            name=profile_name,
            version_id=version_id,
            version_type=version_type,
        )

        # Create and optionally switch to the new profile. ProfileManager
        # persists each successful mutation.
        profile_id = self.app.profile_manager.create_profile(request)
        if profile_id is None:
            return

        if switch_to_current:
            if not self.app.profile_manager.set_current_profile(profile_id):
                return

        self.widget_mgr.signal.show_info_message.emit(
            self.app.tr_text("Profile {profile_id} successfully created.", profile_id=profile_id),
        )

    def handle_fabric_profile_create(self, profile_name: str, minecraft_version: str, loader_version: str | None, switch_to_current=False):
        """
        Handle fabric profile creation.
        :param profile_name:
        :param minecraft_version:
        :param loader_version:
        :param switch_to_current:
        :return:
        """
        if not loader_version:
            self.widget_mgr.signal.show_warning_message.emit(
                self.app.tr_text("Selected a fabric loader version before creating profile."),
            )
            return

        # Create vanilla manifest
        vanilla_manifest = self.manifest_mgr.get_cached_version_manifest(
            minecraft_version
        )
        if not vanilla_manifest:
            self.widget_mgr.signal.show_error_message.emit(
                self.app.tr_text("Unable to create profile due to vanilla manifest fetch failure."),
            )
            return

        version_id = fabric.get_full_version_string(version=minecraft_version, loader_version=loader_version)

        def fetch_loader_manifest(_version_id: str, ) -> tuple[dict, None]:
            manifest = fabric.get_loader_manifest_from_loader_data(
                minecraft_version,
                {"version": loader_version},
            )
            return manifest, None

        loader_manifest = self.manifest_mgr.get_cached_custom_version_manifest(
            version_id, fetch_manifest_handler=fetch_loader_manifest,)

        if not loader_manifest:
            self.widget_mgr.signal.show_error_message.emit(
                self.app.tr_text("Unable to create profile due to mod loader manifest fetch failure."),
            )
            return

        loader_info = find_useful_part_in_mod_version_manifest(
            loader_manifest
        )

        # Check mod info
        if loader_info["id"] != version_id:
            self.app.logger.error(f"Fabric manifest ID mismatch: expected {version_id}, got {loader_info["id"]}.")
            self.widget_mgr.signal.show_error_message.emit(
                self.app.tr_text("Unable to create profile. Exising loader version ID mismatch."),
            )
            return

        if loader_info["inheritsFrom"] != minecraft_version:
            self.app.logger.error(
                f"Fabric manifest inherits from "
                f'{loader_info["inheritsFrom"]}, not {minecraft_version}.'
            )
            self.widget_mgr.signal.show_error_message.emit(
                self.app.tr_text("Unable to create profile. Inherits version is mismatched as expected."),
            )
            return

        request = CreateProfileRequest(
            name=profile_name,
            version_id=version_id,
            version_type=loader_info["type"] or vanilla_manifest["type"] or "custom",
        )

        profile_id = self.app.profile_manager.create_profile(
            request
        )

        if profile_id is None:
            return

        if switch_to_current:
            if not self.app.profile_manager.set_current_profile(profile_id):
                return

        self.widget_mgr.signal.show_info_message.emit(
            self.app.tr_text(
                "Profile {profile_id} with fabric loader successfully created.",
                profile_id=profile_id,
            ),
        )


    def handle_forge_profile_create(self, profile_name: str, minecraft_version: str, loader_version: str | None):
        if not loader_version:
            self.widget_mgr.signal.show_warning_message.emit(
                self.app.tr_text("Selected a forge loader version before creating profile."),
            )

    def handle_neoforge_profile_create(self, profile_name: str, minecraft_version: str, loader_version: str | None):
        if not loader_version:
            self.widget_mgr.signal.show_warning_message.emit(
                self.app.tr_text("Selected a neoforge loader version before creating profile."),
            )

    #
    # Background Thread
    #
    def load_type_list(self):
        manifest = self.manifest_mgr.get_cached_version_manifest()
        if not manifest:
            return

        ver_types = get_available_version_types(manifest)
        release_index = ver_types.index("release") if "release" in ver_types else None

        request = self.UpdateListRequest(
            target_list=self.version_type_dropdown,
            items=ver_types,
            current_index=release_index,
            clean=True,
            block_signals=True,
            complete_callback=self.start_load_version_list,
        )
        self.signals.update_list.emit(request)

    def load_version_list(self):
        # Get selected version type
        request = self.GetSelectedItem(
            target_list=self.version_type_dropdown
        )
        self.signals.get_selected_item.emit(request)

        if not request.wait(10):
            self.widget_mgr.signal.show_error_message.emit(
                self.app.tr_text("Timeout while waiting for selected type."),
            )
            return

        selected_type = request.result()

        if not selected_type:
            self.widget_mgr.signal.show_warning_message.emit(
                self.app.tr_text("No type selected."),
            )
            return

        # Fetch (or read) manifest
        manifest = self.manifest_mgr.get_cached_version_manifest()

        if not manifest:
            return

        versions = get_all_versions(
            manifest,
            specified_type=selected_type
        )

        # Update list
        request = self.UpdateListRequest(
            target_list=self.version_list,
            items=versions,
            clean=True,
            current_index=0,
            custom_handler=self.update_version_list
        )
        self.signals.update_list.emit(request)

    def load_vanilla_version_list(self):
        """
        A dummy port for load_mod_loader_version
        :return:
        """
        self.clean_list(self.mod_loader_version_list)

    def load_fabric_version_list(self):
        self.signals.clean_list.emit(self.mod_loader_version_list)
        request = self.GetSelectedItem(
            target_list=self.version_list
        )
        self.signals.get_selected_item.emit(request)

        if not request.wait(10):
            self.widget_mgr.signal.show_error_message.emit(
                self.app.tr_text("Timeout while waiting for selected version."),
            )

        selected_version = request.result()

        if not selected_version:
            self.widget_mgr.signal.show_warning_message.emit(
                self.app.tr_text("No version selected."),
            )

        try:
            loaders = fabric.get_version_support_loader_list(
                selected_version
            )
        except (VersionManifestFetchException, VersionManifestException) as e:
            self.widget_mgr.signal.show_error_message.emit(
                self.app.tr_text(
                    "Failed to fetch version manifest: {error}", error=e.user_message
                ),
            )
            return
        except Exception as e:
            self.widget_mgr.signal.show_error_message.emit(
                self.app.tr_text(
                    "An unexpected error occurred while fetching version manifest: {error}",
                    error=e,
                ),
            )
            return

        request = self.UpdateListRequest(
            target_list=self.mod_loader_version_list,
            items=loaders,
            current_index=0,
            custom_handler=self.update_version_list,
            block_signals=True,
        )
        self.signals.update_list.emit(request)

    def load_mod_loader_list(self):
        loaders = [loader for loader in self.loader_list.keys()]

        request = self.UpdateListRequest(
            target_list=self.mod_loader_dropdown,
            items=loaders,
            current_index=0,
            clean=True
        )
        self.signals.update_list.emit(request)

    def load_mod_loader_version(self):
        request = self.GetSelectedItem(
            target_list=self.mod_loader_dropdown
        )
        self.signals.get_selected_item.emit(request)

        if not request.wait(10):
            self.widget_mgr.signal.show_error_message.emit(
                self.app.tr_text("Timeout while waiting for selected loader."),
            )
            return

        loader_name = request.result()

        if loader_name not in self.loader_list:
            raise KeyError("Target loader {} not found".format(loader_name))

        loader = self.loader_list[loader_name]
        version_handler = loader.get("loadVersionMethod", None)

        if not version_handler:
            self.widget_mgr.signal.show_warning_message.emit(
                self.app.tr_text(
                    'Selected loader "{loader}" is not implemented',
                    loader=loader_name,
                ),
            )
            return

        if callable(version_handler):
            version_handler()
        else:
            self.app.logger.warning(
                "Select mod loader \"loadVersionMethod\" is not callable."
            )

    def create_install_jvm_dialog(self):
        manifest = None
        selected = self.version_list.currentItem()
        if selected:
            version_id = (
                selected.raw_value
                if isinstance(selected, self.DisplayListItem)
                else selected.text()
            )
            try:
                resolved = self.manifest_mgr.resolve_manifest(version_id)
                manifest = resolved.manifest if resolved else None
            except Exception as exc:
                self.app.logger.warning(f"Unable to resolve Java requirement for {version_id}: {exc}")
        self.dialog = InstallJavaDialog(self.app, manifest=manifest, parent=self)
        self.dialog.setModal(False)
        self.dialog.show()
