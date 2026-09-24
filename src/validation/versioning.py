"""Model versioning: reproducible model-state snapshots.

Captures app version, every registered model version, the exact feature list,
the preprocessing configuration (thresholds) and the frozen risk-engine
weights, so a snapshot can be reproduced later and attached to prospective
predictions and validation reports.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List

from src.config import (
    BASELINE_CAPTURE_S, BASELINE_MIN_SAMPLES, MIN_HR_BPM, MAX_HR_BPM,
    RISK_HIGH, RISK_LOW, RISK_MEDIUM, UI_PLOT_HISTORY_S,
)
from src.models.registry import APP_VERSION, MODEL_REGISTRY

# Input features consumed by the risk / hormone / sleep / stress engines.
FEATURE_LIST: List[str] = [
    "hr_bpm", "rmssd_ms", "sdnn_ms", "spo2_pct", "ppg_pulse_amplitude", "lux",
    "fsr_raw", "ecg_hr_bpm", "ecg_rmssd_ms", "motion_index", "activity_level",
    "skin_temp_c", "temp_slope_c_per_min", "gsr_tonic", "gsr_phasic_per_min",
    "stress_index", "acute_stress", "chronic_stress", "autonomic_imbalance",
    "sleep_probability", "deep_sleep_probability", "rem_probability",
    "glucose_risk", "bp_risk", "insulin_resistance_probability",
    "metabolic_syndrome_proxy", "inflammation_score", "circadian_stability_index",
    "circadian_disruption", "low_activity_risk", "temperature_rhythm_disruption",
    "signal_quality", "baseline_available", "baseline_completeness",
    "mv_challenge_risk", "voice_vasc_score",
]

# Frozen weights of the explainable risk engine (for exact reproduction).
RISK_ENGINE_WEIGHTS: Dict[str, Any] = {
    "intercept": -2.3,
    "metabolic": 1.20, "endocrine": 0.90, "sleep": 0.65, "circadian": 0.60,
    "stress_autonomic": 0.50, "glucose": 0.45, "low_activity": 0.30,
    "temperature_rhythm": 0.20, "metabolic_x_endocrine": 0.35,
    "metabolic_vascular_challenge": 0.35, "voice_vasc_experimental": 0.12,
    "link": "logistic",
}


def preprocessing_config() -> Dict[str, Any]:
    return {
        "risk_thresholds": {"low": RISK_LOW, "medium": RISK_MEDIUM, "high": RISK_HIGH},
        "hr_bounds_bpm": [MIN_HR_BPM, MAX_HR_BPM],
        "baseline_capture_s": BASELINE_CAPTURE_S,
        "baseline_min_samples": BASELINE_MIN_SAMPLES,
        "ui_plot_history_s": UI_PLOT_HISTORY_S,
    }


def snapshot_model_state() -> Dict[str, Any]:
    return {
        "app_version": APP_VERSION,
        "created_unix": time.time(),
        "models": [{"name": m["name"], "version": m["version"]} for m in MODEL_REGISTRY],
        "feature_list": FEATURE_LIST,
        "preprocessing": preprocessing_config(),
        "risk_engine_weights": RISK_ENGINE_WEIGHTS,
        "note": "Explainable equation-based engine: no trained hyperparameters to serialize.",
    }


def snapshot_label(snapshot: Dict[str, Any]) -> str:
    models = ", ".join(f"{m['name']} v{m['version']}" for m in snapshot.get("models", [])[:4])
    return f"{snapshot.get('app_version', '?')} — {models}…"
