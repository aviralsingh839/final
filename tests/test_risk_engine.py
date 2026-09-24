from src.data_models import FeatureVector
from src.models.hormone_estimator import HormoneEstimator
from src.models.metabolic_model import MetabolicEstimator
from src.models.risk_engine import RiskEngine
from src.config import UserProfile


def test_risk_range():
    fv = FeatureVector(hr_bpm=75, rmssd_ms=40, skin_temp_c=32.5, gsr_tonic=430)
    fv.signal_quality = 0.8
    fv.baseline_completeness = 0.5
    profile = UserProfile(age_years=17, bmi=23, glucose_mg_dl=90, glucose_context="fasting")
    h = HormoneEstimator().estimate(fv, profile)
    r = RiskEngine().estimate(fv, h)
    assert 0 <= r.risk_percent <= 100
    assert r.ci_low <= r.risk_percent <= r.ci_high or (0 <= r.ci_low <= 100 and 0 <= r.ci_high <= 100)


def test_manual_bp_is_optional_and_raises_metabolic_proxy():
    model = MetabolicEstimator()
    empty = UserProfile()
    normal = UserProfile(systolic_bp=112, diastolic_bp=72)
    high = UserProfile(systolic_bp=148, diastolic_bp=94)
    assert model.bp_risk(empty) == 0.0
    assert model.bp_risk(normal) < model.bp_risk(high)
    fv = FeatureVector(hr_bpm=75, rmssd_ms=40, skin_temp_c=32.5, gsr_tonic=430, sleep_status="wake", sleep_probability=20)
    low = model.estimate(fv, normal)["metabolic_syndrome_proxy"]
    raised = model.estimate(fv, high)["metabolic_syndrome_proxy"]
    assert raised > low
