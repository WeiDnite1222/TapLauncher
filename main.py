# Nuitka build configuration. The output mode is selected on the command line
# so the same configuration can be used for both standalone and onefile builds.
# nuitka-project: --enable-plugin=pyside6
# nuitka-project: --include-data-dir={MAIN_DIRECTORY}/resources=resources
# nuitka-project: --output-dir={MAIN_DIRECTORY}/build
# nuitka-project: --output-filename=TestLauncher
# nuitka-project: --product-name=TestLauncher
# nuitka-project: --file-description=TestLauncher Minecraft Launcher
# nuitka-project: --copyright=Copyright (c) wei
# nuitka-project: --assume-yes-for-downloads
# nuitka-project-if: {OS} == "Windows":
#    nuitka-project: --windows-console-mode=disable
#    nuitka-project: --windows-icon-from-ico={MAIN_DIRECTORY}/resources/icons/icon.png

import os
import sys
import argparse
import logging

from PySide6.QtWidgets import QApplication, QMainWindow

from app import Launcher

from core_lib.log.default import DEFAULT_FORMAT, DEFAULT_DATE_FORMAT, get_colorful_handler
from core_lib.qt import messagebox

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
    parser.add_argument("-wd", "--work-dir", default=os.getcwd(), help="Work directory")

    args, unknown = parser.parse_known_args()
    for arg in unknown:
        logger.warning("Unknown argument '%s'" % arg)

    debug = args.debug

    # check workdir
    if not os.path.exists(args.work_dir) or not os.path.isdir(args.work_dir):
        app = QApplication(sys.argv)
        app.setApplicationName("Launcher Bootstrapper")
        window = QMainWindow()
        messagebox.error(window, "Error", f"Specified work directory \"{args.work_dir}\" does not exist or"
                                      " is not a directory.")
        logger.error("Work directory '%s' does not exist. Exiting..." % args.work_dir)
        app.exit()
        sys.exit(-1)

    if os.getcwd() != args.work_dir:
        os.chdir(args.work_dir)

    logger.info("Current working directory is {}".format(args.work_dir))

    # Init lib
    level = logging.DEBUG if debug else logging.INFO

    # Set root logger level and configure handler for colorful log (not sure why I added this)
    root_logger.setLevel(level)
    root_logger.addHandler(get_colorful_handler())

    # Logger configure
    logging.basicConfig(format=DEFAULT_FORMAT, datefmt=DEFAULT_DATE_FORMAT, level=level)

    # Start (the real) launcher
    app = Launcher(logger, debug=debug)
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
