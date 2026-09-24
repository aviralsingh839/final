"""Digital-twin timeline (V5, section 28).

A unified chronological view of the wearer's longitudinal record: sessions,
baseline calibrations, anomalies, ECG checkpoints, manual inputs (BP,
glucose, weight, symptoms, cycle, ultrasound) and stored events. Every entry
carries its timestamp, day, kind, severity and source, so clicking through the
timeline lets the user inspect the underlying data.

Nothing here invents events: only entries actually present in the local store
are listed.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import List, Optional

from src.utils.history_store import HistoryStore


@dataclass
class TimelineEvent:
    ts: float
    day: str
    kind: str
    title: str
    detail: str = ""
    severity: str = "info"   # info | ok | warn | alert
    source: str = ""

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def _day(ts: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(ts))


def build_timeline(
    store: HistoryStore,
    days: int = 90,
    include_sessions: bool = True,
    include_calibrations: bool = True,
    include_anomalies: bool = True,
    include_events: bool = True,
    include_manual: bool = True,
    limit: int = 500,
) -> List[TimelineEvent]:
    """Assemble the timeline from the local offline database (oldest first)."""
    since = time.time() - days * 86400.0
    out: List[TimelineEvent] = []

    if include_sessions:
        for s in store.session_summary(limit=200):
            if s.get("started_at", 0) < since:
                continue
            out.append(TimelineEvent(
                ts=s["started_at"], day=_day(s["started_at"]), kind="session",
                title="Monitoring session started",
                detail=f"source={s.get('source', '?')}"
                       + (f", participant={s['participant_id']}" if s.get("participant_id") else ""),
                severity="ok", source="local_db",
            ))

    if include_calibrations:
        for c in store.calibration_history(limit=100):
            if c.get("ts", 0) < since:
                continue
            out.append(TimelineEvent(
                ts=c["ts"], day=_day(c["ts"]), kind="baseline",
                title="Personal baseline calibration",
                detail=f"{c.get('duration_s', 0):.0f} s, quality {c.get('quality', 0):.2f}",
                severity="ok", source="local_db",
            ))

    if include_anomalies:
        for a in store.anomalies(limit=200):
            if a.get("ts", 0) < since:
                continue
            sev = a.get("severity", 0) or 0
            out.append(TimelineEvent(
                ts=a["ts"], day=_day(a["ts"]), kind="anomaly",
                title=f"Anomaly: {a.get('signal', '?')} outside range",
                detail=a.get("description", ""),
                severity="alert" if sev >= 60 else "warn", source="local_db",
            ))

    if include_events:
        for e in store.events(limit=200):
            if e.get("ts", 0) < since:
                continue
            out.append(TimelineEvent(
                ts=e["ts"], day=_day(e["ts"]), kind=e.get("kind", "event"),
                title=e.get("kind", "event").replace("_", " ").title(),
                detail=e.get("detail", ""), severity="info", source="local_db",
            ))

    if include_manual:
        out.extend(_manual_events(store, since))

    out.sort(key=lambda e: e.ts)
    return out[-limit:]


def _manual_events(store: HistoryStore, since: float) -> List[TimelineEvent]:
    out: List[TimelineEvent] = []
    for row in store.bp_readings(limit=200):
        if row.get("ts", 0) < since:
            continue
        out.append(TimelineEvent(
            ts=row["ts"], day=_day(row["ts"]), kind="bp",
            title="Blood pressure entered",
            detail=f"{row.get('systolic')}/{row.get('diastolic')} mmHg"
                   + (f", pulse {row['pulse']}" if row.get("pulse") else ""),
            severity="info", source="manual",
        ))
    for row in store.glucose_readings(limit=200):
        if row.get("ts", 0) < since:
            continue
        out.append(TimelineEvent(
            ts=row["ts"], day=_day(row["ts"]), kind="glucose",
            title="Blood glucose entered",
            detail=f"{row.get('value')} {row.get('unit', 'mg/dL')}"
                   + (f" ({row['context']})" if row.get("context") else ""),
            severity="info", source="manual",
        ))
    for row in store.weight_readings(limit=200):
        if row.get("ts", 0) < since:
            continue
        out.append(TimelineEvent(
            ts=row["ts"], day=_day(row["ts"]), kind="weight",
            title="Weight entered", detail=f"{row.get('weight_kg')} kg",
            severity="info", source="manual",
        ))
    for row in store.symptoms(limit=200):
        if row.get("ts", 0) < since:
            continue
        out.append(TimelineEvent(
            ts=row["ts"], day=_day(row["ts"]), kind="symptom",
            title=f"Symptom: {row.get('symptom', '?')}",
            detail=f"severity {row.get('severity')}/10"
                   + (f" — {row['note']}" if row.get("note") else ""),
            severity="warn" if (row.get("severity") or 0) >= 7 else "info", source="manual",
        ))
    for row in store.cycle_history(limit=200):
        if row.get("ts", 0) < since:
            continue
        out.append(TimelineEvent(
            ts=row["ts"], day=_day(row["ts"]), kind="cycle",
            title="Menstrual cycle entry",
            detail=f"cycle day {row.get('cycle_day', '?')}"
                   + (f", length {row['cycle_length']} d" if row.get("cycle_length") else ""),
            severity="info", source="manual",
        ))
    for row in store.ultrasound_history(limit=200):
        if row.get("ts", 0) < since:
            continue
        out.append(TimelineEvent(
            ts=row["ts"], day=_day(row["ts"]), kind="ultrasound",
            title="Ultrasound observation recorded",
            detail=f"cyst {row.get('cyst_size_mm')} mm"
                   + (f" ({row['morphology']})" if row.get("morphology") else ""),
            severity="info", source="manual",
        ))
    return out


def timeline_text(events: List[TimelineEvent], max_events: int = 120) -> str:
    lines: List[str] = []
    for e in events[-max_events:]:
        lines.append(f"[{e.day}] {e.kind:12s} {e.title}")
        if e.detail:
            lines.append(f"            {e.detail}")
    return "\n".join(lines)
