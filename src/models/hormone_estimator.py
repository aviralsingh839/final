"""Digital Hormone Twin.

All outputs are estimated/inferred, never measured. The model is deliberately
conservative and returns wide confidence intervals for hormones that cannot be
reliably inferred from the available non-invasive signals.
"""
from __future__ import annotations

import math
from typing import Dict, List

import numpy as np

from src.config import UserProfile
from src.data_models import FeatureVector, HormoneEstimate
from src.models.hormone_prior_db import HormonePriorDB
from src.utils.math_utils import clamp, sigmoid


class HormoneEstimator:
    def __init__(self, prior_db: HormonePriorDB | None = None):
        self.priors = prior_db or HormonePriorDB()

    UNITS = {
        "Insulin": "μIU/mL",
        "Testosterone": "ng/dL",
        "LH": "mIU/mL",
        "FSH": "mIU/mL",
        "Estrogen": "pg/mL estradiol-equivalent",
        "Progesterone": "ng/mL",
        "Cortisol": "μg/dL",
        "AMH": "ng/mL",
    }

    def phase(self, profile: UserProfile) -> str:
        day = profile.cycle_day or profile.days_since_last_period
        length = profile.usual_cycle_length_days or 28
        if day is None or day <= 0:
            return "unknown"
        d = ((int(day) - 1) % max(21, length)) + 1
        if d <= 5:
            return "menses"
        if d <= max(8, int(0.45 * length)):
            return "follicular"
        if abs(d - int(0.5 * length)) <= 2:
            return "ovulatory"
        return "luteal"

    def _cycle_baselines(self, phase: str) -> dict[str, float]:
        # Plausible broad reference-like medians for educational visualization.
        # Actual lab ranges are assay/phase dependent.
        table = {
            "menses": {"LH": 5.0, "FSH": 6.5, "Estrogen": 45.0, "Progesterone": 0.6},
            "follicular": {"LH": 6.0, "FSH": 6.0, "Estrogen": 90.0, "Progesterone": 0.8},
            "ovulatory": {"LH": 22.0, "FSH": 8.0, "Estrogen": 180.0, "Progesterone": 1.2},
            "luteal": {"LH": 5.0, "FSH": 4.5, "Estrogen": 120.0, "Progesterone": 8.0},
            "unknown": {"LH": 7.0, "FSH": 6.0, "Estrogen": 90.0, "Progesterone": 2.0},
        }
        return table.get(phase, table["unknown"])

    def estimate(self, fv: FeatureVector, profile: UserProfile) -> Dict[str, HormoneEstimate]:
        phase = self.phase(profile)
        base = self._cycle_baselines(phase)
        # Blend phase physiology with offline public hormone priors when available.
        # NHANES provides population medians; mcPHASES can provide cycle-phase priors.
        for key in ["LH", "FSH", "Estrogen", "Progesterone"]:
            prior_med = self.priors.median(key, profile.age_years, default=base[key])
            base[key] = 0.65 * base[key] + 0.35 * prior_med

        ir = fv.insulin_resistance_probability / 100.0
        stress = max(fv.chronic_stress, fv.stress_index) / 100.0
        sleep_risk = (100.0 - fv.sleep_probability) / 100.0 if fv.sleep_status != "unknown" else 0.5
        crd = fv.circadian_disruption / 100.0
        activity = fv.activity_level / 100.0
        bmi_z = ((profile.bmi or 23.0) - 23.0) / 6.0
        cycle_irreg = 0.0
        if profile.usual_cycle_length_days is not None:
            cycle_irreg = clamp(abs(profile.usual_cycle_length_days - 28.0) / 20.0, 0.0, 1.0)

        # Ovulation evidence from temperature: weak unless multi-day baseline exists.
        bbt_shift = max(0.0, ((fv.skin_temp_c or 32.5) - 32.5))
        ov_evidence = float(sigmoid((bbt_shift - 0.25) / 0.08)) if phase in ("luteal", "unknown") else 0.2

        # Insulin estimate. Population prior can be generated offline from public metabolic/hormone databases.
        insulin_prior = self.priors.median("Insulin", profile.age_years, default=7.5)
        insulin = math.exp(math.log(max(insulin_prior, 1.0)) + 0.90 * ir + 0.25 * stress + 0.20 * sleep_risk + 0.15 * crd - 0.25 * activity)
        insulin = clamp(insulin, 2.0, 80.0)

        # Cortisol: circadian base by time unavailable here; app may call at any time.
        # Use current timestamp local hour if available.
        import datetime as _dt
        hour = _dt.datetime.fromtimestamp(fv.timestamp_s).hour + _dt.datetime.fromtimestamp(fv.timestamp_s).minute / 60 if fv.timestamp_s else 12
        cortisol_base = 5.0 + (18.0 - 5.0) * (1 + math.cos(2 * math.pi * (hour - 8) / 24.0)) / 2.0
        cortisol = cortisol_base * (1 + 0.35 * stress + 0.25 * sleep_risk + 0.20 * crd)
        cortisol = clamp(cortisol, 2.0, 35.0)

        latent_pcos = clamp(0.45 * ir + 0.20 * cycle_irreg + 0.15 * crd + 0.10 * sleep_risk + 0.10 * max(bmi_z, 0), 0.0, 1.0)

        # LH and FSH.
        lh = base["LH"] * math.exp(0.30 * latent_pcos + 0.20 * crd + 0.15 * stress - 0.10 * ov_evidence)
        fsh = base["FSH"] * math.exp(-0.10 * latent_pcos - 0.05 * ir)
        lh = clamp(lh, 0.5, 80.0)
        fsh = clamp(fsh, 0.5, 35.0)
        lh_fsh_index = clamp(lh / max(fsh, 0.1) / 2.0, 0.0, 2.0)

        testosterone_prior = self.priors.median("Testosterone", profile.age_years, default=32.0)
        testosterone = math.exp(math.log(max(testosterone_prior, 1.0)) + 0.45 * ir + 0.20 * lh_fsh_index + 0.15 * crd + 0.10 * sleep_risk + 0.10 * bmi_z)
        testosterone = clamp(testosterone, 8.0, 120.0)

        progesterone = base["Progesterone"] * math.exp(0.80 * ov_evidence - 0.40 * cycle_irreg - 0.20 * stress - 0.20 * crd)
        progesterone = clamp(progesterone, 0.05, 30.0)

        estrogen = base["Estrogen"] * math.exp(0.10 * bmi_z - 0.15 * crd - 0.10 * cycle_irreg)
        estrogen = clamp(estrogen, 10.0, 500.0)

        age = profile.age_years or 17.0
        amh_age_base = self.priors.median("AMH", profile.age_years, default=4.5) * math.exp(-max(age - 20.0, 0.0) / 30.0)
        amh = amh_age_base * math.exp(0.65 * latent_pcos + 0.25 * cycle_irreg + 0.15 * (testosterone - 32.0) / 40.0)
        amh = clamp(amh, 0.05, 20.0)

        estimates = {
            "Insulin": self._make("Insulin", insulin, rel_uncertainty=0.35, confidence=0.60 if profile.glucose_mg_dl else 0.35,
                                  drivers=["manual glucose", "sleep", "stress", "activity", "BMI"]),
            "Cortisol": self._make("Cortisol", cortisol, rel_uncertainty=0.45, confidence=0.45,
                                   drivers=["time-of-day", "HRV", "GSR", "sleep", "circadian rhythm"]),
            "Testosterone": self._make("Testosterone", testosterone, rel_uncertainty=0.60, confidence=0.25,
                                        drivers=["insulin resistance tendency", "LH/FSH tendency", "BMI", "sleep/circadian"]),
            "LH": self._make("LH", lh, rel_uncertainty=0.70, confidence=0.20,
                              drivers=["cycle phase", "circadian disruption", "stress"]),
            "FSH": self._make("FSH", fsh, rel_uncertainty=0.65, confidence=0.20,
                               drivers=["cycle phase", "age", "PCOS latent tendency"]),
            "Estrogen": self._make("Estrogen", estrogen, rel_uncertainty=0.70, confidence=0.20,
                                    drivers=["cycle phase", "temperature rhythm", "BMI"]),
            "Progesterone": self._make("Progesterone", progesterone, rel_uncertainty=0.60, confidence=0.35 if phase == "luteal" else 0.20,
                                        drivers=["cycle phase", "temperature shift", "sleep/stress"]),
            "AMH": self._make("AMH", amh, rel_uncertainty=0.80, confidence=0.15,
                               drivers=["age", "cycle irregularity", "androgen/PCOS latent tendency"]),
        }
        return estimates

    def _make(self, name: str, value: float, rel_uncertainty: float, confidence: float, drivers: List[str]) -> HormoneEstimate:
        low = value * max(0.05, 1.0 - rel_uncertainty)
        high = value * (1.0 + rel_uncertainty)
        return HormoneEstimate(
            name=name,
            value=float(value),
            unit=self.UNITS[name],
            ci_low=float(low),
            ci_high=float(high),
            confidence=float(clamp(confidence * 100.0, 0.0, 100.0)),
            drivers=drivers,
        )
