"""Personal physiological fingerprint (V6.2).

The fingerprint answers: "what is normal for THIS individual, where are they
right now relative to that, and how long has it been that way?".

For every tracked metric we report:

  * personal baseline median + spread (MAD/std) — from the captured baseline
    when available, else the earliest stable portion of the session
  * current value and deviation in robust SD units
  * persistence (how long the deviation has held)
  * slope per day (trajectory)
  * a trend label: stable / elevated / reduced / recovering / insufficient

The exact calculations reuse the ChangeDetector classification (single vs
persistent vs progressive vs recovery) and the BaselineManager personal
ranges, so the fingerprint is consistent with the rest of the app. A single
abnormal reading never redefines the fingerprint — persistence and quality
gates decide what is shown.

Wording discipline: these are descriptive statistics of the wearer's own
sensor data, not clinical reference ranges, and never a diagnosis.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np

from src.data_models import FeatureVector
from src.models.change_detector import ChangeDetector
from src.models.personalization import BaselineManager

# (key, label, unit, lower-is-better) — lower_is_better controls the arrow
# direction so "HRV down" is shown as a warning, not an improvement.
FINGERPRINT_METRICS: List[tuple] = [
    ("hr_bpm", "Heart rate", "bpm", False),
    ("rmssd_ms", "HRV (RMSSD)", "ms", True),
    ("skin_temp_c", "Skin temperature", "°C", False),
    ("gsr_tonic", "GSR tonic", "a.u.", False),
    ("activity_level", "Activity", "0-100", True),
    ("motion_index", "Motion", "g", False),
]


@dataclass
class MetricFingerprint:
    key: str
    label: str
    unit: str
    baseline_median: Optional[float] = None
    baseline_spread: Optional[float] = None
    current: Optional[float] = None
    deviation_sd: Optional[float] = None       # signed robust |z| vs baseline
    persistence_points: int = 0
    persistence_hours: float = 0.0
    slope_per_day: float = 0.0
    trend: str = "insufficient"                # stable | elevated | reduced | recovering | insufficient
    quality: float = 0.0
    confidence: float = 0.0
    n_points: int = 0

    def baseline_text(self) -> str:
        if self.baseline_median is None:
            return "—"
        if self.baseline_spread is not None and self.baseline_spread > 0:
            return f"{self.baseline_median:.1f} ± {self.baseline_spread:.1f}"
        return f"{self.baseline_median:.1f}"

    def deviation_text(self) -> str:
        if self.deviation_sd is None:
            return "—"
        return f"{self.deviation_sd:+.1f} SD"

    def persistence_text(self) -> str:
        if self.persistence_hours >= 2.0:
            return f"{self.persistence_points} pts · ~{self.persistence_hours:.0f} h"
        if self.persistence_points > 0:
            return f"{self.persistence_points} pts"
        return "0"

    def slope_text(self) -> str:
        if self.slope_per_day == 0.0:
            return "—"
        return f"{self.slope_per_day:+.2f}/day"

    def status_color(self) -> str:
        """green / yellow / orange / gray for the UI."""
        if self.trend == "insufficient":
            return "gray"
        if self.trend == "stable":
            return "green"
        if self.trend == "recovering":
            return "yellow"
        # elevated / reduced — how far out of band?
        if self.deviation_sd is not None and abs(self.deviation_sd) >= 3.0:
            return "red"
        return "orange"


@dataclass
class FingerprintReport:
    metrics: List[MetricFingerprint] = field(default_factory=list)
    baseline_available: bool = False
    n_points: int = 0
    data_quality: float = 0.0

    def by_key(self) -> Dict[str, MetricFingerprint]:
        return {m.key: m for m in self.metrics}

    def summary_text(self) -> str:
        """One-paragraph plain-language summary, evidence-linked, no causes."""
        if not self.metrics:
            return "No longitudinal data yet — collect a few hours (or enter manual readings)."
        moved = [m for m in self.metrics if m.trend in ("elevated", "reduced", "recovering")]
        if not moved:
            return ("All tracked metrics are within this person's normal range "
                    "(" + ", ".join(m.label for m in self.metrics[:4]) + "). No persistent change detected.")
        parts = []
        for m in moved[:4]:
            direction = "above" if (m.deviation_sd or 0) > 0 else "below"
            parts.append(f"{m.label} is {direction} personal baseline by {abs(m.deviation_sd or 0):.1f} SD "
                         f"(~{m.persistence_hours:.0f} h, {m.slope_per_day:+.2f}/day)")
        return ("Measurable change from the personal baseline: " + "; ".join(parts) +
                ". This is a research pattern observation with many possible causes — it is not diagnostic of PCOS.")


class FingerprintEngine:
    """Computes the per-metric personal fingerprint from feature history."""

    def __init__(self, baseline: Optional[BaselineManager] = None):
        self.baseline = baseline
        self.change = ChangeDetector(baseline=baseline)

    def compute(self, features: List[FeatureVector]) -> FingerprintReport:
        report = FingerprintReport(
            baseline_available=bool(self.baseline is not None and self.baseline.has_baseline),
            n_points=len(features),
            data_quality=float(np.mean([
                f.signal_quality for f in features if f.signal_quality is not None
            ] or [0.0])),
        )
        change_report = self.change.evaluate(features)

        for key, label, unit, _lower_better in FINGERPRINT_METRICS:
            values = [f for f in features if getattr(f, key, None) is not None]
            if not values:
                report.metrics.append(MetricFingerprint(key=key, label=label, unit=unit))
                continue
            latest = float(getattr(values[-1], key))
            baseline_median = baseline_spread = None
            if self.baseline is not None and self.baseline.has_baseline:
                s = self.baseline.baseline.stats.get(key)
                if s is not None:
                    baseline_median = float(s.median)
                    baseline_spread = float(max(s.std, 0.02 * abs(s.median) + 1e-9))
            if baseline_median is None:
                arr = np.array([float(getattr(f, key)) for f in values], dtype=float)
                baseline_median = float(np.median(arr))
                mad = float(np.median(np.abs(arr - baseline_median)))
                baseline_spread = float(max(1.4826 * mad, 0.02 * abs(baseline_median) + 1e-9))

            deviation_sd = None
            if baseline_spread and baseline_spread > 1e-9:
                deviation_sd = (latest - baseline_median) / baseline_spread

            mc = change_report.per_metric.get(key)
            persistence_points = mc.persistence_points if mc else 0
            persistence_hours = mc.persistence_hours if mc else 0.0
            slope_per_day = mc.slope_per_day if mc else 0.0
            confidence = mc.confidence if mc else 0.0
            quality = mc.quality_ok if mc else False

            trend = self._trend(mc, deviation_sd)
            report.metrics.append(MetricFingerprint(
                key=key, label=label, unit=unit,
                baseline_median=baseline_median,
                baseline_spread=baseline_spread,
                current=latest,
                deviation_sd=deviation_sd,
                persistence_points=persistence_points,
                persistence_hours=persistence_hours,
                slope_per_day=slope_per_day,
                trend=trend,
                quality=float(quality),
                confidence=float(confidence),
                n_points=len(values),
            ))
        return report

    @staticmethod
    def _trend(mc, deviation_sd) -> str:
        if mc is None or mc.kind in ("insufficient",):
            if deviation_sd is not None and abs(deviation_sd) < 2.0:
                return "stable"
            return "insufficient"
        if mc.kind == "normal":
            return "stable"
        if mc.kind == "recovery":
            return "recovering"
        # single / persistent / progressive
        return "elevated" if (deviation_sd or 0) > 0 else "reduced"
