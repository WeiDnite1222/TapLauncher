from PySide6.QtWidgets import QMessageBox, QMainWindow, QWidget

def create_messagebox(parent: QWidget, title: str, message: str,
                      icon: QMessageBox.Icon = QMessageBox.Icon.Information,
                      button: QMessageBox.StandardButton = QMessageBox.StandardButton.Ok) -> QMessageBox:
    msg = QMessageBox(parent)
    msg.setWindowTitle(title)
    msg.setText(message)
    msg.setIcon(icon)
    msg.setStandardButtons(button)
    return msg


def error(parent: QWidget, title: str, message: str,
          button: QMessageBox.StandardButton = QMessageBox.StandardButton.Ok) -> None:
    create_messagebox(
        parent,
        title=title,
        message=message,
        icon=QMessageBox.Icon.Critical,
        button=button
    ).exec()


def info(parent: QWidget, title: str, message: str,
         button: QMessageBox.StandardButton = QMessageBox.StandardButton.Ok) -> None:
    create_messagebox(
        parent,
        title=title,
        message=message,
        icon=QMessageBox.Icon.Information,
        button=button
    ).exec()


def warning(parent: QWidget, title: str, message: str,
            button: QMessageBox.StandardButton = QMessageBox.StandardButton.Ok) -> None:
    create_messagebox(
        parent,
        title=title,
        message=message,
        icon=QMessageBox.Icon.Warning,
        button=button
    ).exec()
