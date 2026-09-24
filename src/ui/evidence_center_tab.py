"""Evidence Center tab (V5, item S).

A read-only dashboard of the project's scientific-evidence state:
  * model status table with explicit TRAINED / NOT TRAINED / FALLBACK /
    NOT YET TRAINED states (never mislabeled as ML when it is a fallback),
  * evidence progress bars computed from real artifacts, audits, reference
    pairs and prospective outcomes (never hard-coded),
  * dataset registry with provenance,
  * training audit history,
  * cyst research module status (NOT YET TRAINED),
  * the permanent claim guard.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.models.cyst_event import CYST_MODEL_REASON, CYST_MODEL_STATUS
from src.models.dataset_manager import check_cross_dataset_subject_overlap, dataset_registry_summary
from src.models.model_status import evidence_progress, compute_model_statuses
from src.models.training_audit import audit_summary
from src.ui.theme import GREEN, ORANGE, RED, TEXT_MUTED, YELLOW
from src.validation.report import CLAIM_GUARD
from src.validation.store import ValidationStore

STATUS_COLORS = {
    "TRAINED": GREEN,
    "NOT TRAINED": ORANGE,
    "FALLBACK": YELLOW,
    "NOT YET TRAINED": RED,
}


class EvidenceCenterTab(QWidget):
    def __init__(self, vstore: ValidationStore, parent=None):
        super().__init__(parent)
        self.vstore = vstore

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        content.setObjectName("OverviewScrollContent")
        root = QVBoxLayout(content)
        root.setContentsMargins(2, 2, 2, 2)
        root.setSpacing(10)

        refresh_row = QHBoxLayout()
        title = QLabel("Evidence Center — every claim below is backed by an artifact, audit, or store row. "
                       "If evidence does not exist, the display says NOT YET VALIDATED.")
        title.setWordWrap(True)
        title.setObjectName("SmallMuted")
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)
        refresh_row.addWidget(title, 1)
        refresh_row.addWidget(refresh)
        root.addLayout(refresh_row)

        self.status_table = QTableWidget(0, 5)
        self.status_table.setHorizontalHeaderLabels(["Model", "Status", "Dataset", "Evidence / metrics", "Reason"])
        self.status_table.horizontalHeader().setStretchLastSection(True)
        self.status_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.status_table.setWordWrap(False)
        root.addWidget(self._boxed("Model status", self.status_table))

        self.progress_labels: dict = {}
        root.addWidget(self._build_progress_box())

        self.dataset_text = QTextEdit()
        self.dataset_text.setReadOnly(True)
        self.dataset_text.setMinimumHeight(150)
        root.addWidget(self._boxed("Dataset registry (provenance)", self.dataset_text))

        self.audit_text = QTextEdit()
        self.audit_text.setReadOnly(True)
        self.audit_text.setMinimumHeight(120)
        root.addWidget(self._boxed("Training audit history", self.audit_text))

        self.cyst_text = QTextEdit()
        self.cyst_text.setReadOnly(True)
        self.cyst_text.setMinimumHeight(110)
        root.addWidget(self._boxed("Ovarian complication research module (O + P)", self.cyst_text))

        guard_lines = "\n".join(f"• {c}" for c in CLAIM_GUARD)
        self.guard_text = QTextEdit()
        self.guard_text.setReadOnly(True)
        self.guard_text.setPlainText("Scientific claim guard (R) — automatically enforced wording:\n" + guard_lines)
        self.guard_text.setMinimumHeight(140)
        root.addWidget(self._boxed("Claim guard", self.guard_text))

        scroll.setWidget(content)
        outer.addWidget(scroll)
        self.refresh()

    def _boxed(self, title: str, widget: QWidget) -> QGroupBox:
        box = QGroupBox(title)
        lay = QVBoxLayout(box)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.addWidget(widget)
        return box

    def _build_progress_box(self) -> QGroupBox:
        box = QGroupBox("Evidence progress (computed from actual evidence — never hard-coded)")
        lay = QVBoxLayout(box)
        self.progress_bars: dict = {}
        self.progress_labels = {}
        for name, label in [
            ("sensor_validation", "Sensor validation (reference-device pairs)"),
            ("model_validation", "Model validation (trained ML artifacts with audits)"),
            ("prospective_validation", "Prospective validation (pre-outcome predictions labelled later)"),
            ("clinical_validation", "Clinical validation"),
        ]:
            row = QHBoxLayout()
            lbl = QLabel(label)
            lbl.setFixedWidth(280)
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setTextVisible(True)
            detail = QLabel("")
            detail.setWordWrap(True)
            detail.setObjectName("SmallMuted")
            self.progress_bars[name] = bar
            self.progress_labels[name] = detail
            row.addWidget(lbl)
            row.addWidget(bar, 1)
            row.addWidget(detail, 2)
            lay.addLayout(row)
        return box

    def refresh(self):
        # --- model status table
        statuses = compute_model_statuses(self.vstore)
        self.status_table.setRowCount(len(statuses))
        for r, s in enumerate(statuses):
            name_item = QTableWidgetItem(f"{s.name}  ({s.kind})")
            status_item = QTableWidgetItem(s.status)
            color = STATUS_COLORS.get(s.status, TEXT_MUTED)
            status_item.setForeground(QColor(color))
            status_item.setBackground(Qt.GlobalColor.transparent)
            dataset_item = QTableWidgetItem(s.dataset_id or "—")
            if s.audit and s.audit.get("metrics"):
                m = s.audit["metrics"]
                metrics = ", ".join(f"{k}={v}" for k, v in m.items())
            else:
                metrics = "—"
            metrics_item = QTableWidgetItem(metrics)
            reason_item = QTableWidgetItem(s.reason)
            for col, item in [(0, name_item), (1, status_item), (2, dataset_item), (3, metrics_item), (4, reason_item)]:
                self.status_table.setItem(r, col, item)
        self.status_table.resizeColumnsToContents()
        self.status_table.setColumnWidth(4, 420)

        # --- evidence progress
        prog = evidence_progress(self.vstore)
        for name, data in prog.items():
            bar = self.progress_bars.get(name)
            if bar is not None:
                bar.setValue(int(round(data["fraction"] * 100)))
                if name == "clinical_validation":
                    bar.setStyleSheet(f"QProgressBar::chunk {{ background: {RED}; }}")
            detail = self.progress_labels.get(name)
            if detail is not None:
                pct = int(round(data["fraction"] * 100))
                detail.setText(f"{pct}% — {data['detail']}")

        # --- dataset registry
        self.dataset_text.setPlainText(dataset_registry_summary())
        overlap = check_cross_dataset_subject_overlap()
        if overlap:
            extra = "\n\nCross-dataset subject-overlap audit:\n" + "\n".join(
                f"  {o['dataset_a']} ∩ {o['dataset_b']}: {o['overlap_subjects']} shared subject id(s) — {o['note']}"
                for o in overlap)
            self.dataset_text.append(extra)

        # --- audit history
        self.audit_text.setPlainText(audit_summary())

        # --- cyst module
        self.cyst_text.setPlainText(
            f"Cyst rupture model status: {CYST_MODEL_STATUS}\n"
            f"Reason: {CYST_MODEL_REASON}\n\n"
            "Research monitor (O): tracks deviation of HR / HRV / BP / GSR / temperature / SpO₂ / "
            "activity / movement / symptoms from the person's own baseline, computes rolling stats, "
            "multimodal anomaly scores and change points, and reports only "
            "'Physiological trajectory abnormality detected' — never a rupture prediction.\n"
            "Data structure (P): longitudinal cyst-event schema (subject_id, timestamps, sensors, "
            "pain score, symptoms, menstrual cycle day, clinical event, clinical outcome) is defined "
            "in src/models/cyst_event.py and ready for future clinical data."
        )
