"""Leave-one-subject-out cross-validation.

Evaluates the (frozen, explainable) risk engine with strict subject-level
separation: data from one subject is never used in the same fold as their own
evaluation rows. Because the engine is a fixed explainable equation, the
"training" fold is informational; the value here is per-subject generalisation
metrics with mean ± SD across folds. Requires labelled rows (synthetic labels,
or reference outcomes).

Metrics: accuracy, precision, recall (sensitivity), specificity, F1, ROC-AUC
and PR-AUC where the class balance allows.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np

from src.utils.history_store import HistoryStore

RISK_THRESHOLD = 50.0


@dataclass
class FoldResult:
    subject: str
    n: int
    accuracy: Optional[float] = None
    precision: Optional[float] = None
    recall: Optional[float] = None
    specificity: Optional[float] = None
    f1: Optional[float] = None
    roc_auc: Optional[float] = None
    pr_auc: Optional[float] = None
    n_pos: int = 0
    n_neg: int = 0


@dataclass
class LosoResult:
    folds: List[FoldResult] = field(default_factory=list)
    threshold: float = RISK_THRESHOLD
    notes: List[str] = field(default_factory=list)

    def mean_sd(self, attr: str) -> Optional[str]:
        vals = [getattr(f, attr) for f in self.folds if getattr(f, attr) is not None]
        if not vals:
            return None
        arr = np.asarray(vals)
        return f"{arr.mean():.3f} ± {arr.std(ddof=1) if len(arr) > 1 else 0.0:.3f}"

    def summary(self) -> str:
        if not self.folds:
            return "No labelled rows for leave-one-subject-out evaluation."
        lines = ["Leave-one-subject-out (frozen engine) — mean ± SD across folds:"]
        for attr, label in [("accuracy", "accuracy"), ("precision", "precision"),
                            ("recall", "sensitivity"), ("specificity", "specificity"),
                            ("f1", "F1"), ("roc_auc", "ROC-AUC"), ("pr_auc", "PR-AUC")]:
            s = self.mean_sd(attr)
            if s:
                lines.append(f"  {label}: {s}")
        return "\n".join(lines)


def _labeled_rows(db: HistoryStore):
    """Feature rows joined with their subject, carrying a label from extra_json."""
    import sqlite3

    rows = []
    conn = sqlite3.connect(str(db.path))
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(
            "SELECT f.ts, f.risk, f.extra_json, COALESCE(NULLIF(TRIM(s.participant_id), ''), 'session#'||s.id) AS subject "
            "FROM features f LEFT JOIN sessions s ON s.id = f.session_id ORDER BY f.ts"
        )
        for r in cur.fetchall():
            extra = r["extra_json"]
            label = None
            if isinstance(extra, str) and extra:
                try:
                    label = json.loads(extra).get("label")
                except Exception:
                    label = None
            if label is None or r["risk"] is None:
                continue
            rows.append({"subject": str(r["subject"]), "risk": float(r["risk"]), "label": int(label)})
    finally:
        conn.close()
    return rows


def leave_one_subject_out(db: HistoryStore, threshold: float = RISK_THRESHOLD,
                          min_rows_per_subject: int = 1) -> LosoResult:
    res = LosoResult(threshold=threshold)
    rows = _labeled_rows(db)
    if not rows:
        res.notes.append("No labelled rows found. Generate a synthetic week with labels, or enter reference outcomes.")
        return res

    subjects: Dict[str, list] = {}
    for r in rows:
        subjects.setdefault(r["subject"], []).append(r)
    subjects = {k: v for k, v in subjects.items() if len(v) >= min_rows_per_subject}
    if not subjects:
        res.notes.append("No subject has enough labelled rows.")
        return res

    from sklearn.metrics import (
        accuracy_score, average_precision_score, f1_score,
        precision_score, recall_score, roc_auc_score,
    )

    for subj, subj_rows in sorted(subjects.items()):
        risks = np.array([r["risk"] for r in subj_rows])
        labels = np.array([r["label"] for r in subj_rows])
        pred = (risks >= threshold).astype(int)
        fold = FoldResult(subject=subj, n=len(subj_rows), n_pos=int(labels.sum()), n_neg=int((1 - labels).sum()))
        if len(set(labels)) < 2:
            # Single-class fold: still report agreement with the label.
            fold.accuracy = float(accuracy_score(labels, pred))
            res.folds.append(fold)
            continue
        fold.accuracy = float(accuracy_score(labels, pred))
        fold.precision = float(precision_score(labels, pred, zero_division=0))
        fold.recall = float(recall_score(labels, pred, zero_division=0))
        fold.f1 = float(f1_score(labels, pred, zero_division=0))
        tn = int(((pred == 0) & (labels == 0)).sum())
        fp = int(((pred == 1) & (labels == 0)).sum())
        fold.specificity = float(tn / max(tn + fp, 1))
        if len(set(risks)) >= 2:
            try:
                fold.roc_auc = float(roc_auc_score(labels, risks / 100.0))
            except Exception:
                fold.roc_auc = None
            try:
                fold.pr_auc = float(average_precision_score(labels, risks / 100.0))
            except Exception:
                fold.pr_auc = None
        res.folds.append(fold)

    res.notes = [
        f"Folds: {len(res.folds)} subject(s); threshold {threshold:.0f}% (>= threshold = positive).",
        "The risk engine is a fixed explainable equation, so folds do not re-fit a model; "
        "they measure per-subject generalisation of the frozen engine on labelled data.",
        "Labels here are synthetic unless reference outcomes were entered in the Validation Lab.",
    ]
    return res
