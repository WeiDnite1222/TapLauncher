import logging
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QTimer, QEvent, QPointF
from PySide6.QtGui import QPalette, QEnterEvent
from PySide6.QtWidgets import QApplication, QWidget, QDialog, QMessageBox, QPushButton

from app import Launcher
from core_lib.qt import messagebox
from pages.launch_profile import ProfileListItem
from pages.manage_profile import ManageProfileItem


class StylesheetApp:
    locate_styles_path = Launcher.locate_styles_path
    apply_qss = Launcher.apply_qss
    apply_theme = Launcher.apply_theme
    _read_theme_manifest = staticmethod(Launcher._read_theme_manifest)
    _read_palette = staticmethod(Launcher._read_palette)
    _palette_from_colors = staticmethod(Launcher._palette_from_colors)

    def __init__(self, root, qt_app):
        self.qt_app = qt_app
        self.styles_path = root / "styles"
        self.styles_path.mkdir()
        self.theme_dir = root / "custom"
        (self.theme_dir / "styles").mkdir(parents=True)
        self.settings_manager = SimpleNamespace(
            get=lambda *_: SimpleNamespace(theme="custom")
        )
        self._system_palette = QPalette(qt_app.palette())
        self.logger = logging.getLogger(__name__)
        self.setPalette = qt_app.setPalette
        self.setStyleSheet = qt_app.setStyleSheet
        self.allWidgets = qt_app.allWidgets

    def _theme_packages(self):
        return {"custom": self.theme_dir}


@pytest.fixture
def style_app(tmp_path):
    qt_app = QApplication.instance() or QApplication([])
    palette = QPalette(qt_app.palette())
    stylesheet = qt_app.styleSheet()
    yield StylesheetApp(tmp_path, qt_app)
    qt_app.setStyleSheet(stylesheet)
    qt_app.setPalette(palette)


def test_theme_stylesheet_override_and_default_fallback(style_app):
    default = style_app.styles_path / "main.qss"
    default.write_text("QWidget { color: red; }", encoding="utf-8")
    override = style_app.theme_dir / "styles" / "main.qss"
    assert style_app.locate_styles_path(Path("main.qss")) == default
    override.mkdir()  # A directory is not a usable stylesheet.
    assert style_app.locate_styles_path(Path("main.qss")) == default
    override.rmdir()
    override.write_text("QWidget { color: blue; }", encoding="utf-8")
    assert style_app.locate_styles_path(Path("main.qss")) == override


def test_switching_theme_reloads_stylesheets(style_app):
    default_qss = "/* 預設樣式 */ QWidget { color: red; }"
    default = style_app.styles_path / "main.qss"
    default.write_text(default_qss, encoding="utf-8")
    override = style_app.theme_dir / "styles" / "main.qss"
    override.write_text("QWidget { color: blue; }", encoding="utf-8")
    widget = QWidget()
    style_app.apply_qss(Path("main.qss"), widget.setStyleSheet)
    assert widget.styleSheet() == override.read_text(encoding="utf-8")
    style_app.apply_theme("system")
    assert widget.styleSheet() == default_qss
    assert style_app.locate_styles_path(Path("main.qss")) == default
    widget.close()


def test_invalid_theme_falls_back_to_default_styles(style_app):
    default = style_app.styles_path / "main.qss"
    default.write_text("QWidget { color: red; }", encoding="utf-8")
    style_app.apply_theme("custom")  # Missing palette and manifest.
    assert style_app._active_theme == "system"
    assert style_app.locate_styles_path(Path("main.qss")) == default


@pytest.mark.parametrize("theme, background", [("aqua", "#f1f3f7"), ("windows-9x", "#c0c0c0"), ("bliss", "#ece9d8")])
def test_message_boxes_follow_application_theme(style_app, theme, background):
    style_app.theme_dir = Path(__file__).resolve().parents[1] / "resources/themes" / theme
    style_app.apply_theme("custom")
    parent = QWidget()
    boxes = [messagebox.create_messagebox(owner, "Theme", "Message")
             for owner in (None, parent)]
    for box in boxes:
        box.ensurePolished()
        assert box.testOption(QMessageBox.Option.DontUseNativeDialog)
        assert box.palette().color(QPalette.ColorRole.Window).name() == background
        button = box.button(QMessageBox.StandardButton.Ok)
        button.ensurePolished()
        assert (button.palette().brush(QPalette.ColorRole.Button).gradient() is not None) == (theme in {"aqua", "bliss"})
    (style_app.styles_path / "main.qss").write_text("", encoding="utf-8")
    style_app.apply_theme("system")
    assert style_app.qt_app.styleSheet() == ""
    for box in boxes:
        box.close()


def test_static_question_inherits_aqua(style_app):
    style_app.theme_dir = Path(__file__).resolve().parents[1] / "resources/themes/aqua"
    style_app.apply_theme("custom")
    colors = []

    def accept_question():
        box = style_app.qt_app.activeModalWidget()
        colors.append(box.palette().color(QPalette.ColorRole.Window).name())
        box.button(QMessageBox.StandardButton.Yes).click()

    QTimer.singleShot(0, accept_question)
    result = QMessageBox.question(None, "Confirm", "Continue?")
    assert result == QMessageBox.StandardButton.Yes
    assert colors == ["#f1f3f7"]


@pytest.mark.parametrize("question", [False, True])
def test_detailed_dialogs_inherit_aqua(style_app, monkeypatch, question):
    style_app.theme_dir = Path(__file__).resolve().parents[1] / "resources/themes/aqua"
    style_app.apply_theme("custom")
    checked = []

    def inspect_dialog(dialog):
        dialog.ensurePolished()
        buttons = dialog.findChildren(QPushButton)
        assert buttons
        for button in buttons:
            button.ensurePolished()
            assert button.palette().brush(QPalette.ColorRole.Button).gradient() is not None
        checked.append(True)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(QDialog, "exec", inspect_dialog)
    if question:
        assert messagebox.ask_yes_no_with_plain_text(None, "Confirm", "Message", "Details")
    else:
        messagebox.error_with_plain_text(None, "Error", "Message", "Details")
    assert checked == [True]


@pytest.mark.parametrize("theme, normal_color", [("aqua", "#626d7e"), ("windows-9x", "#404040"), ("bliss", "#555d69")])
@pytest.mark.parametrize("managed", [False, True])
def test_profile_label_colors_follow_button_state(style_app, theme, normal_color, managed):
    root = Path(__file__).resolve().parents[1]
    style_app.theme_dir = root / "resources/themes" / theme
    style_app.apply_theme("custom")
    style_app.icon_dir = root / "resources/icons"
    profile = SimpleNamespace(icon=str(style_app.icon_dir / "profile_default.png"),
                              display_name="Example", version_id="1.21")
    container = QWidget()
    filename = "manage_profile.qss" if managed else "profile.qss"
    style_app.apply_qss(Path(filename), container.setStyleSheet)
    row = (ManageProfileItem(style_app, profile, container) if managed
           else ProfileListItem(profile, container))
    label = row.findChild(QWidget, "itemVersion")
    label.ensurePolished()

    def color():
        return label.palette().color(QPalette.ColorRole.WindowText).name()

    assert color() == normal_color
    if managed:
        row.setChecked(True)
    else:
        point = QPointF(4, 4)
        QApplication.sendEvent(row, QEnterEvent(point, point, point))
    assert color() == "#ffffff"
    if managed:
        row.setChecked(False)
    else:
        QApplication.sendEvent(row, QEvent(QEvent.Type.Leave))
    assert color() == normal_color
    container.close()
