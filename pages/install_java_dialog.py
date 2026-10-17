import threading
import traceback

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QPushButton,
    QVBoxLayout,
)

from manager.game import InstallableJavaRuntime, JavaManager, JavaRuntime


class InstallJavaDialog(QDialog):
    """Install and register launcher-managed Mojang Java runtimes."""

    class WorkerSignals(QObject):
        components_loaded = Signal(object, object)
        installed = Signal(object, object)

    runtime_installed = Signal(object)

    def __init__(self, app, manifest: dict | None = None, parent=None):
        super().__init__(parent)
        self.app = app
        self.java_manager: JavaManager = app.game_manager.java
        self.manifest = manifest or {}
        self.worker_signals = self.WorkerSignals(self)
        self.worker_signals.components_loaded.connect(self._components_loaded)
        self.worker_signals.installed.connect(self._installed)

        self.setWindowTitle(self.app.tr_text("Install Java"))
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)
        self.requirement_label = QLabel(self._requirement_text())
        self.runtime_list = QListWidget()
        self.component_dropdown = QComboBox()
        self.component_dropdown.setEditable(False)
        self.status_label = QLabel(self.app.tr_text("Loading available Mojang runtimes..."))
        self.install_button = QPushButton(self.app.tr_text("Install"))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)

        layout.addWidget(self.requirement_label)
        layout.addWidget(QLabel(self.app.tr_text("Detected Java runtimes")))
        layout.addWidget(self.runtime_list)
        layout.addWidget(QLabel(self.app.tr_text("Mojang runtime component")))
        layout.addWidget(self.component_dropdown)
        layout.addWidget(self.status_label)
        layout.addWidget(self.install_button)
        layout.addWidget(buttons)

        buttons.rejected.connect(self.reject)
        self.install_button.clicked.connect(self.install_selected)
        self._refresh_runtime_list()
        threading.Thread(target=self._load_components, daemon=True).start()

    def _requirement_text(self) -> str:
        requirement = self.manifest.get("javaVersion") or {}
        major = requirement.get("majorVersion")
        component = requirement.get("component")
        if major:
            return self.app.tr_text(
                "This version requires Java {version}.", version=major
            ) + f" ({component or 'component unknown'})"
        return self.app.tr_text("Choose a Mojang Java runtime component to install.")

    def _refresh_runtime_list(self) -> None:
        self.runtime_list.clear()
        for runtime in self.java_manager.list_runtimes():
            state = "available" if runtime.valid else "missing"
            self.runtime_list.addItem(
                f"Java {runtime.major_version} | {runtime.source} | {state}\n{runtime.executable}"
            )

    def _load_components(self) -> None:
        try:
            runtimes = self.java_manager.list_installable_runtimes()
            self.worker_signals.components_loaded.emit(runtimes, None)
        except Exception as exc:
            self.worker_signals.components_loaded.emit([], exc)

    def _components_loaded(self, runtimes: list[InstallableJavaRuntime], error) -> None:
        requirement = self.manifest.get("javaVersion") or {}
        required = requirement.get("component")
        required_major = requirement.get("majorVersion")
        self.component_dropdown.clear()
        for runtime in runtimes:
            major = runtime.major_version
            if runtime.component == required and required_major is not None:
                # The Minecraft version manifest is authoritative for its own
                # runtime requirement if Mojang's version name is unusual.
                major = int(required_major)
            label = f"Java {major} | {runtime.component}" if major is not None else runtime.component
            if runtime.raw_version:
                label += f" ({runtime.raw_version})"
            self.component_dropdown.addItem(label, runtime.component)
        if required:
            index = self.component_dropdown.findData(required)
            if index < 0:
                label = f"Java {required_major} | {required}" if required_major else required
                self.component_dropdown.addItem(label, required)
                index = self.component_dropdown.count() - 1
            self.component_dropdown.setCurrentIndex(index)
        self.install_button.setEnabled(self.component_dropdown.count() > 0)
        self.status_label.setText(
            self.app.tr_text("Unable to load component list: {error}", error=error)
            if error else self.app.tr_text("Ready to install.")
        )

    def install_selected(self) -> None:
        component = self.component_dropdown.currentData()
        if not component:
            self.status_label.setText(self.app.tr_text("Select a runtime component."))
            return
        self.install_button.setEnabled(False)
        self.component_dropdown.setEnabled(False)
        self.status_label.setText(self.app.tr_text("Installing {component}...", component=component))
        callback, task_id = self.app.game_manager.manifest.create_download_progress_callback(
            self.app.tr_text("Installing Java ({component})", component=component)
        )

        def worker():
            try:
                runtime = self.java_manager.install_runtime(
                    component,
                    progress_callback=callback,
                    redownload_callback=self.app.game_manager.game_file.redownload_files,
                )
                self.app.widget_manager.download_signal.finished.emit(task_id)
                self.worker_signals.installed.emit(runtime, None)
            except Exception as exc:
                traceback.print_exc()
                self.app.widget_manager.download_signal.failed.emit(task_id, str(exc))
                self.worker_signals.installed.emit(None, exc)

        threading.Thread(target=worker, daemon=True).start()

    def _installed(self, runtime: JavaRuntime | None, error) -> None:
        self.install_button.setEnabled(True)
        self.component_dropdown.setEnabled(True)
        if error:
            self.status_label.setText(self.app.tr_text("Installation failed: {error}", error=error))
            return
        self._refresh_runtime_list()
        self.status_label.setText(self.app.tr_text(
            "Java {version} installed successfully.", version=runtime.major_version
        ))
        self.runtime_installed.emit(runtime)
