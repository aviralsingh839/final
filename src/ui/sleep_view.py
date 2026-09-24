"""Sleep probability/hypnogram view."""
from __future__ import annotations

from collections import deque

import pyqtgraph as pg
from PySide6.QtWidgets import QVBoxLayout, QLabel, QWidget

from src.ui.theme import TEXT_MUTED, style_plot


class SleepViewWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.t = deque(maxlen=720)
        self.sleep = deque(maxlen=720)
        self.deep = deque(maxlen=720)
        self.rem = deque(maxlen=720)
        layout = QVBoxLayout(self)
        self.label = QLabel("Sleep status / probability estimates")
        self.label.setStyleSheet(f"font-weight: 600; color: {TEXT_MUTED}; font-size: 10.5pt;")
        self.plot = pg.PlotWidget()
        style_plot(self.plot, y_label="%", x_label="seconds ago")
        self.plot.setYRange(0, 100)
        self.sleep_curve = self.plot.plot(pen=pg.mkPen("#3aa7f0", width=2), name="Sleep")
        self.deep_curve = self.plot.plot(pen=pg.mkPen("#34d399", width=1), name="Deep")
        self.rem_curve = self.plot.plot(pen=pg.mkPen("#f472b6", width=1), name="REM")
        layout.addWidget(self.label)
        layout.addWidget(self.plot)

    def add(self, t_s: float, sleep_prob: float, deep_prob: float, rem_prob: float):
        self.t.append(t_s)
        self.sleep.append(sleep_prob)
        self.deep.append(deep_prob)
        self.rem.append(rem_prob)
        t0 = self.t[-1]
        x = [v - t0 for v in self.t]
        self.sleep_curve.setData(x, list(self.sleep))
        self.deep_curve.setData(x, list(self.deep))
        self.rem_curve.setData(x, list(self.rem))
