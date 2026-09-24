"""Validation Lab tab: the scientific-validation modules behind the dashboard.

Sections: reference-device agreement (with Bland-Altman plot), signal quality
+ decision layer, repeatability (ICC/CV), leave-one-subject-out CV, calibration
(Brier/ECE + reliability curve), ablation, leakage detection, prospective
validation, uncertainty/dataset statistics, automated report and the permanent
limitations / claim guard.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Callable, List, Optional, Tuple

import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.data_models import FeatureVector, RiskResult, SensorSample
from src.models.registry import APP_VERSION
from src.utils.history_store import HistoryStore
from src.validation.agreement import agreement
from src.validation.calibration import calibration
from src.validation.leakage import run_leakage_checks
from src.validation.losocv import leave_one_subject_out
from src.validation.prospective import ProspectiveValidator
from src.validation.repeatability import repeatability
from src.validation.report import CLAIM_GUARD, validation_report_text
from src.validation.sqi import Decision, overall_sqi, per_sensor_sqi, should_withhold
from src.validation.store import ValidationStore
from src.ui.theme import ACCENT, BORDER_LIGHT, GREEN, ORANGE, RED, TEXT_MUTED, YELLOW, style_plot

METRICS = ["HR (bpm)", "SpO2 (%)", "Skin temp (°C)", "RMSSD (ms)", "GSR (raw)", "Stress index"]
METRIC_COLS = {
    "HR (bpm)": "hr", "SpO2 (%)": "spo2", "Skin temp (°C)": "skin_temp",
    "RMSSD (ms)": "rmssd", "GSR (raw)": "gsr", "Stress index": "stress",
}


class OutcomeDialog(QDialog):
    """Pick a pending prospective prediction and label its outcome (0/1)."""

    def __init__(self, pending: List[dict], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Set outcome for a stored prediction")
        self.resize(520, 150)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.pred_combo = QComboBox()
        for p in pending:
            self.pred_combo.addItem(
                f"#{p['id']}  {time.strftime('%H:%M', time.localtime(p['ts']))}  risk {p['risk']:.1f}%  "
                f"(conf {p['confidence']:.0f}%)" if p.get("confidence") is not None
                else f"#{p['id']}  risk {p['risk']:.1f}%", p["id"])
        self.outcome_combo = QComboBox()
        self.outcome_combo.addItem("0 — no elevated risk", 0)
        self.outcome_combo.addItem("1 — elevated risk", 1)
        form.addRow("Prediction", self.pred_combo)
        form.addRow("Outcome", self.outcome_combo)
        layout.addLayout(form)
        row = QHBoxLayout()
        ok = QPushButton("Save outcome")
        ok.clicked.connect(self.accept)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        row.addStretch(1)
        row.addWidget(ok)
        row.addWidget(cancel)
        layout.addLayout(row)

    def values(self) -> Tuple[int, int]:
        return self.pred_combo.currentData(), self.outcome_combo.currentData()


class ValidationTab(QWidget):
    def __init__(self, db: HistoryStore, vstore: ValidationStore,
                 live_provider: Optional[Callable[[], Tuple[Optional[FeatureVector], Optional[RiskResult], Optional[SensorSample]]]] = None,
                 parent=None):
        super().__init__(parent)
        self.db = db
        self.vstore = vstore
        self.live_provider = live_provider
        self.prospective = ProspectiveValidator(vstore)
        self.last_fv: Optional[FeatureVector] = None
        self.last_result: Optional[RiskResult] = None
        self.last_sample: Optional[SensorSample] = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        content.setObjectName("OverviewScrollContent")
        root = QGridLayout(content)
        root.setContentsMargins(2, 2, 2, 2)
        root.setSpacing(8)
        root.setColumnStretch(0, 1)
        root.setColumnStretch(1, 1)

        root.addWidget(self._build_agreement_box(), 0, 0)
        root.addWidget(self._build_sqi_box(), 0, 1)
        root.addWidget(self._build_repeatability_box(), 1, 0)
        root.addWidget(self._build_loso_box(), 1, 1)
        root.addWidget(self._build_calibration_box(), 2, 0)
        root.addWidget(self._build_ablation_box(), 2, 1)
        root.addWidget(self._build_leakage_box(), 3, 0)
        root.addWidget(self._build_prospective_box(), 3, 1)
        root.addWidget(self._build_stats_box(), 4, 0, 1, 2)
        root.addWidget(self._build_report_box(), 5, 0, 1, 2)

        scroll.setWidget(content)
        outer.addWidget(scroll)

    # ------------------------------------------------------------------ boxes
    def _box(self, title: str) -> Tuple[QGroupBox, QVBoxLayout]:
        box = QGroupBox(title)
        lay = QVBoxLayout(box)
        lay.setSpacing(6)
        return box, lay

    # -------------------------------------------------- 1. reference agreement
    def _build_agreement_box(self):
        box, lay = self._box("1. Reference-device validation")
        row = QHBoxLayout()
        self.ag_metric = QComboBox()
        self.ag_metric.addItems(METRICS)
        self.ag_sensor = QDoubleSpinBox(); self.ag_sensor.setRange(0, 500); self.ag_sensor.setDecimals(1)
        self.ag_ref = QDoubleSpinBox(); self.ag_ref.setRange(0, 500); self.ag_ref.setDecimals(1)
        self.ag_subject = QLineEdit(); self.ag_subject.setPlaceholderText("subject")
        self.ag_cond = QLineEdit(); self.ag_cond.setPlaceholderText("condition")
        add_btn = QPushButton("Add pair")
        add_btn.clicked.connect(self._add_pair)
        row.addWidget(QLabel("Metric")); row.addWidget(self.ag_metric)
        row.addWidget(QLabel("Sensor")); row.addWidget(self.ag_sensor)
        row.addWidget(QLabel("Ref")); row.addWidget(self.ag_ref)
        row.addWidget(self.ag_subject)
        row.addWidget(self.ag_cond)
        row.addWidget(add_btn)
        lay.addLayout(row)

        self.ag_table = QTableWidget(0, 4)
        self.ag_table.setHorizontalHeaderLabels(["Metric", "Sensor", "Reference", "Condition"])
        self.ag_table.setMaximumHeight(120)
        lay.addWidget(self.ag_table)

        btn_row = QHBoxLayout()
        self.ag_compute = QPushButton("Compute agreement")
        self.ag_compute.clicked.connect(self._compute_agreement)
        clear_btn = QPushButton("Clear pairs")
        clear_btn.clicked.connect(self._clear_pairs)
        btn_row.addWidget(self.ag_compute)
        btn_row.addWidget(clear_btn)
        lay.addLayout(btn_row)

        self.ag_label = QLabel("No paired measurements recorded yet.")
        self.ag_label.setWordWrap(True)
        self.ag_label.setObjectName("SmallMuted")
        lay.addWidget(self.ag_label)

        self.ba_plot = pg.PlotWidget()
        style_plot(self.ba_plot, y_label="sensor − reference", x_label="mean of pair")
        self.ba_plot.setMaximumHeight(150)
        lay.addWidget(self.ba_plot)
        return box

    def _add_pair(self):
        metric = self.ag_metric.currentText()
        self.vstore.add_reference_pair(
            metric=metric,
            sensor_value=float(self.ag_sensor.value()),
            reference_value=float(self.ag_ref.value()),
            subject_id=self.ag_subject.text().strip(),
            condition=self.ag_cond.text().strip(),
        )
        self._refresh_pairs_table()
        self.ag_label.setText("Pair added — press 'Compute agreement' to update the stats.")

    def _refresh_pairs_table(self):
        pairs = self.vstore.reference_pairs(limit=8)
        self.ag_table.setRowCount(len(pairs))
        for r, p in enumerate(pairs):
            for c, val in enumerate([p["metric"], f"{p['sensor_value']:.1f}", f"{p['reference_value']:.1f}", p["condition"] or ""]):
                self.ag_table.setItem(r, c, QTableWidgetItem(str(val)))
        self.ag_table.resizeColumnsToContents()

    def _clear_pairs(self):
        self.vstore.clear_reference_pairs()
        self._refresh_pairs_table()
        self.ag_label.setText("Reference pairs cleared.")
        self.ba_plot.clear()

    def _compute_agreement(self):
        pairs = self.vstore.reference_pairs()
        if not pairs:
            self.ag_label.setText("No paired measurements recorded yet.")
            return
        by_metric: dict = {}
        for p in pairs:
            by_metric.setdefault(p["metric"], []).append((p["sensor_value"], p["reference_value"]))
        lines = []
        self.ba_plot.clear()
        colors = {0: "#3aa7f0", 1: "#f472b6", 2: "#34d399", 3: "#fbbf24", 4: "#a78bfa", 5: "#fb923c"}
        for i, (metric, pts) in enumerate(by_metric.items()):
            res = agreement(pts)
            lines.append(f"{metric}: {res.summary()}")
            # Bland-Altman: mean vs difference.
            color = colors[i % len(colors)]
            scatter = pg.ScatterPlotItem(
                x=[pt[0] for pt in res.points], y=[pt[1] for pt in res.points],
                size=7, brush=pg.mkBrush(color), pen=pg.mkPen("#0d1626"))
            self.ba_plot.addItem(scatter)
            for y, pen in [(res.bias, pg.mkPen(color, width=1.5)),
                           (res.loa_low, pg.mkPen(BORDER_LIGHT, style=Qt.PenStyle.DashLine)),
                           (res.loa_high, pg.mkPen(BORDER_LIGHT, style=Qt.PenStyle.DashLine))]:
                line = pg.InfiniteLine(pos=y, angle=0, pen=pen)
                self.ba_plot.addItem(line)
        self.ag_label.setText("\n".join(lines))

    # ------------------------------------------------------ 2. SQI + decision
    def _build_sqi_box(self):
        box, lay = self._box("2. Signal quality + decision layer")
        self.sqi_label = QLabel("No live data yet — SQI will appear here.")
        self.sqi_label.setWordWrap(True)
        self.sqi_label.setObjectName("SmallMuted")
        lay.addWidget(self.sqi_label)
        self.decision_label = QLabel("")
        self.decision_label.setWordWrap(True)
        lay.addWidget(self.decision_label)
        note = QLabel("Predictions are withheld when SQI, confidence or data sufficiency are too low — "
                      "the gauge then shows 'Insufficient data for reliable estimation'.")
        note.setWordWrap(True)
        note.setObjectName("SmallMuted")
        lay.addWidget(note)
        return box

    def update_live(self, fv: Optional[FeatureVector], result: Optional[RiskResult],
                    sample: Optional[SensorSample]):
        self.last_fv = fv
        self.last_result = result
        self.last_sample = sample
        if fv is None:
            return
        sensors = per_sensor_sqi(sample, fv)
        overall = overall_sqi(sensors)
        lines = [f"{s.name}: {s.score * 100:.0f}% ({s.grade})" + (f" — {', '.join(s.issues)}" if s.issues else "")
                 for s in sensors]
        lines.append(f"OVERALL SQI: {overall * 100:.0f}%")
        self.sqi_label.setText("\n".join(lines))
        dec: Decision = should_withhold(fv, result)
        if dec.ok:
            self.decision_label.setText(
                f"DECISION: OK — risk may be shown. (confidence "
                f"{result.confidence:.0f}%, CI {result.ci_low:.0f}–{result.ci_high:.0f}%)"
                if result is not None else "DECISION: OK")
            self.decision_label.setStyleSheet(f"color: {GREEN}; font-weight: bold;")
        else:
            self.decision_label.setText("DECISION: WITHHOLD — " + "; ".join(dec.reasons))
            self.decision_label.setStyleSheet(f"color: {YELLOW}; font-weight: bold;")

    # ------------------------------------------------------ 3. repeatability
    def _build_repeatability_box(self):
        box, lay = self._box("4. Repeatability (same subject, same conditions)")
        row = QHBoxLayout()
        self.rep_metric = QComboBox()
        self.rep_metric.addItems(METRICS)
        compute = QPushButton("Compute")
        compute.clicked.connect(self._compute_repeatability)
        row.addWidget(QLabel("Metric")); row.addWidget(self.rep_metric); row.addWidget(compute)
        lay.addLayout(row)
        self.rep_label = QLabel("Repeated measurements are derived from session history: each session = "
                                "one measurement, grouped by subject.")
        self.rep_label.setWordWrap(True)
        self.rep_label.setObjectName("SmallMuted")
        lay.addWidget(self.rep_label)
        return box

    def _repeatability_data(self, col: str):
        import sqlite3

        conn = sqlite3.connect(str(self.db.path))
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                f"SELECT f.session_id, COALESCE(NULLIF(TRIM(s.participant_id), ''), 'session#'||f.session_id) AS subj, "
                f"f.{col} AS v FROM features f LEFT JOIN sessions s ON s.id=f.session_id "
                f"WHERE f.{col} IS NOT NULL ORDER BY f.session_id, f.ts"
            ).fetchall()
        finally:
            conn.close()
        per_subject: dict = {}
        per_session: dict = {}
        for r in rows:
            per_session.setdefault(r["session_id"], {"subj": r["subj"], "vals": []})
            per_session[r["session_id"]]["vals"].append(r["v"])
        for sess in per_session.values():
            vals = [v for v in sess["vals"] if v == v]
            if not vals:
                continue
            per_subject.setdefault(sess["subj"], []).append(float(sum(vals) / len(vals)))
        return per_subject

    def _compute_repeatability(self):
        col = METRIC_COLS[self.rep_metric.currentText()]
        measures = self._repeatability_data(col)
        if not measures:
            self.rep_label.setText("No session history for this metric yet. Run sessions (or load a demo week) first.")
            return
        res = repeatability(measures)
        extra = ""
        if res.within_session_cv_pct is not None or res.between_session_cv_pct is not None:
            extra = (f"\nWithin-session CV {res.within_session_cv_pct:.1f}% · "
                     f"between-session CV {res.between_session_cv_pct:.1f}%") if res.within_session_cv_pct is not None else ""
        self.rep_label.setText(res.summary() + extra + ("\n" + "; ".join(res.notes) if res.notes else ""))

    # ------------------------------------------------------------ 4. LOSO CV
    def _build_loso_box(self):
        box, lay = self._box("5. Leave-one-subject-out CV")
        row = QHBoxLayout()
        run = QPushButton("Run LOSO (labelled rows)")
        run.clicked.connect(self._run_loso)
        row.addWidget(run)
        lay.addLayout(row)
        self.loso_label = QLabel("Runs subject-level evaluation of the frozen risk engine on labelled rows "
                                 "(synthetic labels, or prospective outcomes).")
        self.loso_label.setWordWrap(True)
        self.loso_label.setObjectName("SmallMuted")
        lay.addWidget(self.loso_label)
        return box

    def _run_loso(self):
        res = leave_one_subject_out(self.db)
        if res.folds:
            lines = [res.summary()]
            lines.append("Per-fold:")
            for f in res.folds:
                auc = f"{f.roc_auc:.2f}" if f.roc_auc is not None else "--"
                lines.append(f"  {f.subject}: n={f.n} acc={f.accuracy:.2f} prec={f.precision or 0:.2f} "
                             f"sens={f.recall or 0:.2f} spec={f.specificity or 0:.2f} F1={f.f1 or 0:.2f} AUC={auc}")
            self.loso_label.setText("\n".join(lines))
        else:
            self.loso_label.setText(res.notes[0] if res.notes else "No result.")

    # -------------------------------------------------------- 5. calibration
    def _build_calibration_box(self):
        box, lay = self._box("6. Calibration (Brier / ECE)")
        row = QHBoxLayout()
        run = QPushButton("Compute calibration")
        run.clicked.connect(self._compute_calibration)
        row.addWidget(run)
        lay.addLayout(row)
        self.cal_label = QLabel("Uses labelled predictions (synthetic labels + prospective outcomes).")
        self.cal_label.setWordWrap(True)
        self.cal_label.setObjectName("SmallMuted")
        lay.addWidget(self.cal_label)
        self.cal_plot = pg.PlotWidget()
        style_plot(self.cal_plot, y_label="observed frequency", x_label="predicted probability")
        self.cal_plot.setMaximumHeight(140)
        lay.addWidget(self.cal_plot)
        return box

    def _labelled_pairs(self) -> Tuple[List[float], List[int]]:
        import json
        import sqlite3

        probs: List[float] = []
        labels: List[int] = []
        conn = sqlite3.connect(str(self.db.path))
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT f.risk, f.extra_json FROM features f WHERE f.risk IS NOT NULL"
            ).fetchall()
            for r in rows:
                label = None
                if r["extra_json"]:
                    try:
                        label = json.loads(r["extra_json"]).get("label")
                    except Exception:
                        label = None
                if label is not None:
                    probs.append(float(r["risk"]) / 100.0)
                    labels.append(int(label))
        finally:
            conn.close()
        for p in self.vstore.predictions(with_outcome=True):
            probs.append(float(p["risk"]) / 100.0)
            labels.append(int(p["outcome"]))
        return probs, labels

    def _compute_calibration(self):
        probs, labels = self._labelled_pairs()
        if len(probs) < 2:
            self.cal_label.setText("Not enough labelled predictions (need >= 2). Generate a labelled synthetic "
                                   "week or record prospective outcomes.")
            return
        res = calibration(probs, labels)
        self.cal_label.setText(res.summary())
        self.cal_plot.clear()
        diag = pg.PlotDataItem([0, 1], [0, 1], pen=pg.mkPen(BORDER_LIGHT, style=Qt.PenStyle.DashLine))
        self.cal_plot.addItem(diag)
        xs = [b[0] for b in res.bins]
        ys = [b[1] for b in res.bins]
        self.cal_plot.plot(xs, ys, pen=pg.mkPen(GREEN, width=2), symbol="o", symbolSize=7,
                           symbolBrush=GREEN, symbolPen=pg.mkPen("#0d1626"))

    # ------------------------------------------------------------ 6. ablation
    def _build_ablation_box(self):
        box, lay = self._box("7. Ablation (sensor contribution)")
        row = QHBoxLayout()
        run = QPushButton("Run ablation on current risk")
        run.clicked.connect(self._run_ablation)
        row.addWidget(run)
        lay.addLayout(row)
        self.abl_label = QLabel("Recomputes the risk with each modality removed and isolated.")
        self.abl_label.setWordWrap(True)
        self.abl_label.setObjectName("SmallMuted")
        lay.addWidget(self.abl_label)
        self.abl_plot = pg.PlotWidget()
        style_plot(self.abl_plot, y_label="risk %", x_label="")
        self.abl_plot.setMaximumHeight(160)
        lay.addWidget(self.abl_plot)
        return box

    def _run_ablation(self):
        from src.validation.ablation import run_ablation

        if self.last_result is None:
            self.abl_label.setText("No live risk estimate yet — connect a stream first.")
            return
        rows = run_ablation(dict(self.last_result.domain_scores))
        self.abl_label.setText("\n".join(r.render() for r in rows[:9]))
        self.abl_plot.clear()
        names = [r.name[:24] for r in rows]
        risks = [r.risk for r in rows]
        brushes = [GREEN if r.delta <= 0 else ORANGE if r.delta < 5 else RED for r in rows]
        bar = pg.BarGraphItem(x=list(range(len(rows))), height=risks, width=0.6, brushes=brushes,
                              pen=pg.mkPen("#0d1626"))
        self.abl_plot.addItem(bar)
        self.abl_plot.getAxis("bottom").setTicks([[(i, n) for i, n in enumerate(names)]])
        self.abl_plot.getAxis("bottom").setStyle(tickFont=None)

    # ------------------------------------------------------ 7. leakage checks
    def _build_leakage_box(self):
        box, lay = self._box("8. Model/data-leakage checks")
        row = QHBoxLayout()
        run = QPushButton("Run checks")
        run.clicked.connect(self._run_leakage)
        row.addWidget(run)
        lay.addLayout(row)
        self.leak_label = QLabel("Heuristic checks: subject train/test overlap, duplicates, future rows, "
                                 "normalization timing, label-in-features.")
        self.leak_label.setWordWrap(True)
        self.leak_label.setObjectName("SmallMuted")
        lay.addWidget(self.leak_label)
        return box

    def _run_leakage(self):
        checks = run_leakage_checks(self.db)
        self.leak_label.setText("\n".join(c.render() for c in checks))

    # ----------------------------------------------------- 8. prospective mode
    def _build_prospective_box(self):
        box, lay = self._box("9. Prospective validation")
        row = QHBoxLayout()
        freeze = QPushButton("Freeze model")
        freeze.clicked.connect(self._freeze_model)
        record = QPushButton("Record prediction (pre-outcome)")
        record.clicked.connect(self._record_prediction)
        outcome = QPushButton("Set outcome…")
        outcome.clicked.connect(self._set_outcome)
        self.pros_subject = QLineEdit()
        self.pros_subject.setPlaceholderText("subject id")
        self.pros_subject.setMaximumWidth(110)
        row.addWidget(freeze); row.addWidget(record); row.addWidget(outcome)
        row.addWidget(self.pros_subject)
        lay.addLayout(row)
        self.pros_label = QLabel("1) Freeze the model 2) record predictions before outcomes 3) label outcomes later.")
        self.pros_label.setWordWrap(True)
        self.pros_label.setObjectName("SmallMuted")
        lay.addWidget(self.pros_label)
        return box

    def _freeze_model(self):
        snap = self.prospective.freeze()
        self.pros_label.setText(f"Model frozen: {snap.get('app_version')} with "
                                f"{len(snap.get('models', []))} registered models, "
                                f"{len(snap.get('feature_list', []))} features, "
                                f"{len(snap.get('risk_engine_weights', {}))} engine weights. "
                                "Now record predictions before outcomes.")
        self.pros_label.setStyleSheet(f"color: {GREEN}; font-weight: bold;")

    def _record_prediction(self):
        if self.last_result is None or self.last_fv is None:
            self.pros_label.setText("No live risk estimate yet — connect a stream first.")
            return
        from src.validation.sqi import overall_sqi, per_sensor_sqi

        sqi = overall_sqi(per_sensor_sqi(self.last_sample, self.last_fv))
        subj = self.pros_subject.text().strip()
        pid = self.prospective.record(subj, self.last_fv, self.last_result, sqi=sqi)
        self.pros_label.setText(f"Recorded prediction #{pid}: risk {self.last_result.risk_percent:.1f}% "
                                f"(model: {self.prospective.model_version()}). Enter the outcome later via 'Set outcome…'.")

    def _set_outcome(self):
        pending = self.prospective.pending()
        if not pending:
            self.pros_label.setText("No pending predictions to label — record some first.")
            return
        dlg = OutcomeDialog(pending, parent=self)
        if dlg.exec():
            pid, outcome = dlg.values()
            self.prospective.set_outcome(pid, outcome)
            self.pros_label.setText(self.prospective.summarize().summary())

    # ------------------------------------------------------------ stats + report
    def _build_stats_box(self):
        box, lay = self._box("10. Uncertainty + dataset statistics")
        row = QHBoxLayout()
        refresh = QPushButton("Refresh stats")
        refresh.clicked.connect(self._refresh_stats)
        row.addWidget(refresh)
        lay.addLayout(row)
        self.stats_label = QLabel("")
        self.stats_label.setWordWrap(True)
        self.stats_label.setObjectName("SmallMuted")
        lay.addWidget(self.stats_label)
        return box

    def _refresh_stats(self):
        counts = self.db.row_counts()
        sessions = self.db.session_compare(limit=1000)
        subjects = len({(s.get("participant_id") or f"session#{s['id']}") for s in sessions})
        synthetic = sum(1 for s in sessions if (s.get("source") or "").startswith(("demo", "synth")))
        lines = [
            f"Dataset: {counts.get('sessions', 0)} sessions ({len(sessions) - synthetic} real, {synthetic} synthetic) · "
            f"{counts.get('features', 0)} feature rows · {subjects} subjects · "
            f"{counts.get('calibrations', 0)} calibrations · {counts.get('anomalies', 0)} anomalies.",
        ]
        if self.last_result is not None:
            lines.append(f"Live uncertainty: risk {self.last_result.risk_percent:.1f}% · confidence "
                         f"{self.last_result.confidence:.0f}% · 90% CI width "
                         f"{max(0.0, self.last_result.ci_high - self.last_result.ci_low):.1f} pts.")
        pros = self.prospective.summarize()
        lines.append(pros.summary())
        self.stats_label.setText("\n".join(lines))

    def _build_report_box(self):
        box, lay = self._box("11. Automated validation report")
        row = QHBoxLayout()
        gen = QPushButton("Generate validation report…")
        gen.clicked.connect(self._generate_report)
        row.addWidget(gen)
        lay.addLayout(row)
        guard_lines = "\n".join(f"• {c}" for c in CLAIM_GUARD)
        guard = QLabel("Permanent limitations & claim guard:\n" + guard_lines)
        guard.setWordWrap(True)
        guard.setObjectName("WarningText")
        lay.addWidget(guard)
        return box

    def _generate_report(self):
        default = Path(__file__).resolve().parents[2] / "data" / "exports" / \
            f"validation_report_{time.strftime('%Y%m%d_%H%M%S')}.md"
        path, _ = QFileDialog.getSaveFileName(self, "Save validation report", str(default),
                                              "Markdown (*.md);;Text (*.txt)")
        if not path:
            return
        text = validation_report_text(
            self.db, self.vstore,
            agreement_by_metric=self._agreement_by_metric(),
            repeatability_result=self._compute_repeatability_result(),
            loso_result=leave_one_subject_out(self.db),
            calibration_result=self._calibration_result(),
            ablation_rows=None if self.last_result is None else self._ablation_rows(),
            leakage_checks=run_leakage_checks(self.db),
            prospective_summary=self.prospective.summarize(),
            uncertainty_text=self._uncertainty_text(),
        )
        Path(path).write_text(text, encoding="utf-8")
        self.vstore.log_report(path)
        self.pros_label.setText(f"Validation report saved to {path}")

    def _agreement_by_metric(self):
        pairs = self.vstore.reference_pairs()
        if not pairs:
            return {}
        by: dict = {}
        for p in pairs:
            by.setdefault(p["metric"], []).append((p["sensor_value"], p["reference_value"]))
        return {k: agreement(v) for k, v in by.items()}

    def _compute_repeatability_result(self):
        measures = self._repeatability_data(METRIC_COLS["HR (bpm)"])
        if not measures:
            return None
        return repeatability(measures)

    def _calibration_result(self):
        probs, labels = self._labelled_pairs()
        if len(probs) < 2:
            return None
        return calibration(probs, labels)

    def _ablation_rows(self):
        from src.validation.ablation import run_ablation

        if self.last_result is None:
            return None
        return run_ablation(dict(self.last_result.domain_scores))

    def _uncertainty_text(self):
        lines = []
        if self.last_result is not None:
            lines.append(f"Live: confidence {self.last_result.confidence:.0f}%, 90% CI "
                         f"{self.last_result.ci_low:.0f}–{self.last_result.ci_high:.0f}%, "
                         f"SQI {self.last_fv.signal_quality * 100:.0f}% (if fv present).")
        df = self.db.features_as_frame(days=365)
        if not df.empty:
            low_sqi = int((df["signal_quality"] < 0.5).sum())
            mean_risk = float(df["risk"].mean()) if df["risk"].notna().any() else float("nan")
            lines.append(f"Stored rows: {len(df)}, rows with SQI<0.5: {low_sqi}, mean logged risk: {mean_risk:.1f}%.")
        return " ".join(lines) or "No data."
