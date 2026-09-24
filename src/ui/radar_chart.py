"""Radar chart for risk domains."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QBrush, QColor, QLinearGradient, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

from src.ui import theme
from src.ui.theme import painter_font

# Short human-readable radar axis labels (instead of raw domain keys).
RADAR_LABELS = {
    "cycle": "Cycle",
    "metabolic": "Metabolic",
    "sleep": "Sleep",
    "circadian": "Circadian",
    "stress_autonomic": "Stress",
    "glucose": "Glucose",
    "bp": "BP",
    "low_activity": "Activity",
    "temperature_rhythm": "Temp rhythm",
}


def _radar_label(key: str) -> str:
    if key in RADAR_LABELS:
        return RADAR_LABELS[key]
    return key.replace("_", " ").title()


class RadarChartWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.scores = {}
        self.setMinimumHeight(152)

    def set_scores(self, scores: dict[str, float]):
        self.scores = scores or {}
        self.update()

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        labels = list(self.scores.keys()) or ["cycle", "metabolic", "sleep", "circadian", "stress", "glucose"]
        vals = [self.scores.get(k, 0.0) for k in labels]
        n = len(labels)
        cx, cy = self.width() / 2, self.height() / 2 + 8
        r = min(self.width(), self.height()) * 0.30

        # Grid rings with a soft fill for the inner ones.
        for frac in [0.25, 0.5, 0.75, 1.0]:
            poly = QPolygonF()
            for i in range(n):
                ang = -math.pi / 2 + 2 * math.pi * i / n
                poly.append(QPointF(cx + r * frac * math.cos(ang), cy + r * frac * math.sin(ang)))
            if frac < 1.0:
                fill = theme.qcolor("radar_ring")
                fill.setAlpha(40)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(fill)
                p.drawPolygon(poly)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(theme.qcolor("radar_spoke"), 1))
            p.drawPolygon(poly)

        # Axis spokes.
        p.setPen(QPen(theme.qcolor("radar_spoke"), 1))
        for i, key in enumerate(labels):
            ang = -math.pi / 2 + 2 * math.pi * i / n
            p.drawLine(QPointF(cx, cy), QPointF(cx + r * math.cos(ang), cy + r * math.sin(ang)))

        # Value polygon: cyan → pink gradient fill.
        poly = QPolygonF()
        points = []
        for i, v in enumerate(vals):
            ang = -math.pi / 2 + 2 * math.pi * i / n
            rr = r * max(0.0, min(100.0, v)) / 100.0
            pt = QPointF(cx + rr * math.cos(ang), cy + rr * math.sin(ang))
            poly.append(pt)
            points.append(pt)
        grad = QLinearGradient(cx - r, cy - r, cx + r, cy + r)
        grad.setColorAt(0.0, QColor(61, 167, 240, 150))
        grad.setColorAt(1.0, QColor(244, 114, 182, 130))
        p.setBrush(QBrush(grad))
        p.setPen(QPen(QColor("#5fb6f5"), 2))
        p.drawPolygon(poly)

        # Vertex dots.
        for pt in points:
            p.setBrush(QColor("#ffffff"))
            p.setPen(QPen(QColor("#5fb6f5"), 2))
            p.drawEllipse(int(pt.x() - 3), int(pt.y() - 3), 6, 6)

        # Labels (drawn after the polygon so they stay readable).
        for i, key in enumerate(labels):
            ang = -math.pi / 2 + 2 * math.pi * i / n
            p.setFont(painter_font(8.5))
            p.setPen(theme.qcolor("radar_label"))
            lx = int(cx + (r + 11) * math.cos(ang))
            ly = int(cy + (r + 11) * math.sin(ang))
            p.drawText(lx - 45, ly - 8, 90, 16, Qt.AlignmentFlag.AlignCenter, _radar_label(key))

        # Title.
        p.setPen(theme.qcolor("text"))
        p.setFont(painter_font(11, bold=True))
        p.drawText(0, 5, self.width(), 20, Qt.AlignmentFlag.AlignCenter, "Risk Domain Radar")
