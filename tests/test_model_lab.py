"""CHRONO Model Lab tests (V8.2).

Covers: safe ZIP validation (traversal/absolute/executables), extraction,
label parsing, invalid-dataset handling, duplicate + leakage detection,
patient-level splitting, preprocessing records, training configuration,
checkpoint/resume, evaluation, model comparison, registry statuses,
approval / rejection / keep-current, rollback, model loading and deployment.

No test fabricates results — training runs on a tiny synthetic image dataset
generated on the fly (clearly non-clinical noise images).
"""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import numpy as np
import pytest

from src.modellab.dataset_store import DatasetStore, DatasetStructureError
from src.modellab.lab import ModelLab
from src.modellab.registry import RegistryError
from src.modellab.safezip import UnsafeZipError, extract_dataset_zip, validate_member_name
from src.modellab.splitting import LeakageError, check_split_leakage, split_records
from src.modellab.trainer import (
    TrainingBlockedError,
    TrainingConfig,
    preprocessing_record,
)


# ------------------------------------------------------------ helpers -----
def _png_bytes(seed: int, size=(64, 64), base: float = 0.3) -> bytes:
    from PIL import Image

    rng = np.random.default_rng(seed)
    arr = np.clip(rng.normal(base, 0.18, size), 0, 1)
    # deterministic class-dependent structure so a model can actually learn
    im = Image.fromarray((arr * 255).astype(np.uint8), mode="L")
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def make_dataset_zip(path: Path, n_patients: int = 14, imgs_per_patient: int = 3,
                     with_pid_column: bool = True, with_labels: bool = True,
                     duplicate_pair: bool = False) -> Path:
    """Two-class synthetic dataset: PCOS images brighter than Normal images."""
    rows = ["image,patient_id,label" if with_pid_column else "image,label"]
    with zipfile.ZipFile(path, "w") as zf:
        seed = 0
        for p in range(n_patients):
            pid = f"patient{p:03d}"
            label = "PCOS" if p % 2 == 0 else "Normal"
            base = 0.62 if label == "PCOS" else 0.30
            for i in range(imgs_per_patient):
                seed += 1
                name = f"images/{pid}_img{i:02d}.png"
                zf.writestr(name, _png_bytes(seed, base=base))
                if with_pid_column:
                    rows.append(f"{pid}_img{i:02d}.png,{pid},{label}")
                else:
                    rows.append(f"{pid}_img{i:02d}.png,{label}")
        if duplicate_pair:
            # identical bytes under two different patients -> leakage risk
            blob = _png_bytes(9999, base=0.5)
            zf.writestr("images/patient000_dup.png", blob)
            zf.writestr("images/patient001_dup.png", blob)
            rows.append("patient000_dup.png,patient000,PCOS")
            rows.append("patient001_dup.png,patient001,Normal")
        if with_labels:
            zf.writestr("labels.csv", "\n".join(rows) + "\n")
    return path


# ------------------------------------------------------- safe ZIP ---------
class TestSafeZip:
    def test_rejects_path_traversal(self):
        with pytest.raises(UnsafeZipError):
            validate_member_name("../../etc/passwd")

    def test_rejects_absolute_paths(self):
        with pytest.raises(UnsafeZipError):
            validate_member_name("/etc/passwd")
        with pytest.raises(UnsafeZipError):
            validate_member_name("C:\\windows\\evil.png")

    def test_rejects_executables(self):
        for name in ("run.exe", "script.sh", "code.py", "x.bat", "lib.so"):
            with pytest.raises(UnsafeZipError):
                validate_member_name(name)

    def test_traversal_zip_rejected_entirely(self, tmp_path):
        z = tmp_path / "evil.zip"
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("../escape.png", b"x")
        with pytest.raises(UnsafeZipError):
            extract_dataset_zip(z, tmp_path / "out")
        assert not (tmp_path / "escape.png").exists()

    def test_non_zip_rejected(self, tmp_path):
        f = tmp_path / "fake.zip"
        f.write_bytes(b"not a zip at all")
        with pytest.raises(UnsafeZipError):
            extract_dataset_zip(f, tmp_path / "out")

    def test_skips_unexpected_types_extracts_data(self, tmp_path):
        z = tmp_path / "d.zip"
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("images/a.png", _png_bytes(1))
            zf.writestr("notes.xml", "<xml/>")          # skipped, harmless
            zf.writestr("labels.csv", "image,label\na.png,PCOS\n")
        res = extract_dataset_zip(z, tmp_path / "out")
        names = {p.name for p in res.extracted}
        assert "a.png" in names and "labels.csv" in names
        assert "notes.xml" in res.skipped


