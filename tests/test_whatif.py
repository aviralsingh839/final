from src.config import UserProfile
from src.data_models import FeatureVector
from src.models.hormone_estimator import HormoneEstimator
from src.models.risk_engine import RiskEngine
from src.models.whatif import WhatIfEngine


def _base_fv():
    return FeatureVector(
        hr_bpm=82, rmssd_ms=28, skin_temp_c=32.5, gsr_tonic=600,
        activity_level=12.0, low_activity_risk=70.0,
        sleep_probability=40.0, sleep_status="wake",
        circadian_stability_index=45.0, circadian_disruption=55.0,
        temperature_rhythm_disruption=60.0,
        acute_stress=65.0, chronic_stress=60.0, stress_index=62.0,
        autonomic_imbalance=55.0,
        insulin_resistance_probability=60.0, metabolic_syndrome_proxy=45.0,
        glucose_risk=50.0, signal_quality=0.8, baseline_available=True,
    )


def test_combined_simulation_lowers_risk():
    fv = _base_fv()
    profile = UserProfile(age_years=17, bmi=24)
    hormones = HormoneEstimator()
    risk = RiskEngine()
    result = risk.estimate(fv, hormones.estimate(fv, profile), phase=hormones.phase(profile))
    engine = WhatIfEngine(hormones, risk)
    sim = engine.simulate(fv, profile, result, "combined", strength=0.8)
    assert sim.risk_after < sim.risk_before
    assert sim.delta < 0
    assert sim.improved


def test_ablation_ranks_contributors():
    fv = _base_fv()
    profile = UserProfile()
    hormones = HormoneEstimator()
    engine = WhatIfEngine()
    ablation = engine.counterfactual_ablation(fv, hormones.estimate(fv, profile), phase="unknown")
    assert len(ablation) >= 5
    contribs = [a[3] for a in ablation]
    assert contribs == sorted(contribs, reverse=True)
