"""ULTRASOUND & MULTIMODAL FUSION tab (V8.1).

Three coherent blocks:

  1. ULTRASOUND CV — import an image file, run the quality gate, extract
     structured features (IMAGE-DERIVED values are UNKNOWN until a validated
     labelled dataset exists — the module never fabricates anatomy), and
     compare examinations (descriptive direction-of-change only).

  2. MULTIMODAL FUSION — a provenance-aware view of every input group
     (MEASURED / PATIENT-REPORTED / CLINICALLY-ENTERED / IMAGE-DERIVED /
     MODEL-INFERRED), with per-group reliability weights and an explicit list
     of missing modalities. Nothing is treated as a measurement unless its
     provenance says MEASURED.

  3. LOW-INFRASTRUCTURE REPORTING — one-page clinical summary (text/PDF) and
     the full longitudinal HTML report behind a QR token (token = randomized
     de-identified record identifier; no PII is encoded).

The central research question is kept in view: does combining periodic
clinical/ultrasound information with continuous longitudinal physiology add
useful information between visits?
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional

from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.models.fusion import FusionContext, FusionEngine, GROUP_ORDER
from src.models.longitudinal_report import (
    build_clinical_summary,
    build_full_html_report,
    write_clinical_summary_pdf,
    write_full_html_report,
)
from src.models.ultrasound_cv import (
    IMAGE_DERIVED,
    MEASURED,
    PROVENANCE_LABELS,
    QUALITY_INSUFFICIENT,
    UNKNOWN,
    UltrasoundCV,
    UltrasoundDataset,
)
from src.utils.history_store import HistoryStore
from src.utils.qr_encoder import make_qr_code, QRError


class UltrasoundFusionTab(QWidget):
    def __init__(self, store: HistoryStore, report_metrics_fn: Callable[[], Dict] | None = None,
                 cv_model_provider: Callable[[], Dict | None] | None = None,
                 parent=None):
        super().__init__(parent)
        self.store = store
        self.report_metrics_fn = report_metrics_fn or (lambda: {})
        # V8.2: provider returning the APPROVED Model Lab bundle (or None).
        self.cv_model_provider = cv_model_provider or (lambda: None)
        self.cv = UltrasoundCV()
        self.fusion = FusionEngine()
        self.last_features: Optional[dict] = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        inner = QTabWidget()
        inner.setDocumentMode(True)
        inner.addTab(self._build_ultrasound(), "Ultrasound CV")
        inner.addTab(self._build_fusion(), "Multimodal Fusion")
        inner.addTab(self._build_reporting(), "Reporting + QR")
        inner.addTab(self._build_dataset(), "Dataset Requirements")
        outer.addWidget(inner, 1)
        self.refresh()

    # ------------------------------------------------------------- CV tab
    def _build_ultrasound(self) -> QWidget:
        tab = QWidget(); layout = QVBoxLayout(tab); layout.setSpacing(10)

        top = QHBoxLayout()
        self.us_path = QLineEdit()
        self.us_path.setPlaceholderText("Path to an ultrasound image (.png/.jpg/.jpeg/.bmp/.tif)")
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse_image)
        analyse = QPushButton("Assess quality + extract features")
        analyse.clicked.connect(self._analyse_image)
        top.addWidget(self.us_path, 1)
        top.addWidget(browse)
        top.addWidget(analyse)
        layout.addLayout(top)

        self.us_quality = QLabel("No image assessed yet.")
        self.us_quality.setWordWrap(True)
        self.us_quality.setObjectName("BigValue")
        layout.addWidget(self.us_quality)

        # V8.2: which approved Model Lab model (if any) provides CV output.
        self.active_model_label = QLabel("")
        self.active_model_label.setObjectName("SmallMuted")
        self.active_model_label.setWordWrap(True)
        layout.addWidget(self.active_model_label)
        self._refresh_active_model_label()

        cl = QHBoxLayout()
        self.us_size = QDoubleSpinBox(); self.us_size.setRange(0, 300); self.us_size.setSpecialValueText("none"); self.us_size.setSuffix(" mm")
        self.us_vol = QDoubleSpinBox(); self.us_vol.setRange(0, 1000); self.us_vol.setSpecialValueText("none"); self.us_vol.setSuffix(" cc")
        self.us_morph = QLineEdit(); self.us_morph.setPlaceholderText("Clinician morphology, e.g. polycystic")
        cl.addWidget(QLabel("Cyst size (clinical entry)")); cl.addWidget(self.us_size)
        cl.addWidget(QLabel("Volume (clinical entry)")); cl.addWidget(self.us_vol)
        cl.addWidget(self.us_morph, 2)
        save_cl = QPushButton("Record clinically entered findings")
        save_cl.clicked.connect(self._save_clinical_entry)
        cl.addWidget(save_cl)
        layout.addLayout(cl)

        mid = QHBoxLayout()
        feats_box = QGroupBox("Structured features (provenance-tracked)")
        fb = QVBoxLayout(feats_box)
        self.us_features = QTextEdit(); self.us_features.setReadOnly(True)
        self.us_features.setPlaceholderText(
            "Structured features appear here after analysis. Values the system cannot\n"
            "determine are UNKNOWN — nothing is hallucinated.")
        fb.addWidget(self.us_features)
        mid.addWidget(feats_box, 2)

        cmp_box = QGroupBox("Ultrasound comparison (previous → current)")
        cb = QVBoxLayout(cmp_box)
        self.us_compare = QTextEdit(); self.us_compare.setReadOnly(True)
        self.us_compare.setPlaceholderText(
            "Descriptive comparison of recorded examinations (date, measurements,\n"
            "direction of change). Temporal association is never causation.")
        cb.addWidget(self.us_compare)
        mid.addWidget(cmp_box, 2)
        layout.addLayout(mid, 1)

        note = QLabel(
            "NOT an ultrasound→PCOS black box. The image-quality gate runs on real images; "
            "image-derived anatomical features are UNKNOWN until a validated, labelled, "
            "patient-grouped dataset exists (see Dataset Requirements tab). "
            "No cyst-rupture prediction exists or is claimed.")
        note.setWordWrap(True)
        note.setObjectName("SmallMuted")
        layout.addWidget(note)
        return tab

    # ------------------------------------------------------------ fusion
    def _build_fusion(self) -> QWidget:
        tab = QWidget(); layout = QVBoxLayout(tab); layout.setSpacing(10)

        row = QHBoxLayout()
        build_btn = QPushButton("Build fusion context from current data")
        build_btn.clicked.connect(self._build_fusion_context)
        row.addWidget(build_btn)
        row.addStretch(1)
        layout.addLayout(row)

        self.fusion_text = QTextEdit(); self.fusion_text.setReadOnly(True)
        self.fusion_text.setPlaceholderText(
            "The multimodal fusion context appears here: every input with its\n"
            "provenance (MEASURED / PATIENT-REPORTED / CLINICALLY-ENTERED /\n"
            "IMAGE-DERIVED / MODEL-INFERRED), quality, group weights, and the\n"
            "explicit list of missing modalities.")
        layout.addWidget(self.fusion_text, 2)

        legend = QLabel("Provenance meaning:\n" + "\n".join(
            f"  • {k}: {PROVENANCE_LABELS[k]}" for k in
            (MEASURED, "PATIENT-REPORTED", "CLINICALLY-ENTERED", IMAGE_DERIVED, "MODEL-INFERRED", UNKNOWN)))
        legend.setObjectName("SmallMuted")
        layout.addWidget(legend)
        return tab

    # --------------------------------------------------------- reporting
    def _build_reporting(self) -> QWidget:
        tab = QWidget(); layout = QVBoxLayout(tab); layout.setSpacing(10)

        summary_box = QGroupBox("ONE-PAGE CLINICAL SUMMARY (digital-first, print fallback)")
        sb = QVBoxLayout(summary_box)
        self.summary_text = QTextEdit(); self.summary_text.setReadOnly(True)
        self.summary_text.setPlaceholderText("Generate the one-page summary, then save as text or PDF.")
        sb.addWidget(self.summary_text, 2)
        sr = QHBoxLayout()
        self.summary_participant = QLineEdit(); self.summary_participant.setPlaceholderText("De-identified participant ID")
        gen = QPushButton("Generate summary")
        gen.clicked.connect(self._generate_summary)
        save_txt = QPushButton("Save .txt")
        save_txt.clicked.connect(lambda: self._save_summary("txt"))
        save_pdf = QPushButton("Save .pdf (1 page)")
        save_pdf.clicked.connect(lambda: self._save_summary("pdf"))
        sr.addWidget(self.summary_participant, 1)
        sr.addWidget(gen); sr.addWidget(save_txt); sr.addWidget(save_pdf)
        sb.addLayout(sr)
        layout.addWidget(summary_box, 2)

        qr_box = QGroupBox("QR REPORT ACCESS (full longitudinal report, de-identified)")
        qb = QVBoxLayout(qr_box)
        qr_row = QHBoxLayout()
        self.qr_participant = QLineEdit(); self.qr_participant.setPlaceholderText("Participant ID for the report")
        build_html = QPushButton("Generate full report + QR")
        build_html.clicked.connect(self._build_qr_report)
        qr_row.addWidget(self.qr_participant, 1)
        qr_row.addWidget(build_html)
        qb.addLayout(qr_row)
        self.qr_status = QLabel("No report generated yet.")
        self.qr_status.setWordWrap(True)
        qb.addWidget(self.qr_status)
        self.qr_preview = QLabel("")
        qb.addWidget(self.qr_preview, 1)
        layout.addWidget(qr_box, 2)

        note = QLabel(
            "The QR carries only a randomized record token (e.g. CP-9F3A2B7C) — no "
            "identifying information. Scanning it resolves to the full longitudinal "
            "report through the local lookup. Low-infrastructure path: full dashboard "
            "on a computer, QR on a smartphone, printed one-page summary where neither is available.")
        note.setWordWrap(True)
        note.setObjectName("SmallMuted")
        layout.addWidget(note)
        return tab

    # ------------------------------------------------------------ dataset
    def _build_dataset(self) -> QWidget:
        tab = QWidget(); layout = QVBoxLayout(tab); layout.setSpacing(10)
        ds = QTextEdit(); ds.setReadOnly(True)
        ds.setPlainText(UltrasoundDataset.dataset_schema_doc())
        layout.addWidget(ds, 3)
        check = QPushButton("Validate a candidate dataset CSV (column schema)")
        check.clicked.connect(self._validate_dataset)
        layout.addWidget(check)
        self.dataset_check = QLabel("")
        self.dataset_check.setWordWrap(True)
        self.dataset_check.setObjectName("SmallMuted")
        layout.addWidget(self.dataset_check)
        return tab

    # ------------------------------------------------------------ actions
    def _browse_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select ultrasound image", "",
            "Images (*.png *.jpg *.jpeg *.bmp *.tif *.tiff)")
        if path:
            self.us_path.setText(path)

    def _analyse_image(self):
        p = self.us_path.text().strip()
        if not p:
            self.us_quality.setText("Choose an image file first.")
            return
        quality = self.cv.assess_quality(p)
        self.us_quality.setText(quality.summary)
        self.last_features = None
        if not quality.ok:
            self.us_features.setPlainText(
                QUALITY_INSUFFICIENT + "\n\n" + "\n".join(f"• {i}" for i in quality.issues) +
                "\n\nNo features are extracted from an image that fails the quality gate.")
            self.store.log_ultrasound_image(p, quality_ok=False,
                                            quality_notes="; ".join(quality.issues),
                                            source="file")
            return
        features = self.cv.extract_features(p)
        self.last_features = features.as_dict()
        text = self._features_text(features.as_dict())
        model_text = self._approved_model_output(p)
        if model_text:
            text += "\n\n" + model_text
        self.us_features.setPlainText(text)
        self.store.log_ultrasound_image(
            p, quality_ok=True, quality_notes=quality.summary,
            features_json=json.dumps(features.as_dict()), provenance=features.provenance,
            source="file")
        self._refresh_compare()

    def _features_text(self, d: dict) -> str:
        lines = [f"Exam timestamp: {time.strftime('%Y-%m-%d %H:%M', time.localtime(d.get('exam_ts', 0)))}",
                 f"Source: {d.get('source')}",
                 f"Provenance: {d.get('provenance')}",
                 f"Confidence: {d.get('confidence'):.2f}",
                 ""]
        for label, key in (("Ovaries visible", "ovary_visible"),
                           ("Left ovary volume (cc)", "left_ovary_volume_cc"),
                           ("Right ovary volume (cc)", "right_ovary_volume_cc"),
                           ("Cyst present", "cyst_present"),
                           ("Largest cyst (mm)", "cyst_size_mm"),
                           ("Laterality", "cyst_laterality"),
                           ("Morphology", "morphology"),
                           ("Follicle count notes", "follicle_count_notes")):
            v = d.get(key)
            lines.append(f"{label}: {v if v not in (None, '') else UNKNOWN}")
        if d.get("notes"):
            lines += ["", "Notes:", d["notes"]]
        return "\n".join(lines)

    def _save_clinical_entry(self):
        features = self.cv.extract_features(
            self.us_path.text().strip() or "no-image",
            clinician_entries={
                "cyst_size_mm": self.us_size.value() or None,
                "volume_cc": self.us_vol.value() or None,
                "morphology": self.us_morph.text().strip() or None,
            })
        self.store.log_ultrasound(
            cyst_size_mm=features.cyst_size_mm, volume_cc=features.left_ovary_volume_cc,
            morphology=features.morphology if features.morphology != UNKNOWN else "",
            source="clinical",
            summary="Clinically entered ultrasound observation")
        self._refresh_compare()
        self.us_features.setPlainText(self._features_text(features.as_dict()) +
                                      "\n\nRecorded to the local clinical record.")

    def _refresh_compare(self):
        hist = self.store.ultrasound_history(limit=20)
        if len(hist) < 2:
            self.us_compare.setPlainText("Need at least two recorded examinations to compare.")
            return
        # history is newest-first
        comp = self.cv.compare_exams(hist[1], hist[0])
        self.us_compare.setPlainText(comp.summary_text() if comp else "No comparable fields.")

    def _build_fusion_context(self):
        from src.models.care_plan import CarePlanManager
        from src.models.change_detector import ChangeDetector
        from src.models.fingerprint import FingerprintEngine
        from src.models.risk_engine import RiskEngine

        profile = getattr(self, "_profile", None)
        cycle = self.store.cycle_history(limit=1)
        cycle_d = cycle[0] if cycle else None
        symptoms = self.store.symptoms(limit=50)
        bp = self.store.bp_readings(limit=1)
        glu = self.store.glucose_readings(limit=1)
        meds = CarePlanManager(self.store).adherence_summary(days=60)
        us_hist = self.store.ultrasound_history(limit=1)
        us = us_hist[0] if us_hist else None
        if us is None:
            us = self.last_features

        ctx = self.fusion.build(
            profile=profile, cycle=cycle_d, symptoms=symptoms,
            wearable=None, fingerprint=None, change=None,
            bp=bp[0] if bp else None, glucose=glu[0] if glu else None,
            ultrasound=us, adherence=meds)

        w = ctx.group_weights()
        text = [ctx.summary_text(), "",
                "GROUP RELIABILITY WEIGHTS (missing groups = 0, never drag the estimate):"]
        for g in GROUP_ORDER:
            text.append(f"  {g}: {w.get(g, 0.0):.2f}")
        text += ["", "MISSING MODALITIES (lower confidence, never a fabricated value):"]
        missing = ctx.missing_groups()
        text.append("  " + (", ".join(missing) if missing else "none — all groups present"))
        self.fusion_text.setPlainText("\n".join(text))

    def _generate_summary(self):
        from src.models.care_plan import CarePlanManager
        from src.models.change_detector import ChangeDetector

        pid = self.summary_participant.text().strip() or "anonymous"
        # change report from the local store's real feature rows
        df = self.store.features_as_frame(days=180, include_demo=False)
        change = None
        if not df.empty:
            from src.utils.replay import features_from_frame
            feats = features_from_frame(df)
            if feats:
                change = ChangeDetector().evaluate(feats)
        care = CarePlanManager(self.store)
        adherence = care.adherence_summary(days=60)
        risk = self.store.risk_at_time(time.time())
        quality = 0.0
        if not df.empty and "signal_quality" in df.columns:
            q = df["signal_quality"].dropna()
            if len(q):
                quality = float(q.mean())
        us_lines = []
        hist = self.store.ultrasound_history(limit=20)
        if len(hist) >= 2:
            comp = self.cv.compare_exams(hist[1], hist[0])
            if comp:
                us_lines = [r["label"] + ": " + r["prev"] + " → " + r["curr"] +
                            " (" + r["direction"] + ")" for r in comp.rows]
        text = build_clinical_summary(
            self.store, participant=pid, change=change,
            current_risk=risk, current_confidence=(risk * 0.0 + 50.0) if risk is not None else None,
            data_quality=quality, ultrasound_lines=us_lines)
        self.summary_text.setPlainText(text)

    def _save_summary(self, kind: str):
        text = self.summary_text.toPlainText()
        if not text.strip():
            self.qr_status.setText("Generate the summary first.")
            return
        default_dir = Path("data/exports")
        default_dir.mkdir(parents=True, exist_ok=True)
        if kind == "pdf":
            default = default_dir / f"clinical_summary_{time.strftime('%Y%m%d')}.pdf"
            path, _ = QFileDialog.getSaveFileName(self, "Save one-page summary PDF", str(default), "PDF (*.pdf)")
            if path:
                ok = write_clinical_summary_pdf(path, text)
                self.qr_status.setText(f"PDF {'saved (1 page)' if ok else 'FAILED (spills past one page)'}: {path}")
        else:
            default = default_dir / f"clinical_summary_{time.strftime('%Y%m%d')}.txt"
            path, _ = QFileDialog.getSaveFileName(self, "Save summary text", str(default), "Text (*.txt)")
            if path:
                Path(path).write_text(text, encoding="utf-8")
                self.qr_status.setText(f"Saved: {path}")

    def _build_qr_report(self):
        pid = self.qr_participant.text().strip() or "anonymous"
        df = self.store.features_as_frame(days=180, include_demo=False)
        change = None
        if not df.empty:
            from src.utils.replay import features_from_frame
            feats = features_from_frame(df)
            if feats:
                change = ChangeDetector().evaluate(feats)
        risk = self.store.risk_at_time(time.time())
        html_text = build_full_html_report(self.store, participant=pid, change=change,
                                           current_risk=risk)
        default_dir = Path("data/exports")
        default_dir.mkdir(parents=True, exist_ok=True)
        html_path = default_dir / f"report_{pid}_{time.strftime('%Y%m%d_%H%M%S')}.html"
        write_full_html_report(html_path, html_text)

        # Save a report row, then issue a token for it.
        report_id = self.store.save_report(
            "longitudinal", pid, "Full longitudinal report (HTML) generated for QR access.", {})
        token = self.store.create_report_token(report_id=report_id,
                                               note=f"QR access token for participant {pid}")
        try:
            qr = make_qr_code(token, version=2, level="L")
            png = qr.to_png_bytes(scale=8)
            png_path = default_dir / f"qr_{token.replace('-', '')}.png"
            png_path.write_bytes(png)
            self.qr_status.setText(
                f"Report: {html_path}\nToken: {token} (randomized, no PII)\nQR image: {png_path}")
            self.qr_preview.setText(
                f"QR payload: {token}\n(scan resolves locally to the full report; the token "
                f"expires and contains no identifying information.)")
        except QRError as exc:
            self.qr_status.setText(f"QR generation failed: {exc}")

    def _validate_dataset(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select candidate dataset CSV", "", "CSV (*.csv)")
        if not path:
            return
        try:
            import csv
            with open(path, newline="", encoding="utf-8") as fh:
                records = list(csv.DictReader(fh))
            ds = UltrasoundDataset(records)
            problems = ds.validate_schema()
            if problems:
                self.dataset_check.setText("Schema violations:\n" + "\n".join("• " + p for p in problems))
            else:
                split = ds.patient_split()
                self.dataset_check.setText(
                    f"Schema OK — {split.get('patients', 0)} patients. Patient-level split ready "
                    f"(train {len(split.get('train_patients', []))}, val "
                    f"{len(split.get('val_patients', []))}, test "
                    f"{len(split.get('test_patients', []))}). No model is trained without this "
                    f"dataset being present and its labels verified.")
        except Exception as exc:
            self.dataset_check.setText(f"Could not read CSV: {exc}")

    def set_current(self, profile=None, risk=None, change=None, fingerprint=None):
        """Called from the main window with the live context for fusion builds."""
        self._profile = profile
        self._current_risk = risk
        self._current_change = change
        self._current_fingerprint = fingerprint

    def refresh(self):
        self._refresh_compare()

    # ------------------------------------------- V8.2 Model Lab integration
    def _refresh_active_model_label(self):
        try:
            bundle = self.cv_model_provider()
        except Exception:
            bundle = None
        if bundle:
            self.active_model_label.setText(
                f"Active CV model: {bundle.get('version')} — APPROVED RESEARCH MODEL "
                "(not clinically validated). Research/clinical decision-support output, "
                "not a diagnosis.")
        else:
            self.active_model_label.setText(
                "Active CV model: none deployed — image-derived anatomical features remain "
                "UNKNOWN until a model is trained and approved in Research → Model Lab.")

    def _approved_model_output(self, image_path: str) -> str:
        """Run the APPROVED Model Lab model on a quality-passed image (if any)."""
        self._refresh_active_model_label()
        try:
            bundle = self.cv_model_provider()
        except Exception:
            bundle = None
        if not bundle:
            return ""
        try:
            import numpy as np

            from src.modellab.trainer import load_image_array

            cfg = bundle.get("config") or {}
            size = int(cfg.get("image_size", 32))
            arr = load_image_array(Path(image_path), size)
            if arr is None:
                return ""
            X = ((arr.reshape(1, -1) - 0.5) / 0.25).astype("float32")
            model = bundle["model"]
            classes = bundle.get("classes") or []
            if hasattr(model, "predict_proba"):
                p1 = float(model.predict_proba(X)[0, 1])
            else:
                from scipy.special import expit

                p1 = float(expit(model.decision_function(X))[0])
            pos = classes[1] if len(classes) > 1 else "class 1"
            return (
                "MODEL-INFERRED (research decision support — NOT a diagnosis):\n"
                f"  Model: {bundle.get('version')} (APPROVED RESEARCH MODEL, not clinically validated)\n"
                f"  P({pos}-pattern) = {p1:.2f}  ·  classes: {classes}\n"
                "  This score is an image-pattern estimate for the multimodal engine. "
                "Clinical interpretation of the ultrasound remains with the clinician.")
        except Exception as exc:
            return f"MODEL-INFERRED output unavailable ({type(exc).__name__})."
