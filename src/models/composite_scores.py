"""Composite physiology scores and the multi-modal physiological fingerprint.

Combines the raw risk-domain signals into interpretable 0-100 scores (higher =
better) plus a single daily health score. Used for the daily health card, the
weekly report, and the History tab. All scores are educational summaries.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional

from src.data_models import FeatureVector
from src.utils.math_utils import clamp


@dataclass
class CompositeScores:
    autonomic_balance: float = 50.0
    metabolic_coordination: float = 50.0
    sleep_regularity: float = 50.0
    stress_response: float = 50.0
    activity_consistency: float = 50.0
    circadian_stability: float = 50.0
    daily_health_score: float = 50.0
    fingerprint: Dict[str, float] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, float]:
        return {
            "autonomic": round(self.autonomic_balance, 1),
            "metabolic": round(self.metabolic_coordination, 1),
            "sleep": round(self.sleep_regularity, 1),
            "stress": round(self.stress_response, 1),
            "activity": round(self.activity_consistency, 1),
            "circadian": round(self.circadian_stability, 1),
            "health": round(self.daily_health_score, 1),
        }


def compute_scores(fv: Optional[FeatureVector] = None, *,
                   circadian_stability: Optional[float] = None,
                   night_sleep_prob: Optional[float] = None,
                   stress: Optional[float] = None,
                   activity: Optional[float] = None) -> CompositeScores:
    """Compute composite scores from a FeatureVector or from day-average inputs."""
    if fv is not None:
        return _from_feature(fv)
    return _from_day(circadian_stability, night_sleep_prob, stress, activity)


def _from_feature(fv: FeatureVector) -> CompositeScores:
    autonomic = 100.0 - clamp(fv.autonomic_imbalance, 0.0, 100.0)
    metabolic = 100.0 - clamp(0.60 * fv.insulin_resistance_probability + 0.40 * fv.metabolic_syndrome_proxy, 0.0, 100.0)
    sleep_risk = (100.0 - fv.sleep_probability) if fv.sleep_probability > 0 else 50.0
    sleep_reg = 100.0 - clamp(0.6 * sleep_risk + 0.4 * fv.circadian_disruption, 0.0, 100.0)
    stress_resp = 100.0 - clamp(fv.chronic_stress, 0.0, 100.0)
    activity_consist = 100.0 - clamp(fv.low_activity_risk, 0.0, 100.0)
    circ = clamp(fv.circadian_stability_index, 0.0, 100.0)
    health = _health(metabolic, autonomic, sleep_reg, stress_resp, activity_consist, circ)
    return CompositeScores(
        autonomic_balance=clamp(autonomic, 0.0, 100.0),
        metabolic_coordination=clamp(metabolic, 0.0, 100.0),
        sleep_regularity=clamp(sleep_reg, 0.0, 100.0),
        stress_response=clamp(stress_resp, 0.0, 100.0),
        activity_consistency=clamp(activity_consist, 0.0, 100.0),
        circadian_stability=circ,
        daily_health_score=health,
        fingerprint={
            "Autonomic balance": clamp(autonomic, 0.0, 100.0),
            "Metabolic coordination": clamp(metabolic, 0.0, 100.0),
            "Sleep regularity": clamp(sleep_reg, 0.0, 100.0),
            "Stress response": clamp(stress_resp, 0.0, 100.0),
            "Activity consistency": clamp(activity_consist, 0.0, 100.0),
            "Circadian stability": circ,
        },
    )


def _from_day(circadian_stability: Optional[float], night_sleep_prob: Optional[float],
              stress: Optional[float], activity: Optional[float]) -> CompositeScores:
    circ = circadian_stability if circadian_stability is not None else 50.0
    sleep_reg = night_sleep_prob if night_sleep_prob is not None else 50.0
    stress_resp = 100.0 - (stress if stress is not None else 50.0)
    activity_consist = activity if activity is not None else 50.0
    metabolic = 50.0  # not derivable from the stored day summary; neutral by default
    autonomic = 50.0
    health = _health(metabolic, autonomic, sleep_reg, stress_resp, activity_consist, circ)
    return CompositeScores(
        autonomic_balance=clamp(autonomic, 0.0, 100.0),
        metabolic_coordination=clamp(metabolic, 0.0, 100.0),
        sleep_regularity=clamp(sleep_reg, 0.0, 100.0),
        stress_response=clamp(stress_resp, 0.0, 100.0),
        activity_consistency=clamp(activity_consist, 0.0, 100.0),
        circadian_stability=clamp(circ, 0.0, 100.0),
        daily_health_score=health,
        fingerprint={},
    )


def _health(metabolic: float, autonomic: float, sleep: float, stress: float,
            activity: float, circadian: float) -> float:
    h = (0.25 * metabolic + 0.20 * autonomic + 0.15 * sleep + 0.15 * stress
         + 0.15 * activity + 0.10 * circadian)
    return clamp(h, 0.0, 100.0)


def health_from_day(circadian: Optional[float], night_sleep: Optional[float],
                    stress: Optional[float], activity: Optional[float]) -> float:
    return _from_day(circadian, night_sleep, stress, activity).daily_health_score
