"""Weekly physiological report (text + PDF).

The PDF is produced with Qt's built-in QPdfWriter, so no extra dependency is
needed. All values come from the local offline database via MultiDayAnalyzer.
Reports are educational summaries, not medical documents.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import List

from src.models.multi_day import WeeklyProfile


def weekly_report_text(profile: WeeklyProfile, participant: str = "anonymous",
                       recommendation_lines: List[str] | None = None) -> str:
    lines: List[str] = []
    lines.append("CHRONO-PCOS weekly physiological report (educational)")
    lines.append("=" * 60)
    lines.append(f"Participant: {participant}")
    lines.append(f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"Days analysed: {len(profile.days)}")
    lines.append("")
    if not profile.days:
        lines.append("No data in the local database yet. Start a session and collect at least one day.")
        return "\n".join(lines)

    lines.append("Daily summary (means):")
    lines.append("-" * 60)
    header = f"{'Date':<12}{'HR':>6}{'RestHR':>8}{'RMSSD':>7}{'SpO2':>6}{'TempAmp':>8}{'Act':>6}{'Sleep':>7}{'Circ':>6}{'Stress':>7}{'Risk':>6}"
    lines.append(header)
    for d in profile.days:
        row = d.as_dict()
        lines.append(
            f"{row['date']:<12}{str(row['mean_hr']):>6}{str(row['resting_hr']):>8}{str(row['rmssd']):>7}"
            f"{str(row['spo2']):>6}{str(row['temp_amp']):>8}{str(row['activity']):>6}"
            f"{str(row['night_sleep']):>7}{str(row['circadian']):>6}{str(row['stress']):>7}{str(row['risk']):>6}"
        )
    lines.append("")
    lines.append("Trajectory (slope per day):")
    if profile.trajectory:
        for k, v in profile.trajectory.items():
            lines.append(f"  {k}: {v:+.3f}/day")
    else:
        lines.append("  Not enough days yet (need >= 3).")
    lines.append("")

    if recommendation_lines:
        lines.append("Recommendations:")
        for r in recommendation_lines:
            lines.append(f"  - {r}")
        lines.append("")

    lines.append("DISCLAIMER: educational research demonstration only. Not a diagnosis.")
    return "\n".join(lines)


def write_pdf_report(path: Path | str, profile: WeeklyProfile, participant: str = "anonymous",
                     recommendation_lines: List[str] | None = None) -> bool:
    """Write the weekly report as a PDF using Qt QPdfWriter. Best-effort."""
    try:
        from PySide6.QtCore import QMarginsF, QRectF, Qt
        from PySide6.QtGui import QFont, QPainter, QPdfWriter
    except Exception:
        return False

    text = weekly_report_text(profile, participant, recommendation_lines)
    try:
        writer = QPdfWriter(str(path))
        writer.setPageMargins(QMarginsF(15, 15, 15, 15))
        painter = QPainter(writer)
        painter.setFont(QFont("Arial", 9))
        page_w = writer.width()
        y = 30
        line_h = 22
        for line in text.splitlines():
            if y > writer.height() - 40:
                painter.drawText(QRectF(0, 0, 0, 0), Qt.AlignmentFlag.AlignLeft, "")  # no-op page guard
                # Simple approach: continue on the same page (reports are short).
            painter.drawText(QRectF(30, y, page_w - 60, line_h), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, line)
            y += line_h
        painter.end()
        return True
    except Exception:
        return False
