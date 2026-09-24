"""Explainable PCOS-related risk engine (V6).

Scientifically defensible domains only — NO hormone "twin" values
(testosterone, insulin, AMH, LH, FSH, progesterone, estrogen, cortisol) enter
this score. Those values are illustrative research estimates at best and are
never treated as measurements; the live headline risk is computed exclusively
from:

  * cycle            : self-reported menstrual-cycle regularity (clinical input)
  * metabolic        : insulin-resistance *tendency* proxy (manual glucose,
                       BMI, sleep, stress) — a defensible derived score
  * glucose          : manual glucose risk (optional, contextual)
  * bp               : manual blood pressure risk (optional, contextual)
  * stress_autonomic : HR/HRV/GSR-derived autonomic load (research association)
  * sleep            : sleep/wake quality from HR/HRV/motion/time
  * circadian        : cosinor rhythm stability from the real circadian analyzer
  * temperature_rhythm : skin-temperature rhythm disruption
  * low_activity     : IMU-derived inactivity

The engine is a transparent FALLBACK (see model_status): a real trained,
calibrated model must be connected before this is called a validated model.
Until then the whole system is a RESEARCH PROTOTYPE.
"""
from __future__ import annotations

from typing import Dict, Tuple

import numpy as np

from src.config import RISK_HIGH, RISK_LOW, RISK_MEDIUM, UserProfile
from src.data_models import FeatureVector, RiskResult
from src.utils.math_utils import clamp, rescale_0_100, sigmoid

# Domain weights (research-prototype priors, replaced by an ablation-driven
# trained model when real labelled longitudinal data exists).
CYCLE_W = 1.20
METABOLIC_W = 0.90
AUTONOMIC_W = 0.60
SLEEP_W = 0.50
CIRCADIAN_W = 0.50
TEMPERATURE_W = 0.35
GLUCOSE_W = 0.35
ACTIVITY_W = 0.30
BP_W = 0.20
INTERCEPT = -3.0

# Neutral value used when a domain has no information at all (never a claim).
CYCLE_NEUTRAL = 15.0


