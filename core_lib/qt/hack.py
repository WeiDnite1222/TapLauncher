from pathlib import Path

from PySide6.QtCore import QCoreApplication, QThread, QSize, Qt
from PySide6.QtGui import QScreen, QPixmap, QPainter, QPalette, QIcon, QColor
from PySide6.QtWidgets import QMainWindow, QApplication, QWidget


def move_window_to_center(window: QMainWindow):
    main_screen = QApplication.primaryScreen()
    center = QScreen.availableGeometry(main_screen).center()
    geometry = window.frameGeometry()
    geometry.moveCenter(center)
    window.move(geometry.topLeft())

def is_main_thread() -> bool:
    app = QCoreApplication.instance()
    return app is not None and QThread.currentThread() == app.thread()

# ======================== AI generated ========================
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

def recolor_pixmap(
    path: str | Path,
    color: QColor | None = None,
) -> QPixmap:
    source = QPixmap(str(path))

    if source.isNull():
        raise FileNotFoundError(f"Unable to load image: {path}")

    if color is None:
        color = QApplication.palette().color(
            QPalette.ColorRole.ButtonText
        )

    result = QPixmap(source.size())
    result.setDevicePixelRatio(source.devicePixelRatio())
    result.fill(Qt.GlobalColor.transparent)

    painter = QPainter(result)
    painter.drawPixmap(0, 0, source)
    painter.setCompositionMode(
        QPainter.CompositionMode.CompositionMode_SourceIn
    )
    painter.fillRect(result.rect(), color)
    painter.end()

    return result


def recolor_icon(
    path: str | Path,
    color: QColor | None = None,
) -> QIcon:
    return QIcon(recolor_pixmap(path, color))

def is_light_theme(widget=None) -> bool:
    palette = (
        widget.palette()
        if widget is not None
        else QApplication.palette()
    )

    color = palette.color(QPalette.ColorRole.Window)

    luminance = (
        0.2126 * color.redF()
        + 0.7152 * color.greenF()
        + 0.0722 * color.blueF()
    )

    return luminance >= 0.5

# ======================== AI generated END ========================