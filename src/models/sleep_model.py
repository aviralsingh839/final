"""Wearable sleep-status and sleep-quality estimation.

This is an approximate wearable method. It does not replace polysomnography.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import joblib
import numpy as np

from src.config import DEFAULT_RESTING_HR, DEFAULT_RMSSD_MS
from src.data_models import FeatureVector
from src.utils.math_utils import clamp, sigmoid, zscore


class SleepEstimator:
    def __init__(self, model_path: str | Path | None = None):
        self.model: Any | None = None
        self.feature_names: list[str] | None = None
        if model_path and Path(model_path).exists():
            bundle = joblib.load(model_path)
            if isinstance(bundle, dict):
                self.model = bundle.get("model")
                self.feature_names = bundle.get("feature_names")
            else:
                self.model = bundle

    def estimate_epoch(self, fv: FeatureVector, hour_of_day: float,
                       sleep_onset_h: float | None = None, wake_h: float | None = None) -> dict[str, float | str]:
        hr_z = zscore(fv.hr_bpm, DEFAULT_RESTING_HR, 12.0)
        rmssd_z = zscore(fv.rmssd_ms, DEFAULT_RMSSD_MS, 18.0)
        motion_z = zscore(fv.motion_index, 0.08, 0.20)
        gsr_z = zscore(fv.gsr_tonic, 450.0, 100.0)
        temp_stable = 1.0 if abs(fv.temp_slope_c_per_min) < 0.02 else 0.0
        # Time prior: high from 22:00 to 07:00.
        time_prior = 1.0 if hour_of_day >= 22 or hour_of_day <= 7 else 0.0
        # User-entered sleep/wake timing window (feature 19) sharpens the prior.
        if sleep_onset_h is not None and wake_h is not None:
            if sleep_onset_h <= wake_h:
                window_prior = 1.0 if sleep_onset_h <= hour_of_day <= wake_h else 0.0
            else:
                window_prior = 1.0 if hour_of_day >= sleep_onset_h or hour_of_day <= wake_h else 0.0
            time_prior = 0.7 * window_prior + 0.3 * time_prior
        x = -1.8 * motion_z - 0.7 * hr_z + 0.9 * rmssd_z + 0.4 * temp_stable - 0.4 * gsr_z + 0.6 * time_prior
        p_sleep_formula = float(sigmoid(x))

        p_sleep = p_sleep_formula
        if self.model is not None and self.feature_names:
            xmap = {
                "hr_bpm": fv.hr_bpm or DEFAULT_RESTING_HR,
                "rmssd_ms": fv.rmssd_ms or DEFAULT_RMSSD_MS,
                "motion_index": fv.motion_index,
                "spo2_pct": fv.spo2_pct or 97.0,
                "temp_slope_c_per_min": fv.temp_slope_c_per_min,
                "gsr_tonic": fv.gsr_tonic or 450.0,
                "hour": hour_of_day,
            }
            X = np.array([[xmap.get(n, 0.0) for n in self.feature_names]], dtype=float)
            try:
                if hasattr(self.model, "predict_proba"):
                    p_ml = float(self.model.predict_proba(X)[0, 1])
                    p_sleep = 0.55 * p_sleep_formula + 0.45 * p_ml
            except Exception:
                pass

        early_night = 1.0 if 22 <= hour_of_day or hour_of_day <= 2 else 0.0
        late_night = 1.0 if 3 <= hour_of_day <= 7 else 0.0
        spo2_stable = 1.0 if fv.spo2_pct is None or fv.spo2_pct >= 94 else 0.0
        p_deep = float(sigmoid(-1.2 * motion_z - 0.8 * hr_z + 1.1 * rmssd_z + 0.5 * early_night + 0.3 * spo2_stable))
        p_rem = float(sigmoid(0.4 * abs(rmssd_z) + 0.5 * late_night - 0.7 * motion_z + 0.2 * abs(fv.temp_slope_c_per_min)))

        status = "sleep" if p_sleep > 0.6 else "wake"
        return {
            "sleep_probability": clamp(p_sleep * 100.0, 0.0, 100.0),
            "deep_sleep_probability": clamp(p_deep * 100.0, 0.0, 100.0),
            "rem_probability": clamp(p_rem * 100.0, 0.0, 100.0),
            "sleep_status": status,
        }
