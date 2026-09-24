"""Research Lab: model performance dashboard on synthetic data."""
from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.models.research import evaluate_synthetic
from src.ui.theme import style_plot
from src.utils.history_store import HistoryStore
from src.utils.synthetic import PATIENTS, generate_week


class ResearchWidget(QWidget):
    def __init__(self, db: HistoryStore, parent=None):
        super().__init__(parent)
        self.db = db

        outer = QHBoxLayout(self)

        left = QVBoxLayout()
        gen_box = QGroupBox("Synthetic experiment setup")
        gb = QGridLayout(gen_box)
        gb.addWidget(QLabel("Patient profile"), 0, 0)
        self.patient_combo = QComboBox()
        for pid, name in PATIENTS.items():
            self.patient_combo.addItem(name, pid)
        gb.addWidget(self.patient_combo, 0, 1)
        gb.addWidget(QLabel("Days"), 0, 2)
        self.days_spin = QSpinBox()
        self.days_spin.setRange(3, 30)
        self.days_spin.setValue(7)
        gb.addWidget(self.days_spin, 0, 3)
        gen_btn = QPushButton("Generate synthetic week")
        gen_btn.clicked.connect(self._generate)
        gb.addWidget(gen_btn, 0, 4)
        eval_btn = QPushButton("Evaluate model (confusion matrix + ablation)")
        eval_btn.clicked.connect(self.refresh)
        gb.addWidget(eval_btn, 1, 0, 1, 5)
        left.addWidget(gen_box)

        perf_box = QGroupBox("Model performance (vs synthetic labels)")
        pb = QGridLayout(perf_box)
        self.metric_labels: dict[str, QLabel] = {}
        for i, (key, name) in enumerate([
            ("n", "Labeled rows"), ("acc", "Accuracy"), ("prec", "Precision"),
            ("rec", "Recall"), ("fpr", "False-positive rate"), ("fnr", "False-negative rate"),
        ]):
            pb.addWidget(QLabel(name), i // 2, (i % 2) * 2)
            lab = QLabel("--")
            self.metric_labels[key] = lab
            pb.addWidget(lab, i // 2, (i % 2) * 2 + 1)
        self.cm_label = QLabel("Confusion matrix: --")
        pb.addWidget(self.cm_label, 3, 0, 1, 4)
        left.addWidget(perf_box)

        notes_box = QGroupBox("Protocol notes")
        self.notes_text = QTextEdit()
        self.notes_text.setReadOnly(True)
        nb = QVBoxLayout(notes_box)
        nb.addWidget(self.notes_text)
        left.addWidget(notes_box, 1)
        outer.addLayout(left, 1)

        right = QVBoxLayout()
        abl_box = QGroupBox("Ablation study (risk contribution per domain)")
        ab = QVBoxLayout(abl_box)
        self.ablation_plot = pg.PlotWidget()
        style_plot(self.ablation_plot, y_label="risk points contributed")
        self.ablation_bar = pg.BarGraphItem(x=[], height=[], width=0.6,
                                            brushes=["#7b8cff"], pen=pg.mkPen("#0d1626"))
        self.ablation_plot.addItem(self.ablation_bar)
        ab.addWidget(self.ablation_plot)
        right.addWidget(abl_box, 1)
        outer.addLayout(right, 1)

    def _generate(self):
        patient = self.patient_combo.currentData()
        days = self.days_spin.value()
        sid, n = generate_week(self.db, days=days, patient=patient,
                               participant=f"synth-{patient}")
        self.notes_text.setPlainText(
            f"Generated {n} synthetic feature rows for patient profile "
            f"'{PATIENTS[patient]}' (session #{sid}). Data is clearly marked "
            "synthetic in the database; do not present it as a real participant."
        )

    def refresh(self):
        report = evaluate_synthetic(self.db, days=self.days_spin.value())
        m = report.metrics
        self.metric_labels["n"].setText(str(report.n_labeled))
        self.metric_labels["acc"].setText(f"{m.accuracy * 100:.1f}%" if report.n_labeled else "--")
        self.metric_labels["prec"].setText(f"{m.precision * 100:.1f}%")
        self.metric_labels["rec"].setText(f"{m.recall * 100:.1f}%")
        self.metric_labels["fpr"].setText(f"{m.false_positive_rate * 100:.1f}%")
        self.metric_labels["fnr"].setText(f"{m.false_negative_rate * 100:.1f}%")
        self.cm_label.setText(
            f"Confusion matrix  TP={m.tp} FP={m.fp}  FN={m.fn} TN={m.tn}"
        )
        self.notes_text.setPlainText("\n".join(report.notes))

        if report.ablation:
            names = [a[1] for a in report.ablation[:8]]
            contribs = [a[3] for a in report.ablation[:8]]
            self.ablation_bar.setOpts(x=list(range(len(names))), height=contribs, width=0.6)
            self.ablation_plot.getAxis("bottom").setTicks(
                [[(i, n) for i, n in enumerate(names)]]
            )
        else:
            self.ablation_bar.setOpts(x=[], height=[], width=0.6)
