"""Calibration analysis: Brier score, Expected Calibration Error (ECE) and
reliability/calibration curves.

Checks whether predicted risk probabilities correspond to observed outcome
frequencies. Only meaningful on labelled data (synthetic labels, or reference
outcomes entered in the Validation Lab).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Tuple

import numpy as np

BinPoint = Tuple[float, float, int]  # (mean predicted prob, observed freq, count)


@dataclass
class CalibrationResult:
    n: int = 0
    brier: float = float("nan")
    ece: float = float("nan")
    bins: List[BinPoint] = field(default_factory=list)

    def summary(self) -> str:
        if self.n == 0:
            return "No labelled predictions available for calibration."
        return f"n={self.n} · Brier {self.brier:.4f} · ECE {self.ece:.4f} (lower is better; 0 = perfectly calibrated)"


def calibration(probs: List[float], labels: List[int], n_bins: int = 10) -> CalibrationResult:
    """Calibration metrics. ``probs`` are probabilities in [0, 1]."""
    res = CalibrationResult()
    if not probs or len(probs) != len(labels):
        return res
    p = np.asarray(probs, dtype=float)
    y = np.asarray(labels, dtype=float)
    res.n = int(len(p))
    res.brier = float(np.mean((p - y) ** 2))

    # Expected Calibration Error over equal-width bins (non-empty only).
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    ece = 0.0
    bins: List[BinPoint] = []
    for i in range(n_bins):
        mask = (p >= edges[i]) & (p < edges[i + 1])
        if i == n_bins - 1:  # include the right edge in the last bin
            mask |= p == 1.0
        if mask.sum() == 0:
            continue
        pred = float(p[mask].mean())
        obs = float(y[mask].mean())
        count = int(mask.sum())
        ece += count / res.n * abs(obs - pred)
        bins.append((pred, obs, count))
    res.ece = float(ece)
    res.bins = bins
    return res
