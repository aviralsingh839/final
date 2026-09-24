"""Synthetic physiological week generator (features 59/60).

Builds N days of realistic hourly feature rows for a chosen synthetic patient
profile and writes them into the local offline database, so the History,
Trajectory and Research tabs work even without a real multi-day recording.

CLEARLY LABELLED: every row carries a synthetic ground-truth label and the
`source="synthetic"` marker. This data must never be presented as a real
participant's data.
"""
from __future__ import annotations

import json
import math
import time
from typing import Optional

import numpy as np

from src.config import UserProfile
from src.data_models import FeatureVector
from src.models.composite_scores import compute_scores
from src.models.risk_engine import RiskEngine
from src.utils.history_store import HistoryStore

PATIENTS = {
    0: "Low-risk regular cycle",
    1: "Elevated risk (poor sleep, stress, IR tendency)",
    2: "Improving trajectory",
}


def _patient_params(patient: int, day_index: int, days: int):
    progress = day_index / max(days - 1, 1)
    if patient == 0:
        return dict(
            hr_base=68.0, hr_night=56.0, rmssd_base=48.0, stress_base=25.0,
            ir_prob=18.0, sleep_good=0.9, activity_base=35.0, circ_base=78.0,
            gsr_base=430.0, temp_amp=0.9, label=0, progress=0.0,
            cycle_length=28, cycle_irregular=False, days_since_last_period=12,
        )
    if patient == 1:
        return dict(
            hr_base=84.0, hr_night=72.0, rmssd_base=26.0, stress_base=62.0,
            ir_prob=64.0, sleep_good=0.35, activity_base=15.0, circ_base=42.0,
            gsr_base=620.0, temp_amp=0.3, label=1, progress=0.0,
            cycle_length=36, cycle_irregular=True, days_since_last_period=48,
        )
    # patient 2: starts elevated, improves over the week (cycle normalizes).
    return dict(
        hr_base=84.0 - 14.0 * progress, hr_night=72.0 - 12.0 * progress,
        rmssd_base=26.0 + 16.0 * progress, stress_base=62.0 - 30.0 * progress,
        ir_prob=64.0 - 30.0 * progress, sleep_good=0.35 + 0.5 * progress,
        activity_base=15.0 + 25.0 * progress, circ_base=42.0 + 30.0 * progress,
        gsr_base=620.0 - 140.0 * progress, temp_amp=0.3 + 0.5 * progress,
        label=int(progress < 0.45), progress=progress,
        cycle_length=32, cycle_irregular=True, days_since_last_period=38,
    )


