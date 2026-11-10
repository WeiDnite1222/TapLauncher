import base64
import binascii
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QThread, QSize, Qt, QBuffer, QIODevice
from PySide6.QtGui import QScreen, QPixmap, QPainter, QPalette, QIcon, QColor, QImage, QImageReader
from PySide6.QtWidgets import QMainWindow, QApplication, QWidget, QDialog


def move_window_to_center(window: QMainWindow | QDialog) -> None:
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

def add_icon_padding(icon: QIcon, icon_size=32, padding=6) -> QIcon:
    source = icon.pixmap(icon_size, icon_size)

    canvas_size = icon_size + padding * 2
    canvas = QPixmap(canvas_size, canvas_size)
    canvas.fill(Qt.GlobalColor.transparent)

    painter = QPainter(canvas)
    painter.drawPixmap(padding, padding, source)
    painter.end()

    return QIcon(canvas)

def data_url_to_qt_image(data_url: str) -> QImage:
    try:
        header, encoded_data = data_url.split(",", 1)
    except ValueError:
        raise ValueError("Not a valid data url")

    if ";base64" not in header:
        raise ValueError("Unsupported data url. Supported data urls are base64")

    try:
        image_data = base64.b64decode(encoded_data, validate=True)
    except ValueError as error:
        raise ValueError("Invalid image data") from error

    image = QImage.fromData(image_data)

    if image.isNull():
        raise ValueError("Qt does not support this image")

    return image

def base64_to_qicon(value: str) -> QIcon:
    if value.startswith("data:"):
        header, separator, value = value.partition(",")
        if not separator or ";base64" not in header:
            return QIcon()

    try:
        data = base64.b64decode("".join(value.split()), validate=True)
    except (ValueError, binascii.Error):
        return QIcon()

    pixmap = QPixmap()
    if not pixmap.loadFromData(data):
        return QIcon()

    return QIcon(pixmap)

def is_qt_supported_image(path: Path) -> tuple[bool, str | None]:
    if not path.is_file():
        return False, None

    reader = QImageReader(str(path))
    reader.setDecideFormatFromContent(True)


    if not reader.canRead():
        return False, None
    image_format = bytes(reader.format()).decode("ascii").lower() or None
    return not reader.read().isNull(), image_format

def image_to_data_url(path: Path, mime_type: str) -> str:
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def prepare_profile_icon(path: Path) -> tuple[str, bool]:
    """Validate and encode a square profile icon as a 128px PNG."""
    reader = QImageReader(str(path))
    reader.setDecideFormatFromContent(True)
    reader.setAutoTransform(True)
    image = reader.read()
    if image.isNull():
        raise ValueError("Image format is not supported.")
    if image.width() != image.height() or image.width() < 128:
        raise ValueError("Profile icons must be square and at least 128 x 128 pixels.")
    resized = image.width() > 128
    if resized:
        image = image.scaled(128, 128, Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not image.save(buffer, "PNG"):
        raise ValueError("Unable to encode profile icon.")
    encoded = base64.b64encode(bytes(buffer.data())).decode("ascii")
    return f"data:image/png;base64,{encoded}", resized

# ======================== AI generated END ========================
