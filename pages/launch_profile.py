from pathlib import Path

from PySide6.QtCore import Qt, Signal, Slot, QTimer
from PySide6.QtGui import QIcon, QMouseEvent, QHideEvent, QPixmap, QPainter
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QLabel, QHBoxLayout, QPushButton, QScrollArea, QFrame,
                               QSizePolicy, QApplication)

from manager.game import LaunchManager, LaunchResult
from core_lib.game.version_info import LATEST_VERSION_ALIASES
from manager.profile import ProfileSummary, LaunchProfile, ProfileManager
from manager.widgets import AskForRequest, WidgetManager
from pages.process_log import ProcessLogWindow
from core_lib.qt.item_button import ItemButton


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
        self.name_label.setText(profile.display_name)
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

class ProfileListItem(ItemButton):
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

        name_label = QLabel(profile.display_name)

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
        # Clean old profiles
        self.clean_profiles()

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

    def clean_profiles(self) -> None:
        while self.content_layout.count():
            layout_item = self.content_layout.takeAt(0)
            widget = layout_item.widget()

            if widget is not None:
                widget.hide()
                widget.deleteLater()

    def hideEvent(self, event: QHideEvent) -> None:
        self.closed.emit()
        super().hideEvent(event)


class LaunchProfilePage(QWidget):
    def __init__(self, app, parent=None):
        super(LaunchProfilePage, self).__init__(parent)
        self.app = app
        self.widget_mgr: WidgetManager = app.widget_manager
        self.profile_manager: ProfileManager = app.profile_manager
        self.game_manager = app.game_manager
        self.launch_manager: LaunchManager = self.game_manager.launch
        self.process_log_windows: list[ProcessLogWindow] = []

        # Layout
        self.layout = QVBoxLayout(self)
        self.bottom_layout = QHBoxLayout()

        # Widgets
        self.status_label = QLabel(self.app.tr_text("Select a profile to launch"))
        self.status_label.setObjectName("launchStatus")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Profile button (just like the official launcher look like)
        self.profile_button = ProfileButton(self.app)
        self.profile_button.setMinimumWidth(260)
        self.profile_button.setMaximumWidth(360)
        self.profile_popup = ProfilePopup(parent=self, app=self.app)
        self.profile_button.clicked.connect(self.toggle_profile_popup)
        self.profile_popup.profile_selected.connect(self.select_profile)
        self.profile_popup.closed.connect(self.refresh_profile_button)

        launch_button = QPushButton(self.app.tr_text("Launch Game"))
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
        self.header_label = QLabel(self.app.tr_text("Launch Profile"))
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

        # Handle launch() result
        self.launch_manager.signal.finished.connect(
            self.launch_finished,
            Qt.ConnectionType.QueuedConnection,
        )

        self.profile_manager.profiles_changed.connect(
            self.load_profiles,
        )

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

    @Slot(object, object)
    def launch_finished(self, launch_profile: LaunchProfile, result: LaunchResult) -> None:
        """
        Handle launch finished signal
        :param launch_profile:
        :param result:
        :return:
        """
        if not result.success:
            self.status_label.setText(self.app.tr_text("Launch Failed"))
            self.widget_mgr.signal.show_error_message.emit(
                self.app.tr_text(
                    "Unable to launch profile {profile}: {error}",
                    profile=launch_profile.display_name,
                    error=result.error_message,
                )
            )
            self.status_label_cleanup()
            return
        else:
            if callable(result.success_callback):
                result.success_callback()

        # Create log view
        log_window = ProcessLogWindow(
            self.app,
            result.process,
            launch_profile.profile_id,
            title=(
                f"Minecraft Log - {launch_profile.display_name} "
                f"({launch_profile.version_id})"
            ),
            parent=None,
            finished_callback=self.launch_manager.profile_finished,
        )

        for warning in result.warnings:
            log_window.append_message(
                f"[launcher warning] {warning}"
            )

        self.process_log_windows.append(log_window)
        log_window.show()

        self.status_label.setText(self.app.tr_text("Launched!"))

        # Cleanup for status label
        self.status_label_cleanup()

    def status_label_cleanup(self):
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda: self.status_label.setText(
            self.app.tr_text("Select a profile to launch")
        ))
        timer.start(3000)

    def load_profiles(self):
        profiles: list[ProfileSummary] = self.profile_manager.list_profiles()
        self.profile_popup.load_profiles(profiles)

        if not profiles:
            self.profile_button.setProperty("profile_id", None)
            self.profile_button.name_label.setText(self.app.tr_text("No profiles available"))
            self.profile_button.version_label.clear()
            return

        selected_id = self.profile_button.property("profile_id")
        available = {profile.id: profile for profile in profiles}
        selected = available.get(selected_id)
        if selected is None:
            selected = available.get(self.profile_manager.get_current_profile_id())
        self.select_profile(selected or profiles[0])

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

        if profile_id is None:
            self.widget_mgr.signal.show_warning_message.emit(
                self.app.tr_text("There is no profile is selected. Please create one first.")
            )
            return

        self.status_label.setText(self.app.tr_text("Preparing to launch..."))
        launch_profile = self.app.profile_manager.get_launch_profile(profile_id)

        if launch_profile is None:
            self.status_label.setText(self.app.tr_text("Unable to load the selected profile."))
            return

        if self.launch_manager.is_profile_running(launch_profile.profile_id):
            request = AskForRequest(
                self.app.tr_text("Launch Request"),
                self.app.tr_text(
                    "Target profile {profile} is running. Are you sure you want to launch it again?",
                    profile=launch_profile.display_name,
                ),
            )
            self.widget_mgr.signal.askyesno.emit(request)

            if not request.wait(60):
                self.widget_mgr.signal.show_error_message.emit(
                    self.app.tr_text("Time out waiting for request for launch.")
                )
                return

            if not request.result() is True:
                return

        self.launch_manager.start_launch_task(launch_profile)
        # The log view window creation process has been moved to the method self.launch_finished, move to there!
