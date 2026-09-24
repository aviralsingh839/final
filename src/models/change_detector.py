"""Longitudinal change detector (V5, sections 9 + 20).

Distinguishes the *kind* of change in a personal physiological trajectory:

  * single_deviation     - one abnormal reading (no alert unless quality is good)
  * persistent_deviation - a sustained offset that has held for several points
  * progressive_deviation- a trend that is still moving away from baseline
  * recovery             - a feature that deviated and is now returning to baseline
  * normal               - within the personal normal band
  * insufficient_quality - there is apparent deviation but the data quality is
                           too low to trust it (never alert from one noisy reading)

Every per-metric result carries: |z| from the personal baseline, absolute and
percentage change, slope per day, persistence (points + hours), confidence and
a quality gate. The overall report never invents causes - it only lists the
metrics that actually moved and how long they have been moving.

Wording follows the project claim guard: "research pattern detection",
never a diagnosis.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np

from src.data_models import FeatureVector
from src.models.personalization import BaselineManager

# Default metrics tracked by the change detector.
DEFAULT_METRICS = [
    "hr_bpm", "rmssd_ms", "skin_temp_c", "gsr_tonic", "activity_level", "motion_index",
]

MIN_POINTS = 5
Z_NORMAL = 2.0      # |z| below this -> normal
Z_ALERT = 3.0       # |z| above this -> a real deviation
PERSIST_POINTS = 3  # consecutive out-of-band points -> persistent
PROGRESSIVE_SLOPE = 1.0  # scale-units per day moving away -> progressive


@dataclass
class MetricChange:
    metric: str
    kind: str                    # normal | single | persistent | progressive | recovery | insufficient
    latest_value: float
    baseline_median: float
    z_latest: float              # robust |z| vs the personal baseline
    abs_change: float
    pct_change: float            # signed % vs baseline median
    slope_per_day: float         # fitted slope in natural units per day
    persistence_points: int
    persistence_hours: float
    confidence: float            # 0..1
    quality_ok: bool
    n_points: int = 0

    def phrase(self) -> str:
        """One human-readable sentence for the Explainability panel."""
        if self.kind == "normal":
            return f"{self.metric} within personal range (|z|={self.z_latest:.1f})."
        if self.kind == "insufficient":
            return (f"{self.metric} deviates but signal quality is too low "
                    f"to assess reliably - no alert.")
        base = (f"{self.metric}: {self.abs_change:+.1f} "
                f"({self.pct_change:+.0f}% vs baseline, |z|={self.z_latest:.1f})")
        if self.kind == "single":
            return base + ", single-point deviation."
        if self.kind == "persistent":
            return (base + f", persistent {self.persistence_points} points "
                    f"(~{self.persistence_hours:.1f} h).")
        if self.kind == "progressive":
            return (base + f", progressive ({self.slope_per_day:+.2f}/day, "
                    f"{self.persistence_points} points and rising).")
        if self.kind == "recovery":
            return base + ", returning toward baseline."
        return base


@dataclass
class ChangeReport:
    per_metric: Dict[str, MetricChange] = field(default_factory=dict)
    overall_kind: str = "normal"          # normal | deviation | insufficient_quality
    summary: str = "No persistent change detected."
    contributors: List[str] = field(default_factory=list)
    data_quality: float = 0.0             # mean signal quality over the window
    n_windows: int = 0

    def as_dict(self) -> dict:
        return {
            "overall_kind": self.overall_kind,
            "summary": self.summary,
            "contributors": self.contributors,
            "data_quality": round(self.data_quality, 3),
            "n_windows": self.n_windows,
            "per_metric": {k: v.__dict__ for k, v in self.per_metric.items()},
        }


def _robust_scale(values: np.ndarray) -> float:
    """Median absolute deviation scaled to a sigma, with a small floor."""
    med = float(np.median(values))
    mad = float(np.median(np.abs(values - med)))
    scale = 1.4826 * mad
    return max(scale, 0.02 * abs(med) + 1e-9)


class ChangeDetector:
    """Classifies how each metric is moving relative to the personal baseline."""

    def __init__(
        self,
        baseline: Optional[BaselineManager] = None,
        metrics: Optional[List[str]] = None,
        z_normal: float = Z_NORMAL,
        z_alert: float = Z_ALERT,
        persist_points: int = PERSIST_POINTS,
        progressive_slope: float = PROGRESSIVE_SLOPE,
        min_points: int = MIN_POINTS,
        slope_window: int = 12,
        quality_threshold: float = 0.5,
    ):
        self.baseline = baseline
        self.metrics = metrics or DEFAULT_METRICS
        self.z_normal = z_normal
        self.z_alert = z_alert
        self.persist_points = persist_points
        self.progressive_slope = progressive_slope
        self.min_points = min_points
        self.slope_window = slope_window
        self.quality_threshold = quality_threshold

    # ------------------------------------------------------------- series
    def _series(self, features: List[FeatureVector], metric: str):
        ts, vals, q = [], [], []
        for f in features:
            v = getattr(f, metric, None)
            if v is None:
                continue
            try:
                v = float(v)
            except (TypeError, ValueError):
                continue
            if not np.isfinite(v):
                continue
            ts.append(float(f.timestamp_s))
            vals.append(v)
            q.append(float(f.signal_quality) if f.signal_quality is not None else 0.0)
        return ts, vals, q

    def _baseline_ref(self, metric: str, values: np.ndarray):
        """(median, scale) from the personal baseline when available, else the
        earliest stable portion of this series (never the whole window, so a
        drifted series cannot hide its own drift)."""
        if self.baseline is not None and self.baseline.has_baseline:
            s = self.baseline.baseline.stats.get(metric)
            if s is not None and s.std > 1e-9:
                return s.median, max(s.std, 1e-9)
        # Use the earliest stable quarter as the reference so a later step or
        # drift cannot contaminate the baseline it is measured against.
        n = max(self.min_points, int(np.ceil(len(values) * 0.25)))
        early = values[:n]
        if early.size < 3:
            return None, None
        return float(np.median(early)), _robust_scale(early)

    # --------------------------------------------------------- evaluation
    def evaluate(self, features: List[FeatureVector]) -> ChangeReport:
        if not features:
            return ChangeReport(summary="No feature history yet.")
        report = ChangeReport(
            n_windows=len(features),
            data_quality=float(np.mean([
                f.signal_quality for f in features if f.signal_quality is not None
            ] or [0.0])),
        )

        for metric in self.metrics:
            ts, vals, q = self._series(features, metric)
            if len(vals) < self.min_points:
                continue
            arr = np.asarray(vals, dtype=float)
            med, scale = self._baseline_ref(metric, arr)
            if med is None or scale is None:
                continue
            z = np.abs(arr - med) / scale
            latest = float(arr[-1])
            z_latest = float(z[-1])
            mean_q = float(np.mean(q))
            quality_ok = mean_q >= self.quality_threshold
            n = len(arr)

            # Persistence: trailing consecutive out-of-band points.
            persistence = 0
            for zi in z[::-1]:
                if zi > self.z_normal:
                    persistence += 1
                else:
                    break

            # Quality of the deviant tail: an alert is only trustworthy when the
            # recent (out-of-band) data itself is good quality.
            tail_q_n = max(persistence, 1)
            tail_quality = float(np.mean(q[-tail_q_n:])) if q else 0.0

            # Slope per day over the recent tail (real timestamps -> units/day).
            tail_n = min(self.slope_window, n)
            tail_ts = np.asarray(ts[-tail_n:], dtype=float)
            tail = arr[-tail_n:]
            slope_per_day = 0.0
            if len(tail) >= 3 and np.std(tail) > 1e-9 and np.std(tail_ts) > 1e-9:
                x_hours = (tail_ts - tail_ts[0]) / 3600.0
                slope_per_day = float(np.polyfit(x_hours, tail, 1)[0]) * 24.0

            # Recent-excursion check: maximum |z| over the last half of the
            # series (used to recognise recovery once the deviation has ended).
            recent_n = max(3, n // 2)
            max_z_recent = float(z[-recent_n:].max())
            quality_ok = tail_quality >= self.quality_threshold

            kind = self._classify(z_latest, persistence, slope_per_day, scale,
                                  z, latest, med, quality_ok, max_z_recent)

            # Confidence: more points + longer persistence + good quality -> higher.
            confidence = 0.30 + 0.12 * min(persistence, 6) + 0.15 * min(n / 60.0, 1.0)
            confidence = min(0.95, confidence * (0.8 + 0.2 * mean_q))

            abs_change = latest - med
            pct_change = abs_change / abs(med) * 100.0 if abs(med) > 1e-9 else 0.0
            pers_hours = 0.0
            if persistence >= 2 and len(ts) >= 2:
                # Clamp so persistence == n (all points out of band) can never
                # index past the start of the series.
                idx = min(persistence, len(ts) - 1)
                pers_hours = (ts[-1] - ts[-(idx + 1)]) / 3600.0

            report.per_metric[metric] = MetricChange(
                metric=metric,
                kind=kind,
                latest_value=latest,
                baseline_median=float(med),
                z_latest=z_latest,
                abs_change=float(abs_change),
                pct_change=float(pct_change),
                slope_per_day=slope_per_day,
                persistence_points=persistence,
                persistence_hours=pers_hours,
                confidence=float(confidence),
                quality_ok=quality_ok,
                n_points=n,
            )

        self._finalize(report)
        return report

    def _classify(self, z_latest: float, persistence: int, slope_per_day: float,
                  scale: float, z: np.ndarray, latest: float, med: float,
                  quality_ok: bool, max_z_recent: float) -> str:
        if z_latest <= self.z_normal:
            # Was there a recent excursion that has now ended?
            if max_z_recent > self.z_alert:
                return "recovery"
            return "normal"
        # Deviation of some kind.
        if not quality_ok:
            return "insufficient"
        # Direction of the trend vs direction of the deviation.
        direction = 1.0 if latest > med else -1.0
        moving_away = slope_per_day * direction > 0
        if persistence >= self.persist_points and moving_away and abs(slope_per_day) >= self.progressive_slope:
            return "progressive"
        if persistence >= self.persist_points:
            return "persistent"
        return "single"

    def _finalize(self, report: ChangeReport) -> None:
        alerts = [m for m in report.per_metric.values()
                  if m.kind in ("single", "persistent", "progressive", "recovery")]
        insufficient = [m for m in report.per_metric.values() if m.kind == "insufficient"]
        if alerts:
            report.overall_kind = "deviation"
            report.contributors = [
                f"{m.metric} ({m.kind}, {m.pct_change:+.0f}%)" for m in alerts
            ]
            report.summary = (
                "Change detected: " + "; ".join(
                    f"{m.metric} {m.pct_change:+.0f}% from baseline, {m.kind} "
                    f"({m.persistence_points} points)"
                    for m in alerts[:4]
                )
                + ". Research pattern detection - not a diagnosis."
            )
        elif insufficient:
            report.overall_kind = "insufficient_quality"
            report.summary = (
                "Apparent deviation but signal quality is too low to trust it - "
                "no alert issued. Improve sensor contact and retry."
            )
        else:
            report.overall_kind = "normal"
            report.summary = "No persistent change detected."
