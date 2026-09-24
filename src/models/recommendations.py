"""Personalized recommendations and early-warning level.

Rule-based, explainable advice derived from the current risk domains, signal
quality and baseline state. Every recommendation is a plain-language statement
with a priority so judges can see exactly why it was issued. These are lifestyle
suggestions for an educational demo, never medical advice.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

from src.config import UserProfile
from src.data_models import FeatureVector, RiskResult
from src.utils.math_utils import clamp


@dataclass
class Recommendation:
    domain: str
    priority: int  # 1 = highest
    text: str


WARNING_ORDER = ["ok", "watch", "caution", "alarm"]


def warning_level(fv: FeatureVector, result: RiskResult) -> str:
    """ok / watch / caution / alarm based on risk, anomalies and data quality."""
    if fv.anomaly_score >= 60 or result.risk_percent >= 75:
        return "alarm"
    if result.risk_percent >= 50 or fv.anomaly_score >= 30 or fv.signal_quality < 0.4:
        return "caution"
    if fv.signal_quality < 0.6 or not fv.baseline_available:
        return "watch"
    return "ok"


def generate(fv: FeatureVector, profile: UserProfile, result: RiskResult) -> List[Recommendation]:
    recs: List[Recommendation] = []
    add = lambda domain, prio, text: recs.append(Recommendation(domain, prio, text))  # noqa: E731

    if not fv.baseline_available:
        add("baseline", 1, "Complete a 5-minute calm baseline so personalized ranges and risk confidence improve.")
    if fv.signal_quality < 0.5:
        add("signal_quality", 1, "PPG/sensor contact looks weak — re-seat the fingertip sensor and reduce movement.")
    if fv.anomaly_score >= 30:
        add("anomaly", 1, "A physiological anomaly was detected — check sensor placement and re-measure.")
    if result.domain_scores.get("cycle", 0) >= 55:
        add("cycle", 2, "Cycle irregularity is elevated in the estimate — this is a key PCOS-related screening signal. Track cycle dates daily and discuss patterns with a clinician.")
    if result.domain_scores.get("circadian", 0) >= 55:
        add("circadian", 2, "Circadian disruption is elevated — keep sleep/wake times consistent (see the sleep window input).")
    if result.domain_scores.get("sleep", 0) >= 55:
        add("sleep", 2, "Sleep quality is low — aim for 7-8 h with a regular bedtime.")
    if result.domain_scores.get("stress_autonomic", 0) >= 55:
        add("stress", 2, "Stress/autonomic load is elevated — add short relaxation or breathing breaks.")
    if result.domain_scores.get("low_activity", 0) >= 55:
        add("activity", 2, "Activity is low — add 15-30 min of moderate movement.")
    if result.domain_scores.get("glucose", 0) >= 55 or (profile.glucose_mg_dl or 0) >= 110:
        add("glucose", 2, "Glucose/insulin tendency is elevated — favor lower-glycemic meals and re-test at the same time of day.")
    if result.domain_scores.get("metabolic", 0) >= 60:
        add("metabolic", 2, "Insulin-resistance tendency is high — activity, sleep and weight management are the top levers.")
    if result.domain_scores.get("temperature_rhythm", 0) >= 60:
        add("temperature", 3, "Temperature rhythm is disrupted — consistent sleep timing and stable room temperature help.")
    if not recs:
        add("general", 3, "Current signals are within your personal ranges — continue your routine and re-check tomorrow.")
    recs.sort(key=lambda r: r.priority)
    return recs


def simulation_to_recommendation(name: str, delta: float) -> str:
    if delta <= -10:
        return f"The '{name}' simulation suggests the largest estimated improvement ({delta:+.0f} points)."
    if delta <= -3:
        return f"The '{name}' simulation could help ({delta:+.0f} points estimated)."
    return f"The '{name}' simulation shows limited estimated effect ({delta:+.0f} points)."
