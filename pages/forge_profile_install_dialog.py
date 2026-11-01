import math
import threading
import traceback
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QDialog, QLabel, QPlainTextEdit, QProgressBar, QPushButton, QVBoxLayout,
)

from manager.profile import CreateProfileRequest


INSTALL_STAGES = {
    "validating installation request": "Validating installation request...",
    "loading the vanilla manifest": "Loading Minecraft version information...",
    "preparing the installer": "Downloading and preparing the loader installer...",
    "preparing Java runtime": "Preparing the required Java runtime...",
    "downloading the Minecraft client": "Checking and downloading the Minecraft client...",
    "copying embedded artifacts": "Installing bundled libraries...",
    "downloading installer dependencies": "Downloading required libraries...",
    "running installer processors": "Applying loader patches...",
    "verifying installed artifacts": "Verifying the installed files...",
    "cleaning installer workspace": "Cleaning up temporary installer files...",
    "saving the loader manifest": "Saving the installed version...",
    "creating the profile": "Creating the launch profile...",
}


class ForgeProfileInstallDialog(QDialog):
    """Show loader installation progress and optionally create a launch profile."""

    completed = Signal(bool)
    version_installed = Signal(str)

    class WorkerSignals(QObject):
        stage = Signal(str)
        progress = Signal(str, float)
        failed = Signal(str, str)
        installed = Signal(object, object)

    def __init__(self, app, loader_name: str, minecraft_version: str, loader_version: str,
                 profile_name: str | None = None, switch_to_current: bool = False, parent=None,
                 *, profile_dir: Path | None = None):
        super().__init__(parent)
        self.app = app
        self.loader_name = loader_name
        self.minecraft_version = minecraft_version
        self.loader_version = loader_version
        self.profile_name = profile_name
        self.profile_dir = profile_dir
        self.switch_to_current = switch_to_current
        self.is_running = True
        self._started = False
        self.worker_signals = self.WorkerSignals(self)
        self.worker_signals.stage.connect(self._stage_changed)
        self.worker_signals.progress.connect(self._progress_changed)
        self.worker_signals.failed.connect(self._failed)
        self.worker_signals.installed.connect(self._installed)

        loader = "NeoForge" if loader_name == "neoforge" else "Forge"
        self.setWindowTitle(app.tr_text("Install {loader}", loader=loader))
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setMinimumWidth(600)
        layout = QVBoxLayout(self)
        self.summary_label = QLabel(app.tr_text(
            "Installing {loader} {loader_version} for Minecraft {minecraft_version}",
            loader=loader, loader_version=loader_version, minecraft_version=minecraft_version,
        ))
        self.status_label = QLabel(app.tr_text("Waiting to start installation..."))
        self.item_label = QLabel()
        for label in (self.summary_label, self.status_label, self.item_label):
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setWordWrap(True)
        self.progress_bar = QProgressBar()
        self.progress_bar.setFormat(app.tr_text("Stage progress: %p%"))
        self.progress_bar.setRange(0, 0)
        self.details_label = QLabel(app.tr_text("Installation details"))
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setMinimumHeight(180)
        self.close_button = QPushButton(app.tr_text("Close"))
        self.close_button.setEnabled(False)
        self.close_button.clicked.connect(self.accept)
        for widget in (self.summary_label, self.status_label, self.item_label, self.progress_bar,
                       self.details_label, self.details, self.close_button):
            layout.addWidget(widget)

    def start(self):
        if self._started:
            return
        self._started = True

        def worker():
            reported_error = False

            def failed(stage, details):
                nonlocal reported_error
                reported_error = True
                self.worker_signals.failed.emit(stage, details)

            try:
                vanilla, manifest = self.app.game_manager.game_file.install_forge_like_version(
                    loader_name=self.loader_name,
                    minecraft_version=self.minecraft_version,
                    loader_version=self.loader_version,
                    progress_callback=self.worker_signals.progress.emit,
                    status_callback=self.worker_signals.stage.emit,
                    error_callback=failed,
                )
                if reported_error:
                    return
                if not vanilla or not manifest:
                    self.worker_signals.failed.emit(
                        "", self.app.tr_text("The installer did not return an installed version."),
                    )
                    return
                self.worker_signals.installed.emit(vanilla, manifest)
            except Exception:
                self.app.logger.exception("Loader installation failed")
                self.worker_signals.failed.emit("", traceback.format_exc())

        self.worker = threading.Thread(target=worker, daemon=True)
        self.worker.start()

    @Slot(str)
    def _stage_changed(self, stage: str):
        if not self.is_running:
            return
        text = self.app.tr_text(INSTALL_STAGES.get(stage, stage))
        self.status_label.setText(text)
        self.item_label.clear()
        self.progress_bar.setRange(0, 0)
        self.details.appendPlainText(text)

    @Slot(str, float)
    def _progress_changed(self, name: str, percent: float):
        if not self.is_running or not math.isfinite(percent):
            return
        self.item_label.setText(self.app.tr_text("Current item: {item}", item=name))
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(round(max(0, min(100, percent))))

    @Slot(str, str)
    def _failed(self, stage: str, details: str):
        if not self.is_running:
            return
        if stage:
            text = self.app.tr_text(
                "Installation failed while: {stage}",
                stage=self.app.tr_text(INSTALL_STAGES.get(stage, stage)),
            )
        else:
            text = self.app.tr_text("Installation failed. See the details below.")
        self.status_label.setText(text)
        self.details.appendPlainText(text)
        self.details.appendPlainText(details)
        self.progress_bar.setRange(0, 100)
        self._finish(False)

    @Slot(object, object)
    def _installed(self, vanilla: dict, manifest: dict):
        if not self.is_running:
            return
        stage = "creating the profile" if self.profile_name is not None else "saving the loader manifest"
        try:
            version_id = manifest.get("id")
            if not isinstance(version_id, str) or not version_id:
                raise ValueError(self.app.tr_text("The installed version has no version ID."))
            if self.profile_name is None:
                self._show_success(self.app.tr_text("Added version {version_id}.", version_id=version_id))
                self.version_installed.emit(version_id)
                return
            self._stage_changed("creating the profile")
            request = CreateProfileRequest(
                name=self.profile_name, version_id=version_id,
                game_dir=self.profile_dir,
                version_type=manifest.get("type") or vanilla.get("type") or "custom",
            )

            profile_id = self.app.profile_manager.create_profile(request)
            if profile_id is None:
                raise RuntimeError(self.app.tr_text(
                    "The loader was installed, but the profile could not be created."
                ))
            if self.switch_to_current and not self.app.profile_manager.set_current_profile(profile_id):
                raise RuntimeError(self.app.tr_text(
                    "The profile was created, but could not be selected."
                ))
        except Exception:
            self.app.logger.exception("Unable to create profile after loader installation")
            self._failed(stage, traceback.format_exc())
            return
        text = self.app.tr_text("Profile {profile_id} successfully created.", profile_id=profile_id)
        self._show_success(text)

    def _show_success(self, text: str):
        self.status_label.setText(text)
        self.item_label.clear()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        self.details.appendPlainText(text)
        self._finish(True)

    def _finish(self, success: bool):
        self.is_running = False
        self.close_button.setEnabled(True)
        self.completed.emit(success)

    def accept(self):
        if not self.is_running:
            super().accept()

    def reject(self):
        if not self.is_running:
            super().reject()

    def closeEvent(self, event):
        if self.is_running:
            event.ignore()
        else:
            super().closeEvent(event)
