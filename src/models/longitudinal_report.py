"""V8.1 clinical reporting: one-page summary + full longitudinal HTML report.

Two artifacts, designed for the low-infrastructure "digital-first, print
fallback" story:

  1. ONE-PAGE CLINICAL SUMMARY  (text + PDF)
       - monitoring period, data quality, major changes, relevant clinical
         information, model estimate, uncertainty, clinical review note.
       - intentionally concise: never thousands of raw measurements.

  2. FULL LONGITUDINAL REPORT   (HTML, served through a QR token)
       - patient overview, baseline, timelines, cycle/symptom/adherence
         histories, ultrasound findings, model output + uncertainty.
       - de-identified: the QR carries only a randomized record token.

All content is generated from the local database via the existing engines.
Nothing here fabricates measurements, estimates, or clinical findings.
"""
from __future__ import annotations

import html
import time

from src.config import APP_VERSION as _APP_VERSION
from pathlib import Path
from typing import Dict, List, Optional

from src.models.change_detector import ChangeReport
from src.models.fingerprint import FingerprintReport
from src.utils.history_store import HistoryStore


def _fmt_dt(ts: Optional[float]) -> str:
    if not ts:
        return "—"
    return time.strftime("%Y-%m-%d", time.localtime(ts))


def _fmt_dt_full(ts: Optional[float]) -> str:
    if not ts:
        return "—"
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))


# ---------------------------------------------------------------- one page
def build_clinical_summary(store: HistoryStore, participant: str = "anonymous",
                           change: Optional[ChangeReport] = None,
                           current_risk: Optional[float] = None,
                           current_confidence: Optional[float] = None,
                           data_quality: Optional[float] = None,
                           review_note: str = "",
                           ultrasound_lines: Optional[List[str]] = None) -> str:
    """One-page clinical summary text (also used as the PDF source)."""
    lines: List[str] = []
    lines.append("CHRONO-PCOS — LONGITUDINAL CLINICAL SUMMARY (1 page)")
    lines.append("=" * 62)
    from src.config import APP_VERSION as _app_version

    lines.append(f"Participant (de-identified): {participant}")
    lines.append(f"Generated: {_fmt_dt_full(time.time())} · CHRONO-PCOS v{_app_version}")
    lines.append("Research pre-screening summary — NOT a diagnosis. "
                 "Clinical decisions remain with the treating clinician.")
    lines.append("")

    # monitoring period + coverage
    sessions = store.session_compare(limit=100)
    real = [s for s in sessions if s.get("source") not in ("demo", "synthetic")]
    if real:
        first = min(s["started_at"] for s in real)
        last = max(s["started_at"] for s in real)
        days = max(1, round((last - first) / 86400.0))
        lines.append(f"Monitoring period: {_fmt_dt(first)} → {_fmt_dt(last)} "
                     f"({days} days, {len(real)} sessions)")
    else:
        lines.append("Monitoring period: no real sessions recorded yet.")
    lines.append(f"Longitudinal coverage: {store.coverage_days(days=180, include_demo=False)} "
                 "distinct days (real data)")
    if data_quality is not None:
        lines.append(f"Data quality: {data_quality:.0%}")
    lines.append("")

    # major changes
    lines.append("MAJOR CHANGES SINCE LAST ASSESSMENT")
    lines.append("-" * 62)
    if change is not None:
        lines.append(f"  {change.summary}")
    else:
        lines.append("  No persistent physiological deviation detected.")
    us_lines = ultrasound_lines or []
    for u in us_lines:
        lines.append("  " + u)
    lines.append("")

    # clinical information
    lines.append("RELEVANT CLINICAL INFORMATION")
    lines.append("-" * 62)
    cyc = store.cycle_history(limit=50)
    if cyc:
        lengths = [c["cycle_length"] for c in cyc if c.get("cycle_length")]
        lines.append(f"  Cycle log entries: {len(cyc)} "
                     f"(recorded lengths: {lengths if lengths else '—'})")
    else:
        lines.append("  Cycle log: none recorded in this window.")
    sym = store.symptoms(limit=50)
    if sym:
        lines.append(f"  Symptom logs: {len(sym)} entries (most recent severity "
                     f"{sym[0].get('severity')})")
    us_hist = store.ultrasound_history(limit=50)
    if us_hist:
        latest = us_hist[0]
        lines.append(f"  Ultrasound (clinically entered): "
                     f"cyst {latest.get('cyst_size_mm', '—')} mm, "
                     f"morphology {latest.get('morphology') or '—'}, "
                     f"{_fmt_dt(latest.get('ts'))}")
    bp = store.bp_readings(limit=10)
    if bp:
        b = bp[0]
        lines.append(f"  BP: {b.get('systolic')}/{b.get('diastolic')} mmHg "
                     f"({_fmt_dt(b.get('ts'))})")
    glu = store.glucose_readings(limit=10)
    if glu:
        g = glu[0]
        lines.append(f"  Glucose: {g.get('value')} {g.get('unit')} "
                     f"({g.get('context') or 'unknown'} context)")
    lines.append("")

    # model estimate
    lines.append("MODEL ESTIMATE")
    lines.append("-" * 62)
    if current_risk is not None and current_confidence is not None:
        lines.append(f"  PCOS-related risk estimate: {current_risk:.0f}%")
        lines.append(f"  Confidence: {current_confidence:.0f}%")
        lines.append("  (Research estimate — requires clinical context; "
                     "NOT a diagnosis.)")
    else:
        lines.append("  NO RELIABLE ESTIMATE — insufficient data/quality.")
    lines.append("")

    if review_note:
        lines.append("CLINICAL REVIEW NOTE")
        lines.append("-" * 62)
        lines.append("  " + review_note)
        lines.append("")

    lines.append("=" * 62)
    lines.append("NOT A DIAGNOSTIC DEVICE · NOT A SUBSTITUTE FOR A DOCTOR OR "
                 "ULTRASOUND · RESEARCH PROTOTYPE — NOT CLINICALLY VALIDATED")
    return "\n".join(lines)


