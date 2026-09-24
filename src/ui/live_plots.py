"""PyQtGraph plot wrappers."""
from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel

from src.ui.theme import TEXT_MUTED, style_plot


class TimeSeriesPlot(QWidget):
    def __init__(self, title: str, y_label: str = "", color: str = "#3aa7f0", parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.label = QLabel(title)
        self.label.setStyleSheet(f"font-weight: 600; color: {TEXT_MUTED}; font-size: 10.5pt;")
        self.plot = pg.PlotWidget()
        style_plot(self.plot, y_label=y_label, x_label="seconds ago")
        self.curve = self.plot.plot(pen=pg.mkPen(color, width=2))
        self.curve.setShadowPen(pg.mkPen(color, width=5, alpha=0.25))
        layout.addWidget(self.label)
        layout.addWidget(self.plot)

    def set_data(self, x, y):
        x = np.asarray(x, dtype=float)
        y = np.asarray(y, dtype=float)
        mask = np.isfinite(x) & np.isfinite(y)
        if mask.sum() == 0:
            self.curve.setData([], [])
        else:
            self.curve.setData(x[mask], y[mask])
