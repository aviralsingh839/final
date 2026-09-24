"""Personal physiological fingerprint widget (V6.2).

A compact table that shows, per metric: personal baseline, current value,
deviation (SD), persistence, slope, trend and quality — the "what is normal
for THIS person and where are they now" view. Row coloring follows the shared
status colors (green = in range, orange/red = out of band, gray = no data).
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from src.models.fingerprint import FingerprintReport
from src.ui.theme import status_color

COLUMNS = ["Metric", "Personal baseline", "Current", "Deviation", "Persistence", "Slope/day", "Trend", "Quality"]


class FingerprintWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.summary = QLabel("No longitudinal data yet — collect a few hours or enter manual readings.")
        self.summary.setWordWrap(True)
        self.summary.setObjectName("SmallMuted")
        layout.addWidget(self.summary)
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table)

    def set_report(self, report: FingerprintReport):
        self.summary.setText(report.summary_text())
        self.table.setRowCount(len(report.metrics))
        for r, m in enumerate(report.metrics):
            color = status_color(m.status_color())
            cells = [
                m.label,
                m.baseline_text(),
                f"{m.current:.1f} {m.unit}" if m.current is not None else "—",
                m.deviation_text(),
                m.persistence_text(),
                m.slope_text(),
                m.trend,
                f"{m.quality * 100.0:.0f}%" if m.quality > 0 else "—",
            ]
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setForeground(Qt.GlobalColor.white if c != 0 else Qt.GlobalColor.white)
                if c == 0:
                    from PySide6.QtGui import QColor as _QC
                    from src.ui import theme as _theme
                    item.setForeground(_QC(_theme.color("accent_text")))
                if c == 6 and m.trend not in ("stable", "insufficient"):
                    item.setForeground(__import__("PySide6.QtGui", fromlist=["QColor"]).QColor(color))
                self.table.setItem(r, c, item)
        self.table.resizeColumnsToContents()