def write_clinical_summary_pdf(path: Path | str, text: str) -> bool:
    """Render the one-page summary to PDF via Qt QPdfWriter (best-effort)."""
    try:
        from PySide6.QtCore import QMarginsF, QRectF, Qt
        from PySide6.QtGui import QFont, QPainter, QPdfWriter
    except Exception:
        return False
    try:
        writer = QPdfWriter(str(path))
        writer.setPageMargins(QMarginsF(12, 12, 12, 12))
        painter = QPainter(writer)
        painter.setFont(QFont("Arial", 9))
        page_w = writer.width()
        y = 20
        line_h = 20
        for line in text.splitlines():
            painter.drawText(
                QRectF(24, y, page_w - 48, line_h),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, line)
            y += line_h
            if y > writer.height() - 30:
                painter.end()
                return False  # one page only — refuses to spill
        painter.end()
        return True
    except Exception:
        return False


# ------------------------------------------------------------------- HTML
def _svg_sparkline(values: List[Optional[float]], width: int = 240,
                   height: int = 40, color: str = "#4a6fa5") -> str:
    """Tiny inline SVG sparkline for the HTML report (no JS needed)."""
    vals = [v for v in values if v is not None]
    if len(vals) < 2:
        return f'<span style="color:#999">insufficient data</span>'
    mn, mx = min(vals), max(vals)
    rng = (mx - mn) or 1.0
    pts = []
    n = len(vals)
    for i, v in enumerate(vals):
        x = 2 + i * (width - 4) / max(1, n - 1)
        y = height - 4 - (v - mn) / rng * (height - 8)
        pts.append(f"{x:.1f},{y:.1f}")
    return (f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
            f'<polyline points="{" ".join(pts)}" fill="none" stroke="{color}" '
            f'stroke-width="2"/></svg>')


