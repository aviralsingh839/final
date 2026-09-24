"""Hormone estimate panel."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QLabel, QFrame, QVBoxLayout, QWidget

from src.data_models import HormoneEstimate
from src.ui.theme import ACCENT, ACCENT_STRONG, INDIGO, PINK, TEXT_MUTED, VIOLET

# Accent per hormone so each card reads at a glance.
HORMONE_ACCENTS = {
    "Insulin": ACCENT_STRONG,
    "Testosterone": INDIGO,
    "LH": VIOLET,
    "FSH": PINK,
    "Estrogen": PINK,
    "Progesterone": VIOLET,
    "Cortisol": ACCENT_STRONG,
    "AMH": INDIGO,
}


class HormoneCard(QFrame):
    def __init__(self, name: str, parent=None):
        super().__init__(parent)
        self.name = name
        self.accent = HORMONE_ACCENTS.get(name, ACCENT)
        self.setObjectName("HormoneCard")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        # Background/border come from the shared theme stylesheet; only the
        # per-hormone accent stripe is set here.
        self.setStyleSheet(
            f"QFrame#HormoneCard {{ border-left: 4px solid {self.accent}; }}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        self.title = QLabel(name)
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title.setObjectName("HormoneTitle")
        self.title.setStyleSheet(f"color: {self.accent}; font-weight: bold; font-size: 10.5pt;")
        self.value = QLabel("--")
        self.value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.value.setObjectName("HormoneValue")
        self.note = QLabel("Estimated Hormone Level\nnot measured")
        self.note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.note.setWordWrap(True)
        self.note.setObjectName("SmallMuted")
        self.note.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 9pt;")
        layout.addWidget(self.title)
        layout.addWidget(self.value)
        layout.addWidget(self.note)

    def update_estimate(self, est: HormoneEstimate):
        self.value.setText(f"{est.value:.2f} {est.unit}\nCI {est.ci_low:.2f}–{est.ci_high:.2f}")
        self.note.setText(f"Estimated Hormone Level\nConfidence {est.confidence:.0f}%")
        from src.ui import theme as _theme
        color = _theme.PINK if est.confidence < 35 else _theme.color("value_strong")
        self.value.setStyleSheet(f"font-size: 11.5pt; font-weight: bold; color: {color};")


class HormonePanel(QWidget):
    NAMES = ["Insulin", "Testosterone", "LH", "FSH", "Estrogen", "Progesterone", "Cortisol", "AMH"]

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QGridLayout(self)
        layout.setSpacing(10)
        self.cards = {}
        for i, name in enumerate(self.NAMES):
            card = HormoneCard(name)
            self.cards[name] = card
            layout.addWidget(card, i // 2, i % 2)

    def update_hormones(self, hormones: dict[str, HormoneEstimate]):
        for name, est in hormones.items():
            if name in self.cards:
                self.cards[name].update_estimate(est)
