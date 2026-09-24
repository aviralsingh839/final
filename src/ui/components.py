"""Reusable V8.2 UI building blocks.

Centralizes the card / stat-tile / collapsible-detail patterns so pages do not
duplicate styling.  All colors come from the shared theme tokens.

Information levels (V8.2):
  Level 1 — simple statement ("What is happening?")            → cards/tiles
  Level 2 — explanation ("Why is the system showing this?")    → [WHY?]
  Level 3 — technical ("What data/statistics support this?")   → [TECHNICAL DETAILS]
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from src.ui import theme

# Data-source provenance labels (V8.2 §24).
SOURCE_LABELS = {
    "measured": "MEASURED · wearable/device",
    "patient": "PATIENT REPORTED",
    "clinical": "CLINICALLY ENTERED",
    "image": "IMAGE-DERIVED",
    "model": "MODEL-INFERRED",
    "demo": "DEMO DATA",
}


def page_title(text: str, subtitle: str = "") -> QWidget:
    """A large page heading with an optional one-line subtitle."""
    box = QWidget()
    lay = QVBoxLayout(box)
    lay.setContentsMargins(2, 2, 2, 2)
    lay.setSpacing(2)
    title = QLabel(text)
    title.setObjectName("PageTitle")
    title.setWordWrap(True)
    lay.addWidget(title)
    if subtitle:
        sub = QLabel(subtitle)
        sub.setObjectName("PageSubtitle")
        sub.setWordWrap(True)
        lay.addWidget(sub)
    return box


def source_tag(kind: str) -> QLabel:
    """Small provenance chip, e.g. MEASURED / PATIENT REPORTED / MODEL-INFERRED."""
    label = QLabel(SOURCE_LABELS.get(kind, kind))
    label.setObjectName("SourceTag")
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
    return label


def empty_state(text: str) -> QLabel:
    """Professional empty-state placeholder — never fabricate values."""
    label = QLabel(text)
    label.setObjectName("EmptyState")
    label.setWordWrap(True)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return label


class SectionCard(QFrame):
    """A clean white card with a section title and optional subtitle."""

    def __init__(self, title: str = "", subtitle: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(18, 14, 18, 16)
        self._lay.setSpacing(8)
        if title:
            t = QLabel(title)
            t.setObjectName("SectionTitle")
            t.setWordWrap(True)
            self._lay.addWidget(t)
        if subtitle:
            s = QLabel(subtitle)
            s.setObjectName("SmallMuted")
            s.setWordWrap(True)
            self._lay.addWidget(s)

    def add_widget(self, w: QWidget, stretch: int = 0):
        self._lay.addWidget(w, stretch)
        return w

    def add_layout(self, lay, stretch: int = 0):
        self._lay.addLayout(lay, stretch)
        return lay


class StatTile(QFrame):
    """Big-number tile: label on top, large value, optional caption below.

    Never shrinks its font to fit — captions wrap instead.
    """

    def __init__(self, label: str, value: str = "—", caption: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("StatCard")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(3)
        self.label = QLabel(label)
        self.label.setObjectName("StatLabel")
        self.label.setWordWrap(True)
        self.value = QLabel(value)
        self.value.setObjectName("StatValue")
        self.value.setWordWrap(True)
        self.caption = QLabel(caption)
        self.caption.setObjectName("SmallMuted")
        self.caption.setWordWrap(True)
        self.caption.setVisible(bool(caption))
        lay.addWidget(self.label)
        lay.addWidget(self.value)
        lay.addWidget(self.caption)

    def set(self, value: str, caption: str | None = None, state: str | None = None):
        self.value.setText(value)
        if caption is not None:
            self.caption.setText(caption)
            self.caption.setVisible(bool(caption))
        if state is not None:
            color = theme.status_color(state)
            self.value.setStyleSheet(f"font-size: 17pt; font-weight: 700; color: {color};")
        else:
            self.value.setStyleSheet("")


class StatusRow(QFrame):
    """One 'What changed?' row: icon/emoji + metric + plain statement + chip."""

    def __init__(self, icon: str, metric: str, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(10)
        self.icon = QLabel(icon)
        self.icon.setStyleSheet("font-size: 15pt;")
        self.icon.setFixedWidth(34)
        self.icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_box = QVBoxLayout()
        name_box.setSpacing(1)
        # NOTE: never name this attribute "metric" — it would shadow the
        # inherited QPaintDevice.metric() virtual and crash Qt style updates.
        self.metric_label = QLabel(metric)
        self.metric_label.setStyleSheet("font-weight: 700; font-size: 11pt;")
        self.statement = QLabel("—")
        self.statement.setObjectName("SmallMuted")
        self.statement.setWordWrap(True)
        name_box.addWidget(self.metric_label)
        name_box.addWidget(self.statement)
        self.chip = QLabel("STABLE")
        self.chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.chip.setFixedWidth(110)
        lay.addWidget(self.icon)
        lay.addLayout(name_box, 1)
        lay.addWidget(self.chip)
        self.set_state("stable", "No major change")

    def set_state(self, state: str, statement: str):
        """state: stable | improved | changed | review"""
        palette = {
            "stable": (theme.GREEN, "STABLE"),
            "improved": (theme.ACCENT_STRONG, "IMPROVED"),
            "changed": (theme.YELLOW, "CHANGED"),
            "review": (theme.ORANGE, "REVIEW"),
        }
        color, text = palette.get(state, (theme.TEXT_MUTED, state.upper()))
        self.chip.setText(text)
        self.chip.setStyleSheet(
            f"QLabel {{ background: {theme.tint(color, 0.12)}; border: 1px solid {color}; color: {color};"
            f" font-size: 9.5pt; font-weight: 700; padding: 3px 10px; border-radius: 10px; }}")
        self.statement.setText(statement)


class CollapsibleSection(QWidget):
    """Expandable [TECHNICAL DETAILS] / [WHY?] container.

    Level-2/3 information lives here so the main view stays simple.
    """

    def __init__(self, title: str = "Technical details", parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 0)
        lay.setSpacing(4)
        self.toggle = QToolButton()
        self.toggle.setText("▸ " + title)
        self.toggle.setCheckable(True)
        self.toggle.setChecked(False)
        self.toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self._title = title
        self.body = QWidget()
        self.body.setVisible(False)
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(8, 2, 2, 2)
        self.body_layout.setSpacing(6)
        self.toggle.toggled.connect(self._on_toggled)
        lay.addWidget(self.toggle)
        lay.addWidget(self.body)

    def _on_toggled(self, checked: bool):
        self.body.setVisible(checked)
        self.toggle.setText(("▾ " if checked else "▸ ") + self._title)

    def add_widget(self, w: QWidget):
        self.body_layout.addWidget(w)
        return w


def status_banner(text: str, state: str = "yellow") -> QLabel:
    """A calm, readable banner (used for withheld predictions / notices)."""
    color = theme.status_color(state)
    label = QLabel(text)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setWordWrap(True)
    label.setStyleSheet(
        f"QLabel {{ background: {theme.tint(color, 0.10)}; border: 1px solid {color}; color: {color}; "
        f"font-size: 11pt; font-weight: 600; padding: 10px; border-radius: 8px; }}")
    return label
