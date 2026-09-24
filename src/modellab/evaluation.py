"""Model evaluation — never accuracy alone, never fabricated.

Reports AUROC, AUPRC, sensitivity, specificity, precision, recall, F1,
confusion matrix, calibration bins and bootstrap confidence intervals.
If evaluation has not run, callers must render "NOT YET EVALUATED";
if data is insufficient the functions return honest None values.
"""
from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np


def _safe_auroc(y_true: np.ndarray, y_score: np.ndarray) -> Optional[float]:
    from sklearn.metrics import roc_auc_score

    if len(np.unique(y_true)) < 2:
        return None
    return float(roc_auc_score(y_true, y_score))


def _safe_auprc(y_true: np.ndarray, y_score: np.ndarray) -> Optional[float]:
    from sklearn.metrics import average_precision_score

    if len(np.unique(y_true)) < 2:
        return None
    return float(average_precision_score(y_true, y_score))


def evaluate_binary(y_true, y_score, threshold: float = 0.5,
                    n_bootstrap: int = 200, seed: int = 42) -> dict:
    """Full binary evaluation dict.  y_true in {0,1}, y_score = P(class 1)."""
    y_true = np.asarray(y_true, dtype=int)
    y_score = np.asarray(y_score, dtype=float)
    n = len(y_true)
    if n == 0:
        return {"status": "INSUFFICIENT DATA", "n": 0}

    y_pred = (y_score >= threshold).astype(int)
    tp = int(np.sum((y_pred == 1) & (y_true == 1)))
    tn = int(np.sum((y_pred == 0) & (y_true == 0)))
    fp = int(np.sum((y_pred == 1) & (y_true == 0)))
    fn = int(np.sum((y_pred == 0) & (y_true == 1)))

    def div(a, b):
        return float(a / b) if b else None

    sens = div(tp, tp + fn)                      # recall / sensitivity
    spec = div(tn, tn + fp)
    prec = div(tp, tp + fp)
    f1 = div(2 * tp, 2 * tp + fp + fn)

    out = {
        "status": "EVALUATED",
        "n": n,
        "threshold": threshold,
        "auroc": _safe_auroc(y_true, y_score),
        "auprc": _safe_auprc(y_true, y_score),
        "sensitivity": sens,
        "specificity": spec,
        "precision": prec,
        "recall": sens,
        "f1": f1,
        "confusion_matrix": {"tp": tp, "tn": tn, "fp": fp, "fn": fn},
        "calibration": calibration_bins(y_true, y_score),
    }
    if len(np.unique(y_true)) < 2:
        out["warnings"] = ["Test set contains a single class — AUROC/AUPRC unavailable."]

    # Bootstrap 95% CI for AUROC (only when feasible).
    if out["auroc"] is not None and n >= 20:
        rng = np.random.default_rng(seed)
        vals: List[float] = []
        for _ in range(n_bootstrap):
            idx = rng.integers(0, n, n)
            a = _safe_auroc(y_true[idx], y_score[idx])
            if a is not None:
                vals.append(a)
        if len(vals) >= 50:
            out["auroc_ci95"] = [float(np.percentile(vals, 2.5)),
                                 float(np.percentile(vals, 97.5))]
    return out


def calibration_bins(y_true, y_score, n_bins: int = 10) -> List[dict]:
    y_true = np.asarray(y_true, dtype=float)
    y_score = np.asarray(y_score, dtype=float)
    bins = []
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    for i in range(n_bins):
        mask = (y_score >= edges[i]) & (y_score < edges[i + 1] if i < n_bins - 1 else y_score <= edges[i + 1])
        if mask.sum() == 0:
            continue
        bins.append({
            "bin": f"{edges[i]:.1f}-{edges[i + 1]:.1f}",
            "n": int(mask.sum()),
            "mean_predicted": float(y_score[mask].mean()),
            "observed_rate": float(y_true[mask].mean()),
        })
    return bins


def compare_metrics(current: Optional[dict], candidate: Optional[dict]) -> List[dict]:
    """Side-by-side rows: metric / current / candidate / difference."""
    keys = ["auroc", "auprc", "sensitivity", "specificity", "precision", "f1"]
    rows = []
    for k in keys:
        a = (current or {}).get(k)
        b = (candidate or {}).get(k)
        diff = None
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            diff = b - a
        rows.append({"metric": k.upper(), "current": a, "candidate": b, "difference": diff})
    return rows
