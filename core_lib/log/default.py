import logging
import sys

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