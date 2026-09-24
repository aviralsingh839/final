"""Stress and autonomic-balance estimation.

A trained WESAD model can be loaded if available. Otherwise the scientifically
explainable formula below is used.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import joblib
import numpy as np

from src.config import DEFAULT_RESTING_HR, DEFAULT_RMSSD_MS
from src.data_models import FeatureVector
from src.utils.math_utils import clamp, sigmoid, zscore


class StressEstimator:
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

    def estimate(self, fv: FeatureVector, gsr_z: float = 0.0) -> dict[str, float]:
        hr_z = zscore(fv.hr_bpm, DEFAULT_RESTING_HR, 12.0)
        rmssd_z = zscore(fv.rmssd_ms, DEFAULT_RMSSD_MS, 18.0)
        motion_z = zscore(fv.motion_index, 0.10, 0.22)
        temp_drop_z = zscore(-(fv.temp_slope_c_per_min or 0.0), 0.0, 0.03)
        phasic_z = zscore(fv.gsr_phasic_per_min, 1.0, 4.0)

        formula = 100.0 * sigmoid(
            0.9 * hr_z
            - 1.1 * rmssd_z
            + 0.9 * phasic_z
            + 0.5 * gsr_z
            - 0.5 * max(motion_z, 0.0)
            + 0.3 * temp_drop_z
        )

        if self.model is not None and self.feature_names:
            xmap = {
                "hr_bpm": fv.hr_bpm or DEFAULT_RESTING_HR,
                "rmssd_ms": fv.rmssd_ms or DEFAULT_RMSSD_MS,
                "gsr_z": gsr_z,
                "gsr_phasic_per_min": fv.gsr_phasic_per_min,
                "motion_index": fv.motion_index,
                "temp_slope_c_per_min": fv.temp_slope_c_per_min,
            }
            X = np.array([[xmap.get(n, 0.0) for n in self.feature_names]], dtype=float)
            try:
                if hasattr(self.model, "predict_proba"):
                    ml = float(self.model.predict_proba(X)[0, 1] * 100.0)
                else:
                    ml = float(self.model.predict(X)[0] * 100.0)
                acute = 0.55 * formula + 0.45 * ml
            except Exception:
                acute = formula
        else:
            acute = formula

        # Motion gate: if highly active, stress confidence and stress estimate are reduced.
        if fv.activity_level > 45:
            acute = 0.65 * acute

        chronic = clamp(0.55 * fv.chronic_stress + 0.45 * acute if fv.chronic_stress else acute * 0.7, 0.0, 100.0)
        autonomic = 100.0 * sigmoid(-1.0 * rmssd_z + 0.5 * hr_z + 0.4 * gsr_z)
        return {
            "acute_stress": float(clamp(acute, 0.0, 100.0)),
            "chronic_stress": float(clamp(chronic, 0.0, 100.0)),
            "autonomic_imbalance": float(clamp(autonomic, 0.0, 100.0)),
            "stress_index": float(clamp(0.65 * acute + 0.35 * chronic, 0.0, 100.0)),
        }
