"""24-hour circadian clock widget."""
from __future__ import annotations

import math

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from src.ui import theme
from src.ui.theme import painter_font


class CircadianClockWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.stability = 50.0
        self.sleep_prob = 0.0
        self.setMinimumSize(190, 200)

    def set_values(self, stability: float, sleep_prob: float):
        self.stability = stability
        self.sleep_prob = sleep_prob
        self.update()

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        size = min(self.width(), self.height()) - 36
        cx, cy = self.width() / 2, self.height() / 2 - 4
        r = size / 2

        # Outer track ring.
        p.setPen(QPen(theme.qcolor("gauge_track"), 12))
        p.drawEllipse(int(cx - r), int(cy - r), int(2 * r), int(2 * r))

        # Progress ring.
        color = QColor(theme.GREEN) if self.stability >= 70 else QColor(theme.YELLOW) if self.stability >= 45 else QColor(theme.RED)
        p.setPen(QPen(color, 12, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(int(cx - r), int(cy - r), int(2 * r), int(2 * r), 90 * 16, int(-360 * 16 * self.stability / 100))
        # Brighter leading edge cap.
        end_ang = 90 + 360 * self.stability / 100.0
        p.setPen(QPen(color.lighter(150), 12, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawArc(int(cx - r), int(cy - r), int(2 * r), int(2 * r), int(-end_ang * 16) - 3, 3)
        p.setBrush(Qt.BrushStyle.NoBrush)

        # Hour ticks: 24 small ticks, major ticks every 6 h with labels.
        p.setFont(painter_font(9))
        for hour in range(24):
            ang = math.radians(90 - hour / 24 * 360)
            is_major = hour % 6 == 0
            r1 = r - 20
            r2 = r - (28 if is_major else 24)
            x1, y1 = cx + r1 * math.cos(ang), cy - r1 * math.sin(ang)
            x2, y2 = cx + r2 * math.cos(ang), cy - r2 * math.sin(ang)
            p.setPen(QPen(theme.qcolor("tick") if not is_major else theme.qcolor("accent_text"), 2 if is_major else 1))
            p.drawLine(int(x1), int(y1), int(x2), int(y2))
            if is_major:
                p.setPen(theme.qcolor("text_muted"))
                lx = cx + (r - 42) * math.cos(ang)
                ly = cy - (r - 42) * math.sin(ang)
                p.drawText(int(lx - 12), int(ly - 9), 24, 18, Qt.AlignmentFlag.AlignCenter, str(hour))

        # Center readout.
        p.setPen(theme.qcolor("value_strong"))
        p.setFont(painter_font(19, bold=True))
        p.drawText(int(cx - 60), int(cy - 38), 120, 34, Qt.AlignmentFlag.AlignCenter, f"{self.stability:.0f}%")
        p.setPen(theme.qcolor("accent_text"))
        p.setFont(painter_font(9, bold=True))
        p.drawText(int(cx - 60), int(cy - 8), 120, 18, Qt.AlignmentFlag.AlignCenter, "CSI")
        p.setPen(theme.qcolor("text_muted"))
        p.setFont(painter_font(9))
        p.drawText(int(cx - 60), int(cy + 16), 120, 18, Qt.AlignmentFlag.AlignCenter,
                   f"sleep P {self.sleep_prob * 100:.0f}%")
