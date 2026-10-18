import subprocess
import threading
from collections import deque
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QFileDialog,
    QSizePolicy,
    QWidget,
)

from core_lib.qt import messagebox


class _ProcessSignals(QObject):
    output = Signal(str, str)
    # Windows may return an unsigned 32-bit exit code (for example
    # 0xFFFFFFFF), which does not fit in Qt's signed Signal(int).
    finished = Signal(object)
    read_failed = Signal(str)


class ProcessLogWindow(QMainWindow):
    """
    A Simple client log view
    """

    MAX_LOG_LINES = 100_000
    LOG_TRIM_LINES = 10_000

    def __init__(self, app, process: subprocess.Popen, profile_id: str, title: str = "Game Log",
                 parent: QWidget | None = None, finished_callback: Callable[[str, int], None]=None) -> None:
        super().__init__(parent)
        self.app = app
        self.process = process
        self.profile_id = profile_id
        self._signals = _ProcessSignals(self)
        self._last_error_message: str | None = None
        self.lines: list[tuple[str, str]] = []  # type, message
        self._trimmed_line_count = 0
        self._stderr_lines: deque[str] = deque(maxlen=500)

        self.setWindowTitle(self.app.tr_text(title))
        self.resize(700, 720)

        container = QWidget(self)
        layout = QVBoxLayout(container)
        controls = QHBoxLayout()

        layout.setContentsMargins(0, 0, 0, 0)
        controls.setContentsMargins(8, 8, 8, 0)

        self.status_label = QLabel(self.app.tr_text("Running (PID {pid})", pid=process.pid))
        self.kill_button = QPushButton(self.app.tr_text("Kill Process"))
        self.save_log_button = QPushButton(self.app.tr_text("Save Log"))
        self.kill_button.clicked.connect(self.kill_process)
        self.save_log_button.clicked.connect(self.save_log)

        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.log_output.setMaximumBlockCount(self.MAX_LOG_LINES)
        self.log_output.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        controls.addWidget(self.status_label)
        controls.addStretch()
        controls.addWidget(self.save_log_button)
        controls.addWidget(self.kill_button)
        layout.addLayout(controls)
        layout.addWidget(self.log_output)
        self.setCentralWidget(container)

        self.app.apply_qss(Path("process_log.qss"), self.setStyleSheet)

        self._signals.output.connect(self._append_output)
        self._signals.finished.connect(self._process_finished)
        self._signals.read_failed.connect(self._read_failed)

        self.finished_callback = finished_callback

        self._stdout_reader = threading.Thread(
            target=self._read_stdout,
            name=f"process-stdout-{process.pid}",
            daemon=True,
        )
        self._stderr_reader = threading.Thread(
            target=self._read_stderr,
            name=f"process-stderr-{process.pid}",
            daemon=True,
        )
        self._waiter = threading.Thread(
            target=self._wait_for_process,
            name=f"process-wait-{process.pid}",
            daemon=True,
        )
        self._stdout_reader.start()
        self._stderr_reader.start()
        self._waiter.start()

    def append_message(self, message: str) -> None:
        self._append_output("launcher", message)

    def _append_output(self, line_type: str, message: str) -> None:
        """Store and display one line, trimming old output in bounded chunks."""
        if len(self.lines) >= self.MAX_LOG_LINES:
            trim_count = min(self.LOG_TRIM_LINES, len(self.lines))

            # Replace the previous truncation marker; it is not process output.
            if self.lines and self.lines[0][0] == "truncated":
                del self.lines[0]
                trim_count = min(trim_count - 1, len(self.lines))

            del self.lines[:trim_count]
            self._trimmed_line_count += trim_count

            trimmed_at = datetime.now().astimezone().isoformat(timespec="seconds")
            marker = "[launcher] " + self.app.tr_text(
                "Log truncated at {time}; {count} older lines removed.",
                time=trimmed_at,
                count=self._trimmed_line_count,
            )
            self.lines.insert(0, ("truncated", marker))

            # Keep the widget and the saved-log buffer identical after trimming.
            self.log_output.setPlainText(
                "\n".join(stored_message for _, stored_message in self.lines)
            )

        self.lines.append((line_type, message))
        self.log_output.appendPlainText(message)

    @property
    def last_error_message(self) -> str | None:
        return self._last_error_message

    def _read_stdout(self) -> None:
        try:
            if self.process.stdout is not None:
                for line in self.process.stdout:
                    self._signals.output.emit("normal", line.rstrip("\r\n"))
        except Exception as exc:
            self._signals.read_failed.emit(str(exc))

    def _read_stderr(self) -> None:
        try:
            if self.process.stderr is not None:
                for line in self.process.stderr:
                    message = line.rstrip("\r\n")
                    if message.strip():
                        self._last_error_message = message.strip()
                        self._stderr_lines.append(message)
                    self._signals.output.emit("error", message)
        except Exception as exc:
            self._signals.read_failed.emit(str(exc))

    def _wait_for_process(self) -> None:
        exit_code = self._normalize_exit_code(self.process.wait())
        self._stdout_reader.join()
        self._stderr_reader.join()
        self._signals.finished.emit(exit_code)

    @staticmethod
    def _normalize_exit_code(exit_code: int) -> int:
        # Avoid some system (WINDOWS) give exit code that overflow in 32bit integer
        if exit_code > 0x7FFFFFFF:
            return exit_code - 0x100000000
        return exit_code

    def kill_process(self) -> None:
        if self.process.poll() is not None:
            self._process_finished(
                self._normalize_exit_code(self.process.returncode or 0)
            )
            return

        self.kill_button.setEnabled(False)
        self.status_label.setText(self.app.tr_text("Killing process..."))

        try:
            self.process.kill()
        except Exception as exc:
            self.kill_button.setEnabled(True)
            self.status_label.setText(self.app.tr_text("Unable to kill process"))
            self.append_message(f"[launcher] Unable to kill process: {exc}")

    def save_log(self) -> None:
        file_name, _ = QFileDialog.getSaveFileName(
            None,
            self.app.tr_text("Select where to save the log file"),
            "game-output.txt",
            self.app.tr_text("Text Files (*.txt);;All Files (*)"),
        )

        # cancel
        if not file_name:
            return

        if not self.lines:
            messagebox.warning(
                self,
                self.app.tr_text("Warning"),
                self.app.tr_text("Log output is empty. No need to save it."),
            )
            return

        try:
            with open(file_name, "w", encoding="utf-8", newline="\n") as log_file:
                for _, message in self.lines:
                    log_file.write(message + "\n")

            messagebox.info(
                self,
                self.app.tr_text("Log Viewer"),
                self.app.tr_text("Log output saved to {file_name}", file_name=file_name),
            )
        except Exception as exc:
            messagebox.error(
                self,
                self.app.tr_text("Error"),
                self.app.tr_text("Unable to save log file: {error}", error=exc),
            )

    def _process_finished(self, exit_code: int) -> None:
        self.kill_button.setEnabled(False)
        self.status_label.setText(self.app.tr_text(
            "Process exited with code {exit_code}", exit_code=exit_code
        ))
        self.append_message(f"[launcher] Process exited with code {exit_code}.")

        if exit_code != 0 and self._last_error_message:
            self.append_message(
                f"[launcher] Last error: {self._last_error_message}"
            )

        if exit_code != 0:
            error_content = "\n".join(self._stderr_lines)
            if not error_content:
                error_content = (
                    "The client did not write an error message to stderr.\n"
                    f"Process exit code: {exit_code}"
                )

            messagebox.error_with_plain_text(
                self,
                title=self.app.tr_text("Minecraft Client Error"),
                message=self.app.tr_text(
                    "Minecraft exited with code {exit_code}.", exit_code=exit_code
                ),
                content=error_content,
            )

        if callable(self.finished_callback):
            self.finished_callback(self.profile_id, exit_code)

    def _read_failed(self, message: str) -> None:
        self.append_message(f"[launcher] Unable to read process output: {message}")
        if self.process.poll() is not None:
            self._process_finished(
                self._normalize_exit_code(self.process.returncode or 0)
            )

    def closeEvent(self, event: QCloseEvent) -> None:
        # Closing the log window must not stop the game. The process remains
        # available through this window instance and can be shown again.
        event.accept()
