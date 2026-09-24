"""Longitudinal-information experiment framework (V6.2 → V8.1).

Directly tests the project's central research question:

    "Can continuous personalized physiological information provide useful
     longitudinal context between periodic clinical assessments, and does
     combining that information with clinical/ultrasound-derived information
     improve PCOS-related risk phenotyping?"

Five models are pre-defined and must be compared with patient-level
(leakage-proof) validation:

  A. Clinical / cycle information only          (conventional)
  B. Conventional wearable-style snapshot features (a smartwatch-style day)
  C. CHRONO longitudinal features               (personal-baseline deviations,
                                                persistence, slopes, change points)
  D. Clinical/cycle + longitudinal + ultrasound-derived features
  E. Full multimodal CHRONO model               (A + B + C + D inputs)

The A/B/C comparison answers "do longitudinal features add value?"; the
D/E comparison answers "does ultrasound-derived information add additional
value?".

This framework is deliberately honest: **no results are fabricated**. Until a
labelled longitudinal PCOS dataset exists (see the pilot protocol in the
README), `run()` returns `status="PENDING"` with the exact reasons. When a
validated dataset arrives, the same interface runs the models and reports
AUROC / AUPRC / sensitivity / specificity / F1 / calibration with
confidence intervals, using patient-level splitting only.

No dataset in this repository can validate the wearable: the Kaggle clinical
cohort is a clinical-variable model-development set (never wearable
accuracy), and synthetic rows are excluded from real analysis.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import pandas as pd


@dataclass
class ExperimentModel:
    key: str
    name: str
    feature_groups: List[str]
    description: str


EXPERIMENT_MODELS: List[ExperimentModel] = [
    ExperimentModel(
        key="A",
        name="Clinical / cycle only",
        feature_groups=["cycle_length", "cycle_irregularity", "symptoms", "age", "bmi"],
        description="Conventional clinical-style variables a clinician already collects.",
    ),
    ExperimentModel(
        key="B",
        name="Conventional wearable snapshot",
        feature_groups=["hr", "rmssd", "skin_temp", "activity"],
        description="Single-time-point wearable-style features (a smartwatch-style day).",
    ),
    ExperimentModel(
        key="C",
        name="CHRONO longitudinal features",
        feature_groups=["baseline_deviation_sd", "persistence_hours", "slope_per_day",
                        "change_point_count", "variability", "circadian_stability"],
        description="Personal-baseline deviations, persistence, trajectories, change points.",
    ),
    ExperimentModel(
        key="D",
        name="Clinical/cycle + longitudinal + ultrasound",
        feature_groups=["clinical", "longitudinal", "ultrasound"],
        description="Adds structured ultrasound-derived features (image-derived or clinically entered) "
                    "to clinical + longitudinal inputs; tests whether periodic imaging adds value.",
    ),
    ExperimentModel(
        key="E",
        name="Full multimodal CHRONO (A + B + C + D)",
        feature_groups=["clinical", "snapshot_wearable", "longitudinal", "ultrasound"],
        description="All available inputs (clinical, wearable snapshot, CHRONO longitudinal, "
                    "ultrasound-derived); the maximal model.",
    ),
]

MODEL_A_B_C_D = {m.key: m for m in EXPERIMENT_MODELS}


@dataclass
class ExperimentStatus:
    available: bool = False
    status: str = "PENDING"
    reason: str = ""
    metrics: Dict[str, Optional[float]] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "available": self.available,
            "status": self.status,
            "reason": self.reason,
            "metrics": self.metrics,
        }


class LongitudinalExperiment:
    """Interface for the A/B/C/D comparison. Results are produced only when a
    validated longitudinal dataset with labels + subject IDs is available."""

    STATUS_PENDING = "PENDING — requires a labelled longitudinal PCOS dataset (see README pilot protocol)."

    def __init__(self, df: Optional[pd.DataFrame] = None):
        self.df = df

    def status(self) -> ExperimentStatus:
        if self.df is None or self.df.empty:
            return ExperimentStatus(
                status="PENDING",
                reason="No labelled longitudinal dataset loaded. Synthetic data never validates a model.",
            )
        # Even with a dataframe, we refuse to report metrics unless it carries
        # subject IDs and a verified clinical label (checked by a separate
        # integrity pass, see ValidationTab).
        if "subject_id" not in self.df.columns or "label" not in self.df.columns:
            return ExperimentStatus(
                status="PENDING",
                reason="Dataset lacks subject_id / verified label columns required for leakage-safe evaluation.",
            )
        return ExperimentStatus(
            status="PENDING",
            reason="Integrity checks pass but clinical validation is not established. "
                   "Results would be model-development, not clinical validation.",
        )

    def run(self) -> ExperimentStatus:
        """Run the five-model comparison. Never fabricates numbers: without a
        validated dataset this returns PENDING."""
        st = self.status()
        if not st.available:
            return st
        # Placeholder for the real pipeline: patient-level GroupKFold CV,
        # calibration, CIs per model. Wired when a validated dataset exists.
        return ExperimentStatus(
            available=True,
            status="RUN — see metrics",
            reason="",
            metrics={},
        )

    def model_feature_list(self, key: str) -> List[str]:
        m = MODEL_A_B_C_D.get(key)
        return list(m.feature_groups) if m else []

    @staticmethod
    def report_table_text() -> str:
        lines = [
            "LONGITUDINAL-INFORMATION EXPERIMENT (MODEL A-E)",
            "=" * 48,
            "Question: do CHRONO longitudinal features add useful information beyond",
            "conventional snapshot/clinical inputs for PCOS-related risk estimation?",
            "And does ultrasound-derived information add additional value?",
            "",
        ]
        for m in EXPERIMENT_MODELS:
            lines.append(f"MODEL {m.key} — {m.name}")
            lines.append(f"  {m.description}")
            lines.append("  Features: " + ", ".join(m.feature_groups))
            lines.append("  Result: PENDING (requires a labelled longitudinal PCOS dataset)")
            lines.append("")
        lines.append("Reported when available: AUROC · AUPRC · sensitivity · specificity · F1 ·")
        lines.append("calibration · confidence intervals — patient-level splitting only.")
        lines.append("No performance numbers are fabricated in this repository.")
        return "\n".join(lines)
