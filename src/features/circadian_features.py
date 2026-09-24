"""Circadian rhythm analysis using cosinor fits and sleep timing."""
from __future__ import annotations

import math
from typing import Iterable

import numpy as np
import pandas as pd

from src.data_models import CircadianMetrics, FeatureVector
from src.utils.math_utils import clamp


class CircadianAnalyzer:
    def _cosinor_r2(self, hours: np.ndarray, values: np.ndarray) -> float:
        mask = np.isfinite(hours) & np.isfinite(values)
        hours = hours[mask]
        y = values[mask]
        if y.size < 12 or np.nanstd(y) < 1e-6:
            return 0.0
        w = 2.0 * math.pi / 24.0
        X = np.column_stack([np.ones_like(hours), np.cos(w * hours), np.sin(w * hours)])
        beta, *_ = np.linalg.lstsq(X, y, rcond=None)
        pred = X @ beta
        ss_res = float(np.sum((y - pred) ** 2))
        ss_tot = float(np.sum((y - np.mean(y)) ** 2))
        if ss_tot <= 0:
            return 0.0
        return clamp(1.0 - ss_res / ss_tot, 0.0, 1.0)

    def analyze(self, features: Iterable[FeatureVector]) -> CircadianMetrics:
        rows = [f.as_dict() for f in features]
        if len(rows) < 60:
            return CircadianMetrics(stability_index=50.0, disruption_score=50.0)
        df = pd.DataFrame(rows).sort_values("timestamp_s")
        dt = pd.to_datetime(df["timestamp_s"], unit="s")
        hours = dt.dt.hour.to_numpy() + dt.dt.minute.to_numpy() / 60.0 + dt.dt.second.to_numpy() / 3600.0
        hr_r2 = self._cosinor_r2(hours, df["hr_bpm"].to_numpy(dtype=float) if "hr_bpm" in df else np.array([]))
        temp_r2 = self._cosinor_r2(hours, df["skin_temp_c"].to_numpy(dtype=float) if "skin_temp_c" in df else np.array([]))
        hrv_r2 = self._cosinor_r2(hours, df["rmssd_ms"].to_numpy(dtype=float) if "rmssd_ms" in df else np.array([]))
        gsr_r2 = self._cosinor_r2(hours, df["gsr_tonic"].to_numpy(dtype=float) if "gsr_tonic" in df else np.array([]))

        # Activity regularity: lower coefficient of variation in hourly activity profile.
        df["hour"] = dt.dt.hour
        if "activity_level" in df:
            hourly = df.groupby("hour")["activity_level"].mean()
            activity_regular = clamp(1.0 - float(hourly.std()) / 45.0, 0.0, 1.0)
        else:
            activity_regular = 0.0

        # Sleep regularity needs multi-day sleep onset/midpoint; approximate with sleep probability by hour.
        if "sleep_probability" in df:
            sleep_hour = df.groupby("hour")["sleep_probability"].mean()
            sleep_regular = clamp(float((sleep_hour.max() - sleep_hour.min()) / 100.0), 0.0, 1.0)
        else:
            sleep_regular = 0.0

        # Light regularity: brighter daytime and darker nighttime is better.
        if "lux" in df and df["lux"].notna().sum() > 10:
            day_mask = (df["hour"] >= 7) & (df["hour"] <= 18)
            night_mask = (df["hour"] >= 22) | (df["hour"] <= 5)
            day_lux = float(df.loc[day_mask, "lux"].median()) if day_mask.any() else 0.0
            night_lux = float(df.loc[night_mask, "lux"].median()) if night_mask.any() else 0.0
            light_regular = clamp((day_lux - night_lux) / 500.0, 0.0, 1.0)
        else:
            light_regular = 0.5

        stability = 100.0 * (0.20 * hr_r2 + 0.10 * hrv_r2 + 0.25 * temp_r2 + 0.10 * gsr_r2 + 0.15 * activity_regular + 0.15 * sleep_regular + 0.05 * light_regular)
        stability = clamp(stability, 0.0, 100.0)
        return CircadianMetrics(
            stability_index=stability,
            disruption_score=100.0 - stability,
            hr_r2=hr_r2,
            hrv_r2=hrv_r2,
            temp_r2=temp_r2,
            gsr_r2=gsr_r2,
            activity_regular=activity_regular,
            sleep_regular=sleep_regular,
            light_regular=light_regular,
        )
