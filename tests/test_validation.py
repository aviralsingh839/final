"""Tests for the Validation Lab modules."""
from __future__ import annotations

import json
import time

import pytest

from src.data_models import FeatureVector, RiskResult, SensorSample
from src.utils.history_store import HistoryStore
from src.validation.agreement import agreement
from src.validation.calibration import calibration
from src.validation.leakage import run_leakage_checks
from src.validation.losocv import leave_one_subject_out
from src.validation.prospective import ProspectiveValidator
from src.validation.repeatability import icc2_1, repeatability
from src.validation.report import CLAIM_GUARD, validation_report_text
from src.validation.sqi import overall_sqi, per_sensor_sqi, should_withhold
from src.validation.store import ValidationStore


def _fv(sq: float = 0.95, hr: float = 75.0, rmssd: float = 40.0) -> FeatureVector:
    return FeatureVector(
        timestamp_s=time.time(), hr_bpm=hr, rmssd_ms=rmssd, spo2_pct=97.0,
        skin_temp_c=32.5, gsr_tonic=450.0, motion_index=0.05, signal_quality=sq,
        ecg_quality=0.9, stress_index=30.0, circadian_stability_index=60.0,
    )


def _result(risk: float = 40.0, conf: float = 60.0) -> RiskResult:
    return RiskResult(
        risk_percent=risk, ci_low=risk - 10, ci_high=risk + 10, confidence=conf,
        category="Watch", domain_scores={}, contributions=[], explanation="x",
    )


def _sample() -> SensorSample:
    return SensorSample(timestamp_s=time.time(), ms=1, ir=30000, red=20000,
                        ax_g=0.1, ay_g=0.0, az_g=1.0, gx_dps=0, gy_dps=0, gz_dps=0,
                        temp_c=32.5, gsr_raw=450, lux=100, ecg_raw=500)


# ---------------------------------------------------------------- SQI
def test_sqi_per_sensor_and_overall():
    fv = _fv()
    sensors = per_sensor_sqi(_sample(), fv)
    names = {s.name for s in sensors}
    assert names == {"PPG", "ECG", "GSR", "IMU", "Temperature"}
    overall = overall_sqi(sensors)
    assert 0.0 <= overall <= 1.0
    assert overall > 0.7


def test_sqi_missing_sensors_score_zero():
    sensors = per_sensor_sqi(None, None)
    assert all(not s.present for s in sensors)
    assert overall_sqi(sensors) == 0.0


def test_decision_layer_withholds():
    assert should_withhold(_fv(sq=0.9), _result()).ok
    assert not should_withhold(_fv(sq=0.1), _result()).ok          # SQI too low
    assert not should_withhold(_fv(rmssd=None), _result()).ok      # HRV missing
    assert not should_withhold(_fv(sq=0.9), _result(conf=10.0)).ok  # confidence too low
    wide = RiskResult(risk_percent=50, ci_low=0, ci_high=90, confidence=60,
                      category="x", domain_scores={}, contributions=[], explanation="")
    assert not should_withhold(_fv(sq=0.9), wide).ok               # CI too wide
    assert should_withhold(None, None).message == "Insufficient data for reliable estimation."


# ------------------------------------------------------------ agreement
def test_agreement_stats():
    pairs = [(97.0, 98.0), (99.0, 100.0), (95.0, 97.0)]
    res = agreement(pairs)
    assert res.n == 3
    assert res.mae == pytest.approx(4.0 / 3.0)
    assert res.bias == pytest.approx(-4.0 / 3.0)
    assert res.rmse == pytest.approx(2.0 ** 0.5)
    assert res.pearson_r > 0.98
    assert res.loa_low < res.bias < res.loa_high


def test_agreement_empty():
    res = agreement([])
    assert res.n == 0


# ---------------------------------------------------------- repeatability
def test_repeatability_perfect_icc():
    measures = {"A": [70.0, 70.0, 70.0], "B": [80.0, 80.0, 80.0], "C": [90.0, 90.0, 90.0]}
    res = repeatability(measures)
    assert res.icc == pytest.approx(1.0)
    assert res.mean_cv_pct == pytest.approx(0.0)


def test_repeatability_cv():
    measures = {"A": [100.0, 110.0, 90.0], "B": [200.0, 210.0, 190.0]}
    res = repeatability(measures)
    assert res.icc is not None
    assert res.mean_cv_pct > 0.0


def test_icc_requires_subjects():
    assert icc2_1({"A": [1.0, 2.0]}) is None


# ------------------------------------------------------------ calibration
def test_calibration_perfect():
    probs = [0.0, 0.0, 0.0, 1.0, 1.0, 1.0]
    labels = [0, 0, 0, 1, 1, 1]
    res = calibration(probs, labels)
    assert res.n == 6
    assert res.brier == pytest.approx(0.0)
    assert res.ece == pytest.approx(0.0)


def test_calibration_bad():
    probs = [0.9, 0.9, 0.9, 0.1, 0.1, 0.1]
    labels = [0, 0, 0, 1, 1, 1]
    res = calibration(probs, labels)
    assert res.brier > 0.5
    assert res.ece > 0.5


