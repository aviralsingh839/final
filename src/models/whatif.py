"""Counterfactual digital twin: what-if simulation engine.

Lets the user ask "what would my risk be if I improved sleep / lowered stress /
raised activity / fixed glucose?" Each scenario copies the current FeatureVector,
applies a realistic, conservative intervention, re-runs the hormone twin and the
risk engine, and reports the before/after risk plus which domains moved.

Also provides the sensor/domain ablation laboratory: recompute the risk with each
domain zeroed to show exactly "what changed my risk" (feature 14 / 13).

Educational note: simulations are heuristic projections of the explainable risk
equation - they are not clinical predictions.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from src.config import UserProfile
from src.data_models import FeatureVector, HormoneEstimate, RiskResult
from src.models.hormone_estimator import HormoneEstimator
from src.models.risk_engine import RiskEngine
from src.utils.math_utils import clamp


@dataclass
class SimulationResult:
    name: str
    description: str
    risk_before: float
    risk_after: float
    delta: float
    domain_changes: Dict[str, float] = field(default_factory=dict)
    top_domains: List[str] = field(default_factory=list)

    @property
    def improved(self) -> bool:
        return self.delta < -0.5


SCENARIOS = {
    "improve_sleep": {
        "label": "Improve sleep",
        "desc": "Sleep duration and efficiency normalize (e.g. 7-8 h, fewer awakenings).",
    },
    "reduce_stress": {
        "label": "Reduce stress",
        "desc": "Acute/chronic stress and autonomic imbalance drop toward personal baseline.",
    },
    "increase_activity": {
        "label": "Increase activity",
        "desc": "Daily activity rises to a consistent moderate level.",
    },
    "improve_glucose": {
        "label": "Improve glucose",
        "desc": "Fasting glucose normalizes (≈85 mg/dL) with lower insulin-resistance tendency.",
    },
    "combined": {
        "label": "Combined lifestyle",
        "desc": "Sleep + stress + activity + glucose interventions together.",
    },
    "ideal": {
        "label": "Ideal profile",
        "desc": "Combined intervention plus BMI in the healthy range and a regular cycle.",
    },
}


class WhatIfEngine:
    def __init__(self, hormones: HormoneEstimator | None = None, risk_engine: RiskEngine | None = None):
        self.hormones = hormones or HormoneEstimator()
        self.risk_engine = risk_engine or RiskEngine()

    # ------------------------------------------------------------ simulate
    def simulate(self, fv: FeatureVector, profile: UserProfile, result: RiskResult,
                 scenario: str, strength: float = 1.0) -> SimulationResult:
        if scenario not in SCENARIOS:
            raise ValueError(f"unknown scenario {scenario}")
        strength = clamp(strength, 0.0, 1.0)
        base_risk = result.risk_percent

        fv2 = self._copy_with_interventions(fv, profile, scenario, strength)
        profile2 = self._profile_with_interventions(profile, scenario, strength)
        res2 = self.risk_engine.estimate(fv2, profile=profile2)

        domain_changes = {}
        for k in result.domain_scores:
            domain_changes[k] = round(result.domain_scores[k] - res2.domain_scores[k], 1)

        changed = sorted(
            ((k, v) for k, v in domain_changes.items() if abs(v) >= 1.0),
            key=lambda kv: kv[1], reverse=True,
        )
        return SimulationResult(
            name=SCENARIOS[scenario]["label"],
            description=SCENARIOS[scenario]["desc"],
            risk_before=base_risk,
            risk_after=res2.risk_percent,
            delta=round(res2.risk_percent - base_risk, 1),
            domain_changes=domain_changes,
            top_domains=[k for k, _ in changed[:4]],
        )

    def _copy_with_interventions(self, fv: FeatureVector, profile: UserProfile,
                                 scenario: str, strength: float) -> FeatureVector:
        import copy

        fv2 = copy.copy(fv)
        s = strength
        sleep = scenario in ("improve_sleep", "combined", "ideal")
        stress = scenario in ("reduce_stress", "combined", "ideal")
        activity = scenario in ("increase_activity", "combined", "ideal")
        glucose = scenario in ("improve_glucose", "combined", "ideal")

        if sleep:
            fv2.sleep_status = "sleep"
            fv2.sleep_probability = clamp(fv2.sleep_probability + 45.0 * s, 0.0, 95.0)
            fv2.deep_sleep_probability = clamp(fv2.deep_sleep_probability + 20.0 * s, 0.0, 70.0)
            fv2.circadian_stability_index = clamp(fv2.circadian_stability_index + 18.0 * s, 0.0, 100.0)
            fv2.circadian_disruption = 100.0 - fv2.circadian_stability_index
            fv2.temperature_rhythm_disruption = clamp(fv2.temperature_rhythm_disruption - 12.0 * s, 0.0, 100.0)
        if stress:
            fv2.acute_stress = clamp(fv2.acute_stress - 35.0 * s, 0.0, 100.0)
            fv2.chronic_stress = clamp(fv2.chronic_stress - 30.0 * s, 0.0, 100.0)
            fv2.stress_index = clamp(fv2.stress_index - 30.0 * s, 0.0, 100.0)
            fv2.autonomic_imbalance = clamp(fv2.autonomic_imbalance - 25.0 * s, 0.0, 100.0)
        if activity:
            fv2.activity_level = clamp(fv2.activity_level + 30.0 * s, 0.0, 70.0)
            fv2.low_activity_risk = clamp(fv2.low_activity_risk - 30.0 * s, 0.0, 100.0)
        if glucose:
            fv2.insulin_resistance_probability = clamp(fv2.insulin_resistance_probability - 22.0 * s, 0.0, 100.0)
            fv2.metabolic_syndrome_proxy = clamp(fv2.metabolic_syndrome_proxy - 15.0 * s, 0.0, 100.0)
            fv2.glucose_risk = clamp(fv2.glucose_risk - 25.0 * s, 0.0, 100.0)
        if scenario == "ideal":
            fv2.low_activity_risk = clamp(fv2.low_activity_risk - 15.0, 0.0, 100.0)
            fv2.circadian_disruption = clamp(fv2.circadian_disruption - 10.0, 0.0, 100.0)
            fv2.circadian_stability_index = 100.0 - fv2.circadian_disruption
        return fv2

    def _profile_with_interventions(self, profile: UserProfile, scenario: str, strength: float) -> UserProfile:
        import dataclasses

        p = dataclasses.replace(profile)
        if scenario == "ideal":
            if p.bmi is not None and p.bmi > 22.0:
                p.bmi = max(22.0, p.bmi - (p.bmi - 22.0) * strength)
            p.usual_cycle_length_days = p.usual_cycle_length_days or 28
            p.cycle_irregular = False
        if scenario in ("improve_glucose", "combined", "ideal"):
            p.glucose_mg_dl = 85.0
            p.glucose_context = "fasting"
        return p

    # ------------------------------------------------- ablation laboratory
    def counterfactual_ablation(self, fv: FeatureVector, hormones: Dict[str, HormoneEstimate],
                                phase: str) -> List[Tuple[str, str, float, float]]:
        """Zero each domain in turn and measure the risk change.

        Returns (domain key, human label, risk without this domain, contribution).
        A large contribution means that domain is currently pushing risk up.
        """
        result = self.risk_engine.estimate(fv, hormones, phase=phase)
        names = {
            "cycle": "Cycle irregularity",
            "metabolic": "Metabolic / insulin-resistance tendency",
            "glucose": "Glucose",
            "bp": "Blood pressure",
            "stress_autonomic": "Stress / autonomic",
            "sleep": "Sleep disruption",
            "circadian": "Circadian disruption",
            "temperature_rhythm": "Temperature rhythm",
            "low_activity": "Low activity",
        }
        out = []
        for key in result.domain_scores:
            scores = dict(result.domain_scores)
            scores[key] = 0.0
            risk_without = self.risk_engine._risk_from_scores(scores)
            out.append((key, names.get(key, key), risk_without, result.risk_percent - risk_without))
        out.sort(key=lambda x: x[3], reverse=True)
        return out