# --------------------------------------------------- dataset intake -------
class TestDatasetIntake:
    def test_import_and_report(self, tmp_path):
        z = make_dataset_zip(tmp_path / "d.zip")
        store = DatasetStore(tmp_path / "lab")
        meta = store.import_zip(z, name="PCOSGEN")
        assert meta["id"].startswith("DATASET-PCOSGEN-001")
        assert meta["n_images"] == 42
        assert meta["n_patients"] == 14
        assert set(meta["classes"]) == {"PCOS", "Normal"}
        assert meta["has_patient_ids"] is True
        assert len(meta["zip_hash"]) == 64
        report = store.report(meta["id"])
        assert report["patient_ids_available"] is True
        assert report["corrupt"] == []
        assert report["missing_labels"] == []

    def test_label_parsing_without_pid_column_uses_filename(self, tmp_path):
        z = make_dataset_zip(tmp_path / "d.zip", with_pid_column=False)
        store = DatasetStore(tmp_path / "lab")
        meta = store.import_zip(z, name="NOPID")
        # patient ids recovered from the `patientNNN_` filename prefix
        assert meta["n_patients"] == 14

    def test_unintelligible_dataset_stops_with_explanation(self, tmp_path):
        z = tmp_path / "bad.zip"
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("images/a.png", _png_bytes(1))   # no labels, one folder
        store = DatasetStore(tmp_path / "lab")
        with pytest.raises(DatasetStructureError) as exc:
            store.import_zip(z, name="BAD")
        assert "could not be reliably interpreted" in str(exc.value)
        assert "labels" in str(exc.value).lower()
        assert store.list_datasets() == []               # nothing kept

    def test_no_images_stops(self, tmp_path):
        z = tmp_path / "empty.zip"
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("labels.csv", "image,label\nx.png,PCOS\n")
        store = DatasetStore(tmp_path / "lab")
        with pytest.raises(DatasetStructureError):
            store.import_zip(z, name="EMPTY")

    def test_duplicates_detected(self, tmp_path):
        z = make_dataset_zip(tmp_path / "d.zip", duplicate_pair=True)
        store = DatasetStore(tmp_path / "lab")
        meta = store.import_zip(z, name="DUP")
        report = store.report(meta["id"])
        assert report["exact_duplicates"]
        assert report["leakage_risks"]                   # same bytes, two patients
        assert any("leakage" in w.lower() for w in report["warnings"])

    def test_class_folder_structure(self, tmp_path):
        z = tmp_path / "cf.zip"
        with zipfile.ZipFile(z, "w") as zf:
            for p in range(6):
                lb = "PCOS" if p % 2 == 0 else "Normal"
                zf.writestr(f"{lb}/patient{p:03d}_img00.png", _png_bytes(p + 1))
        store = DatasetStore(tmp_path / "lab")
        meta = store.import_zip(z, name="FOLDERS")
        assert meta["structure"] == "class_folders"
        assert set(meta["classes"]) == {"PCOS", "Normal"}
        assert meta["n_patients"] == 6


