# Nuitka build configuration. The output mode is selected on the command line
# so the same configuration can be used for both standalone and onefile builds.
# nuitka-project: --enable-plugin=pyside6
# nuitka-project: --include-data-dir={MAIN_DIRECTORY}/resources=resources
# nuitka-project: --output-dir={MAIN_DIRECTORY}/build
# nuitka-project: --output-filename=launcher
# nuitka-project: --product-name=TapLauncher
# nuitka-project: --file-description=TapLauncher
# nuitka-project: --copyright=Copyright (c) Wei's Garage
# nuitka-project: --assume-yes-for-downloads
# nuitka-project-if: {OS} == "Windows":
#    nuitka-project: --windows-console-mode=disable
#    nuitka-project: --windows-icon-from-ico={MAIN_DIRECTORY}/resources/icons/icon.png
# nuitka-project-if: {OS} == "Darwin":
#    nuitka-project: --macos-create-app-bundle
#    nuitka-project: --macos-app-icon={MAIN_DIRECTORY}/resources/icons/apple-app-icon-default.png
#    nuitka-project: --macos-app-name="TapLauncher"
#    nuitka-project: --macos-signed-app-name="net.wei.taplauncher"
#    nuitka-project: --output-filename="TapLauncher"
#    nuitka-project: --output-folder-name=TapLauncher.app
import os
import sys
import argparse
import logging

from PySide6.QtWidgets import QApplication, QMainWindow
from platformdirs import (
    user_data_dir,
)

from app import Launcher
from constant import LAUNCHER_DIR_NAME

from core_lib.log.default import DEFAULT_FORMAT, DEFAULT_DATE_FORMAT, get_colorful_handler, LogCaptureHandler
from core_lib.qt import messagebox

def show_error(message):
    app = QApplication(sys.argv)
    app.setApplicationName("Launcher Bootstrapper")
    window = QMainWindow()
    messagebox.error(window, "Error", message)
    app.exit()

def main():
    root_logger = logging.getLogger()
    logger = logging.getLogger("Launcher.Main")

    # parse arguments
    parser = argparse.ArgumentParser()
    parser.add_argument("-m", "--mode", choices=['lightweight', 'full', 'choice'], default='choice',
                        help="Select a mode (lightweight for TUI, full for GUI, or choice to open a mode-selection window). "
                             "TUI is not implemented yet.", required=False)
    parser.add_argument("-d", "--debug", action="store_true",
                        help="Enable debug mode", default=False)
    parser.add_argument("-wd", "--work-dir", default=None, help="Work directory")

    args, unknown = parser.parse_known_args()
    for arg in unknown:
        logger.warning("Unknown argument '%s'" % arg)

    debug = args.debug

    work_dir = args.work_dir

    if work_dir is None:
        if debug:
            # Use working directory if launcher is in debug mode
            work_dir = os.getcwd()
        else:
            try:
                # Use user application data directory
                work_dir = user_data_dir(LAUNCHER_DIR_NAME, appauthor=False, roaming=True)
                os.makedirs(work_dir, exist_ok=True)
            except Exception as e:
                logger.warning("Failed to get application directory: %s", e)
                show_error("Unable to get application directory. Try specifying 'work_dir' argument.")
                sys.exit(-1)
    else:
        # check workdir
        if not os.path.exists(work_dir) or not os.path.isdir(work_dir):
            logger.error("Work directory '%s' does not exist." % work_dir)
            show_error(f"Specified work directory \"{work_dir}\" does not exist or is not a directory.")
            sys.exit(-1)

    if os.getcwd() != args.work_dir:
        os.chdir(work_dir)

    logger.info("Current working directory is {}".format(work_dir))

    # Init lib
    level = logging.DEBUG if debug else logging.INFO

    # Set root logger level and configure handler for colorful log (not sure why I added this)
    root_logger.setLevel(level)
    root_logger.addHandler(get_colorful_handler())

    # log record handler
    capture_handler = LogCaptureHandler(max_messages=5000)
    capture_handler.setLevel(logging.DEBUG)
    capture_handler.setFormatter(logging.Formatter(
        DEFAULT_FORMAT,
        datefmt=DEFAULT_DATE_FORMAT,
    ))

    root_logger.addHandler(capture_handler)

    # Logger configure
    logging.basicConfig(format=DEFAULT_FORMAT, datefmt=DEFAULT_DATE_FORMAT, level=level)

    # Start (the real) launcher
    app = Launcher(logger, capture_handler, debug=debug)
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
