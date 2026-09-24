"""Animated digital twin flow diagram."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QTimer, Qt
from PySide6.QtGui import QBrush, QColor, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QWidget

from src.ui import theme
from src.ui.theme import painter_font


class DigitalTwinWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.phase = 0.0
        self.risk = 0.0
        self.metabolic = 0.0
        self.cycle = 0.0
        self.stress = 0.0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._animate)
        self.timer.start(40)
        self.setMinimumHeight(148)

    def set_state(self, risk: float, metabolic: float, cycle: float, stress: float):
        self.risk = risk
        self.metabolic = metabolic
        self.cycle = cycle
        self.stress = stress
        self.update()

    def _animate(self):
        self.phase = (self.phase + 0.04) % (2 * math.pi)
        self.update()

    def _color(self, v):
        if v < 35:
            return QColor(theme.GREEN)
        if v < 65:
            return QColor(theme.YELLOW)
        return QColor(theme.RED)

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        nodes = [
            ("Physiological\nstate", 0.16 * w, 0.50 * h, self.stress),
            ("Metabolic\nstate", 0.40 * w, 0.50 * h, self.metabolic),
            ("Cycle/clinical\nstate", 0.64 * w, 0.50 * h, self.cycle),
            ("Estimated\nPCOS Risk", 0.88 * w, 0.50 * h, self.risk),
        ]

        # Animated dashed connectors (flow from left to right).
        dash_offset = int(self.phase * 6.0)
        for i in range(len(nodes) - 1):
            x1, y1 = int(nodes[i][1]) + 57, int(nodes[i][2])
            x2, y2 = int(nodes[i + 1][1]) - 57, int(nodes[i + 1][2])
            pen = QPen(QColor("#4fb7f0"), 2.2)
            pen.setDashPattern([7, 6])
            pen.setDashOffset(dash_offset)
            p.setPen(pen)
            p.drawLine(x1, y1, x2, y2)
            # Arrowhead.
            p.setPen(QPen(QColor("#4fb7f0"), 2.2))
            p.setBrush(QColor("#4fb7f0"))
            p.drawPolygon([
                QPointF(x2, y2),
                QPointF(x2 - 10, y2 - 5),
                QPointF(x2 - 10, y2 + 5),
            ])

        for label, x, y, val in nodes:
            color = self._color(val)
            xi, yi = int(x), int(y)
            # Soft glow behind the node.
            glow = QColor(color)
            glow.setAlpha(38)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(glow)
            p.drawRoundedRect(xi - 62, yi - 42, 124, 84, 18, 18)
            # Node body with a vertical gradient.
            grad = QLinearGradient(0, yi - 40, 0, yi + 40)
            grad.setColorAt(0.0, color.lighter(125))
            grad.setColorAt(1.0, color.darker(230))
            p.setPen(QPen(color.lighter(140), 2))
            p.setBrush(QBrush(grad))
            p.drawRoundedRect(xi - 57, yi - 38, 114, 76, 14, 14)
            # Label + value.
            p.setPen(theme.qcolor("value_strong"))
            p.setFont(painter_font(10, bold=True))
            p.drawText(xi - 52, yi - 30, 104, 42, Qt.AlignmentFlag.AlignCenter, label)
            p.setFont(painter_font(13, bold=True))
            p.drawText(xi - 52, yi + 12, 104, 22, Qt.AlignmentFlag.AlignCenter, f"{val:.0f}%")