# ------------------------------------------- splitting & leakage ----------
class TestSplitting:
    def _records(self, tmp_path, **kw):
        z = make_dataset_zip(tmp_path / "d.zip", **kw)
        store = DatasetStore(tmp_path / "lab")
        meta = store.import_zip(z, name="SPLIT")
        return store.load_records(meta["id"])

    def test_patient_level_split_never_crosses_patients(self, tmp_path):
        records = self._records(tmp_path)
        split = split_records(records, (0.7, 0.15, 0.15), seed=7)
        assert split.patient_level is True
        tr = {r.patient_id for r in split.train}
        va = {r.patient_id for r in split.val}
        te = {r.patient_id for r in split.test}
        assert not (tr & va) and not (tr & te) and not (va & te)
        assert check_split_leakage(split) == []

    def test_split_ratios_configurable_and_seeded(self, tmp_path):
        records = self._records(tmp_path)
        a = split_records(records, (0.6, 0.2, 0.2), seed=1)
        b = split_records(records, (0.6, 0.2, 0.2), seed=1)
        assert [r.image for r in a.train] == [r.image for r in b.train]  # reproducible

    def test_missing_patient_ids_warns_image_level(self, tmp_path):
        records = self._records(tmp_path)
        for r in records:
            r.patient_id = None
        split = split_records(records, seed=3)
        assert split.patient_level is False
        assert any("cannot be reliably ruled out" in w for w in split.warnings)

    def test_cross_split_duplicate_hash_raises(self, tmp_path):
        records = self._records(tmp_path)
        split = split_records(records, seed=7)
        # inject an artificial duplicate across train/test
        split.test[0].sha256 = split.train[0].sha256
        split.test[0].patient_id = split.train[0].patient_id  # also same patient
        with pytest.raises(LeakageError) as exc:
            check_split_leakage(split)
        assert "Potential data leakage detected" in str(exc.value)

    def test_insufficient_data(self, tmp_path):
        records = self._records(tmp_path)[:3]
        with pytest.raises(LeakageError) as exc:
            split_records(records)
        assert "INSUFFICIENT DATA" in str(exc.value)


# ------------------------------------------------ training pipeline -------
@pytest.fixture()
def trained_lab(tmp_path):
    """A ModelLab with one dataset and one completed run (session-scoped work)."""
    z = make_dataset_zip(tmp_path / "d.zip", n_patients=16, imgs_per_patient=3)
    lab = ModelLab(tmp_path / "lab")
    meta = lab.store.import_zip(z, name="TRAIN")
    cfg = TrainingConfig(dataset_id=meta["id"], model="baseline_linear",
                         epochs=6, batch_size=16, image_size=24,
                         early_stopping_patience=0, seed=11)
    run = lab.new_run(cfg)
    summary = run.execute()
    return lab, meta, cfg, run, summary


