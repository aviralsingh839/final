"""Ovarian complication research module (V5, items O + P).

This module is deliberately RESEARCH-ONLY and NOT CLINICALLY VALIDATED:

  * It does NOT predict cyst rupture. It only reports deviations of a personal
    physiological trajectory from that person's own baseline.
  * The cyst-rupture model is explicitly "NOT YET TRAINED": training is blocked
    until a real longitudinal dataset with clinical outcomes exists. No fake
    rupture events or labels are ever generated.
  * All wording follows the project claim guard: "Physiological trajectory
    abnormality detected" instead of "Cyst will rupture".

It also defines the longitudinal data structure (SQLite DDL + dataclass) needed
for a future clinical study: subject_id, timestamps, sensors, symptoms,
menstrual cycle day, clinical event markers and clinical outcome.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np

CYST_EVENT_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS cyst_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_id TEXT NOT NULL,
    timestamp REAL NOT NULL,
    hr REAL, hrv REAL, ecg_raw TEXT, ppg_raw TEXT,
    bp_sys REAL, bp_dia REAL,
    gsr REAL, temperature REAL, spo2 REAL, activity REAL,
    pain_score INTEGER, symptoms TEXT,
    menstrual_cycle_day INTEGER,
    clinical_event INTEGER, event_timestamp REAL,
    clinical_outcome INTEGER,
    notes TEXT
);
"""

# The cyst model may only be trained after real outcome-labelled data exists.
CYST_MODEL_STATUS = "NOT YET TRAINED"
CYST_MODEL_REASON = ("No real outcome-labelled cyst-event dataset exists. Training is blocked by design. "
                     "Do not generate fake rupture events or labels.")


@dataclass
class CystEventRecord:
    subject_id: str
    timestamp: float
    hr: Optional[float] = None
    hrv: Optional[float] = None
    bp_sys: Optional[float] = None
    bp_dia: Optional[float] = None
    gsr: Optional[float] = None
    temperature: Optional[float] = None
    spo2: Optional[float] = None
    activity: Optional[float] = None
    pain_score: Optional[int] = None
    symptoms: str = ""
    menstrual_cycle_day: Optional[int] = None
    clinical_event: Optional[int] = None
    event_timestamp: Optional[float] = None
    clinical_outcome: Optional[int] = None
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return self.__dict__.copy()


# Metrics used for the multimodal anomaly score, with a per-metric weight.
MONITOR_METRICS = {
    "hr_bpm": 0.25,
    "rmssd_ms": 0.20,
    "gsr_tonic": 0.20,
    "skin_temp_c": 0.15,
    "motion_index": 0.10,
    "spo2_pct": 0.10,
}


@dataclass
class TrajectoryReport:
    deviation_scores: Dict[str, float] = field(default_factory=dict)  # metric -> |z|
    multimodal_score: float = 0.0
    rate_of_change: Dict[str, float] = field(default_factory=dict)  # metric -> slope per hour
    change_points: int = 0
    baseline_n: int = 0
    verdict: str = "No physiological trajectory abnormality detected (research monitor)."
    research_only: str = "RESEARCH ONLY — NOT CLINICALLY VALIDATED. This does not predict cyst rupture."

    def summary(self) -> str:
        lines = [
            f"Multimodal deviation score: {self.multimodal_score:.1f}/100",
            f"Baseline windows: {self.baseline_n}",
        ]
        for metric, z in sorted(self.deviation_scores.items(), key=lambda kv: -kv[1]):
            if z > 0:
                lines.append(f"  {metric}: |z| = {z:.2f}")
        if self.rate_of_change:
            lines.append("Rate of change (per hour): " + ", ".join(
                f"{k} {v:+.2f}" for k, v in list(self.rate_of_change.items())[:4]))
        if self.change_points:
            lines.append(f"Change points detected: {self.change_points}")
        lines.append("Verdict: " + self.verdict)
        lines.append(self.research_only)
        return "\n".join(lines)


class CystResearchMonitor:
    """Personal-baseline physiological trajectory monitor (research only)."""

    def __init__(self, baseline_windows: int = 30):
        self.baseline_windows = baseline_windows

    @staticmethod
    def _series(features, attr: str) -> List[float]:
        out: List[float] = []
        for f in features:
            v = getattr(f, attr, None)
            if v is not None:
                try:
                    v = float(v)
                except (TypeError, ValueError):
                    continue
                if np.isfinite(v):
                    out.append(v)
        return out

    def evaluate(self, features) -> TrajectoryReport:
        """features: chronologically ordered list of FeatureVector (or objects with
        the monitor attributes)."""
        if not features:
            return TrajectoryReport(verdict="No feature history yet.")
        dev: Dict[str, float] = {}
        roc: Dict[str, float] = {}
        n_baseline = 0
        for metric, weight in MONITOR_METRICS.items():
            series = self._series(features, metric)
            if len(series) < 5:
                continue
            baseline = series[: self.baseline_windows]
            n_baseline = max(n_baseline, len(baseline))
            mu, sd = float(np.mean(baseline)), float(np.std(baseline))
            # Zero-variance baseline (e.g. an ideal calibration run) must not make
            # every later deviation infinite or undetectable: floor the scale at a
            # small fraction of the mean, like a robust z-score with a MAD floor.
            sd = max(sd, 0.02 * abs(mu) + 1e-9)
            recent = series[-max(5, len(baseline) // 4):]
            dev[metric] = abs(float(np.mean(recent) - mu)) / sd
            # rate of change: slope of the last min(len, 15) points vs time index.
            tail = series[-15:]
            x = np.arange(len(tail), dtype=float)
            slope = float(np.polyfit(x, tail, 1)[0])
            roc[metric] = slope  # per feature-log interval
        multimodal = float(np.sum([dev[m] * MONITOR_METRICS[m] for m in dev])) * 100.0 / max(
            sum(MONITOR_METRICS.values()), 1e-9)
        multimodal = min(100.0, multimodal)

        # Change points: |running mean - overall mean| > 2 SD sustained over 3 points.
        change_points = 0
        combined = []
        for metric in MONITOR_METRICS:
            combined.extend(self._series(features, metric))
        if len(combined) >= 10:
            arr = np.asarray(combined, dtype=float)
            mu, sd = float(np.mean(arr)), float(np.std(arr))
            if sd > 1e-9:
                run_mean = np.convolve(arr, np.ones(3) / 3, mode="valid")
                change_points = int(np.sum(np.abs(run_mean - mu) > 2.0 * sd))

        verdict = "No physiological trajectory abnormality detected (research monitor)."
        if multimodal >= 55:
            verdict = "PHYSIOLOGICAL TRAJECTORY ABNORMALITY DETECTED — research monitor flag. " \
                      "Not a cyst prediction; clinical assessment required."
        elif multimodal >= 30:
            verdict = "Mild trajectory deviation from personal baseline (research monitor)."

        return TrajectoryReport(
            deviation_scores=dev, multimodal_score=multimodal, rate_of_change=roc,
            change_points=change_points, baseline_n=n_baseline, verdict=verdict,
        )
