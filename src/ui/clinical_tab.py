"""CLINICAL DASHBOARD tab (V6.2) — clinician-facing longitudinal evidence.

Not a fancier patient dashboard: it is organized around the clinician's
questions — what changed since the last visit, report history with comparison,
clinically entered ultrasound findings, notes, and the care journey summary
with a strict OBSERVED / ASSOCIATED / UNKNOWN separation.

Every value shown here links back to the local offline store; nothing is
fabricated and nothing diagnoses PCOS.
"""
from __future__ import annotations

import time
from typing import Callable, Dict, List, Optional

from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.models.care_plan import CarePlanManager
from src.models.change_detector import ChangeReport
from src.models.clinical_record import ClinicalRecord
from src.models.what_changed import WhatChangedEngine
from src.ui import theme
from src.ui.theme import GREEN, ORANGE, RED, TEXT_MUTED, YELLOW
from src.utils.history_store import HistoryStore
from src.validation.longitudinal_experiment import LongitudinalExperiment


class ClinicalTab(QWidget):
    def __init__(self, store: HistoryStore, clinical: ClinicalRecord, care: CarePlanManager,
                 report_metrics_fn: Callable[[], Dict[str, Optional[float]]] | None = None,
                 parent=None):
        super().__init__(parent)
        self.store = store
        self.clinical = clinical
        self.care = care
        self.what_changed = WhatChangedEngine(store)
        self.report_metrics_fn = report_metrics_fn or (lambda: {})
        self._current_change: Optional[ChangeReport] = None
        self._current_risk: Optional[float] = None
        self._current_confidence: Optional[float] = None
        self._current_profile = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        inner = QTabWidget()
        inner.setDocumentMode(True)
        inner.addTab(self._build_what_changed(), "What Changed")
        inner.addTab(self._build_reports(), "Report History + Compare")
        inner.addTab(self._build_ultrasound_notes(), "Ultrasound + Notes")
        inner.addTab(self._build_research(), "Research: Model A-D")
        outer.addWidget(inner, 1)
        self.refresh()

    # ------------------------------------------------------- what changed
    def _build_what_changed(self) -> QWidget:
        tab = QWidget(); layout = QVBoxLayout(tab); layout.setSpacing(10)

        ov = QGroupBox("Patient overview (local record)")
        vb = QVBoxLayout(ov)
        self.ov_participant = QLabel("Participant: —")
        self.ov_period = QLabel("Monitoring period: —")
        self.ov_coverage = QLabel("Longitudinal coverage: — days")
        self.ov_quality = QLabel("Data quality: —")
        for w in [self.ov_participant, self.ov_period, self.ov_coverage, self.ov_quality]:
            w.setObjectName("BigValue")
            vb.addWidget(w)
        layout.addWidget(ov)

        wc = QGroupBox("WHAT CHANGED SINCE LAST VISIT? (evidence-linked)")
        wb = QVBoxLayout(wc)
        self.what_changed_text = QTextEdit()
        self.what_changed_text.setReadOnly(True)
        self.what_changed_text.setPlaceholderText(
            "Evidence-linked changes appear here. Every statement carries its source numbers; "
            "causality is never claimed (\"temporally associated with\").")
        wb.addWidget(self.what_changed_text)
        layout.addWidget(wc, 2)

        cj = QGroupBox("CARE JOURNEY SUMMARY — OBSERVED / ASSOCIATED / UNKNOWN")
        cb = QVBoxLayout(cj)
        self.care_journey_text = QTextEdit()
        self.care_journey_text.setReadOnly(True)
        cb.addWidget(self.care_journey_text)
        layout.addWidget(cj, 1)

        note = QLabel(
            "All statements are generated from the local, timestamped record. \"Associated\" means "
            "temporal co-occurrence only. The system cannot establish causation and cannot diagnose PCOS.")
        note.setWordWrap(True)
        note.setObjectName("SmallMuted")
        layout.addWidget(note)
        return tab

    # ------------------------------------------------------------- reports
    def _build_reports(self) -> QWidget:
        tab = QWidget(); layout = QVBoxLayout(tab); layout.setSpacing(10)
        row = QHBoxLayout()
        self.report_participant = QLineEdit(); self.report_participant.setPlaceholderText("Participant ID")
        save_btn = QPushButton("Save current report (periodic summary)")
        save_btn.clicked.connect(self._save_report)
        row.addWidget(self.report_participant, 1)
        row.addWidget(save_btn)
        layout.addLayout(row)

        hist = QGroupBox("REPORT HISTORY (open any previous assessment)")
        hb = QVBoxLayout(hist)
        self.report_table = QTableWidget(0, 4)
        self.report_table.setHorizontalHeaderLabels(["ID", "Date", "Kind", "Participant"])
        self.report_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.report_table.verticalHeader().setVisible(False)
        self.report_table.itemSelectionChanged.connect(self._on_report_selected)
        hb.addWidget(self.report_table)
        self.report_detail = QTextEdit()
        self.report_detail.setReadOnly(True)
        self.report_detail.setPlaceholderText("Select a report to view its full text.")
        hb.addWidget(self.report_detail, 1)
        layout.addWidget(hist, 3)

        cmp = QGroupBox("COMPARE REPORTS (e.g. month 1 vs month 3)")
        cb = QVBoxLayout(cmp)
        crow = QHBoxLayout()
        self.cmp_a = QComboBox()
        self.cmp_b = QComboBox()
        cmp_btn = QPushButton("Compare")
        cmp_btn.clicked.connect(self._compare)
        crow.addWidget(QLabel("Report A")); crow.addWidget(self.cmp_a, 1)
        crow.addWidget(QLabel("Report B")); crow.addWidget(self.cmp_b, 1)
        crow.addWidget(cmp_btn)
        cb.addLayout(crow)
        self.compare_text = QTextEdit()
        self.compare_text.setReadOnly(True)
        self.compare_text.setPlaceholderText("Comparison summary: improved / worsened / stable / uncertain.")
        cb.addWidget(self.compare_text)
        layout.addWidget(cmp, 2)

        qr = QGroupBox("QR REPORT ACCESS (de-identified, digital-first / print fallback)")
        qb = QVBoxLayout(qr)
        qrow = QHBoxLayout()
        self.qr_participant = QLineEdit()
        self.qr_participant.setPlaceholderText("De-identified participant ID")
        qr_btn = QPushButton("Generate full longitudinal report + QR token")
        qr_btn.clicked.connect(self._generate_qr_access)
        qrow.addWidget(self.qr_participant, 1)
        qrow.addWidget(qr_btn)
        qb.addLayout(qrow)
        self.qr_status = QLabel("No QR report generated yet.")
        self.qr_status.setWordWrap(True)
        self.qr_status.setObjectName("SmallMuted")
        qb.addWidget(self.qr_status)
        qr_note = QLabel(
            "The QR payload is a randomized record token (e.g. CP-9F3A2B7C) — no identifying "
            "information. Scanning it resolves locally to the full longitudinal report.")
        qr_note.setWordWrap(True)
        qr_note.setObjectName("SmallMuted")
        qb.addWidget(qr_note)
        layout.addWidget(qr, 1)
        return tab

    # --------------------------------------------------- ultrasound + notes
    def _build_ultrasound_notes(self) -> QWidget:
        tab = QWidget(); layout = QVBoxLayout(tab); layout.setSpacing(10)
        mid = QHBoxLayout()

        us = QGroupBox("Ultrasound findings (CLINICALLY ENTERED — the wearable cannot see the ovaries)")
        ub = QVBoxLayout(us)
        r1 = QHBoxLayout()
        self.us_size = QDoubleSpinBox(); self.us_size.setRange(0, 300); self.us_size.setSpecialValueText("none"); self.us_size.setSuffix(" mm")
        self.us_vol = QDoubleSpinBox(); self.us_vol.setRange(0, 1000); self.us_vol.setSpecialValueText("none"); self.us_vol.setSuffix(" cc")
        self.us_morph = QLineEdit(); self.us_morph.setPlaceholderText("Morphology, e.g. polycystic / simple cyst")
        r1.addWidget(QLabel("Cyst size")); r1.addWidget(self.us_size)
        r1.addWidget(QLabel("Volume")); r1.addWidget(self.us_vol)
        r1.addWidget(self.us_morph, 2)
        ub.addLayout(r1)
        r2 = QHBoxLayout()
        self.us_sept = QSpinBox(); self.us_sept.setRange(0, 5); self.us_sept.setSpecialValueText("none"); self.us_sept.setSuffix(" sept")
        self.us_solid = QSpinBox(); self.us_solid.setRange(0, 1); self.us_solid.setSpecialValueText("none")
        self.us_fluid = QSpinBox(); self.us_fluid.setRange(0, 1); self.us_fluid.setSpecialValueText("none")
        self.us_summary = QLineEdit(); self.us_summary.setPlaceholderText("Clinician summary / interpretation")
        r2.addWidget(QLabel("Septations")); r2.addWidget(self.us_sept)
        r2.addWidget(QLabel("Solid")); r2.addWidget(self.us_solid)
        r2.addWidget(QLabel("Free fluid")); r2.addWidget(self.us_fluid)
        ub.addLayout(r2)
        ub.addWidget(self.us_summary)
        add_us = QPushButton("Record ultrasound observation (clinical entry)")
        add_us.clicked.connect(self._add_ultrasound)
        ub.addWidget(add_us)
        self.us_table = QTableWidget(0, 4)
        self.us_table.setHorizontalHeaderLabels(["Date", "Cyst mm", "Volume cc", "Morphology"])
        self.us_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.us_table.verticalHeader().setVisible(False)
        ub.addWidget(self.us_table, 1)
        us_note = QLabel(
            "EXPERIMENTAL / RESEARCH ONLY: no rupture-prediction model exists and none is claimed. "
            "For concerning symptoms the guidance is always: seek appropriate medical evaluation.")
        us_note.setWordWrap(True)
        us_note.setStyleSheet(
            f"QLabel {{ color: {YELLOW}; border: 1px solid {YELLOW}; background: {theme.tint(YELLOW, 0.10)}; "
            f"font-size: 9.5pt; padding: 8px; border-radius: 6px; }}")
        ub.addWidget(us_note)
        mid.addWidget(us, 3)

        notes = QGroupBox("Clinician notes")
        nb = QVBoxLayout(notes)
        self.note_edit = QTextEdit()
        self.note_edit.setPlaceholderText("Clinician note / plan for this period")
        nb.addWidget(self.note_edit, 2)
        nr = QHBoxLayout()
        self.note_clinician = QLineEdit(); self.note_clinician.setPlaceholderText("Clinician name")
        add_note = QPushButton("Save note")
        add_note.clicked.connect(self._add_note)
        nr.addWidget(self.note_clinician, 1); nr.addWidget(add_note)
        nb.addLayout(nr)
        self.notes_table = QTableWidget(0, 3)
        self.notes_table.setHorizontalHeaderLabels(["Date", "Clinician", "Note"])
        self.notes_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.notes_table.verticalHeader().setVisible(False)
        nb.addWidget(self.notes_table, 1)
        mid.addWidget(notes, 2)
        layout.addLayout(mid, 1)
        return tab

    # -------------------------------------------------------------- research
    def _build_research(self) -> QWidget:
        tab = QWidget(); layout = QVBoxLayout(tab); layout.setSpacing(10)
        exp = QGroupBox("LONGITUDINAL-INFORMATION EXPERIMENT (MODEL A-D) — pending")
        eb = QVBoxLayout(exp)
        self.experiment_text = QTextEdit()
        self.experiment_text.setReadOnly(True)
        self.experiment_text.setPlainText(LongitudinalExperiment.report_table_text())
        eb.addWidget(self.experiment_text)
        layout.addWidget(exp, 3)
        note = QLabel(
            "This experiment directly tests the central research question. Results are reported "
            "only when a labelled longitudinal PCOS dataset (subject-level splitting, verified "
            "labels) exists. No performance numbers are fabricated.")
        note.setWordWrap(True)
        note.setObjectName("SmallMuted")
        layout.addWidget(note)
        return tab

    # ------------------------------------------------------------- actions
    def set_current(self, change: Optional[ChangeReport], risk: Optional[float],
                    confidence: Optional[float], profile=None,
                    participant: str = "anonymous", coverage_days: int = 0,
                    data_quality: float = 0.0, monitoring_days: float | None = None):
        self._current_change = change
        self._current_risk = risk
        self._current_confidence = confidence
        self._current_profile = profile

        self.ov_participant.setText(f"Participant: {participant}")
        if monitoring_days is not None:
            self.ov_period.setText(f"Monitoring period: {monitoring_days:.0f} days")
        else:
            self.ov_period.setText("Monitoring period: —")
        self.ov_coverage.setText(f"Longitudinal coverage: {coverage_days} days")
        self.ov_quality.setText(f"Data quality: {data_quality * 100.0:.0f}/100")

        adherence = self.care.adherence_summary(days=60)
        report = self.what_changed.compute(
            change=change, profile=profile, current=self._last_result(),
            previous_risk=self._previous_risk(), adherence=adherence)
        self.what_changed_text.setPlainText(
            report.markdown() if report else "No meaningful changes detected in the available window.")

        journey = self.care.care_gap_analysis(change_report=change)
        lines = ["OBSERVED (recorded facts):"]
        lines += ["  • " + s for s in (journey["observed"] or ["No gaps recorded in the review window."])]
        lines.append("")
        lines.append("ASSOCIATED (temporal co-occurrence only):")
        lines += ["  • " + s for s in journey["associated"]]
        lines.append("")
        lines.append("UNKNOWN (not established):")
        lines += ["  • " + s for s in journey["unknown"]]
        self.care_journey_text.setPlainText("\n".join(lines))

    def _last_result(self):
        # Kept simple: the what-changed engine needs a RiskResult for the model
        # item; main window passes it through set_current_result().
        return getattr(self, "_current_result", None)

    def set_current_result(self, result):
        self._current_result = result
        if self._current_risk is None and result is not None:
            self._current_risk = result.risk_percent
            self._current_confidence = result.confidence

    def _previous_risk(self) -> Optional[float]:
        evs = self.store.events(kind="recommendation_issued", limit=1)
        if evs:
            return self.store.risk_at_time(evs[0]["ts"])
        return None

    def _generate_qr_access(self):
        """Generate the full longitudinal HTML report + a QR token for it.

        The token is randomized and contains no PII; the report itself is
        de-identified. This is the low-infrastructure smartphone path.
        """
        try:
            from pathlib import Path
            from src.models.longitudinal_report import build_full_html_report
            from src.utils.qr_encoder import make_qr_code
        except Exception as exc:
            self.qr_status.setText(f"QR module unavailable: {exc}")
            return
        pid = self.qr_participant.text().strip() or "anonymous"
        df = self.store.features_as_frame(days=180, include_demo=False)
        change = None
        if not df.empty:
            from src.utils.replay import features_from_frame
            feats = features_from_frame(df)
            if feats:
                from src.models.change_detector import ChangeDetector
                change = ChangeDetector().evaluate(feats)
        risk = self.store.risk_at_time(time.time())
        html_text = build_full_html_report(self.store, participant=pid, change=change,
                                           current_risk=risk)
        out_dir = Path("data/exports")
        out_dir.mkdir(parents=True, exist_ok=True)
        html_path = out_dir / f"report_{pid}_{time.strftime('%Y%m%d_%H%M%S')}.html"
        html_path.write_text(html_text, encoding="utf-8")
        rid = self.clinical.save_report(
            "longitudinal", pid, "Full longitudinal report (HTML) for QR access.", {})
        token = self.store.create_report_token(report_id=rid,
                                               note=f"QR token for {pid}")
        try:
            png = make_qr_code(token, version=2, level="L").to_png_bytes(scale=8)
            png_path = out_dir / f"qr_{token.replace('-', '')}.png"
            png_path.write_bytes(png)
            self.qr_status.setText(
                f"Report: {html_path}\nToken: {token}\nQR image: {png_path}\n"
                "(token is randomized; no identifying information is encoded)")
        except Exception as exc:
            self.qr_status.setText(f"Report saved but QR failed ({exc}); token: {token}")

    def _save_report(self):
        metrics = self.report_metrics_fn()
        participant = self.report_participant.text().strip() or "anonymous"
        text = ("CHRONO-PCOS periodic report (research prototype — not clinically validated).\n"
                + "Metrics: " + ", ".join(f"{k}={v:.1f}" for k, v in metrics.items() if v is not None)
                + "\nParticipant: " + participant)
        rid = self.clinical.save_report("periodic", participant, text, metrics)
        self.store.log_event(None, "report_saved", f"report #{rid}")
        self.refresh_reports()

    def _compare(self):
        a_id = self.cmp_a.currentData()
        b_id = self.cmp_b.currentData()
        if not a_id or not b_id or a_id == b_id:
            self.compare_text.setPlainText("Select two different reports to compare.")
            return
        comp = self.clinical.compare_reports(a_id, b_id)
        self.compare_text.setPlainText(comp.summary_text() if comp else "Report(s) not found.")

    def _add_ultrasound(self):
        self.clinical.add_ultrasound(
            cyst_size_mm=self.us_size.value() or None,
            volume_cc=self.us_vol.value() or None,
            morphology=self.us_morph.text().strip(),
            septations=self.us_sept.value() or None,
            solid_components=self.us_solid.value() or None,
            free_fluid=self.us_fluid.value() or None,
            source="clinical",
            summary=self.us_summary.text().strip(),
        )
        self.us_size.setValue(0); self.us_vol.setValue(0)
        self.us_morph.clear(); self.us_summary.clear()
        self.refresh()

    def _add_note(self):
        note = self.note_edit.toPlainText().strip()
        if not note:
            return
        self.clinical.add_note(note, self.note_clinician.text().strip())
        self.note_edit.clear()
        self.refresh()

    # ------------------------------------------------------------- display
    def refresh(self):
        self.refresh_reports()
        self.refresh_ultrasound()
        self.refresh_notes()

    def refresh_reports(self):
        reports = self.clinical.reports()
        self.report_table.setRowCount(len(reports))
        self.cmp_a.clear(); self.cmp_b.clear()
        for r, rep in enumerate(reports):
            when = time.strftime("%Y-%m-%d %H:%M", time.localtime(rep["ts"]))
            cells = [str(rep["id"]), when, rep.get("kind", "periodic"), rep.get("participant", "")]
            for c, text in enumerate(cells):
                self.report_table.setItem(r, c, QTableWidgetItem(text))
            self.cmp_a.addItem(f"#{rep['id']} {when}", rep["id"])
            self.cmp_b.addItem(f"#{rep['id']} {when}", rep["id"])
        if reports:
            self.cmp_a.setCurrentIndex(0)
            self.cmp_b.setCurrentIndex(min(1, len(reports) - 1))
        self.report_table.resizeColumnsToContents()

    def _on_report_selected(self):
        row = self.report_table.currentRow()
        reports = self.clinical.reports()
        if 0 <= row < len(reports):
            self.report_detail.setPlainText(reports[row].get("text", ""))

    def refresh_ultrasound(self):
        us = self.clinical.ultrasound_history()
        self.us_table.setRowCount(len(us))
        for r, u in enumerate(us):
            when = time.strftime("%Y-%m-%d", time.localtime(u["ts"]))
            cells = [when,
                     f"{u['cyst_size_mm']:.1f}" if u.get("cyst_size_mm") else "—",
                     f"{u['volume_cc']:.1f}" if u.get("volume_cc") else "—",
                     u.get("morphology") or "—"]
            for c, text in enumerate(cells):
                self.us_table.setItem(r, c, QTableWidgetItem(text))
        self.us_table.resizeColumnsToContents()

    def refresh_notes(self):
        notes = self.clinical.notes()
        self.notes_table.setRowCount(len(notes))
        for r, n in enumerate(notes):
            when = time.strftime("%Y-%m-%d %H:%M", time.localtime(n["ts"]))
            for c, text in enumerate([when, n.get("clinician") or "—", n.get("note", "")]):
                self.notes_table.setItem(r, c, QTableWidgetItem(text))
        self.notes_table.resizeColumnsToContents()