class TestTraining:
    def test_recommended_settings(self):
        cfg = TrainingConfig.recommended("DATASET-X-001")
        assert cfg.epochs > 0 and cfg.batch_size > 0 and cfg.seed == 42
        assert cfg.class_weighting == "balanced"

    def test_preprocessing_recorded_without_valtest_augmentation(self):
        rec = preprocessing_record(TrainingConfig(augment_hflip=True))
        assert rec["train_augmentation"]["horizontal_flip"] is True
        assert "never applied outside training" in rec["val_test_augmentation"]

    def test_training_produces_artifacts_and_real_metrics(self, trained_lab):
        lab, meta, cfg, run, summary = trained_lab
        d = run.run_dir
        for artifact in ("config.json", "metrics.csv", "training.log",
                         "checkpoint.joblib", "model.joblib", "evaluation.json"):
            assert (d / artifact).exists(), artifact
        assert summary["test_metrics"]["status"] == "EVALUATED"
        assert summary["test_metrics"]["auroc"] is not None
        assert 0.0 <= summary["test_metrics"]["auroc"] <= 1.0
        assert summary["split"]["patient_level"] is True
        assert "confusion_matrix" in summary["test_metrics"]
        cfg_json = json.loads((d / "config.json").read_text())
        assert cfg_json["dataset"]["hash"] == meta["zip_hash"]      # reproducibility
        assert cfg_json["config"]["seed"] == 11
        assert cfg_json["environment"]["cpu_count"] >= 1

    def test_training_blocked_on_leaky_dataset(self, tmp_path):
        z = make_dataset_zip(tmp_path / "d.zip", duplicate_pair=True)
        lab = ModelLab(tmp_path / "lab")
        meta = lab.store.import_zip(z, name="LEAKY")
        run = lab.new_run(TrainingConfig(dataset_id=meta["id"], epochs=2, image_size=24))
        with pytest.raises(LeakageError):
            run.execute()

    def test_training_blocked_on_missing_dataset(self, tmp_path):
        lab = ModelLab(tmp_path / "lab")
        run = lab.new_run(TrainingConfig(dataset_id="DATASET-NOPE-001"))
        with pytest.raises(TrainingBlockedError):
            run.execute()

    def test_cnn_backend_refused_gracefully_without_torch(self, tmp_path):
        pytest.importorskip("sklearn")
        try:
            import torch  # noqa: F401
            pytest.skip("torch installed — graceful refusal not applicable")
        except ImportError:
            pass
        z = make_dataset_zip(tmp_path / "d.zip")
        lab = ModelLab(tmp_path / "lab")
        meta = lab.store.import_zip(z, name="CNN")
        run = lab.new_run(TrainingConfig(dataset_id=meta["id"], model="cnn_transfer"))
        with pytest.raises(TrainingBlockedError) as exc:
            run.execute()
        assert "GPU-enabled environment" in str(exc.value)

    def test_checkpoint_resume(self, tmp_path):
        z = make_dataset_zip(tmp_path / "d.zip", n_patients=16)
        lab = ModelLab(tmp_path / "lab")
        meta = lab.store.import_zip(z, name="RESUME")
        cfg = TrainingConfig(dataset_id=meta["id"], epochs=5, image_size=24,
                             early_stopping_patience=0, seed=5)
        run = lab.new_run(cfg)
        # interrupt after 2 epochs
        counter = {"n": 0}

        def cb(em):
            counter["n"] += 1
            if counter["n"] >= 2:
                run.cancel()

        run.execute(progress_cb=cb)
        assert (run.run_dir / "checkpoint.joblib").exists()
        # resume the same run to completion
        resumed = lab.resume_run(run.run_id)
        assert resumed is not None
        summary = resumed.execute(resume=True)
        assert summary["epochs_completed"] >= 4                # continued, not restarted
        assert summary["test_metrics"]["status"] == "EVALUATED"


