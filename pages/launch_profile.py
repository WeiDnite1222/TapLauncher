from pathlib import Path

from PySide6.QtCore import Qt, Signal, QPointF
from PySide6.QtGui import QIcon, QMouseEvent, QHideEvent, QPixmap, QPainter, QColor
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QHBoxLayout, QPushButton, QScrollArea, QGridLayout, \
    QComboBox, QFrame, QSizePolicy, QApplication, QGraphicsDropShadowEffect

from manager.profile import ProfileSummary


class ProfileButton(QFrame):
    clicked = Signal()
    """
    ProfileButton

    This object is coded by codex!
    """

    def __init__(self, app, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.app = app
        self.setObjectName("profileButton")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(64)
        self.setMaximumHeight(64)

        # Layout
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(12, 8, 12, 8)
        self.layout.setSpacing(12)
        self.text_layout = QVBoxLayout()
        self.text_layout.setSpacing(1)

        # Widget
        self.icon_label = QLabel()
        self.icon_label.setFixedSize(40, 40)
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.name_label = QLabel()
        self.name_label.setObjectName("profileName")
        self.version_label = QLabel()
        self.version_label.setObjectName("profileVersion")
        self.arrow_label = QLabel("▾")
        self.arrow_label.setObjectName("profileArrow")
        self.arrow_label.setStyleSheet("border-style:solid; background-color: transparent; ")
        self.arrow_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.arrow_label.setFixedWidth(24)

        # Bind
        self.text_layout.addWidget(self.name_label)
        self.text_layout.addWidget(self.version_label)

        self.layout.addWidget(self.icon_label)
        self.layout.addLayout(self.text_layout, 1)
        self.layout.addWidget(self.arrow_label)

    def set_profile(self, profile: ProfileSummary) -> None:
        """
        Set current profile id
        :param profile:
        :return:
        """
        self.setProperty("profile_id", profile.id)
        self.name_label.setText(profile.name)
        self.version_label.setText(profile.version_id)

        icon_path = profile.icon

        if not isinstance(icon_path, Path):
            icon_path = Path(icon_path)

        if not icon_path.exists() or not icon_path.is_file():
            # Use default
            icon_path = Path(self.app.icon_dir, "profile_default.png")

        self.icon_label.setPixmap(QIcon(icon_path.as_posix()).pixmap(36, 36))

    def set_popup_open(self, opened: bool) -> None:
        self.arrow_label.setText("▴" if opened else "▾")

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

class ProfileListItem(QPushButton):
    selected = Signal(object)

    def __init__(self, profile: ProfileSummary, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.profile = profile
        self.setObjectName("profileItem")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(62)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 7, 12, 7)
        layout.setSpacing(12)

        self.icon_label = QLabel()
        self.icon_label.setFixedSize(40, 40)
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(1)
        name_label = QLabel(profile.name)
        name_label.setObjectName("itemName")
        version_label = QLabel(profile.version_id)
        version_label.setObjectName("itemVersion")
        text_layout.addWidget(name_label)
        text_layout.addWidget(version_label)

        layout.addWidget(self.icon_label)
        layout.addLayout(text_layout, 1)
        self.clicked.connect(lambda: self.selected.emit(self.profile))

    def set_icon(self, icon_path: Path) -> None:
        self.icon_label.setPixmap(QIcon(icon_path.as_posix()).pixmap(36, 36))

class ProfilePopup(QFrame):
    profile_selected = Signal(object)
    closed = Signal()

    def __init__(self, app, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Popup)
        self.app = app
        self.setFixedHeight(210)
        self.setObjectName("profilePopup")

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(4, 4, 4, 4)
        self.layout.setSpacing(0)

        self.scroll_area = QScrollArea(self)
        self.scroll_area.setObjectName("profileScrollArea")
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.scroll_area.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )

        self.content = QWidget()
        self.content.setObjectName("profileListContent")
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(2)

        self.scroll_area.setWidget(self.content)
        self.layout.addWidget(self.scroll_area)
        self.content_layout.setAlignment(
            Qt.AlignmentFlag.AlignTop
        )

    def load_profiles(self, profiles: list[ProfileSummary]) -> None:
        for profile in profiles:
            icon_path = profile.icon

            if not isinstance(icon_path, Path):
                icon_path = Path(icon_path)

            if not icon_path.exists() or not icon_path.is_file():
                # Use default
                icon_path = Path(self.app.icon_dir, "profile_default.png")

            item = ProfileListItem(profile, self)
            item.selected.connect(self.profile_selected)
            item.set_icon(icon_path)
            self.content_layout.addWidget(item)


    def hideEvent(self, event: QHideEvent) -> None:
        self.closed.emit()
        super().hideEvent(event)


