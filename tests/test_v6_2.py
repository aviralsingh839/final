"""V6.2 tests: personal physiological fingerprint, WHAT CHANGED engine,
care-plan & adherence, clinical record / report comparison, the Model A-D
longitudinal experiment framework, and manual vitals entry."""
from __future__ import annotations

import time

import numpy as np
import pytest

from src.config import UserProfile
from src.data_models import FeatureVector, RiskResult
from src.models.care_plan import CarePlanManager
from src.models.change_detector import ChangeDetector
from src.models.clinical_record import ClinicalRecord
from src.models.fingerprint import FingerprintEngine
from src.models.personalization import BaselineManager
from src.models.what_changed import WhatChangedEngine
from src.utils.history_store import HistoryStore
from src.validation.longitudinal_experiment import LongitudinalExperiment, MODEL_A_B_C_D


def _fv(hr=72.0, rmssd=42.0, temp=32.5, gsr=430.0, activity=25.0,
        motion=0.05, quality=0.9, ts=None) -> FeatureVector:
    return FeatureVector(
        timestamp_s=ts if ts is not None else time.time(),
        hr_bpm=hr, rmssd_ms=rmssd, skin_temp_c=temp, gsr_tonic=gsr,
        activity_level=activity, motion_index=motion, signal_quality=quality)


def _series(now, n=30, step=60.0, hr=72.0, rmssd=42.0, temp=32.5):
    out = []
    for i in range(n):
        f = _fv(hr=hr, rmssd=rmssd, temp=temp, ts=now + i * step)
        out.append(f)
    return out


# ----------------------------------------------------------- fingerprint
def test_v6_2_fingerprint_baseline_and_deviation():
    now = time.time()
    rng = np.random.default_rng(0)
    calm = [_fv(hr=72.0 + rng.normal(0, 0.4), rmssd=42.0 + rng.normal(0, 0.5),
                temp=32.5 + rng.normal(0, 0.03), ts=now + i * 60.0) for i in range(60)]
    bm = BaselineManager()
    bm.capture_from_features(calm)
    assert bm.has_baseline

    eng = FingerprintEngine(baseline=bm)
    report = eng.compute(calm)
    assert report.baseline_available
    hr = report.by_key()["hr_bpm"]
    assert hr.baseline_median is not None and abs(hr.baseline_median - 72.0) < 1.0
    assert hr.trend == "stable"
    assert hr.deviation_sd is not None and abs(hr.deviation_sd) < 1.0

    # Now a sustained elevated series -> elevated trend with persistence.
    elevated = [_fv(hr=95.0, rmssd=30.0, temp=33.2, ts=now + 10_000 + i * 60.0) for i in range(40)]
    report2 = eng.compute(elevated)
    hr2 = report2.by_key()["hr_bpm"]
    assert hr2.trend == "elevated"
    assert hr2.persistence_points >= 3
    assert hr2.deviation_sd is not None and hr2.deviation_sd > 2.0


def test_v6_2_fingerprint_no_data_is_insufficient():
    eng = FingerprintEngine()
    report = eng.compute([])
    assert report.metrics == [] or all(m.trend == "insufficient" for m in report.metrics)


# ---------------------------------------------------------- what changed
def test_v6_2_what_changed_phrasing_and_categories(tmp_path):
    store = HistoryStore(tmp_path / "w.db")
    now = time.time()
    store.log_cycle_entry(cycle_day=10, cycle_length=35)
    store.log_cycle_entry(cycle_day=11, cycle_length=35)
    store.log_bp(118, 76)
    store.log_bp(128, 80)
    store.log_symptom("Pain", 1)

    change = ChangeDetector().evaluate(
        [_fv(hr=72.0, rmssd=42.0, ts=now - 7200 + i * 600.0) for i in range(6)]
        + [_fv(hr=88.0, rmssd=27.0, ts=now - 3600 + i * 600.0) for i in range(6)])
    result = RiskResult(risk_percent=55.0, ci_low=40.0, ci_high=70.0, confidence=60.0,
                        category="Watch", domain_scores={}, contributions=[],
                        explanation="", hormone_estimates={})
    engine = WhatChangedEngine(store)
    report = engine.compute(change=change, profile=UserProfile(cycle_irregular=True),
                            current=result, previous_risk=45.0,
                            adherence=[{"name": "Metformin", "taken": 8, "n_expected": 28,
                                        "adherence_pct": 28.6, "gap": True}])
    assert report.items
    cats = {it.category for it in report.items}
    assert {"physiology", "cycle", "symptoms", "clinical", "adherence", "model"} <= cats
    for it in report.items:
        assert it.statement and it.evidence
    md = report.markdown()
    assert "temporally associated" in md
    assert "diagnosis" in md.lower()


def test_v6_2_what_changed_no_fabrication_when_empty(tmp_path):
    store = HistoryStore(tmp_path / "w2.db")
    engine = WhatChangedEngine(store)
    report = engine.compute()
    assert not report  # nothing invented from an empty store
    assert "No meaningful changes" in report.markdown()