# --------------------------------------- registry / approval / rollback ---
class TestRegistryAndDeployment:
    def test_register_compare_approve_deploy(self, trained_lab):
        lab, meta, cfg, run, summary = trained_lab
        from dataclasses import asdict

        entry = lab.registry.register_run(summary, run.run_dir, asdict(cfg))
        assert entry["version"] == "CHRONO-CV-001"
        assert entry["status"] == "CANDIDATE"
        assert entry["dataset_hash"] == meta["zip_hash"]

        # No approval yet -> nothing deployed, model not loadable
        assert lab.registry.active_version() is None
        assert lab.registry.load_active_model() is None

        cmp = lab.registry.compare(None, "CHRONO-CV-001")
        assert any(r["metric"] == "AUROC" for r in cmp["rows"])
        assert cmp["current"]["version"] is None

        # HUMAN APPROVAL GATE
        approved = lab.registry.approve("CHRONO-CV-001", reviewer="researcher-1")
        assert approved["status"] == "APPROVED"
        assert lab.registry.active_version() == "CHRONO-CV-001"
        bundle = lab.registry.load_active_model()
        assert bundle is not None and bundle["version"] == "CHRONO-CV-001"
        # model card written
        card = (run.run_dir / "model_card.md").read_text()
        assert "MODEL CARD — CHRONO-CV-001" in card
        assert "Not intended for" in card

    def test_reject_and_keep_current(self, trained_lab):
        lab, meta, cfg, run, summary = trained_lab
        from dataclasses import asdict

        lab.registry.register_run(summary, run.run_dir, asdict(cfg))
        lab.registry.register_run(summary, run.run_dir, asdict(cfg))
        lab.registry.approve("CHRONO-CV-001", reviewer="r1")
        rejected = lab.registry.reject("CHRONO-CV-002", reviewer="r1", note="worse")
        assert rejected["status"] == "REJECTED"
        assert lab.registry.active_version() == "CHRONO-CV-001"   # unchanged
        kept = lab.registry.keep_current("CHRONO-CV-002", reviewer="r1")
        assert kept["review"]["decision"] == "KEEP_CURRENT"

    def test_rollback(self, trained_lab):
        lab, meta, cfg, run, summary = trained_lab
        from dataclasses import asdict

        lab.registry.register_run(summary, run.run_dir, asdict(cfg))
        lab.registry.register_run(summary, run.run_dir, asdict(cfg))
        lab.registry.approve("CHRONO-CV-001", reviewer="r1")
        lab.registry.approve("CHRONO-CV-002", reviewer="r1")
        assert lab.registry.active_version() == "CHRONO-CV-002"
        prev = lab.registry.rollback(reviewer="r1", note="unexpected behavior")
        assert prev == "CHRONO-CV-001"
        assert lab.registry.active_version() == "CHRONO-CV-001"
        # complete history retained
        actions = [h["action"] for h in lab.registry.deployment_state()["history"]]
        assert actions == ["deployed", "deployed", "rollback"]

    def test_cannot_approve_unevaluated(self, trained_lab):
        lab, meta, cfg, run, summary = trained_lab
        from dataclasses import asdict

        broken = dict(summary)
        broken["test_metrics"] = {"status": "NOT YET EVALUATED"}
        entry = lab.registry.register_run(broken, run.run_dir, asdict(cfg))
        assert entry["status"] == "EXPERIMENT"                     # demoted
        with pytest.raises(RegistryError):
            lab.registry.approve(entry["version"], reviewer="r1")

    def test_rollback_without_history_refuses(self, tmp_path):
        lab = ModelLab(tmp_path / "lab")
        with pytest.raises(RegistryError):
            lab.registry.rollback()

    def test_external_validation_requires_separate_dataset(self, trained_lab):
        lab, meta, cfg, run, summary = trained_lab
        from dataclasses import asdict

        lab.registry.register_run(summary, run.run_dir, asdict(cfg))
        with pytest.raises(RegistryError):
            lab.external_validate("CHRONO-CV-001", meta["id"])     # same dataset

    def test_external_validation_on_separate_dataset(self, trained_lab, tmp_path):
        lab, meta, cfg, run, summary = trained_lab
        from dataclasses import asdict

        lab.registry.register_run(summary, run.run_dir, asdict(cfg))
        z2 = make_dataset_zip(tmp_path / "ext.zip", n_patients=10)
        ext = lab.store.import_zip(z2, name="EXTVAL")
        metrics = lab.external_validate("CHRONO-CV-001", ext["id"], source="external site")
        assert metrics.get("status") in ("EVALUATED", "INSUFFICIENT DATA")
        entry = lab.registry.get("CHRONO-CV-001")
        assert len(entry["external_validations"]) == 1
        assert entry["external_validations"][0]["dataset_id"] == ext["id"]

    def test_dashboard_counts_honest(self, trained_lab):
        lab, meta, cfg, run, summary = trained_lab
        counts = lab.dashboard_counts()
        assert counts["datasets"] == 1
        assert counts["models"] == 0                              # nothing registered yet
        assert counts["approved"] == 0
        assert counts["training_runs"] == 1
        assert counts["active_model"] == "None deployed"


