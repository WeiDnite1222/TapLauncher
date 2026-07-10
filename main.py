import os
import sys
import argparse
import logging
from app import Launcher
import tkinter as tk

# Logger configure
logging.basicConfig(format='%(asctime)s:%(name)s:%(levelname)s: %(message)s',
                    level=logging.INFO,
                    datefmt='%H:%M:%S')

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
    logger = logging.getLogger("Launcher.Main")

    parser = argparse.ArgumentParser()
    parser.add_argument("-m", "--mode", choices=['lightweight', 'full', 'choice'], default='choice',
                        help="Select mode (lightweight for tui, full is gui,"
                             "choice for a mode select window)", required=False)

    args, unknown = parser.parse_known_args()
    for arg in unknown:
        logging.warning("Unknown argument '%s'" % arg)

    if not hasattr(args, "mode") or args.mode == "choice":
        mode = select_mode()

        if mode is None:
            logging.warning("No mode selected. Exiting...")
            sys.exit(0)
    else:
        mode = args.mode

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
