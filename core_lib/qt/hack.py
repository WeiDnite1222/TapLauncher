from PySide6.QtCore import QCoreApplication, QThread, QSize, Qt
from PySide6.QtGui import QScreen, QPixmap, QPainter, QPalette, QIcon
from PySide6.QtWidgets import QMainWindow, QApplication


def move_window_to_center(window: QMainWindow):
    main_screen = QApplication.primaryScreen()
    center = QScreen.availableGeometry(main_screen).center()
    geometry = window.frameGeometry()
    geometry.moveCenter(center)
    window.move(geometry.topLeft())

def is_main_thread() -> bool:
    app = QCoreApplication.instance()
    return app is not None and QThread.currentThread() == app.thread()

def recolor_standard_icon(widget, standard_pixmap, size=24):
    source_icon = widget.style().standardIcon(standard_pixmap)
    source = source_icon.pixmap(QSize(size, size))

    result = QPixmap(source.size())
    result.fill(Qt.GlobalColor.transparent)

    painter = QPainter(result)
    painter.drawPixmap(0, 0, source)
    painter.setCompositionMode(
        QPainter.CompositionMode.CompositionMode_SourceIn
    )
    painter.fillRect(
        result.rect(),
        widget.palette().color(QPalette.ColorRole.ButtonText),
    )
    painter.end()

    return QIcon(result)