# ----------------------------------------------------------- UI wiring ----
def test_model_lab_only_in_research_section(tmp_path):
    pytest.importorskip("PySide6")
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from src.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    w = MainWindow(db_path=tmp_path / "ml.db")
    try:
        research = [w.research_tabs.tabText(i) for i in range(w.research_tabs.count())]
        assert any("Model Lab" in t for t in research)
        patient = [w.patient_tabs.tabText(i) for i in range(w.patient_tabs.count())]
        clinician = [w.clinician_tabs.tabText(i) for i in range(w.clinician_tabs.count())]
        assert not any("Model Lab" in t for t in patient + clinician)
        # research-only safety notice is visible in the Model Lab
        from src.modellab import RESEARCH_ONLY_NOTICE
        assert "not medical diagnoses" in RESEARCH_ONLY_NOTICE
        # the lab never exposes "self-training" wording
        assert "self-training" not in w.model_lab_tab.safety_label.text().lower()
        assert "controlled automated model training" in w.model_lab_tab.safety_label.text().lower()
    finally:
        w.stop_stream(); w._end_session()
        w.feature_timer.stop(); w.circadian_timer.stop(); w.close()


def test_model_lab_ui_end_to_end(tmp_path):
    """Upload → train (worker thread) → evaluate → register → approve →
    deploy → ultrasound consumption → rollback, all through the UI layer."""
    pytest.importorskip("PySide6")
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import time as _t
    from dataclasses import asdict

    from PySide6.QtWidgets import QApplication
    from src.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    w = MainWindow(db_path=tmp_path / "e2e.db")
    try:
        lab_tab = w.model_lab_tab
        z = make_dataset_zip(tmp_path / "PCOSGEN.zip", n_patients=16)
        meta = lab_tab.lab.store.import_zip(z, name="PCOSGEN")
        lab_tab.refresh_all()
        lab_tab._show_dataset_report(meta["id"])
        assert "Patient grouping: Available" in lab_tab.ds_report.toPlainText()

        lab_tab.cfg_dataset.setCurrentIndex(0)
        lab_tab.cfg_epochs.setValue(4)
        lab_tab.cfg_imgsize.setValue(24)
        lab_tab.cfg_patience.setValue(0)
        lab_tab._start_training()
        end = _t.time() + 90
        while _t.time() < end and (lab_tab.worker and lab_tab.worker.isRunning()):
            app.processEvents()
            _t.sleep(0.02)
        app.processEvents()
        assert lab_tab.last_summary is not None
        assert lab_tab.last_summary["test_metrics"]["status"] == "EVALUATED"
        assert "TEST-SET METRICS" in lab_tab.eval_text.toPlainText()

        lab_tab._register_candidate()
        assert lab_tab.lab.registry.candidates()
        lab_tab.reviewer_edit.setText("e2e-researcher")
        lab_tab.review_model.setCurrentIndex(0)
        lab_tab._approve()
        assert lab_tab.lab.registry.active_version() == "CHRONO-CV-001"

        # Clinician ultrasound module consumes the approved model (read-only).
        w.ultrasound_tab._refresh_active_model_label()
        assert "CHRONO-CV-001" in w.ultrasound_tab.active_model_label.text()
        assert "APPROVED RESEARCH MODEL" in w.ultrasound_tab.active_model_label.text()

        # Deploy a second version, then roll back through the UI.
        entry2 = lab_tab.lab.registry.register_run(
            lab_tab.last_summary, lab_tab.current_run.run_dir,
            asdict(lab_tab.current_run.cfg))
        lab_tab.lab.registry.approve(entry2["version"], reviewer="e2e")
        lab_tab._rollback()
        assert lab_tab.lab.registry.active_version() == "CHRONO-CV-001"
    finally:
        w.stop_stream(); w._end_session()
        w.feature_timer.stop(); w.circadian_timer.stop(); w.close()
