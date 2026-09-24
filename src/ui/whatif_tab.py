"""What-if Lab: counterfactual simulations and the sensor ablation laboratory."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSlider,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.config import UserProfile
from src.data_models import FeatureVector, RiskResult
from src.models.hormone_estimator import HormoneEstimator
from src.models.whatif import SCENARIOS, SimulationResult, WhatIfEngine
from src.ui.theme import progress_state_qss


class WhatIfWidget(QWidget):
    simulation_ran = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.engine = WhatIfEngine()
        self.hormones = HormoneEstimator()
        self.last_fv: FeatureVector | None = None
        self.last_profile: UserProfile | None = None
        self.last_result: RiskResult | None = None

        outer = QHBoxLayout(self)

        left = QVBoxLayout()
        controls = QGroupBox("Interventions (what-if)")
        cb = QVBoxLayout(controls)
        row = QHBoxLayout()
        row.addWidget(QLabel("Strength"))
        self.strength_slider = QSlider()
        self.strength_slider.setOrientation(Qt.Orientation.Horizontal)
        self.strength_slider.setRange(10, 100)
        self.strength_slider.setValue(70)
        self.strength_label = QLabel("70%")
        self.strength_slider.valueChanged.connect(lambda v: self.strength_label.setText(f"{v}%"))
        row.addWidget(self.strength_slider, 1)
        row.addWidget(self.strength_label)
        cb.addLayout(row)
        btn_row = QHBoxLayout()
        for key in SCENARIOS:
            b = QPushButton(SCENARIOS[key]["label"])
            b.clicked.connect(lambda _=False, k=key: self._run_single(k))
            btn_row.addWidget(b)
        cb.addLayout(btn_row)
        run_all = QPushButton("Run all simulations")
        run_all.clicked.connect(self._run_all)
        cb.addWidget(run_all)
        self.detail_label = QLabel("Select an intervention to see the simulated effect.")
        self.detail_label.setWordWrap(True)
        self.detail_label.setObjectName("SmallMuted")
        cb.addWidget(self.detail_label)
        left.addWidget(controls)

        table_box = QGroupBox("Simulation results")
        tb = QVBoxLayout(table_box)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Scenario", "Risk now %", "Simulated %", "Delta", "Main domains changed"])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        tb.addWidget(self.table)
        left.addWidget(table_box, 1)
        outer.addLayout(left, 3)

        right = QVBoxLayout()
        ablation_box = QGroupBox("What changed my risk? (ablation lab)")
        ab = QVBoxLayout(ablation_box)
        self.ablation_widgets: list[tuple[QLabel, QProgressBar]] = []
        for _ in range(6):
            label = QLabel("--")
            bar = QProgressBar()
            bar.setRange(0, 100)
            ab.addWidget(label)
            ab.addWidget(bar)
            self.ablation_widgets.append((label, bar))
        note = QLabel("Each bar = how many risk points that domain currently adds. "
                      "Zero it out and re-estimate the risk.")
        note.setWordWrap(True)
        note.setObjectName("SmallMuted")
        ab.addWidget(note)
        right.addWidget(ablation_box)
        outer.addLayout(right, 2)

    def set_current(self, fv: FeatureVector, profile: UserProfile, result: RiskResult):
        self.last_fv = fv
        self.last_profile = profile
        self.last_result = result
        self._run_all()

    def _strength(self) -> float:
        return self.strength_slider.value() / 100.0

    def _run_single(self, key: str):
        if self.last_fv is None or self.last_result is None or self.last_profile is None:
            return
        res = self.engine.simulate(self.last_fv, self.last_profile, self.last_result, key, self._strength())
        self.detail_label.setText(
            f"{res.description}\nEstimated risk: {res.risk_before:.1f}% → {res.risk_after:.1f}% "
            f"({res.delta:+.1f}). Main changes: {', '.join(res.top_domains) or 'none'}."
        )
        self.simulation_ran.emit(f"{key}:{res.delta}")

    def _run_all(self):
        if self.last_fv is None or self.last_result is None or self.last_profile is None:
            return
        results: list[SimulationResult] = []
        for key in SCENARIOS:
            results.append(self.engine.simulate(self.last_fv, self.last_profile, self.last_result, key, self._strength()))
        self.table.setRowCount(len(results))
        for i, r in enumerate(results):
            self.table.setItem(i, 0, QTableWidgetItem(r.name))
            self.table.setItem(i, 1, QTableWidgetItem(f"{r.risk_before:.1f}"))
            self.table.setItem(i, 2, QTableWidgetItem(f"{r.risk_after:.1f}"))
            self.table.setItem(i, 3, QTableWidgetItem(f"{r.delta:+.1f}"))
            self.table.setItem(i, 4, QTableWidgetItem(", ".join(r.top_domains) if r.top_domains else "-"))
        self.table.resizeColumnsToContents()
        self._refresh_ablation()

    def _refresh_ablation(self):
        if self.last_fv is None or self.last_profile is None:
            return
        hormones = self.hormones.estimate(self.last_fv, self.last_profile)
        phase = self.hormones.phase(self.last_profile)
        ablation = self.engine.counterfactual_ablation(self.last_fv, hormones, phase)
        for i, (label, bar) in enumerate(self.ablation_widgets):
            if i < len(ablation):
                _key, name, risk_without, contribution = ablation[i]
                label.setText(f"{i + 1}. {name}  (+{contribution:.1f} pts)")
                value = int(max(0, min(100, contribution * 4.0)))
                bar.setValue(value)
                bar.setStyleSheet(progress_state_qss(contribution * 4.0))
            else:
                label.setText("--")
                bar.setValue(0)
                bar.setStyleSheet(progress_state_qss(0))
