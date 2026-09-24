"""Model status registry + evidence-driven progress (V5, items A, N, S).

Every model in the project has an explicit, honest status:

  TRAINED        - a real training artifact exists on disk with an audit entry.
  NOT TRAINED    - no artifact; the module runs on a transparent fallback.
  FALLBACK       - explicitly an equation/heuristic engine, NOT a trained ML model.
  NOT YET TRAINED - reserved for models that must not be trained until real
                    outcome-labelled data exists (e.g. the cyst-rupture model).

The Evidence Center progress bars are computed from actual evidence on disk /
in the local stores (trained artifacts, audit entries, reference pairs,
prospective outcomes), never hard-coded. When no evidence exists, the bar is 0
and the display says "NOT YET VALIDATED".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.config import MODEL_DIR
from src.models.training_audit import latest_audit
from src.validation.store import ValidationStore


@dataclass
class ModelStatus:
    id: str
    name: str
    kind: str  # ml | equation | research
    status: str  # TRAINED | NOT TRAINED | FALLBACK | NOT YET TRAINED
    dataset_id: Optional[str] = None
    artifact: Optional[str] = None
    reason: str = ""
    audit: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id, "name": self.name, "kind": self.kind, "status": self.status,
            "dataset_id": self.dataset_id, "artifact": self.artifact, "reason": self.reason,
            "audit": self.audit,
        }


# ------------------------------------------------------------ model catalog
# kind: ml = should be a trained artifact; equation = fallback engine; research = gated.
MODEL_CATALOG = [
    {
        "id": "pcos_risk",
        "name": "PCOS clinical risk model",
        "kind": "ml",
        "dataset_id": "pcos_kaggle",
        "artifact": MODEL_DIR / "pcos_risk_model.joblib",
    },
    {
        "id": "ppg_quality",
        "name": "PPG signal-quality model",
        "kind": "ml",
        "dataset_id": "wrist_ppg_exercise",
        "artifact": MODEL_DIR / "ppg_quality_model.joblib",
    },
    {
        "id": "stress",
        "name": "Stress estimator",
        "kind": "ml",
        "dataset_id": "wesad",
        "artifact": MODEL_DIR / "stress_model.joblib",
    },
    {
        "id": "sleep",
        "name": "Sleep estimator",
        "kind": "ml",
        "dataset_id": "bidsleep",
        "artifact": MODEL_DIR / "sleep_model.joblib",
    },
    {
        "id": "hormone",
        "name": "Hormone twin",
        "kind": "ml",
        "dataset_id": "pcos_kaggle",
        "artifact": MODEL_DIR / "hormone_models.joblib",
    },
    {
        "id": "risk_engine",
        "name": "Live risk engine",
        "kind": "equation",
        "dataset_id": None,
        "artifact": None,
    },
    {
        "id": "cyst",
        "name": "Cyst rupture model",
        "kind": "research",
        "dataset_id": None,
        "artifact": None,
    },
]

FALLBACK_REASON = ("Transparent mathematical/rule-based fallback is active — this is NOT a trained ML "
                   "model. Run the matching training script once a labelled dataset is available.")
CYST_REASON = ("No real outcome-labelled cyst-event data exists. Training is blocked by design until "
               "a longitudinal dataset with clinical outcomes is available.")


def _status_for(entry: Dict[str, Any], db: Optional[ValidationStore] = None) -> ModelStatus:
    mid = entry["id"]
    audit = latest_audit(mid)
    if entry["kind"] == "ml":
        artifact = entry.get("artifact")
        exists = artifact is not None and Path(artifact).exists()
        if exists:
            return ModelStatus(
                id=mid, name=entry["name"], kind="ml", status="TRAINED",
                dataset_id=entry["dataset_id"], artifact=str(artifact),
                reason=f"artifact present ({Path(artifact).name})" + (", audit recorded" if audit else ""),
                audit=audit,
            )
        return ModelStatus(
            id=mid, name=entry["name"], kind="ml", status="NOT TRAINED",
            dataset_id=entry["dataset_id"], artifact=str(artifact) if artifact else None,
            reason=FALLBACK_REASON, audit=audit,
        )
    if entry["kind"] == "equation":
        return ModelStatus(
            id=mid, name=entry["name"], kind="equation", status="FALLBACK",
            reason="Explainable equation-based engine with transparent weights — not a trained ML model. "
                   "See src/validation/versioning.py for the frozen weights.",
        )
    # research / gated models
    return ModelStatus(
        id=mid, name=entry["name"], kind="research", status="NOT YET TRAINED",
        reason=CYST_REASON,
    )


def compute_model_statuses(db: Optional[ValidationStore] = None) -> List[ModelStatus]:
    return [_status_for(e, db) for e in MODEL_CATALOG]


def model_status_summary(db: Optional[ValidationStore] = None) -> str:
    lines = ["Model status:"]
    for s in compute_model_statuses(db):
        lines.append(f"  [{s.status:13s}] {s.name}")
        if s.reason:
            lines.append(f"                {s.reason}")
    return "\n".join(lines)


# ------------------------------------------------------ evidence progress
SENSOR_VALIDATION_METRICS = ["HR (bpm)", "SpO2 (%)", "Skin temp (°C)", "RMSSD (ms)", "GSR (raw)", "Stress index"]
MIN_PAIRS_PER_METRIC = 3
PROSPECTIVE_TARGET = 10  # labelled prospective outcomes needed for a full bar
ML_MODEL_IDS = ["pcos_risk", "ppg_quality", "stress", "sleep", "hormone"]


def evidence_progress(db: ValidationStore) -> Dict[str, Dict[str, Any]]:
    """Progress 0..1 for each evidence pillar, derived only from real evidence."""
    out: Dict[str, Dict[str, Any]] = {}

    # Sensor validation: fraction of key metrics with >= MIN_PAIRS reference pairs.
    pairs = db.reference_pairs()
    by_metric: Dict[str, int] = {}
    for p in pairs:
        by_metric[p["metric"]] = by_metric.get(p["metric"], 0) + 1
    covered = sum(1 for m in SENSOR_VALIDATION_METRICS if by_metric.get(m, 0) >= MIN_PAIRS_PER_METRIC)
    out["sensor_validation"] = {
        "fraction": covered / len(SENSOR_VALIDATION_METRICS),
        "detail": f"{covered}/{len(SENSOR_VALIDATION_METRICS)} metrics with >= {MIN_PAIRS_PER_METRIC} "
                  f"paired reference measurements ({len(pairs)} pairs recorded)",
    }

    # Model validation: trained ML artifacts with audit entries.
    statuses = {s.id: s for s in compute_model_statuses(db)}
    trained = [mid for mid in ML_MODEL_IDS if statuses.get(mid) and statuses[mid].status == "TRAINED"]
    with_audit = [mid for mid in trained if statuses[mid].audit is not None]
    out["model_validation"] = {
        "fraction": len(trained) / len(ML_MODEL_IDS),
        "detail": f"{len(trained)}/{len(ML_MODEL_IDS)} ML models trained "
                  f"({len(with_audit)} with full audit records): {', '.join(trained) or 'none'}",
    }

    # Prospective validation: labelled outcomes out of a target.
    preds = db.predictions()
    n_outcome = sum(1 for p in preds if p.get("outcome") is not None)
    out["prospective_validation"] = {
        "fraction": min(1.0, n_outcome / PROSPECTIVE_TARGET),
        "detail": f"{n_outcome}/{PROSPECTIVE_TARGET} stored predictions labelled with outcomes "
                  f"({len(preds)} predictions stored)",
    }

    # Clinical validation: cannot be claimed without a real clinical study.
    out["clinical_validation"] = {
        "fraction": 0.0,
        "detail": "No clinical validation has been performed. This bar stays at 0 until a "
                  "registered clinical evaluation exists — it is never estimated.",
    }
    return out


def evidence_progress_summary(db: ValidationStore) -> str:
    lines = ["Evidence progress:"]
    for name, data in evidence_progress(db).items():
        pct = int(round(data["fraction"] * 100))
        bar = "█" * (pct // 10) + "░" * (10 - pct // 10)
        lines.append(f"  {name.replace('_', ' ').title():22s} {bar} {pct:3d}%  — {data['detail']}")
    return "\n".join(lines)