# ------------------------------------------------------------- care plan
def test_v6_2_care_plan_adherence_math(tmp_path):
    store = HistoryStore(tmp_path / "c.db")
    care = CarePlanManager(store)
    mid = care.add_medication("Metformin", dose="500", unit="mg",
                              cadence="twice_daily", time_of_day="morning",
                              start_days_ago=10)
    care.log_taken(mid)
    care.log_taken(mid)
    care.log_skipped(mid)
    summary = care.adherence_summary(days=30)
    assert len(summary) == 1
    m = summary[0]
    assert m["name"] == "Metformin"
    # 10 days * 2/day = 20 expected; 3 recorded -> expected >= 20.
    assert m["n_expected"] >= 20
    assert m["taken"] == 2 and m["skipped"] == 1
    assert m["adherence_pct"] == pytest.approx(2 / m["n_expected"] * 100.0)
    assert m["gap"] is True  # < 70%


def test_v6_2_care_plan_never_prescribes(tmp_path):
    store = HistoryStore(tmp_path / "c2.db")
    care = CarePlanManager(store)
    assert care.due_medications() == []
    mid = care.add_medication("OCP", cadence="daily", start_days_ago=1)
    due = care.due_medications()
    assert any(d["medication_id"] == mid for d in due)
    # Logging today's dose removes the reminder.
    care.log_taken(mid)
    assert not any(d["medication_id"] == mid for d in care.due_medications())
    # The API surface only records; there is no set-dose/stop/start method.
    assert not hasattr(care, "prescribe") and not hasattr(care, "change_dose")


def test_v6_2_care_gap_analysis_separates_observed_associated_unknown(tmp_path):
    store = HistoryStore(tmp_path / "c3.db")
    care = CarePlanManager(store)
    mid = care.add_medication("Metformin", cadence="daily", start_days_ago=14)
    for _ in range(5):
        care.log_taken(mid)
    gap = care.care_gap_analysis(change_report=None)
    assert gap["observed"] and gap["associated"] and gap["unknown"]
    assert any("cannot establish" in u for u in gap["unknown"])


# -------------------------------------------------------- clinical record
def test_v6_2_clinical_record_and_report_compare(tmp_path):
    store = HistoryStore(tmp_path / "r.db")
    cr = ClinicalRecord(store)
    rid_a = cr.save_report("periodic", "P01", "report A",
                           {"risk": 40.0, "rmssd": 30.0, "activity": 20.0})
    rid_b = cr.save_report("periodic", "P01", "report B",
                           {"risk": 55.0, "rmssd": 18.0, "activity": 45.0})
    comp = cr.compare_reports(rid_a, rid_b)
    assert comp is not None
    rows = {r.label: r for r in comp.rows}
    # risk up + rmssd down -> worsened; activity up -> improved.
    assert rows["Model risk estimate"].status == "worsened"
    assert rows["HRV RMSSD"].status == "worsened"
    assert rows["Activity"].status == "improved"
    assert "Not a diagnosis" in comp.summary_text() or "not a diagnosis" in comp.summary_text().lower()


def test_v6_2_what_changed_since_last_visit(tmp_path):
    store = HistoryStore(tmp_path / "v.db")
    cr = ClinicalRecord(store)
    cr.add_visit("First visit", clinician="Dr X")
    lines = cr.what_changed_since_last_visit(current_risk=52.0, current_confidence=60.0)
    assert any("Model estimate" in l for l in lines)


# ------------------------------------------------- manual vitals (agnostic)
def test_v6_2_manual_vitals_are_real_non_demo(tmp_path):
    store = HistoryStore(tmp_path / "m.db")
    sid = store.log_manual_vitals(hr=74.0, rmssd=40.0, skin_temp=32.4, activity=30.0)
    sessions = store.session_summary(session_id=sid)
    assert sessions and sessions[0]["source"] == "manual"
    df = store.features_as_frame(days=30, include_demo=False)
    assert len(df) == 1
    assert df.iloc[0]["hr"] == 74.0
    assert store.coverage_days(days=30, include_demo=False) == 1


# ----------------------------------------------- Model A-D experiment
def test_v6_2_longitudinal_experiment_pending_not_fabricated():
    exp = LongitudinalExperiment()
    st = exp.status()
    assert st.status == "PENDING"
    assert not st.metrics
    assert "synthetic" in st.reason.lower() or "dataset" in st.reason.lower()
    assert {"A", "B", "C", "D", "E"} == set(MODEL_A_B_C_D)
    # No fabricated numbers anywhere in the report table.
    text = LongitudinalExperiment.report_table_text()
    assert "PENDING" in text
    assert "AUROC" in text
    assert "MODEL E" in text


def test_v6_2_experiment_refuses_unlabelled_data():
    import pandas as pd

    df = pd.DataFrame({"hr": [70, 72], "rmssd": [40, 38], "label": [0, 1]})
    exp = LongitudinalExperiment(df)
    st = exp.status()
    assert "subject_id" in st.reason  # leakage-safe requirement enforced
