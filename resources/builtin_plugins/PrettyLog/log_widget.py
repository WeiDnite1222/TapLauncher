"""Plain-text log viewer with severity colors and no HTML interpretation."""

import re

from PySide6.QtGui import QColor, QPalette, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QPlainTextEdit


class ColoredLogOutput(QPlainTextEdit):
    DARK_COLORS = {
        "TRACE": "#9299a5", "DEBUG": "#93a8c4", "INFO": "#8ed49f",
        "WARN": "#f2c66d", "WARNING": "#f2c66d", "ERROR": "#ff8585", "FATAL": "#f099d7",
    }
    LIGHT_COLORS = {
        "TRACE": "#616977", "DEBUG": "#405e91", "INFO": "#24713a",
        "WARN": "#946000", "WARNING": "#946000", "ERROR": "#bc2424", "FATAL": "#952278",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._has_entries = False

    def append_log_entry(self, line_type: str, message: str) -> None:
        level = line_type.upper()
        if line_type in {"normal", "error"}:
            match = re.search(r"\[[^\]\n]*/(TRACE|DEBUG|INFO|WARN|ERROR|FATAL)\]", message)
            warning = re.match(r"^(WARNING|WARN|ERROR|FATAL):", message)
            if match or warning:
                level = (match or warning).group(1)
        colors = (self.LIGHT_COLORS if self.palette().color(QPalette.ColorRole.Base).lightness() > 128
                  else self.DARK_COLORS)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(colors[level]) if level in colors else self.palette().color(QPalette.ColorRole.Text))
        fmt.setFontWeight(700 if level == "FATAL" else 400)
        scroll = self.verticalScrollBar()
        follow = scroll.value() >= scroll.maximum()
        cursor = QTextCursor(self.document())
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.beginEditBlock()
        if self._has_entries:
            cursor.insertBlock()
        cursor.insertText(message, fmt)
        cursor.endEditBlock()
        self._has_entries = True
        if follow:
            scroll.setValue(scroll.maximum())

    def set_log_entries(self, entries) -> None:
        self.clear()
        self._has_entries = False
        for line_type, message in entries:
            self.append_log_entry(line_type, message)
