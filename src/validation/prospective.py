"""Prospective validation mode.

The scientific protocol:
  1. FREEZE the model (a reproducible snapshot is stored).
  2. Record predictions BEFORE the outcome is known (timestamped, with CI,
     confidence and SQI).
  3. Enter the outcome label later.
  4. Compare stored predictions with outcomes.

This prevents hindsight bias: predictions are locked in before the outcome is
seen, and every prediction is tied to a frozen model version.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np

from src.data_models import FeatureVector, RiskResult
from src.validation.store import ValidationStore
from src.validation.versioning import snapshot_model_state


@dataclass
class ProspectiveSummary:
    n_frozen: int = 0
    n_pending: int = 0
    n_labeled: int = 0
    accuracy: Optional[float] = None
    brier: Optional[float] = None
    mean_ci_width: Optional[float] = None
    mean_confidence: Optional[float] = None

    def summary(self) -> str:
        if self.n_pending == 0 and self.n_labeled == 0:
            return "No prospective predictions recorded yet. Freeze the model, then record predictions before outcomes."
        parts = [f"pending={self.n_pending}", f"labelled={self.n_labeled}"]
        if self.accuracy is not None:
            parts.append(f"accuracy={self.accuracy:.3f}")
        if self.brier is not None:
            parts.append(f"Brier={self.brier:.4f}")
        if self.mean_ci_width is not None:
            parts.append(f"mean CI width={self.mean_ci_width:.1f}")
        if self.mean_confidence is not None:
            parts.append(f"mean confidence={self.mean_confidence:.1f}%")
        return "Prospective validation · " + " · ".join(parts)


class ProspectiveValidator:
    def __init__(self, store: ValidationStore):
        self.store = store

    def freeze(self) -> Dict:
        """Store a reproducible model snapshot; returns it."""
        snap = snapshot_model_state()
        self.store.add_snapshot(snap)
        return snap

    def model_version(self) -> str:
        latest = self.store.latest_snapshot()
        if latest:
            snap = latest.get("snapshot") or {}
            return f"{snap.get('app_version', '?')} (snapshot #{latest['id']})"
        return "no frozen snapshot"

    def record(self, subject_id: str, fv: FeatureVector, result: RiskResult,
               sqi: Optional[float] = None) -> int:
        """Record a prediction made before the outcome is known."""
        return self.store.add_prediction(
            subject_id=subject_id or "anonymous",
            model_version=self.model_version(),
            risk=float(result.risk_percent),
            ci_low=float(result.ci_low) if result.ci_low is not None else None,
            ci_high=float(result.ci_high) if result.ci_high is not None else None,
            confidence=float(result.confidence) if result.confidence is not None else None,
            sqi=float(sqi) if sqi is not None else None,
        )

    def set_outcome(self, prediction_id: int, outcome: int) -> None:
        self.store.set_outcome(prediction_id, outcome)

    def pending(self) -> List[dict]:
        return self.store.predictions(with_outcome=False)

    def labeled(self) -> List[dict]:
        return self.store.predictions(with_outcome=True)

    def summarize(self) -> ProspectiveSummary:
        s = ProspectiveSummary()
        latest = self.store.latest_snapshot()
        if latest:
            s.n_frozen = 1
        pending = self.store.predictions(with_outcome=False)
        labeled = self.store.predictions(with_outcome=True)
        s.n_pending = len(pending)
        s.n_labeled = len(labeled)
        if labeled:
            risks = np.array([p["risk"] for p in labeled], dtype=float)
            outs = np.array([p["outcome"] for p in labeled], dtype=float)
            pred = (risks >= 50.0).astype(int)
            s.accuracy = float(np.mean(pred == outs))
            s.brier = float(np.mean((risks / 100.0 - outs) ** 2))
            ci_w = [p["ci_high"] - p["ci_low"] for p in labeled if p.get("ci_high") is not None and p.get("ci_low") is not None]
            if ci_w:
                s.mean_ci_width = float(np.mean(ci_w))
            confs = [p["confidence"] for p in labeled if p.get("confidence") is not None]
            if confs:
                s.mean_confidence = float(np.mean(confs))
        return s
