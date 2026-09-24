"""Risk explanation panel."""
from __future__ import annotations

from PySide6.QtWidgets import QLabel, QProgressBar, QVBoxLayout, QWidget

from src.data_models import RiskResult
from src.ui.theme import ACCENT, progress_state_qss


class ExplanationPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        self.summary = QLabel("Waiting for data...")
        self.summary.setWordWrap(True)
        self.summary.setStyleSheet(f"font-size: 12pt; font-weight: bold; color: {ACCENT};")
        self.layout.addWidget(self.summary)
        self.bars: list[tuple[QLabel, QProgressBar]] = []
        for _ in range(8):
            label = QLabel("--")
            bar = QProgressBar()
            bar.setRange(0, 100)
            self.layout.addWidget(label)
            self.layout.addWidget(bar)
            self.bars.append((label, bar))
        self.notice = QLabel("Educational estimate only — not a medical diagnosis. Hormones are estimated, not measured.")
        self.notice.setWordWrap(True)
        self.notice.setObjectName("WarningText")
        self.layout.addWidget(self.notice)

    def update_result(self, result: RiskResult):
        self.summary.setText(result.explanation)
        for i, (label, bar) in enumerate(self.bars):
            if i < len(result.contributions):
                name, score, key = result.contributions[i]
                label.setText(f"{i+1}. {name}")
                value = int(max(0, min(100, result.domain_scores.get(key, 0))))
                bar.setValue(value)
                bar.setStyleSheet(progress_state_qss(value))
            else:
                label.setText("--")
                bar.setValue(0)
                bar.setStyleSheet(progress_state_qss(0))