class LaunchProfilePage(QWidget):
    def __init__(self, app, parent=None):
        super(LaunchProfilePage, self).__init__(parent)
        self.app = app
        self.profile_manager = app.profile_manager

        # Layout
        self.layout = QVBoxLayout(self)
        self.bottom_layout = QHBoxLayout()

        # Widgets
        self.status_label = QLabel("Select a version to launch")
        self.status_label.setStyleSheet("font-size: 12px; font-weight: 600;")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Profile button (just like the official launcher look like)
        self.profile_button = ProfileButton(self.app)
        self.profile_button.setMinimumWidth(260)
        self.profile_button.setMaximumWidth(360)
        self.profile_popup = ProfilePopup(parent=self, app=self.app)
        self.profile_button.clicked.connect(self.toggle_profile_popup)
        self.profile_popup.profile_selected.connect(self.select_profile)
        self.profile_popup.closed.connect(self.refresh_profile_button)

        launch_button = QPushButton("Launch Game")
        launch_button.setObjectName("launchButton")
        launch_button.setMinimumWidth(120)
        launch_button.setMinimumHeight(42)
        launch_button.setMaximumHeight(64)
        launch_button.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Expanding,
        )
        launch_button.clicked.connect(self.launch_profile)

        # Profile overlay
        self.profile_frame = self.ProfileBackgroundFrame(
            parent=self,
            image_path=Path(
                self.app.icon_dir,
                "profile_default.png",
            ),
        )
        self.profile_frame.setObjectName("profileFrame")

        # Frame layout and overlay
        frame_layout = QVBoxLayout(self.profile_frame)
        frame_layout.setContentsMargins(20, 20, 20, 20)

        self.profile_overlay = QFrame(self.profile_frame)
        self.profile_overlay.setObjectName("header")

        # Add a nice shadow
        # shadow = QGraphicsDropShadowEffect(self.profile_frame)
        # shadow.setBlurRadius(24)
        # shadow.setOffset(QPointF(0, 6))
        # shadow.setColor(QColor(0, 0, 0, 150))

        # self.profile_frame.setGraphicsEffect(shadow)

        # Header
        self.header_label = QLabel("Launch Profile")
        self.header_label.setObjectName("headerLabel")

        self.header_layout = QHBoxLayout(self.profile_overlay)
        self.header_layout.addWidget(self.header_label)
        self.header_layout.addStretch()

        frame_layout.addWidget(self.profile_overlay)
        frame_layout.addStretch()

        # Bind button widget
        self.bottom_layout.setContentsMargins(0, 0, 0, 0)
        self.bottom_layout.setSpacing(10)
        self.bottom_layout.addWidget(self.profile_button)
        self.bottom_layout.addStretch()
        self.bottom_layout.addWidget(self.status_label)
        self.bottom_layout.addStretch()
        self.bottom_layout.addWidget(launch_button)

        self.layout.addWidget(self.profile_frame, 1)
        self.layout.addLayout(self.bottom_layout)

        self.app.apply_qss(Path("profile.qss"), self.setStyleSheet)

        self.load_profiles()

    class ProfileBackgroundFrame(QFrame):
        def __init__(self, image_path, parent=None):
            super().__init__(parent)
            self.background = QPixmap(str(image_path))

        def paintEvent(self, event):
            super().paintEvent(event)

            painter = QPainter(self)

            if not self.background.isNull():
                scaled = self.background.scaled(
                    self.size(),
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation,
                )

                x = (self.width() - scaled.width()) // 2
                y = (self.height() - scaled.height()) // 2
                painter.drawPixmap(x, y, scaled)

    def load_profiles(self):
        profiles: list[ProfileSummary] = self.profile_manager.list_profiles()
        self.profile_popup.load_profiles(profiles)

        if len(profiles) > 0:
            self.select_profile(profiles[0])

    def toggle_profile_popup(self) -> None:
        if self.profile_popup.isVisible():
            self.profile_popup.hide()
            self.profile_button.set_popup_open(False)
            return

        self.profile_popup.setFixedWidth(self.profile_button.width())

        button_top = self.profile_button.mapToGlobal(
            self.profile_button.rect().topLeft()
        )
        button_bottom = self.profile_button.mapToGlobal(
            self.profile_button.rect().bottomLeft()
        )

        screen = QApplication.screenAt(
            self.profile_button.mapToGlobal(
                self.profile_button.rect().center()
            )
        )
        if screen is None:
            screen = QApplication.primaryScreen()

        # Show profile popup at bottom if screen space is enough to render (if not, render at top of the button)
        available = screen.availableGeometry()
        popup_width = self.profile_popup.width()
        popup_height = self.profile_popup.height()
        space_below = available.bottom() - button_bottom.y()
        space_above = button_top.y() - available.top()

        if space_below < popup_height and space_above > space_below:
            popup_y = button_top.y() - popup_height
        else:
            popup_y = button_bottom.y() + 1

        popup_x = max(
            available.left(),
            min(button_bottom.x(), available.right() - popup_width + 1),
        )
        popup_y = max(
            available.top(),
            min(popup_y, available.bottom() - popup_height + 1),
        )

        self.profile_popup.move(popup_x, popup_y)
        self.profile_popup.show()
        self.profile_button.set_popup_open(True)

    def refresh_profile_button(self) -> None:
        # Refresh profile button (Due to some unknown issue, the button arrow have a black
        # background after profile menu profile_popup. Rerender the button can fix this issue)
        self.profile_button.set_popup_open(False)
        self.profile_button.updateGeometry()
        self.profile_button.repaint()

    def select_profile(self, profile: ProfileSummary) -> None:
        # Update select profile id
        self.profile_button.set_profile(profile)
        self.profile_popup.hide()
        self.profile_button.set_popup_open(False)

    def launch_profile(self) -> None:
        profile_id = self.profile_button.property("profile_id")
        self.status_label.setText(f"Preparing to launch...")