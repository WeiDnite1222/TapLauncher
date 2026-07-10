import sys
import argparse
import logging

from app import Launcher
import tkinter as tk

from core_lib.log.default import DEFAULT_FORMAT, DEFAULT_DATE_FORMAT, get_colorful_handler


def select_mode() -> None | str:
    value = None

    def get_value(root: tk.Tk, listbox_obj: tk.Listbox):
        nonlocal value
        value = listbox.get(listbox_obj.curselection()[0]) if listbox_obj.curselection() else None
        root.destroy()

    support_list = ["full", "lightweight"]

    r = tk.Tk()
    r.title("TestLauncher")
    r.geometry("300x300")

    label = tk.Label(r, text="Select a mode to continue")
    label.pack(anchor="n")

    listbox = tk.Listbox(r, selectmode=tk.SINGLE)
    listbox.pack(expand=True, fill="both")
    listbox.bind("<Double-Button-1>", lambda e: get_value(r, listbox))

    for support in support_list:
        listbox.insert(tk.END, support)

    listbox.selection_set(0)

    # move to center
    r.eval('tk::PlaceWindow . center')

    r.mainloop()

    return value


def tui_entry():
    logger = logging.getLogger("TestLauncher.Tui")
    logger.info("Wow tui is unfinished")

def main():
    root_logger = logging.getLogger()
    logger = logging.getLogger("Launcher.Main")

    # parse arguments
    parser = argparse.ArgumentParser()
    parser.add_argument("-m", "--mode", choices=['lightweight', 'full', 'choice'], default='choice',
                        help="Select mode (lightweight for tui, full is gui,"
                             "choice for a mode select window)", required=False)
    parser.add_argument("-d", "--debug", action="store_true",
                        help="Enable debug mode", default=False)

    args, unknown = parser.parse_known_args()
    for arg in unknown:
        logger.warning("Unknown argument '%s'" % arg)

    # args value set
    if not hasattr(args, "mode") or args.mode == "choice":
        mode = select_mode()

        if mode is None:
            logger.warning("No mode selected. Exiting...")
            sys.exit(0)
    else:
        mode = args.mode

    debug = args.debug

    # Init lib
    level = logging.DEBUG if debug else logging.INFO

    # Set root logger level and configure handler for colorful log (not sure why I added this)
    root_logger.setLevel(level)
    root_logger.addHandler(get_colorful_handler())

    # Logger configure
    logging.basicConfig(format=DEFAULT_FORMAT, datefmt=DEFAULT_DATE_FORMAT, level=level)

    # Start (the real) launcher
    if mode == 'lightweight':
        sys.exit(tui_entry())
    elif mode == 'full':
        app = Launcher()
        sys.exit(app.exec())
    else:
        logger.error("Unknown mode '%s'" % mode)
        sys.exit(1)

if __name__ == '__main__':
    main()
