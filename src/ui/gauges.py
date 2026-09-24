"""Gauge widgets."""
from __future__ import annotations

import math

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from src.ui import theme
from src.ui.theme import painter_font

# Gauge arc geometry: start at 210° and sweep -240° (i.e. a 300° dial).
START_ANGLE = 210 * 16
SPAN_TOTAL = -240 * 16

# Value bands used both for the zone track and the needle colour.
ZONES = [
    (0.00, 0.25, theme.GREEN),    # low     -> green
    (0.25, 0.50, theme.YELLOW),   # medium  -> amber
    (0.50, 0.75, theme.ORANGE),   # high    -> orange
    (0.75, 1.01, theme.RED),      # very hi -> red
]


class GaugeWidget(QWidget):
    def __init__(self, title: str = "Risk", parent=None):
        super().__init__(parent)
        self.title = title
        self.value = 0.0
        self.ci = (0.0, 0.0)
        self.withheld: str | None = None
        self.setMinimumSize(190, 156)

    def set_value(self, value: float, ci_low: float | None = None, ci_high: float | None = None):
        self.value = max(0.0, min(100.0, float(value)))
        if ci_low is not None and ci_high is not None:
            self.ci = (float(ci_low), float(ci_high))
        self.update()

    def set_withheld(self, reason: str | None):
        """Show 'Insufficient data for reliable estimation' instead of a number."""
        self.withheld = reason
        self.update()

    def _color(self):
        for lo, hi, col in ZONES:
            if self.value < hi:
                return QColor(col)
        return QColor(ZONES[-1][2])

    def _angle_for(self, value: float) -> float:
        """Angle (in 1/16 deg units) for a value in [0, 100]."""
        return START_ANGLE + SPAN_TOTAL * max(0.0, min(100.0, value)) / 100.0

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        title_h = 26
        ci_h = 22
        side = min(w - 24, h - title_h - ci_h - 16)
        rect = QRectF((w - side) / 2.0, title_h + 8, side, side)

        if self.withheld:
            # Dim the track, then show the withhold message instead of a value.
            p.setPen(QPen(theme.qcolor("gauge_track"), 14, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
            p.drawArc(rect, START_ANGLE, SPAN_TOTAL)
            p.setPen(theme.qcolor("accent_text"))
            p.setFont(painter_font(11, bold=True))
            p.drawText(0, 4, w, title_h, Qt.AlignmentFlag.AlignCenter, self.title)
            p.setPen(QColor(theme.YELLOW))
            p.setFont(painter_font(11, bold=True))
            p.drawText(0, title_h + 10, w, h - title_h - ci_h - 10, Qt.AlignmentFlag.AlignCenter,
                       "Insufficient data\nfor reliable estimation")
            p.setPen(theme.qcolor("text_muted"))
            p.setFont(painter_font(8))
            p.drawText(0, h - ci_h, w, ci_h, Qt.AlignmentFlag.AlignCenter, self.withheld[:60])
            return

        # 1) Zone track: subtle coloured bands under the needle.
        for lo, hi, col in ZONES:
            a0 = self._angle_for(lo * 100.0)
            a1 = self._angle_for(hi * 100.0)
            band = QColor(col)
            band.setAlpha(70)
            p.setPen(QPen(band, 14, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
            p.drawArc(rect, int(a0), int(a1 - a0))

        # 2) Tick marks every 10 units.
        p.setPen(QPen(theme.qcolor("tick"), 2))
        for v in range(0, 101, 10):
            ang = self._angle_for(v) / 16.0
            rad = math.radians(ang - 90)
            r1 = rect.width() / 2.0 - 14
            r2 = rect.width() / 2.0 - (18 if v % 20 == 0 else 21)
            cx = rect.center().x()
            cy = rect.center().y()
            p.drawLine(int(cx + r1 * math.cos(rad)), int(cy + r1 * math.sin(rad)),
                       int(cx + r2 * math.cos(rad)), int(cy + r2 * math.sin(rad)))

        # 3) Glow + value arc.
        glow = self._color()
        glow.setAlpha(45)
        p.setPen(QPen(glow, 22, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawArc(rect, START_ANGLE, int(SPAN_TOTAL * self.value / 100.0))
        p.setPen(QPen(self._color(), 12, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawArc(rect, START_ANGLE, int(SPAN_TOTAL * self.value / 100.0))

        # 4) Needle.
        ang = math.radians(self._angle_for(self.value) / 16.0 - 90)
        rn = rect.width() / 2.0 - 26
        cx, cy = rect.center().x(), rect.center().y()
        p.setPen(QPen(theme.qcolor("needle"), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(int(cx), int(cy), int(cx + rn * math.cos(ang)), int(cy + rn * math.sin(ang)))
        p.setBrush(self._color())
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(int(cx - 5), int(cy - 5), 10, 10)

        # 5) Title.
        p.setPen(theme.qcolor("accent_text"))
        p.setFont(painter_font(11, bold=True))
        p.drawText(0, 4, w, title_h, Qt.AlignmentFlag.AlignCenter, self.title)

        # 6) Value.
        p.setPen(theme.qcolor("value_strong"))
        p.setFont(painter_font(25, bold=True))
        p.drawText(0, title_h + 8, w, h - title_h - ci_h - 8, Qt.AlignmentFlag.AlignCenter,
                   f"{self.value:.0f}%")

        # 7) Confidence interval.
        p.setPen(theme.qcolor("text_muted"))
        p.setFont(painter_font(9))
        p.drawText(0, h - ci_h, w, ci_h, Qt.AlignmentFlag.AlignCenter,
                   f"90% CI {self.ci[0]:.0f}–{self.ci[1]:.0f}%")
