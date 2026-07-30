import threading
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QObject, Signal, Slot
from PySide6.QtWidgets import QWidget, QVBoxLayout, QComboBox, QListWidget, QPushButton, QLabel, QHBoxLayout, \
    QSizePolicy

from core_lib.game.version_info import get_all_versions, get_available_version_types
from manager.game import ManifestManager, GameManager
from manager.widgets import SignalTransferItem, WidgetManager

LOADER_LIST = {
    "fabric": {
        "type": "modded",
        "loadVersionMethod": None,
    },
    "Don't Install": {
        "type": "vanilla",
        "loadVersionMethod": "official",
    }
}

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
        self.version_type_label = QLabel("Version Type")
        self.version_type_dropdown = QComboBox()
        self.version_type_dropdown.setObjectName("Dropdown")

        # Mod loader
        self.mod_loader_icon_label = QLabel()
        icon = self.app.get_icon(Path(self.app.icon_dir, "mod_loader_temp.png"))
        pixmap = icon.pixmap(QSize(100, 100))
        self.mod_loader_icon_label.setPixmap(pixmap)
        self.mod_loader_label = QLabel("Mod Loader")
        self.mod_loader_dropdown = QComboBox()
        self.mod_loader_dropdown.setObjectName("Dropdown")

        # Mod loader layout
        self.mod_config_layout = QHBoxLayout()
        self.mod_config_fields_layout = QVBoxLayout()

        self.mod_loader_version_label = QLabel(
            "Mod Loader Version"
        )

        self.mod_loader_version_list = QListWidget()
        self.mod_loader_version_list.setObjectName(
            "ListWidget"
        )

        # Version list
        self.version_list_type_label = QLabel("Version: Vanilla")
        self.version_list_label = QLabel("Select a version to continue:")
        self.version_list = QListWidget()
        self.version_list.setObjectName("ListWidget")

        # Button
        self.create_profile = QPushButton("Create Profile")
        self.create_profile.setObjectName("Button")

        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setObjectName("Button")

        # Bind widget
        self.main_layout.addWidget(self.version_list_label)
        self.main_layout.addWidget(self.version_list)
        self.operate_layout.addWidget(self.version_list_type_label)
        self.operate_layout.addStretch()
        self.operate_layout.addWidget(self.refresh_button)
        self.operate_layout.addWidget(self.create_profile)

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

        self.signals.get_selected_type.connect(self.get_selected_type)
        self.signals.get_selected_version.connect(self.get_selected_version)
        self.signals.update_type_dropdown.connect(self.update_type_dropdown)
        self.signals.update_version_dropdown.connect(self.update_version_dropdown)

        # events
        self.type_list_loading = threading.Event()
        self.version_list_loading = threading.Event()

        self.init_all()

    class PageSignal(QObject):
        mod_loader_dropdown_changed = Signal(str)
        load_version_list = Signal()

        # widget
        clean_list = Signal(object)
        update_version_dropdown = Signal(list)
        update_type_dropdown = Signal(list)
        update_mod_loader_icon_label = Signal(object)
        update_mod_loader_dropdown = Signal(list)
        update_mod_loader_version_list = Signal(list)

        get_selected_version = Signal(object)
        get_selected_type = Signal(object)

    #
    # Signal Handler
    #
    @staticmethod
    def clean_list(target_list: QListWidget | QComboBox):
        if not isinstance(target_list, QListWidget | QComboBox):
            raise TypeError("Target list is not a QListWidget")

        target_list.clear()

    @Slot(dict)
    def get_selected_type(self, item: SignalTransferItem):
        if not isinstance(item, SignalTransferItem):
            raise TypeError("Item is not a SignalTransferItem")

        selected_type = self.version_type_dropdown.currentText()

        if not selected_type:
            item.result_queue.put(None)
        else:
            item.result_queue.put(selected_type)

        item.wait_event.set()

    @Slot(object)
    def get_selected_version(self, item: SignalTransferItem):
        if not isinstance(item, SignalTransferItem):
            raise TypeError("Item is not a SignalTransferItem")

        selected_item = self.version_list.currentItem()

        if selected_item is None:
            item.result_queue.put(None)
        else:
            item.result_queue.put(selected_item.text())

        item.wait_event.set()

    def update_type_dropdown(self, types: list):
        # Move release to top
        if "release" in types:
            types.pop(types.index("release"))
            types.insert(0, "release")

        self.version_type_dropdown.addItems(types)

        if len(self.version_type_dropdown.currentText()) == 0:
            self.version_type_dropdown.setCurrentIndex(0)

    def update_version_dropdown(self, versions: list):
        ids = []

        for version in versions:
            ver_id = version.get("id", None)
            if ver_id is not None:
                ids.append(ver_id)

        self.version_list.addItems(ids)

        selected_item = self.version_list.currentItem()

        if selected_item is None and len(ids) > 0:
            self.version_list.setCurrentRow(0)

    #
    # Thread Starter
    #
    def init_all(self):
        self.start_load_type_list(callback=self.start_load_version_list)

    def start_load_type_list(self, callback=None):
        thread = threading.Thread(target=self.load_type_list, args=(callback,))
        thread.start()

    def start_load_version_list(self):
        thread = threading.Thread(target=self.load_version_list)
        thread.start()

    def start_load_mod_loader_list_and_version(self):
        pass

    #
    # Background Thread
    #
    def load_type_list(self, callback: Callable[None]=None):
        # Cleanup
        self.signals.clean_list.emit(self.version_type_dropdown)

        manifest = self.manifest_mgr.get_cached_version_manifest()
        if not manifest:
            return

        ver_types = get_available_version_types(manifest)

        self.signals.update_type_dropdown.emit(ver_types)

        if callable(callback):
            callback()

    def load_version_list(self, callback: Callable[Callable[None] | None]=None):
        # Cleanup
        self.version_list.clear()

        # Get selected version type
        request = SignalTransferItem()
        self.signals.get_selected_type.emit(request)

        if not request.wait(10):
            self.widget_mgr.signal.show_error_message.emit(
                "Timeout while waiting for selected type.",
            )
            return

        selected_type = request.result()

        if not selected_type:
            self.widget_mgr.signal.show_warning_message.emit(
                "No type selected.",
            )
            return

        # Fetch (or read) manifest
        manifest = self.manifest_mgr.get_cached_version_manifest()
        versions = get_all_versions(
            manifest,
            specified_type=selected_type
        )

        # Update list
        self.update_version_dropdown(versions)

        if callable(callback):
            callback(None)
