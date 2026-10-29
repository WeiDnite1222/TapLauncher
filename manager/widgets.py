import queue
import threading

from PySide6.QtCore import QObject, Signal

class SignalTransferItem:
    def __init__(self):
        self.result_queue = queue.Queue()
        self.wait_event = threading.Event()

    def wait(self, timeout: int | None = 10):
        return self.wait_event.wait(timeout)

    def result(self):
        try:
            return self.result_queue.get_nowait()
        except queue.Empty:
            return None

class AskForRequest(SignalTransferItem):
    def __init__(self, title, message):
        super(AskForRequest, self).__init__()
        self.title = title
        self.message = message
        self.result_queue = queue.Queue(maxsize=1)

        self.details = None # Set this if flag use_plain_text is enabled

        # flags
        self.use_plain_text = True

class SelectPathRequest(AskForRequest):
    def __init__(self, title, message, filter_raw=None):
        super().__init__(title, message)
        self.filter = filter_raw

class WidgetManager(QObject):
    def __init__(self):
        super(WidgetManager, self).__init__()

        self.signal = self.WidgetSignal(self)
        self.download_signal = self.DownloadSignal(self)

    def register_plugin_apis(self, plugin_manager):
        plugin_manager.register_api("launcher.ui.show_info", self.signal.show_info_message.emit)
        plugin_manager.register_api("launcher.ui.show_warning", self.signal.show_warning_message.emit)
        plugin_manager.register_api("launcher.ui.show_error", self.signal.show_error_message.emit)

    class DownloadSignal(QObject):
        started = Signal(str, str)  # task_id, display_name
        progress = Signal(str, str, float)  # task_id, status, percent
        finished = Signal(str)  # task_id
        failed = Signal(str, str)  # task_id, error
        removed = Signal(str)  # task_id
        log = Signal(str)

    class WidgetSignal(QObject):
        show_error_message = Signal(str)
        show_and_print_error_message = Signal(dict)
        show_warning_message = Signal(str)
        show_info_message = Signal(str)
        show_plain_error_text = Signal(dict)
        enable_widget = Signal(object)
        disable_widget = Signal(object)
        askyesno = Signal(object)
        ask_for_path = Signal(object)
