"""Metabolic-Vascular Challenge tab.

This widget implements a safe, educational version of the user's PCOS-VoxVasc
idea. It compares baseline and post-carbohydrate physiology, but it does not
perform or recommend unsupervised medical OGTT. Use a normal meal/snack or
clinician-approved glucose readings.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.data_models import FeatureVector
from src.utils.math_utils import clamp, sigmoid


@dataclass
class ChallengePoint:
    glucose_mg_dl: Optional[float]
    ppg_amp: Optional[float]
    temp_c: Optional[float]
    rmssd_ms: Optional[float]
    stress_index: float
    autonomic_imbalance: float


class MetabolicChallengeWidget(QWidget):
    """Baseline/post challenge capture and premium display."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_fv: FeatureVector | None = None
        self.baseline: ChallengePoint | None = None
        self.post: ChallengePoint | None = None
        self.mv_risk: float = 0.0
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        header = QLabel("Metabolic–Vascular Response Test / MV-AST")
        header.setObjectName("SectionTitle")
        root.addWidget(header)

        safety = QLabel(
            "Safety: do not perform a 75 g glucose challenge without medical/guardian approval. "
            "For exhibitions, use already available glucometer readings or a normal snack/meal response. "
            "This tab estimates response patterns only; it is not a diagnostic OGTT."
        )
        safety.setWordWrap(True)
        safety.setObjectName("WarningText")
        root.addWidget(safety)

        input_box = QGroupBox("Manual glucose values and capture")
        il = QHBoxLayout(input_box)
        self.base_glucose = QDoubleSpinBox(); self.base_glucose.setRange(0, 500); self.base_glucose.setSpecialValueText("none"); self.base_glucose.setSuffix(" mg/dL")
        self.post_glucose = QDoubleSpinBox(); self.post_glucose.setRange(0, 500); self.post_glucose.setSpecialValueText("none"); self.post_glucose.setSuffix(" mg/dL")
        self.capture_base_btn = QPushButton("Capture Baseline Physiology")
        self.capture_post_btn = QPushButton("Capture Post-Meal / 30-min Physiology")
        self.capture_base_btn.clicked.connect(self.capture_baseline)
        self.capture_post_btn.clicked.connect(self.capture_post)
        il.addWidget(QLabel("Baseline glucose")); il.addWidget(self.base_glucose)
        il.addWidget(QLabel("Post glucose")); il.addWidget(self.post_glucose)
        il.addWidget(self.capture_base_btn); il.addWidget(self.capture_post_btn)
        root.addWidget(input_box)

        metrics_box = QGroupBox("Dynamic Indices")
        grid = QGridLayout(metrics_box)
        self.metric_labels = {}
        metrics = [
            ("ΔG", "Glucose delta"),
            ("IMVI", "Insulin-Mediated Vasodilation Index"),
            ("IMTI", "Insulin-Mediated Thermal Index"),
            ("ARR", "Autonomic Response Ratio"),
            ("MV Risk", "Metabolic-Vascular risk contribution"),
            ("Quality", "Capture quality"),
        ]
        for i, (key, title) in enumerate(metrics):
            box = QGroupBox(title)
            fl = QFormLayout(box)
            lab = QLabel("--")
            lab.setObjectName("StatValue")
            fl.addRow(key, lab)
            self.metric_labels[key] = lab
            grid.addWidget(box, i // 3, i % 3)
        root.addWidget(metrics_box)

        self.report = QTextEdit()
        self.report.setReadOnly(True)
        self.report.setMinimumHeight(180)
        root.addWidget(self.report)
        self._write_initial_report()

    def set_current_feature(self, fv: FeatureVector):
        self.current_fv = fv

    def _point_from_current(self, glucose: Optional[float]) -> ChallengePoint | None:
        fv = self.current_fv
        if fv is None:
            return None
        return ChallengePoint(
            glucose_mg_dl=glucose,
            ppg_amp=fv.ppg_pulse_amplitude,
            temp_c=fv.skin_temp_c,
            rmssd_ms=fv.rmssd_ms,
            stress_index=fv.stress_index,
            autonomic_imbalance=fv.autonomic_imbalance,
        )

    def capture_baseline(self):
        g = self.base_glucose.value() if self.base_glucose.value() > 0 else None
        self.baseline = self._point_from_current(g)
        self.update_results()

    def capture_post(self):
        g = self.post_glucose.value() if self.post_glucose.value() > 0 else None
        self.post = self._point_from_current(g)
        self.update_results()

    def update_results(self):
        if self.baseline is None or self.post is None:
            self._write_initial_report()
            return
        b, p = self.baseline, self.post
        delta_g = None if b.glucose_mg_dl is None or p.glucose_mg_dl is None else p.glucose_mg_dl - b.glucose_mg_dl
        imvi = None if not b.ppg_amp or not p.ppg_amp else p.ppg_amp / max(b.ppg_amp, 1e-6)
        imti = None if b.temp_c is None or p.temp_c is None else p.temp_c - b.temp_c
        # ARR: higher means more post-meal autonomic load. Uses stress/autonomic proxy because LF/HF is not robust from short PPG.
        b_auto = max(5.0, 0.5 * b.stress_index + 0.5 * b.autonomic_imbalance)
        p_auto = max(5.0, 0.5 * p.stress_index + 0.5 * p.autonomic_imbalance)
        arr = p_auto / b_auto
        quality_items = [b.ppg_amp is not None, p.ppg_amp is not None, b.temp_c is not None, p.temp_c is not None, b.rmssd_ms is not None, p.rmssd_ms is not None]
        quality = sum(quality_items) / len(quality_items) * 100.0

        risk_terms = []
        if delta_g is not None:
            risk_terms.append(float(sigmoid((delta_g - 45.0) / 18.0)))
        if imvi is not None:
            # Healthy vasodilation tends to increase pulse amplitude; flat/drop increases score.
            risk_terms.append(float(sigmoid((1.12 - imvi) / 0.08)))
        if imti is not None:
            risk_terms.append(float(sigmoid((0.10 - imti) / 0.18)))
        risk_terms.append(float(sigmoid((arr - 1.18) / 0.18)))
        mv_risk = 100.0 * sum(risk_terms) / max(1, len(risk_terms))
        mv_risk = clamp(mv_risk, 0.0, 100.0)
        self.mv_risk = mv_risk

        self.metric_labels["ΔG"].setText("--" if delta_g is None else f"{delta_g:+.0f} mg/dL")
        self.metric_labels["IMVI"].setText("--" if imvi is None else f"{imvi:.2f}×")
        self.metric_labels["IMTI"].setText("--" if imti is None else f"{imti:+.2f} °C")
        self.metric_labels["ARR"].setText(f"{arr:.2f}×")
        self.metric_labels["MV Risk"].setText(f"{mv_risk:.0f}%")
        self.metric_labels["Quality"].setText(f"{quality:.0f}%")

        interpretation = []
        if delta_g is not None:
            interpretation.append(f"Glucose delta is {delta_g:+.0f} mg/dL.")
        if imvi is not None:
            interpretation.append("PPG amplitude increased after carbohydrate." if imvi >= 1.12 else "PPG amplitude did not increase strongly; this may suggest weak peripheral vasodilation or motion/temperature artifact.")
        if imti is not None:
            interpretation.append("Finger/skin temperature warmed after carbohydrate." if imti > 0.10 else "Temperature did not warm; check sensor contact and room conditions before interpreting.")
        interpretation.append(f"Autonomic Response Ratio is {arr:.2f}; values above ~1.2 mean higher post-meal sympathetic/autonomic load in this educational model.")
        interpretation.append("Do not call this PCOS-positive/negative. It is only one module inside the larger multi-signal risk engine.")
        self.report.setText("\n".join(interpretation))

    def _write_initial_report(self):
        self.report.setText(
            "Protocol:\n"
            "1. Sit quietly for 5 minutes. Enter baseline glucose if available. Capture baseline physiology.\n"
            "2. Eat a normal measured snack/meal, or use clinician-approved glucose challenge data.\n"
            "3. Rest quietly. Capture post-meal physiology at 30 minutes and optionally 60/120 minutes.\n"
            "4. Interpret only trends: ΔG, PPG amplitude ratio, temperature shift, and autonomic response ratio.\n\n"
            "Why not direct diagnosis? PPG amplitude is affected by finger pressure, room temperature, sensor contact, anxiety, caffeine, hydration, and motion."
        )
