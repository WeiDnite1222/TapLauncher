import logging
import sys
from collections import deque

from PySide6.QtCore import QObject, Signal
from colorlog import ColoredFormatter

DEFAULT_FORMAT = '%(asctime)s:%(name)s:%(levelname)s: %(message)s'
DEFAULT_DATE_FORMAT = '%H:%M:%S'

def get_colorful_handler():
    handler = logging.StreamHandler(sys.stdout)
    formatter = ColoredFormatter(
        '%(light_white)s%(asctime)s:%(light_green)s%(name)s:%(log_color)s%(levelname)s%(reset)s: %(message)s',
        log_colors={
            'DEBUG': 'cyan',
            'INFO': 'green',
            'WARNING': 'yellow',
            'ERROR': 'light_red',
            'CRITICAL': 'red',
        },
        datefmt=DEFAULT_DATE_FORMAT
    )
    handler.setFormatter(formatter)
    return handler

class LogEmitter(QObject):
    message_emitted = Signal(str)
    record_emitted = Signal(object)


class LogCaptureHandler(logging.Handler):
    def __init__(self, max_messages: int = 5000):
        super().__init__()
        self.messages = deque(maxlen=max_messages)
        self.records = deque(maxlen=max_messages)
        self.emitter = LogEmitter()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record)

            self.records.append(record)
            self.messages.append(message)

            self.emitter.message_emitted.emit(message)
            self.emitter.record_emitted.emit(record)
        except Exception:
            self.handleError(record)

    def get_messages(self) -> list[str]:
        return list(self.messages)

    def clear(self) -> None:
        self.messages.clear()
        self.records.clear()