class RiskEngine:
    """Risk estimate with the confidence-based decision layer kept separate."""

    # ------------------------------------------------------------ cycle
    @staticmethod
    def cycle_score(profile: UserProfile | None) -> float:
        """Cycle-irregularity score 0-100 from self-reported information only.

        Returns CYCLE_NEUTRAL (small, non-zero) when no cycle information is
        available, so an absence of data never masquerades as 'regular'.
        """
        if profile is None:
            return CYCLE_NEUTRAL
        length = profile.usual_cycle_length_days
        dslp = profile.days_since_last_period
        irregular = profile.cycle_irregular
        if length is None and dslp is None and irregular is None:
            return CYCLE_NEUTRAL
        parts: list[float] = []
        if length is not None:
            # Deviation from a 28-day reference, normalized (21-35 -> moderate).
            parts.append(clamp(abs(float(length) - 28.0) / 20.0 * 100.0, 0.0, 100.0))
        if irregular is True:
            parts.append(60.0)
        elif irregular is False:
            parts.append(10.0)
        if dslp is not None and dslp > 35:
            # Prolonged gap between periods (self-reported) -> oligo-pattern.
            parts.append(clamp((float(dslp) - 35.0) / 25.0 * 100.0, 0.0, 100.0))
        if not parts:
            return CYCLE_NEUTRAL
        return float(np.mean(parts))

    # ----------------------------------------------------------- domains
    def domain_scores(self, fv: FeatureVector, profile: UserProfile | None = None) -> Dict[str, float]:
        sleep_risk = 50.0 if fv.sleep_status == "unknown" else clamp(100.0 - fv.sleep_probability, 0.0, 100.0)
        return {
            "cycle": self.cycle_score(profile),
            "metabolic": clamp(fv.insulin_resistance_probability, 0.0, 100.0),
            "glucose": clamp(fv.glucose_risk, 0.0, 100.0),
            "bp": clamp(fv.bp_risk, 0.0, 100.0),
            "stress_autonomic": clamp(max(fv.stress_index, fv.autonomic_imbalance), 0.0, 100.0),
            "sleep": sleep_risk,
            "circadian": clamp(fv.circadian_disruption, 0.0, 100.0),
            "temperature_rhythm": clamp(fv.temperature_rhythm_disruption, 0.0, 100.0),
            "low_activity": clamp(fv.low_activity_risk, 0.0, 100.0),
        }

    def _risk_from_scores(self, d: Dict[str, float]) -> float:
        c = d["cycle"] / 100.0
        m = d["metabolic"] / 100.0
        a = d["stress_autonomic"] / 100.0
        s = d["sleep"] / 100.0
        ci = d["circadian"] / 100.0
        t = d["temperature_rhythm"] / 100.0
        l = d["low_activity"] / 100.0
        g = d["glucose"] / 100.0
        b = d["bp"] / 100.0
        z = (INTERCEPT
             + CYCLE_W * c
             + METABOLIC_W * m
             + AUTONOMIC_W * a
             + SLEEP_W * s
             + CIRCADIAN_W * ci
             + TEMPERATURE_W * t
             + GLUCOSE_W * g
             + ACTIVITY_W * l
             + BP_W * b)
        return float(clamp(100.0 * sigmoid(z), 0.0, 100.0))

    # ---------------------------------------------------------- estimate
    def estimate(self, fv: FeatureVector,
                 hormones: Dict[str, object] | None = None,
                 phase: str = "unknown",
                 profile: UserProfile | None = None) -> RiskResult:
        """Compute the headline risk from defensible domains only.

        `hormones` (if passed) is carried into the result for the RESEARCH-only
        hormone illustration tab and the assistant; it NEVER influences the
        headline score.
        """
        domains = self.domain_scores(fv, profile=profile)
        risk = self._risk_from_scores(domains)
        ci_low, ci_high = self._bootstrap_ci(domains, fv)
        confidence = self._confidence(fv, profile, ci_low, ci_high)
        category = self.category(risk)
        contributions = self._contributions(domains)
        explanation = self._explanation(risk, category, contributions, confidence, profile)
        return RiskResult(
            risk_percent=risk,
            ci_low=ci_low,
            ci_high=ci_high,
            confidence=confidence,
            category=category,
            domain_scores=domains,
            contributions=contributions,
            explanation=explanation,
            hormone_estimates=dict(hormones or {}),
        )

    def _bootstrap_ci(self, domains: Dict[str, float], fv: FeatureVector) -> tuple[float, float]:
        rng = np.random.default_rng(42)
        risks = []
        q = clamp(fv.signal_quality, 0.0, 1.0)
        sigma = 5.0 + (1.0 - q) * 14.0
        for _ in range(250):
            d = {k: clamp(float(rng.normal(v, sigma)), 0.0, 100.0) for k, v in domains.items()}
            risks.append(self._risk_from_scores(d))
        return float(np.percentile(risks, 5)), float(np.percentile(risks, 95))

    def _confidence(self, fv: FeatureVector, profile: UserProfile | None,
                    ci_low: float, ci_high: float) -> float:
        data_quality = clamp(fv.signal_quality, 0.0, 1.0)
        baseline = 1.0 if fv.baseline_available else 0.4 * clamp(fv.baseline_completeness, 0.0, 1.0)
        ci_width = max(0.0, ci_high - ci_low)
        ci_score = clamp(1.0 - ci_width / 80.0, 0.0, 1.0)
        feature_completeness = np.mean([
            fv.hr_bpm is not None,
            fv.rmssd_ms is not None,
            fv.skin_temp_c is not None,
            fv.activity_level > 0,
        ])
        cycle_info = profile is not None and (
            profile.usual_cycle_length_days is not None
            or profile.days_since_last_period is not None
            or profile.cycle_irregular is not None)
        cycle_completeness = 1.0 if cycle_info else 0.4
        conf = 100.0 * (0.30 * data_quality
                        + 0.20 * baseline
                        + 0.20 * ci_score
                        + 0.20 * feature_completeness
                        + 0.10 * cycle_completeness)
        return float(clamp(conf, 0.0, 100.0))

    def _contributions(self, domains: Dict[str, float]):
        names = {
            "cycle": "Cycle irregularity",
            "metabolic": "Insulin-resistance tendency",
            "glucose": "Manual glucose risk",
            "bp": "Blood pressure risk",
            "stress_autonomic": "Stress / autonomic load",
            "sleep": "Sleep disruption",
            "circadian": "Circadian rhythm disruption",
            "temperature_rhythm": "Temperature rhythm disruption",
            "low_activity": "Low activity",
        }
        weights = {
            "cycle": CYCLE_W, "metabolic": METABOLIC_W, "glucose": GLUCOSE_W,
            "bp": BP_W, "stress_autonomic": AUTONOMIC_W, "sleep": SLEEP_W,
            "circadian": CIRCADIAN_W, "temperature_rhythm": TEMPERATURE_W,
            "low_activity": ACTIVITY_W,
        }
        raw = [(names[k], weights[k] * domains[k] / 100.0, k) for k in domains]
        raw.sort(key=lambda x: x[1], reverse=True)
        return [(label, float(score * 10.0), key) for label, score, key in raw]

    def _explanation(self, risk: float, category: str, contributions,
                     confidence: float, profile: UserProfile | None) -> str:
        top = "; ".join(f"{name}" for name, _, _ in contributions[:3])
        text = (
            f"Estimated PCOS-related risk is {risk:.1f}% ({category}). "
            f"Main contributing domains: {top}. "
        )
        if profile is not None and self.cycle_score(profile) >= 55:
            text += "Cycle irregularity is the largest clinical-style signal in this estimate. "
        text += (
            f"Confidence is {confidence:.0f}% (low confidence means more baseline, sleep and "
            "cycle data are needed). This is a research/pre-screening estimate, NOT a diagnosis; "
            "clinical evaluation is required for diagnosis."
        )
        return text

    @staticmethod
    def category(risk: float) -> str:
        if risk < RISK_LOW:
            return "Low estimated risk"
        if risk < RISK_MEDIUM:
            return "Watch / lifestyle monitoring"
        if risk < RISK_HIGH:
            return "Elevated estimated risk"
        return "High estimated risk - consider professional evaluation if symptomatic"
