"""Real-time physiological anomaly detection.

Each monitored metric is compared against its *personal* normal range when a
baseline exists, otherwise against adaptive rolling statistics of the recent
window. A metric that strays beyond the expected band raises an anomaly with a
severity score; anomalies are rate-limited so they surface as discrete events
rather than a constant alarm stream.

This is an educational outlier detector, not a medical alert system.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Deque, List, Optional, Tuple

import numpy as np

from src.data_models import FeatureVector
from src.models.personalization import BaselineManager

# (feature attribute, human label, z threshold, cooldown seconds)
MONITORED_METRICS: List[Tuple[str, str, float, float]] = [
    ("hr_bpm", "Heart rate", 2.5, 60.0),
    ("rmssd_ms", "HRV (RMSSD)", 2.5, 90.0),
    ("skin_temp_c", "Skin temperature", 3.0, 90.0),
    ("gsr_tonic", "GSR tonic level", 2.5, 60.0),
    ("motion_index", "Motion index", 3.5, 45.0),
]

ROLLING_WINDOW_S = 300.0


@dataclass
class Anomaly:
    signal: str
    value: float
    expected_low: float
    expected_high: float
    severity: float  # 0-100
    description: str


class AnomalyDetector:
    def __init__(self, baseline: BaselineManager | None = None, window_s: float = ROLLING_WINDOW_S):
        self.baseline = baseline
        self.window_s = window_s
        self._history: Deque[FeatureVector] = deque(maxlen=int(window_s * 2))
        self._cooldown_until: dict[str, float] = {}
        self.active: List[Anomaly] = []

    def evaluate(self, fv: FeatureVector, now: float | None = None) -> Tuple[List[Anomaly], float]:
        """Return (anomalies raised this tick, overall anomaly score 0-100)."""
        now = now if now is not None else fv.timestamp_s
        self._history.append(fv)
        found: List[Anomaly] = []

        for attr, label, z_thr, cooldown in MONITORED_METRICS:
            value = getattr(fv, attr)
            if value is None or not np.isfinite(value):
                continue
            low, high = self._expected_range(attr, value, now)
            if low is None or high is None:
                continue
            if low <= value <= high:
                self._cooldown_until[attr] = 0.0
                continue
            if now < self._cooldown_until.get(attr, 0.0):
                continue
            z = abs(value - (low + high) / 2.0) / max((high - low) / 4.0, 1e-6)
            severity = float(np.clip(20.0 + 40.0 * max(z - z_thr, 0.0) / z_thr, 20.0, 100.0))
            description = f"{label} outside personal range ({value:.1f}, expected {low:.1f}-{high:.1f})"
            found.append(Anomaly(
                signal=attr,
                value=float(value),
                expected_low=float(low),
                expected_high=float(high),
                severity=severity,
                description=description,
            ))
            self._cooldown_until[attr] = now + cooldown

        self.active = found
        overall = float(max((a.severity for a in found), default=0.0))
        return found, overall

    def _expected_range(self, attr: str, value: float, now: float) -> Tuple[Optional[float], Optional[float]]:
        # Personal baseline first.
        if self.baseline is not None and self.baseline.has_baseline:
            rng = self.baseline.normal_range(attr)
            if rng is not None:
                return rng

        # Adaptive fallback: rolling mean +/- 3 std.
        values = np.array([
            getattr(f, attr) for f in self._history
            if getattr(f, attr) is not None and np.isfinite(getattr(f, attr))
        ], dtype=float)
        if values.size < 30:
            return None, None
        mean = float(np.mean(values))
        std = float(np.std(values))
        if std <= 1e-6:
            return None, None
        return mean - 3.0 * std, mean + 3.0 * std
