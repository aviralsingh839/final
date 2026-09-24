"""Model version registry and self-learning architecture hooks.

Feature 29 (model version tracking): every model/algorithm in the dashboard is
registered here with a version and a short description. The version list is
shown on the Diagnostics page and logged at startup.

Feature 30 (future self-learning architecture): instead of hard-coding a
learning loop we do not yet have (there is no labelled clinical dataset), we
provide the *hooks* a future online-update loop would need:
  - EventLabelStore: manual events (mode button, post-meal, baseline) are
    persisted with timestamps so a future model can be fine-tuned on labelled
    windows.
  - SelfLearningArchitecture.update_weights(): a clearly-marked entry point
    that refuses to run until a labelled dataset and a validation protocol are
    supplied, so the educational model can never silently "learn" from
    unvalidated data.
"""
from __future__ import annotations

from typing import Optional

from src.utils.history_store import HistoryStore

APP_VERSION = "1.4.0"

MODEL_REGISTRY = [
    {"name": "Risk engine", "version": "2.0", "role": "Explainable PCOS risk score with bootstrap CI"},
    {"name": "Hormone twin", "version": "1.3", "role": "Estimated hormone tendencies from physiology + cycle phase"},
    {"name": "Sleep estimator", "version": "1.2", "role": "Wearable sleep/deep/REM probability"},
    {"name": "Stress estimator", "version": "1.1", "role": "Acute/chronic stress from HRV + GSR"},
    {"name": "Metabolic estimator", "version": "1.1", "role": "Insulin resistance / metabolic syndrome proxy"},
    {"name": "Circadian analyzer", "version": "1.3", "role": "Cosinor HR/HRV/temp/GSR rhythm + CSI"},
    {"name": "Anomaly detector", "version": "1.0", "role": "Real-time outlier detection vs personal baseline"},
    {"name": "Personal baseline", "version": "1.0", "role": "Personalized normal ranges from calibration"},
    {"name": "Multi-day analyzer", "version": "1.0", "role": "7-day profile + long-term trajectory"},
    {"name": "VoxVasc voice proxy", "version": "0.9", "role": "Experimental voice signal proxy"},
    {"name": "What-if simulator", "version": "1.0", "role": "Counterfactual intervention projections"},
    {"name": "Composite scores", "version": "1.0", "role": "Daily health + physiological fingerprint"},
    {"name": "Recommendations", "version": "1.0", "role": "Rule-based explainable advice + early warning"},
    {"name": "Synthetic generator", "version": "1.0", "role": "Synthetic week / patient simulation (clearly labelled)"},
    {"name": "Research lab", "version": "1.0", "role": "Confusion matrix / FP-FN / ablation on synthetic labels"},
    {"name": "AI assistant", "version": "1.0", "role": "Conversational answers grounded in live data; optional LLM mode"},
    {"name": "Validation lab", "version": "1.0", "role": "Reference-device agreement, SQI + prediction rejection, LOSO CV, repeatability, calibration, ablation, leakage, prospective validation, report"},
    {"name": "PPG quality model", "version": "1.0", "role": "Learned PPG motion-artifact quality gate (wrist-PPG-during-exercise); blended into ppg_quality() at 40% when models/ppg_quality_model.joblib exists"},
    {"name": "Dataset manager", "version": "1.0", "role": "Central dataset registry with provenance, hashes and quality checks (duplicates, missing, units, impossible values)"},
    {"name": "Training audit", "version": "1.0", "role": "Reproducibility audit log for every training run (data/training_audit.jsonl)"},
    {"name": "Evidence center", "version": "1.0", "role": "Model status (TRAINED/NOT TRAINED/FALLBACK/NOT YET TRAINED) + evidence-driven progress bars"},
    {"name": "Cyst research monitor", "version": "0.1", "role": "RESEARCH ONLY: personal-baseline trajectory monitor; cyst rupture model NOT YET TRAINED by design"},
]


def registry_summary() -> str:
    from src.config import APP_VERSION as _app_version

    lines = [f"CHRONO-PCOS application v{_app_version} (model registry v{APP_VERSION})"]
    for m in MODEL_REGISTRY:
        lines.append(f"- {m['name']} v{m['version']}: {m['role']}")
    return "\n".join(lines)


class EventLabelStore:
    """Persists labelled event windows for a future fine-tuning pipeline."""

    def __init__(self, store: HistoryStore):
        self.store = store

    def log_event(self, session_id: Optional[int], kind: str, detail: str = "") -> None:
        self.store.log_event(session_id, kind, detail)

    def events(self, kind: Optional[str] = None, limit: int = 500) -> list[dict]:
        return self.store.events(kind=kind, limit=limit)


class SelfLearningArchitecture:
    """Placeholder for an online, model-updating loop (feature 30).

    The design intent: after enough labelled event windows and a validation
    protocol exist, `update_weights()` would re-fit the risk engine from the
    EventLabelStore while keeping the explainable-equation fallback as a
    baseline. Until then it intentionally refuses to update so the educational
    system can never silently drift on unvalidated data.
    """

    is_available = False
    reason = ("No labelled dataset or validation protocol configured. "
              "Self-learning is disabled by design for an educational tool.")

    def update_weights(self) -> None:
        raise NotImplementedError(
            "Self-learning is not enabled. " + self.reason +
            " Future steps: (1) collect labelled event windows via EventLabelStore, "
            "(2) define a held-out validation set, (3) re-fit with sklearn and "
            "register the new version in MODEL_REGISTRY."
        )