def build_full_html_report(store: HistoryStore, participant: str = "anonymous",
                           fingerprint: Optional[FingerprintReport] = None,
                           change: Optional[ChangeReport] = None,
                           current_risk: Optional[float] = None,
                           current_confidence: Optional[float] = None,
                           data_quality: Optional[float] = None,
                           review_note: str = "") -> str:
    """Full de-identified longitudinal report as a single HTML page.

    This is the artifact a QR token resolves to. It contains no names and no
    PII beyond the (de-identified) participant label.
    """
    e = html.escape
    sections: List[str] = []

    # header
    sections.append(
        f"<h1>CHRONO-PCOS — Longitudinal Clinical Report</h1>"
        f"<p class='meta'>Software: CHRONO-PCOS v{_APP_VERSION}</p>"
        f"<p class='sub'>De-identified participant: {e(participant)} · "
        f"Generated {_fmt_dt_full(time.time())}</p>"
        f"<p class='banner'>RESEARCH PRE-SCREENING REPORT — NOT A DIAGNOSIS. "
        f"NOT A SUBSTITUTE FOR A DOCTOR OR ULTRASOUND.</p>")

    # overview cards
    cards = []
    sessions = store.session_compare(limit=100)
    real = [s for s in sessions if s.get("source") not in ("demo", "synthetic")]
    if real:
        first = min(s["started_at"] for s in real)
        last = max(s["started_at"] for s in real)
        days = max(1, round((last - first) / 86400.0))
        cards.append(("<b>Monitoring period</b><br/>"
                      f"{_fmt_dt(first)} → {_fmt_dt(last)}<br/>{days} days"))
    cards.append(f"<b>Coverage</b><br/>{store.coverage_days(days=180, include_demo=False)} "
                 f"days")
    cards.append(f"<b>Data quality</b><br/>"
                 f"{f'{data_quality:.0%}' if data_quality is not None else '—'}")
    if current_risk is not None:
        conf_html = (f"<br/><span class='dim'>conf. {current_confidence:.0f}%</span>"
                     if current_confidence is not None else "")
        cards.append(f"<b>Risk estimate</b><br/>{current_risk:.0f}%{conf_html}")
    sections.append("<div class='cards'>" +
                    "".join(f"<div class='card'>{c}</div>" for c in cards) +
                    "</div>")

    # personal fingerprint
    if fingerprint is not None:
        rows = ["<tr><th>Metric</th><th>Baseline</th><th>Current</th>"
                "<th>Deviation</th><th>Persistence</th><th>Trend</th></tr>"]
        for m, label in (("hr", "HR (bpm)"), ("rmssd", "HRV RMSSD (ms)"),
                         ("skin_temp", "Skin temp (°C)"), ("activity", "Activity")):
            d = (fingerprint.get(m) or {})
            if not d:
                continue
            rows.append(
                f"<tr><td>{label}</td>"
                f"<td>{d.get('baseline_mean', '—'):.1f} ± {d.get('baseline_std', '—'):.1f}</td>"
                f"<td>{d.get('current', '—'):.1f}</td>"
                f"<td>{d.get('deviation_sd', '—'):+.2f} SD</td>"
                f"<td>{d.get('persistence_days', '—'):.1f} d</td>"
                f"<td>{d.get('trend', '—')}</td></tr>")
        sections.append("<h2>Personal physiological fingerprint</h2>"
                        f"<table class='tbl'>{''.join(rows)}</table>")

    # change summary
    if change is not None:
        sections.append(f"<h2>Change analysis</h2>"
                        f"<p>{e(change.summary)}</p>")

    # longitudinal timeline
    df = store.features_as_frame(days=180, include_demo=False)
    if not df.empty:
        import pandas as pd

        df = df.sort_values("ts")
        rows = []
        for col, label in (("hr", "Heart rate"), ("rmssd", "HRV"),
                           ("skin_temp", "Skin temp"), ("activity", "Activity"),
                           ("risk", "Risk estimate")):
            vals = df[col].dropna().tolist()
            rows.append(f"<tr><td>{label}</td>"
                        f"<td>{_svg_sparkline(vals[-180:])}</td>"
                        f"<td>{len(vals)} samples</td></tr>")
        sections.append("<h2>Longitudinal timeline (real data)</h2>"
                        f"<table class='tbl'>{''.join(rows)}</table>")

    # cycle + symptoms
    cyc = store.cycle_history(limit=100)
    if cyc:
        lines = ["<li>" + e(_fmt_dt(c.get("ts"))) + " — cycle day " +
                 e(str(c.get("cycle_day"))) +
                 (", length " + e(str(c.get("cycle_length"))) if c.get("cycle_length") else "") +
                 "</li>" for c in cyc[:30]]
        sections.append("<h2>Cycle timeline</h2><ul>" + "".join(lines) + "</ul>")
    sym = store.symptoms(limit=100)
    if sym:
        lines = ["<li>" + e(_fmt_dt(s.get("ts"))) + " — " + e(str(s.get("symptom"))) +
                 f" (severity {s.get('severity')})</li>" for s in sym[:30]]
        sections.append("<h2>Symptom timeline</h2><ul>" + "".join(lines) + "</ul>")

    # ultrasound
    us_hist = store.ultrasound_history(limit=50)
    if us_hist:
        rows = ["<tr><th>Date</th><th>Cyst (mm)</th><th>Volume (cc)</th>"
                "<th>Morphology</th><th>Source</th></tr>"]
        for u in us_hist[:10]:
            rows.append(
                f"<tr><td>{_fmt_dt(u.get('ts'))}</td>"
                f"<td>{u.get('cyst_size_mm') or '—'}</td>"
                f"<td>{u.get('volume_cc') or '—'}</td>"
                f"<td>{e(str(u.get('morphology') or '—'))}</td>"
                f"<td>{e(str(u.get('source') or '—'))}</td></tr>")
        sections.append("<h2>Ultrasound examinations (clinically entered)</h2>"
                        f"<table class='tbl'>{''.join(rows)}</table>")

    # adherence
    from src.models.care_plan import CarePlanManager
    mgr = CarePlanManager(store)
    meds = mgr.adherence_summary(days=180)
    if meds:
        rows = ["<tr><th>Medication</th><th>Adherence</th><th>Status</th></tr>"]
        for m in meds:
            rows.append(f"<tr><td>{e(m['name'])}</td>"
                        f"<td>{m.get('adherence_pct', 0):.0f}%</td>"
                        f"<td>{'potential gap' if m.get('gap') else 'ok'}</td></tr>")
        sections.append("<h2>Care-plan adherence</h2>"
                        f"<table class='tbl'>{''.join(rows)}</table>")

    # clinical review note
    if review_note:
        sections.append(f"<h2>Clinical review note</h2><p>{e(review_note)}</p>")

    sections.append(
        "<p class='footer'>This report is generated locally from de-identified "
        "records. It is a research pre-screening summary, not a medical "
        "document. The QR code on the printed copy carries only a randomized "
        "record token — no identifying information.</p>")

    return ("<!DOCTYPE html><html><head><meta charset='utf-8'>"
            "<title>CHRONO-PCOS Longitudinal Report</title>"
            "<style>"
            "body{font-family:'Segoe UI',Arial,sans-serif;max-width:860px;margin:24px auto;"
            "padding:0 16px;color:#22303f;line-height:1.5}"
            "h1{font-size:22px;color:#1f3a5f}h2{font-size:16px;color:#1f3a5f;"
            "border-bottom:1px solid #dde5ee;padding-bottom:4px;margin-top:28px}"
            ".sub{color:#5a6b7c;font-size:13px}.banner{background:#fdf3e7;border:1px solid #e6c79a;"
            "color:#7a4f12;padding:8px 12px;border-radius:6px;font-size:13px}"
            ".cards{display:flex;gap:12px;flex-wrap:wrap;margin:16px 0}"
            ".card{background:#f4f7fb;border:1px solid #dce6f2;border-radius:8px;"
            "padding:10px 14px;min-width:130px;font-size:13px}"
            ".dim{color:#7c8ba0;font-size:12px}"
            "table.tbl{border-collapse:collapse;width:100%;font-size:13px;margin:8px 0}"
            ".tbl th,.tbl td{border:1px solid #dde5ee;padding:6px 8px;text-align:left}"
            ".tbl th{background:#eef3fa}.footer{color:#7c8ba0;font-size:12px;margin-top:28px}"
            "</style></head><body>" + "\n".join(sections) + "</body></html>")


def write_full_html_report(path: Path | str, html_text: str) -> None:
    Path(path).write_text(html_text, encoding="utf-8")
