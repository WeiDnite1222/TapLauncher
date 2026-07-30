from PySide6.QtWidgets import QWidget


class LaunchProfilePage(QWidget):
    def __init__(self, app, parent=None):
        super(LaunchProfilePage, self).__init__(parent)
        self.app = app