# --------------------------------------------------------------- leakage
def test_leakage_detects_subject_overlap(tmp_path):
    db = HistoryStore(path=tmp_path / "leak.db")
    s1 = db.start_session(source="test", participant_id="P1")
    s2 = db.start_session(source="test", participant_id="P1")
    db.end_session(s1, sample_count=1)
    db.end_session(s2, sample_count=1)
    checks = run_leakage_checks(db)
    statuses = {c.name: c.status for c in checks}
    assert statuses.get("Subject train/test separation") == "fail"


def test_leakage_detects_duplicate_windows(tmp_path):
    db = HistoryStore(path=tmp_path / "leak2.db")
    sid = db.start_session(source="test", participant_id="P2")
    row = {"ts": time.time(), "hr": 72.0, "rmssd": 40.0, "risk": 30.0, "signal_quality": 0.8}
    db.log_feature(sid, row)
    db.log_feature(sid, row)
    db.end_session(sid, sample_count=2)
    checks = run_leakage_checks(db)
    statuses = {c.name: c.status for c in checks}
    assert statuses.get("Duplicate windows") == "warn"


def test_leakage_clean_db_passes(tmp_path):
    db = HistoryStore(path=tmp_path / "leak3.db")
    checks = run_leakage_checks(db)
    assert any(c.status == "info" for c in checks)  # no data -> info entries


# ----------------------------------------------------------------- LOSO
def _labeled_db(tmp_path, name: str) -> HistoryStore:
    db = HistoryStore(path=tmp_path / name)
    for subj, risk, label in [("A", 70.0, 1), ("A", 75.0, 1), ("B", 20.0, 0), ("B", 25.0, 0)]:
        sid = db.start_session(source="synth", participant_id=subj)
        db.log_feature(sid, {"ts": time.time(), "hr": 72.0, "risk": risk, "signal_quality": 0.9},
                       extra_json=json.dumps({"label": label}))
        db.end_session(sid, sample_count=1)
    return db


def test_loso_two_subjects(tmp_path):
    db = _labeled_db(tmp_path, "loso.db")
    res = leave_one_subject_out(db)
    assert len(res.folds) == 2
    assert all(f.accuracy == pytest.approx(1.0) for f in res.folds)
    assert "mean ± SD" in res.summary()


def test_loso_no_labels(tmp_path):
    db = HistoryStore(path=tmp_path / "loso2.db")
    sid = db.start_session(source="real", participant_id="A")
    db.log_feature(sid, {"ts": time.time(), "risk": 50.0})
    db.end_session(sid, sample_count=1)
    res = leave_one_subject_out(db)
    assert res.folds == []


# --------------------------------------------------------------- ablation
def test_ablation_configs_and_rows():
    from src.validation.ablation import run_ablation

    # V6 defensible domain set (no endocrine / voice / mv domains).
    domains = {"metabolic": 60.0, "cycle": 55.0, "sleep": 40.0, "circadian": 30.0,
               "stress_autonomic": 45.0, "glucose": 10.0, "low_activity": 20.0,
               "temperature_rhythm": 25.0, "bp": 15.0}
    rows = run_ablation(domains)
    # 1 all + 8 removed + 8 only = 17
    assert len(rows) == 17
    all_row = rows[0]
    assert all_row.name == "All sensors"
    assert all_row.delta == pytest.approx(0.0)
    removed = [r for r in rows if "removed" in r.name]
    assert len(removed) == 8
    assert all(r.risk <= all_row.risk + 1e-9 for r in removed)  # removing a positive-weight domain lowers risk
    assert all(0.0 <= r.risk <= 100.0 for r in rows)
    assert all(not any(k in r.name for k in ("VoxVasc", "endocrine", "metabolic-vascular")) for r in rows)


# ------------------------------------------------------------ prospective
def test_prospective_flow(tmp_path):
    store = ValidationStore(tmp_path / "val.db")
    val = ProspectiveValidator(store)
    snap = val.freeze()
    assert snap["app_version"]
    fv = _fv()
    pid = val.record("S1", fv, _result(risk=95.0))
    assert val.pending()
    val.set_outcome(pid, 1)
    s = val.summarize()
    assert s.n_labeled == 1
    assert s.accuracy == pytest.approx(1.0)
    assert s.brier < 0.1


def test_ground_truth_store(tmp_path):
    store = ValidationStore(tmp_path / "val2.db")
    pid = store.add_reference_pair("HR (bpm)", 74.0, 73.0, subject_id="S1", condition="rest")
    pairs = store.reference_pairs()
    assert len(pairs) == 1
    assert pairs[0]["metric"] == "HR (bpm)"
    store.clear_reference_pairs()
    assert store.reference_pairs() == []


# ---------------------------------------------------------------- report
def test_validation_report_sections(tmp_path):
    db = HistoryStore(path=tmp_path / "rep.db")
    vstore = ValidationStore(tmp_path / "rep_val.db")
    text = validation_report_text(db, vstore)
    assert "CHRONO-PCOS Validation Report" in text
    assert "Methodology" in text
    assert "Limitations & claim guard" in text
    assert "Conclusion" in text
    for line in CLAIM_GUARD:
        assert line.split(":")[0][:25] in text or line[:25] in text
    assert "not a diagnostic" in text.lower() or "not a diagnostic device" in text.lower()
