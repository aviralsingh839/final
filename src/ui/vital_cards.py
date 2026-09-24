"""Reusable vital sign card widgets."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout

from src.ui import theme
from src.ui.theme import ACCENT, TEXT_MUTED


class VitalCard(QFrame):
    def __init__(self, title: str, unit: str = "", compact: bool = False, parent=None):
        super().__init__(parent)
        self.title = title
        self.unit = unit
        self.compact = compact
        self.setObjectName("VitalCard")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setProperty("state", "gray")
        self.setMinimumHeight(44 if compact else 70)
        layout = QVBoxLayout(self)
        if compact:
            layout.setContentsMargins(6, 2, 6, 2)
            layout.setSpacing(0)
        else:
            layout.setContentsMargins(10, 5, 10, 5)
            layout.setSpacing(1)
        self.title_label = QLabel(title)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setWordWrap(True)
        self.title_label.setStyleSheet(
            f"font-weight: bold; color: {ACCENT}; font-size: {'8.5pt' if compact else '10pt'};")
        self.value_label = QLabel("--")
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.value_label.setObjectName("VitalValue")
        self._value_pt = 13 if compact else 18
        self.value_label.setStyleSheet(
            f"font-size: {self._value_pt}pt; font-weight: bold; color: {TEXT_MUTED};")
        # V8.2: no tiny labels — keep captions at 9pt minimum.
        self.status_label = QLabel("")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setWordWrap(True)
        self.status_label.setMinimumHeight(11 if compact else 16)
        self.status_label.setObjectName("SmallMuted")
        self.status_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: {'7.5pt' if compact else '9pt'};")
        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)
        layout.addWidget(self.status_label)

    def set_value(self, value, status: str = "", decimals: int = 1):
        if value is None:
            text = "--"
            if not status:
                status = "awaiting data"
        elif isinstance(value, str):
            text = value
        else:
            text = f"{float(value):.{decimals}f} {self.unit}".strip()
        self.value_label.setText(text)
        self.status_label.setText(status)
        # Missing data renders muted so "--" reads as intentional, not broken.
        color = TEXT_MUTED if value is None else theme.color("value_strong")
        self.value_label.setStyleSheet(
            f"font-size: {self._value_pt}pt; font-weight: bold; color: {color};")

    def set_color_state(self, state: str):
        """Set the semantic state; the shared theme stylesheet renders it."""
        if state not in ("green", "yellow", "orange", "red", "blue", "gray"):
            state = "gray"
        if self.property("state") == state:
            return
        self.setProperty("state", state)
        self.style().unpolish(self)
        self.style().polish(self)
