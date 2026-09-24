import json
import tempfile
from pathlib import Path

import pandas as pd

from src.config import DATA_DIR
from src.models.cyst_event import CYST_MODEL_STATUS, CystResearchMonitor, CystEventRecord, CYST_EVENT_TABLE_DDL
from src.models.dataset_manager import (
    DATASET_REGISTRY,
    check_cross_dataset_subject_overlap,
    check_impossible_values,
    check_duplicates,
    check_missing_values,
    dataset_registry_summary,
    get_dataset,
    run_quality_checks,
)
from src.models.model_status import compute_model_statuses, evidence_progress
from src.models.training_audit import audit_summary, latest_audit, load_audits, record_training_audit
from src.data_models import FeatureVector


# ------------------------------------------------------------ training audit
def test_training_audit_roundtrip(tmp_path):
    log = tmp_path / "audit.jsonl"
    record_training_audit({"model_id": "m1", "model_name": "M1", "n_samples": 10, "metrics": {"roc_auc": 0.9}}, log)
    record_training_audit({"model_id": "m2", "model_name": "M2"}, log)
    entries = load_audits(log)
    assert len(entries) == 2
    assert latest_audit("m1", log)["n_samples"] == 10
    assert "m1" in audit_summary(log)
    assert latest_audit("nope", log) is None


def test_training_audit_no_fabrication_on_missing():
    assert load_audits(Path("/nonexistent/audit.jsonl")) == []
    assert latest_audit("anything", Path("/nonexistent/audit.jsonl")) is None


# ------------------------------------------------------------ dataset manager
def test_dataset_registry_entries():
    assert get_dataset("pcos_kaggle") is not None
    assert get_dataset("wrist_ppg_exercise").status == "present"
    assert get_dataset("wesad").status == "absent"
    assert get_dataset("pcos_extended").status == "synthetic"
    text = dataset_registry_summary()
    assert "SYNTHETIC" in text
    assert "pcos_kaggle" in text


def test_quality_checks():
    df = pd.DataFrame({
        "Age (yrs)": [25, 250],  # 250 is impossible
        "Weight (Kg)": [60, 65],
        "Height(Cm)": [165, 170],
        "Pulse rate(bpm)": [70, 75],
        "PCOS (Y/N)": [0, 1],
        "Patient File No.": [1, 1],  # duplicate subject id
    })
    res = run_quality_checks(df, id_col="Patient File No.")
    assert res["missing"]["total_missing"] == 0
    assert any("age" in f["column"].lower() for f in res["impossible_values"])
    assert res["duplicates"]["duplicate_subject_ids"] == 1
    dup = check_duplicates(df, id_col="Patient File No.")
    assert dup["n_unique_subjects"] == 1


def test_cross_dataset_overlap_detected():
    overlap = check_cross_dataset_subject_overlap()
    by = {o["dataset_a"] + "|" + o["dataset_b"]: o for o in overlap}
    # pcos_kaggle ∩ pcos_infertility share all 541 patients.
    assert by["pcos_kaggle|pcos_infertility"]["overlap_subjects"] == 541
    # extended reuses the original patients - flagged, never treated as new subjects.
    ext = by["pcos_kaggle|pcos_extended"]
    assert ext["overlap_subjects"] > 0
    assert "SYNTHETIC" in ext["note"]


def test_missing_value_detection():
    df = pd.DataFrame({"A": [1, None, 3], "B": [None, None, None]})
    res = check_missing_values(df)
    assert res["total_missing"] == 4
    assert res["rows_with_any_missing"] == 3


# ------------------------------------------------------------ model status
def test_model_statuses_honest():
    statuses = {s.id: s for s in compute_model_statuses()}
    # Cyst model must never claim trained status.
    assert statuses["cyst"].status == "NOT YET TRAINED"
    # Equation engine is explicitly NOT an ML model.
    assert statuses["risk_engine"].status == "FALLBACK"
    assert "not a trained ml model" in statuses["risk_engine"].reason.lower()
    # Stress/sleep/hormone have no artifacts in this checkout -> NOT TRAINED.
    for mid in ("stress", "sleep", "hormone"):
        assert statuses[mid].status == "NOT TRAINED"
    # The two artifacts we trained must report TRAINED.
    assert statuses["pcos_risk"].status == "TRAINED"
    assert statuses["ppg_quality"].status == "TRAINED"


def test_evidence_progress_from_store(tmp_path):
    from src.validation.store import ValidationStore

    store = ValidationStore(tmp_path / "v.db")
    prog = evidence_progress(store)
    assert prog["sensor_validation"]["fraction"] == 0.0
    assert prog["clinical_validation"]["fraction"] == 0.0
    # Add pairs for one metric -> sensor progress > 0.
    for i in range(3):
        store.add_reference_pair(metric="HR (bpm)", sensor_value=70 + i, reference_value=71 + i)
    prog2 = evidence_progress(store)
    assert prog2["sensor_validation"]["fraction"] == 1 / 6


# ------------------------------------------------------------ cyst module
def test_cyst_status_not_trained():
    assert CYST_MODEL_STATUS == "NOT YET TRAINED"


def test_cyst_monitor_reports_trajectory_not_rupture():
    mon = CystResearchMonitor()
    baseline = [FeatureVector(timestamp_s=100 + i, hr_bpm=72.0, rmssd_ms=40.0, gsr_tonic=450.0,
                              skin_temp_c=32.5, motion_index=0.05, spo2_pct=98.0) for i in range(40)]
    rep = mon.evaluate(baseline)
    assert rep.multimodal_score < 30
    assert "rupture" not in rep.verdict.lower()
    # Extreme deviation -> research flag, still never a rupture claim.
    abnormal = list(baseline)
    for i in range(10):
        abnormal.append(FeatureVector(timestamp_s=200 + i, hr_bpm=125.0, rmssd_ms=12.0,
                                      gsr_tonic=900.0, skin_temp_c=34.5, motion_index=0.6, spo2_pct=96.0))
    rep2 = mon.evaluate(abnormal)
    assert rep2.multimodal_score > rep.multimodal_score
    assert "rupture" not in rep2.verdict.lower()
    assert "RESEARCH" in rep2.research_only


def test_cyst_record_schema():
    rec = CystEventRecord(subject_id="P01", timestamp=123.0, hr=80.0, pain_score=3, symptoms="mild")
    d = rec.to_dict()
    assert d["subject_id"] == "P01"
    assert "clinical_outcome" in d
    assert "CREATE TABLE" in CYST_EVENT_TABLE_DDL
    assert "clinical_outcome" in CYST_EVENT_TABLE_DDL
