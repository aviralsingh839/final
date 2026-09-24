"""Metabolic risk estimators using manual glucose and physiology."""
from __future__ import annotations

from src.config import UserProfile
from src.data_models import FeatureVector
from src.utils.math_utils import clamp, sigmoid


class MetabolicEstimator:
    def glucose_risk(self, profile: UserProfile) -> float:
        g = profile.glucose_mg_dl
        if g is None:
            return 0.0
        ctx = (profile.glucose_context or "unknown").lower()
        if "fast" in ctx:
            return float(clamp(100.0 * sigmoid((g - 100.0) / 12.0), 0.0, 100.0))
        if "2" in ctx or "post" in ctx:
            return float(clamp(100.0 * sigmoid((g - 140.0) / 20.0), 0.0, 100.0))
        # Random values are harder to interpret.
        return float(clamp(100.0 * sigmoid((g - 160.0) / 30.0), 0.0, 100.0))

    def bp_risk(self, profile: UserProfile) -> float:
        """Educational BP contribution from a manual cuff reading.

        This is not a hypertension diagnosis. ACC/AHA adult cut-points are used
        only as a soft metabolic-syndrome proxy. If BP is not entered, return 0
        so the model does not invent a blood-pressure problem.
        """
        s = profile.systolic_bp
        d = profile.diastolic_bp
        if s is None and d is None:
            return 0.0
        s = float(s) if s is not None else 110.0
        d = float(d) if d is not None else 70.0
        sys_r = clamp((s - 110.0) / 40.0 * 100.0, 0.0, 100.0)
        dia_r = clamp((d - 70.0) / 25.0 * 100.0, 0.0, 100.0)
        return float(max(sys_r, dia_r))

    def estimate(self, fv: FeatureVector, profile: UserProfile) -> dict[str, float]:
        glucose_risk = self.glucose_risk(profile)
        bp_risk = self.bp_risk(profile)
        bmi = profile.bmi if profile.bmi is not None else 23.0
        bmi_risk = clamp((bmi - 22.0) / 10.0 * 100.0, 0.0, 100.0)
        sleep_risk = clamp(100.0 - fv.sleep_probability, 0.0, 100.0) if fv.sleep_status != "unknown" else 50.0
        stress = fv.chronic_stress or fv.stress_index
        crd = fv.circadian_disruption
        activity_score = fv.activity_level

        ir = 100.0 * sigmoid(
            -2.0
            + 0.025 * ((profile.glucose_mg_dl or 90.0) - 90.0)
            + 0.045 * (bmi - 23.0)
            + 0.004 * bp_risk
            + 0.008 * sleep_risk
            + 0.007 * stress
            + 0.005 * crd
            - 0.006 * activity_score
        )
        metsyn = (
            0.28 * glucose_risk
            + 0.20 * bmi_risk
            + 0.18 * bp_risk
            + 0.12 * (100.0 - activity_score)
            + 0.12 * sleep_risk
            + 0.10 * stress
        )
        temp_elev = max(0.0, (fv.skin_temp_c or 32.5) - 33.5) * 25.0
        inflammation = 100.0 * sigmoid(
            -1.5
            + 0.004 * ((fv.hr_bpm or 72.0) - 72.0)
            + 0.004 * temp_elev
            + 0.004 * sleep_risk
            + 0.004 * glucose_risk
            + 0.003 * stress
        )
        return {
            "glucose_risk": float(clamp(glucose_risk, 0.0, 100.0)),
            "bp_risk": float(clamp(bp_risk, 0.0, 100.0)),
            "insulin_resistance_probability": float(clamp(ir, 0.0, 100.0)),
            "metabolic_syndrome_proxy": float(clamp(metsyn, 0.0, 100.0)),
            "inflammation_score": float(clamp(inflammation, 0.0, 100.0)),
        }
