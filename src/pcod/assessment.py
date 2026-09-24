"""Combined PCOD/PMOS assessment — the two sections in one report.

Section 1: **PCOD detection**       (`criteria.evaluate`)
Section 2: **Complication detection** (`complications.evaluate`)

Plus the shared "latest data" payload: watch summary + evidence headlines.
This module is what both the web app and the Qt shell render, so the two
surfaces can never drift apart.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from src.pcod import criteria, complications, evidence, watch


@dataclass
class Assessment:
    generated_at: float
    generated_at_iso: str
    section1: criteria.DetectionResult
    section2: complications.ComplicationResult
    watch: Dict[str, Any]
    evidence_headlines: list
    evidence_last_verified: str
    condition_label: str
    safety: str = (
        "Research and education companion. Not a diagnostic device. A smartwatch cannot "
        "measure hormones, glucose, lipids or ovarian morphology. No result here starts, "
        "stops or changes treatment — discuss everything with a clinician."
    )

    def as_dict(self) -> dict:
        return {
            "generated_at": self.generated_at,
            "generated_at_iso": self.generated_at_iso,
            "condition_label": self.condition_label,
            "safety": self.safety,
            "watch": self.watch,
            "section1_detection": self.section1.as_dict(),
            "section2_complications": self.section2.as_dict(),
            "evidence_headlines": self.evidence_headlines,
            "evidence_last_verified": self.evidence_last_verified,
        }


def build(patient: dict, clinical: dict, store: watch.WatchStore | None = None) -> Assessment:
    p = criteria.PatientInputs.from_dict(patient or {})
    c = complications.ClinicalInputs.from_dict(clinical or {})

    summary = store.summary() if store else {}
    wc = criteria.WatchContext(
        resting_hr_bpm=summary.get("hr_mean_24h"),
        rmssd_ms=summary.get("rmssd_mean_24h"),
        steps_last_24h=summary.get("steps_24h"),
        sleep_hours_last_night=summary.get("sleep_hours_latest"),
        spo2_pct=summary.get("spo2_mean_24h"),
        wrist_temp_delta_c=None,
        data_sufficiency=summary.get("sufficiency", 0.0),
        days_of_data=summary.get("covered_days", 0),
        device_name=summary.get("device", ""),
    )

    s1 = criteria.evaluate(p, wc)
    s2 = complications.evaluate(c, watch_device=summary.get("device", ""))

    return Assessment(
        generated_at=time.time(),
        generated_at_iso=time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
        section1=s1,
        section2=s2,
        watch=summary,
        evidence_headlines=evidence.HEADLINES,
        evidence_last_verified=evidence.LAST_VERIFIED,
        condition_label=condition_label(),
    )


def condition_label() -> str:
    from src.pcod import CONDITION_LABEL
    return CONDITION_LABEL


# --------------------------------------------------------------------------
def to_text_report(a: Assessment) -> str:
    """Plain-text one-page summary for printing or sharing."""
    L: list[str] = []
    add = L.append
    add("=" * 78)
    add(f"  CHRONO {a.condition_label} — COMPANION SUMMARY")
    add(f"  Generated {a.generated_at_iso}")
    add("  Research and education companion — NOT a diagnosis.")
    add("=" * 78)

    w = a.watch or {}
    if w.get("connected"):
        add("")
        add(f"  SMARTWATCH: {w.get('device')} ({w.get('source')})")
        add(f"  Coverage: {w.get('covered_days')}/{w.get('window_days')} days "
            f"({(w.get('sufficiency') or 0) * 100:.0f}% of window) · {w.get('samples_24h')} readings in 24 h")
        latest = w.get("latest") or {}
        bits = []
        if latest.get("hr_bpm"):
            bits.append(f"HR {latest['hr_bpm']:.0f} bpm")
        if latest.get("rmssd_ms"):
            bits.append(f"HRV {latest['rmssd_ms']:.0f} ms")
        if latest.get("spo2_pct"):
            bits.append(f"SpO2 {latest['spo2_pct']:.0f}% (wellness estimate)")
        if latest.get("battery_pct") is not None:
            bits.append(f"battery {latest['battery_pct']:.0f}%")
        if bits:
            add("  Latest: " + ", ".join(bits))
    else:
        add("")
        add("  SMARTWATCH: not connected.")

    s1 = a.section1
    add("")
    add("-" * 78)
    add("  SECTION 1 — PCOD / PMOS DETECTION")
    add("-" * 78)
    add(f"  Life stage: {s1.life_stage}")
    for c in s1.criteria:
        add(f"    [{c.status:^7}] {c.label}")
        add(f"              {c.detail}")
        for b in c.blockers:
            add(f"              → to resolve: {b}")
    add("")
    add(f"  RESULT: {s1.headline}")
    add(f"  {s1.explanation}")
    if not s1.exclusions_complete:
        add(f"  Still to exclude: {', '.join(s1.exclusions_missing)}")
    add(f"  Ultrasound needed to complete the picture: {'YES' if s1.ultrasound_needed else 'NO'}")
    add(f"  {s1.watch_note}")

    s2 = a.section2
    add("")
    add("-" * 78)
    add("  SECTION 2 — COMPLICATION SCREENING")
    add("-" * 78)
    order = {s: i for i, s in enumerate(complications.STATUS_PRIORITY)}
    for d in sorted(s2.domains, key=lambda d: order.get(d.status, 99)):
        add(f"    [{complications.STATUS_LABELS[d.status].upper()}] {d.label}")
        add(f"              {d.why}")
        for s in d.signals:
            add(f"              · {s}")
        add(f"              ACTION: {d.action}")
        if d.interval_note:
            add(f"              Timing: {d.interval_note}")
    add("")
    add(f"  {s2.watch_note}")
    add(f"  {s2.disclaimer}")

    if a.evidence_headlines:
        add("")
        add("-" * 78)
        add(f"  LATEST EVIDENCE (verified {a.evidence_last_verified})")
        add("-" * 78)
        for h in a.evidence_headlines[:4]:
            add(f"    {h['date']}  [{h['tag']}] {h['headline']}")
            add(f"              {h['detail']}")

    add("")
    add("=" * 78)
    add(f"  {a.safety}")
    add("=" * 78)
    return "\n".join(L)
