"""Personal baseline calibration and personalized normal ranges.

The dashboard starts from conservative population defaults. Once the user (or
the physical BASELINE button) starts a calibration session, a 5-minute window
of good-quality data is distilled into *personal* normal ranges for the key
physiological metrics. Everything downstream (risk confidence, anomaly
detection, sleep priors) then compares the live signal against these personal
ranges instead of the fixed defaults.

Educational note: these ranges are descriptive statistics of the wearer's own
sensor data; they are not clinical reference ranges.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, Optional, Tuple

import numpy as np

from src.config import DATA_DIR
from src.data_models import FeatureVector

# Metrics tracked for personalization and their human-readable labels.
BASELINE_METRICS = {
    "hr_bpm": "Heart rate (bpm)",
    "rmssd_ms": "HRV RMSSD (ms)",
    "skin_temp_c": "Skin temperature (°C)",
    "gsr_tonic": "GSR tonic (raw)",
    "activity_level": "Activity level (0-100)",
}


@dataclass
class MetricStats:
    median: float
    p05: float
    p95: float
    mean: float
    std: float
    count: int
    mad: float = 0.0

    def to_dict(self) -> dict:
        return {
            "median": round(float(self.median), 4),
            "p05": round(float(self.p05), 4),
            "p95": round(float(self.p95), 4),
            "mean": round(float(self.mean), 4),
            "std": round(float(self.std), 4),
            "count": int(self.count),
            "mad": round(float(self.mad), 4),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "MetricStats":
        return cls(
            median=float(d["median"]),
            p05=float(d["p05"]),
            p95=float(d["p95"]),
            mean=float(d["mean"]),
            std=float(d["std"]),
            count=int(d.get("count", 0)),
            mad=float(d.get("mad", 0.0)),
        )


@dataclass
class PersonalBaseline:
    captured_at: float = 0.0
    duration_s: float = 0.0
    samples: int = 0
    quality: float = 0.0
    stats: Dict[str, MetricStats] = field(default_factory=dict)

    @property
    def has_data(self) -> bool:
        return bool(self.stats) and self.captured_at > 0

    def normal_range(self, metric: str) -> Optional[Tuple[float, float]]:
        s = self.stats.get(metric)
        if s is None:
            return None
        return s.p05, s.p95

    def zscore(self, metric: str, value: Optional[float]) -> Optional[float]:
        if value is None or np.isnan(value):
            return None
        s = self.stats.get(metric)
        if s is None or s.std <= 1e-9:
            return None
        return float((value - s.median) / s.std)

    def robust_zscore(self, metric: str, value: Optional[float]) -> Optional[float]:
        """Robust z-score using the median + MAD scale (resistant to outliers)."""
        if value is None or np.isnan(value):
            return None
        s = self.stats.get(metric)
        if s is None:
            return None
        scale = 1.4826 * s.mad if s.mad > 1e-9 else s.std
        if scale <= 1e-9:
            return None
        return float((value - s.median) / scale)


class BaselineManager:
    """Owns the current personal baseline and its calibration history.

    The baseline is established by an explicit calibration capture, then kept
    current by `update_observation()`: a rolling median/MAD window is blended
    into the stored stats with a small EWMA weight, and outliers (|z| > 3.5)
    are rejected so a single abnormal measurement can never redefine the
    baseline.
    """

    def __init__(self, path: Path | str | None = None, history_path: Path | str | None = None):
        self.path = Path(path) if path else DATA_DIR / "baselines" / "personal_baseline.json"
        self.history_path = Path(history_path) if history_path else DATA_DIR / "baselines" / "calibration_history.json"
        self.baseline = PersonalBaseline()
        self._history: list[dict] = []
        self._last_capture_wall = 0.0
        self._rolling: Dict[str, list] = {}
        self._updates_since_save = 0
        self.load()

    # ------------------------------------------------------------- capture
    def capture_from_features(self, features: Iterable[FeatureVector], min_samples: int = 60) -> PersonalBaseline:
        """Distill a calibration window into personalized normal ranges."""
        rows = [f for f in features if f is not None]
        if len(rows) < min_samples:
            raise ValueError(f"Not enough samples for calibration ({len(rows)} < {min_samples}). "
                             "Keep the sensors on and collect at least 5 minutes of calm data.")

        ts = [f.timestamp_s for f in rows]
        stats: Dict[str, MetricStats] = {}
        qualities = [f.signal_quality for f in rows if f.signal_quality is not None]
        for metric in BASELINE_METRICS:
            values = np.array([getattr(f, metric) for f in rows if getattr(f, metric) is not None], dtype=float)
            if values.size < min_samples * 0.4:
                continue
            values = values[np.isfinite(values)]
            if values.size < 10:
                continue
            stats[metric] = MetricStats(
                median=float(np.percentile(values, 50)),
                p05=float(np.percentile(values, 5)),
                p95=float(np.percentile(values, 95)),
                mean=float(np.mean(values)),
                std=float(np.std(values)),
                count=int(values.size),
            )

        if not stats:
            raise ValueError("No usable signals during calibration window.")

        baseline = PersonalBaseline(
            captured_at=ts[-1] if ts else time.time(),
            duration_s=max(ts) - min(ts) if len(ts) > 1 else 0.0,
            samples=len(rows),
            quality=float(np.mean(qualities)) if qualities else 0.0,
            stats=stats,
        )
        self.baseline = baseline
        self._history.append({
            "captured_at": baseline.captured_at,
            "iso": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(baseline.captured_at)),
            "duration_s": round(baseline.duration_s, 1),
            "samples": baseline.samples,
            "quality": round(baseline.quality, 3),
            "metrics": [m for m in stats],
        })
        if len(self._history) > 200:
            self._history = self._history[-200:]
        self.save()
        self._last_capture_wall = time.time()
        return baseline

    # -------------------------------------------------------------- access
    @property
    def has_baseline(self) -> bool:
        return self.baseline.has_data

    def normal_range(self, metric: str) -> Optional[Tuple[float, float]]:
        return self.baseline.normal_range(metric)

    def zscore(self, metric: str, value: Optional[float]) -> Optional[float]:
        return self.baseline.zscore(metric, value)

    def robust_zscore(self, metric: str, value: Optional[float]) -> Optional[float]:
        return self.baseline.robust_zscore(metric, value)

    def history(self) -> list[dict]:
        return list(self._history)

    # ---------------------------------------------------- gradual updates
    def update_observation(self, fv: "FeatureVector", alpha: float = 0.05,
                           window: int = 600) -> Optional[PersonalBaseline]:
        """Blend one observation into the personal baseline (rolling median/MAD,
        EWMA). Returns the updated baseline once enough data exists, else None.

        Outlier guard: if the rolling median is more than 3.5 scale units from
        the current baseline, the observation is treated as an abnormal event
        and does NOT move the baseline.
        """
        if fv is None:
            return None
        ts = float(getattr(fv, "timestamp_s", time.time()))
        touched = False
        for metric in BASELINE_METRICS:
            v = getattr(fv, metric)
            if v is None:
                continue
            try:
                v = float(v)
            except (TypeError, ValueError):
                continue
            if not np.isfinite(v):
                continue
            dq = self._rolling.setdefault(metric, [])
            dq.append(v)
            if len(dq) > window:
                dq = dq[-window:]
                self._rolling[metric] = dq
            if len(dq) < 30:
                continue
            med = float(np.median(dq))
            mad = float(np.median(np.abs(np.asarray(dq) - med)))
            scale = max(1.4826 * mad, 0.02 * abs(med) + 1e-9)

            cur = self.baseline.stats.get(metric)
            if cur is not None and cur.median != 0.0:
                # Do not let an abnormal window drag the baseline.
                z = (med - cur.median) / max(scale, cur.std if cur.std > 1e-9 else scale)
                if abs(z) > 3.5:
                    continue
                new_median = (1.0 - alpha) * cur.median + alpha * med
                new_std = (1.0 - alpha) * cur.std + alpha * scale
                new_mad = (1.0 - alpha) * cur.mad + alpha * (scale / 1.4826)
                new_count = cur.count + 1
            else:
                new_median, new_std, new_mad, new_count = med, scale, scale / 1.4826, len(dq)
            self.baseline.stats[metric] = MetricStats(
                median=float(new_median),
                p05=float(np.percentile(dq, 5)),
                p95=float(np.percentile(dq, 95)),
                mean=float(np.mean(dq)),
                std=float(new_std),
                count=int(new_count),
                mad=float(new_mad),
            )
            touched = True

        if not touched:
            return None
        self.baseline.captured_at = ts
        self.baseline.samples += 1
        self._updates_since_save += 1
        if self._updates_since_save >= 10:
            self.save()
            self._updates_since_save = 0
        return self.baseline

    # ------------------------------------------------------------ persist
    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "captured_at": self.baseline.captured_at,
            "duration_s": self.baseline.duration_s,
            "samples": self.baseline.samples,
            "quality": self.baseline.quality,
            "stats": {k: v.to_dict() for k, v in self.baseline.stats.items()},
        }
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self.history_path.write_text(json.dumps(self._history, indent=2), encoding="utf-8")

    def load(self) -> None:
        try:
            if self.path.exists():
                d = json.loads(self.path.read_text(encoding="utf-8"))
                stats = {k: MetricStats.from_dict(v) for k, v in d.get("stats", {}).items()}
                self.baseline = PersonalBaseline(
                    captured_at=float(d.get("captured_at", 0.0)),
                    duration_s=float(d.get("duration_s", 0.0)),
                    samples=int(d.get("samples", 0)),
                    quality=float(d.get("quality", 0.0)),
                    stats=stats,
                )
        except Exception:
            self.baseline = PersonalBaseline()
        try:
            if self.history_path.exists():
                self._history = json.loads(self.history_path.read_text(encoding="utf-8"))
                if not isinstance(self._history, list):
                    self._history = []
        except Exception:
            self._history = []
