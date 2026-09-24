"""Multi-day trend analysis: 7-day physiological profile and long-term trajectory.

Consumes the local offline database (features table) and distills it into a
daily summary plus a linear trajectory (slope per day) for the key metrics.
This gives the "7-day physiological profile" and "long-term personal
trajectory" views of the feature list.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from src.utils.history_store import HistoryStore


@dataclass
class DaySummary:
    date: str  # YYYY-MM-DD
    sample_count: int = 0
    mean_hr: Optional[float] = None
    resting_hr: Optional[float] = None          # 5th percentile daytime HR
    mean_rmssd: Optional[float] = None
    mean_spo2: Optional[float] = None
    temp_min_c: Optional[float] = None
    temp_max_c: Optional[float] = None
    temp_amplitude_c: Optional[float] = None
    activity_mean: Optional[float] = None
    night_sleep_prob: Optional[float] = None    # mean sleep prob 00:00-06:00
    circadian_stability: Optional[float] = None
    mean_stress: Optional[float] = None
    mean_risk: Optional[float] = None
    anomaly_count: int = 0
    health_score: Optional[float] = None        # daily composite health score
    light_exposure_score: Optional[float] = None
    label: Optional[int] = None                 # synthetic ground truth (research only)

    def as_dict(self) -> dict:
        return {
            "date": self.date,
            "samples": self.sample_count,
            "mean_hr": _f(self.mean_hr),
            "resting_hr": _f(self.resting_hr),
            "rmssd": _f(self.mean_rmssd),
            "spo2": _f(self.mean_spo2),
            "temp_min": _f(self.temp_min_c),
            "temp_max": _f(self.temp_max_c),
            "temp_amp": _f(self.temp_amplitude_c),
            "activity": _f(self.activity_mean),
            "night_sleep": _f(self.night_sleep_prob),
            "circadian": _f(self.circadian_stability),
            "stress": _f(self.mean_stress),
            "risk": _f(self.mean_risk),
            "anomalies": self.anomaly_count,
            "health": _f(self.health_score),
            "light": _f(self.light_exposure_score),
            "label": self.label,
        }


@dataclass
class WeeklyProfile:
    days: List[DaySummary] = field(default_factory=list)
    trajectory: Dict[str, float] = field(default_factory=dict)  # slope per day

    def metric_series(self, key: str) -> List[Optional[float]]:
        return [d.as_dict().get(key) for d in self.days]


def _f(v: Optional[float]) -> Optional[float]:
    return round(float(v), 2) if v is not None else None


def _int_mode(s: pd.Series) -> Optional[int]:
    s = pd.to_numeric(s, errors="coerce").dropna()
    if s.empty:
        return None
    counts = s.round().astype(int).value_counts()
    return int(counts.index[0])


def _parse_extra_json(df: pd.DataFrame) -> pd.DataFrame:
    """Promote stored extra_json fields (health score, light exposure, labels) to columns."""
    if "extra_json" not in df.columns:
        return df
    import json

    rows = []
    for v in df["extra_json"]:
        try:
            rows.append(json.loads(v) if isinstance(v, str) and v else {})
        except Exception:
            rows.append({})
    if not rows:
        return df
    extra = pd.DataFrame(rows)
    for col in ["health_score", "light_exposure", "label",
                "autonomic_imbalance", "chronic_stress",
                "insulin_resistance_probability", "metabolic_syndrome_proxy",
                "circadian_disruption", "temperature_rhythm_disruption",
                "low_activity_risk"]:
        if col in extra.columns:
            df[col] = extra[col].values
    return df


class MultiDayAnalyzer:
    def __init__(self, store: HistoryStore):
        self.store = store

    def build_profile(self, days: int = 7, trajectory_days: int = 30,
                      include_demo: bool = True) -> WeeklyProfile:
        df = self.store.features_as_frame(days=max(days, trajectory_days), include_demo=include_demo)
        profile = WeeklyProfile()
        if df.empty:
            return profile

        df = _parse_extra_json(df)
        df = df.sort_values("ts")
        df["dt"] = pd.to_datetime(df["ts"], unit="s")
        df["date"] = df["dt"].dt.strftime("%Y-%m-%d")
        df["hour"] = df["dt"].dt.hour + df["dt"].dt.minute / 60.0

        daily: List[DaySummary] = []
        for date, g in df.groupby("date"):
            day = DaySummary(date=str(date), sample_count=len(g))
            day.mean_hr = _mean(g["hr"])
            daytime = g[(g["hour"] >= 8) & (g["hour"] <= 22)]
            if len(daytime) >= 10:
                day.resting_hr = _pct(daytime["hr"], 5)
            day.mean_rmssd = _mean(g["rmssd"])
            day.mean_spo2 = _mean(g["spo2"])
            t = g["skin_temp"].dropna()
            if len(t) >= 5:
                day.temp_min_c = float(t.min())
                day.temp_max_c = float(t.max())
                day.temp_amplitude_c = float(t.max() - t.min())
            day.activity_mean = _mean(g["activity"])
            night = g[(g["hour"] >= 0) & (g["hour"] <= 6)]
            if len(night) >= 5:
                day.night_sleep_prob = _mean(night["sleep_prob"])
            day.circadian_stability = _mean(g["circadian"])
            day.mean_stress = _mean(g["stress"])
            day.mean_risk = _mean(g["risk"])
            day.health_score = _mean(g.get("health_score", pd.Series(dtype=float)))
            day.light_exposure_score = _mean(g.get("light_exposure", pd.Series(dtype=float)))
            day.label = _int_mode(g.get("label", pd.Series(dtype=float)))
            daily.append(day)

        daily.sort(key=lambda d: d.date)
        profile.days = daily[-days:] if days > 0 else daily

        # Trajectory over the (longer) requested window.
        profile.trajectory = {}
        for key in ["mean_hr", "resting_hr", "rmssd", "temp_amp", "night_sleep", "circadian", "stress", "risk", "health"]:
            series = [d.as_dict().get(key) for d in daily]
            if len(series) >= 3:
                x = np.arange(len(series), dtype=float)
                y = np.array([v if v is not None else np.nan for v in series], dtype=float)
                mask = np.isfinite(y)
                if mask.sum() >= 3 and np.std(y[mask]) > 1e-9:
                    slope = float(np.polyfit(x[mask], y[mask], 1)[0])
                    profile.trajectory[key] = round(slope, 3)
        return profile


def _mean(s: pd.Series) -> Optional[float]:
    s = pd.to_numeric(s, errors="coerce").dropna()
    if s.empty:
        return None
    return float(s.mean())


def _pct(s: pd.Series, q: float) -> Optional[float]:
    s = pd.to_numeric(s, errors="coerce").dropna()
    if s.empty:
        return None
    return float(np.percentile(s, q))
