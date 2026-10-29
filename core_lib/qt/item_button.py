from PySide6.QtWidgets import QLabel, QPushButton


class ItemButton(QPushButton):
    """Expose button states on child labels for reliable QSS color rules."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.toggled.connect(
            lambda checked: self._set_label_state("itemChecked", checked)
        )

    def _set_label_state(self, name: str, active: bool) -> None:
        for label in self.findChildren(QLabel):
            label.setProperty(name, active)
            label.style().unpolish(label)
            label.style().polish(label)
            label.update()

    def enterEvent(self, event):
        super().enterEvent(event)
        self._set_label_state("itemHovered", True)

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self._set_label_state("itemHovered", False)