def generate_week(db: HistoryStore, days: int = 7, patient: int = 0,
                  participant: str = "synth-A", rows_per_day: int = 24,
                  seed: int = 7) -> tuple[int, int]:
    """Write a synthetic week into the DB. Returns (session_id, row_count)."""
    if patient not in PATIENTS:
        raise ValueError(f"unknown patient profile {patient}")
    rng = np.random.default_rng(seed)
    sid = db.start_session(source="synthetic", note=f"synthetic patient {patient}",
                           participant_id=participant)
    risk_engine = RiskEngine()
    p0 = _patient_params(patient, 0, days)
    profile = UserProfile(
        age_years=17,
        bmi=23 if patient == 0 else 26,
        usual_cycle_length_days=int(p0["cycle_length"]),
        cycle_irregular=bool(p0["cycle_irregular"]),
        days_since_last_period=int(p0["days_since_last_period"]),
    )

    now = time.time()
    n = 0
    for d in range(days):
        p = _patient_params(patient, d, days)
        day_start = now - (days - d) * 86400.0
        for hour in range(rows_per_day):
            h = hour * (24.0 / rows_per_day)
            night = h >= 22 or h <= 6
            sleep_prob = (78.0 + p["sleep_good"] * 18.0) if night else (10.0 + (1 - p["sleep_good"]) * 30.0)
            hr = p["hr_night"] + (p["hr_base"] - p["hr_night"]) * (0.5 + 0.5 * math.sin(math.pi * (h - 9) / 14.0))
            hr += rng.normal(0, 2.5)
            stress = p["stress_base"] + (35.0 if 12 <= h <= 14 else 0.0) * (1 - p["sleep_good"])
            stress += rng.normal(0, 6)
            activity = p["activity_base"] + 30.0 * math.exp(-((h - 17) ** 2) / 8.0) + rng.normal(0, 4)
            temp = 31.6 + 0.9 * math.sin(math.pi * (h - 4) / 16.0) + p["temp_amp"] * 0.4 * math.sin(2 * math.pi * (h - 3) / 24.0) + rng.normal(0, 0.03)
            circadian = p["circ_base"] + rng.normal(0, 3)
            circ_disruption = 100.0 - circadian
            temp_rhythm_disruption = max(0.0, 55.0 - p["temp_amp"] * 40.0)
            low_activity_risk = max(0.0, 100.0 - p["activity_base"] * 2.2)
            anomaly = 0.0
            if patient in (1, 2) and rng.random() < 0.02:
                anomaly = float(rng.uniform(45, 85))

            fv = FeatureVector(
                timestamp_s=day_start + hour * 3600.0,
                hr_bpm=float(hr),
                rmssd_ms=float(p["rmssd_base"] + rng.normal(0, 3)),
                spo2_pct=float(96.5 + rng.normal(0, 0.4)),
                skin_temp_c=float(temp),
                gsr_tonic=float(p["gsr_base"] + rng.normal(0, 25) + (120.0 if 12 <= h <= 14 else 0.0) * (p["stress_base"] / 60.0)),
                motion_index=float(rng.normal(0.05 if night else 0.25, 0.05)),
                activity_level=float(max(0.0, activity)),
                low_activity_risk=float(low_activity_risk),
                stress_index=float(stress),
                acute_stress=float(stress),
                chronic_stress=float(stress * 0.7),
                autonomic_imbalance=float(max(0.0, 60.0 - p["rmssd_base"] + rng.normal(0, 4))),
                sleep_probability=float(sleep_prob),
                sleep_status="sleep" if sleep_prob > 55 else "wake",
                circadian_stability_index=float(circadian),
                circadian_disruption=float(circ_disruption),
                temperature_rhythm_disruption=float(temp_rhythm_disruption),
                insulin_resistance_probability=float(p["ir_prob"] + rng.normal(0, 4)),
                metabolic_syndrome_proxy=float(p["ir_prob"] * 0.55 + rng.normal(0, 3)),
                signal_quality=float(0.75 + rng.normal(0, 0.05)),
                anomaly_score=anomaly,
                fsr_pressure_index=1.0,
            )
            scores = compute_scores(fv)
            risk = risk_engine.estimate(fv, profile=profile).risk_percent
            fv.insulin_resistance_probability = max(fv.insulin_resistance_probability, 0.0)

            extra = {
                "autonomic_imbalance": fv.autonomic_imbalance,
                "chronic_stress": fv.chronic_stress,
                "insulin_resistance_probability": fv.insulin_resistance_probability,
                "metabolic_syndrome_proxy": fv.metabolic_syndrome_proxy,
                "circadian_disruption": fv.circadian_disruption,
                "temperature_rhythm_disruption": fv.temperature_rhythm_disruption,
                "low_activity_risk": fv.low_activity_risk,
                "health_score": scores.daily_health_score,
                "light_exposure": float(150.0 + 60.0 * math.sin(2 * math.pi * (h - 6) / 18.0) if 6 <= h <= 21 else 5.0),
                "label": p["label"],
                "patient": patient,
                "synthetic": True,
            }
            db.log_feature(sid, {
                "ts": fv.timestamp_s,
                "hr": fv.hr_bpm,
                "rmssd": fv.rmssd_ms,
                "spo2": fv.spo2_pct,
                "skin_temp": fv.skin_temp_c,
                "gsr": fv.gsr_tonic,
                "motion": fv.motion_index,
                "activity": fv.activity_level,
                "stress": fv.stress_index,
                "sleep_prob": fv.sleep_probability,
                "circadian": fv.circadian_stability_index,
                "risk": risk,
                "anomaly": fv.anomaly_score,
                "signal_quality": fv.signal_quality,
            }, extra_json=json.dumps(extra))
            n += 1
    db.end_session(sid, sample_count=n)
    return sid, n
