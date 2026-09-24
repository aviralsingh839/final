"""Repeatability & reproducibility: multiple measurements from the same subject
under the same conditions.

Reports mean, SD, coefficient of variation (CV) and the intraclass correlation
coefficient ICC(2,1) for repeated measures, plus within-session vs
between-session variability when a subject has several sessions.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np


@dataclass
class RepeatabilityResult:
    n_subjects: int = 0
    n_measures: int = 0
    grand_mean: float = float("nan")
    mean_sd: float = float("nan")
    mean_cv_pct: float = float("nan")
    icc: Optional[float] = None
    within_session_cv_pct: Optional[float] = None
    between_session_cv_pct: Optional[float] = None
    notes: List[str] = field(default_factory=list)

    def summary(self) -> str:
        if self.n_measures == 0:
            return "No repeated measurements available yet."
        icc_txt = f"ICC(2,1)={self.icc:.3f}" if self.icc is not None else "ICC: n/a (unequal repeats)"
        return (
            f"subjects={self.n_subjects} · measures={self.n_measures} · mean={self.grand_mean:.2f} · "
            f"SD={self.mean_sd:.2f} · CV={self.mean_cv_pct:.1f}% · {icc_txt}"
        )


def icc2_1(measures: Dict[str, List[float]]) -> Optional[float]:
    """ICC(2,1) for repeated measures per subject (two-way random, single score).

    Uses mean number of measures k; returns None when data is degenerate
    (single subject, zero between-subject variance, or all identical).
    """
    if len(measures) < 2:
        return None
    rows = [np.asarray(v, dtype=float) for v in measures.values() if len(v) > 0]
    if len(rows) < 2:
        return None
    k = float(np.mean([len(r) for r in rows]))
    if k < 1.5:
        return None
    n = len(rows)
    grand = float(np.mean([r.mean() for r in rows]))
    msb = float(np.mean([(r.mean() - grand) ** 2 for r in rows])) * (n / (n - 1) if n > 1 else 1.0)
    # Mean squared error: pooled within-subject variance.
    mse = float(np.mean([np.mean((r - r.mean()) ** 2) for r in rows]))
    denom = msb + (k - 1.0) * mse
    if denom <= 0 or msb <= 0:
        return None
    icc = (msb - mse) / denom
    if not math.isfinite(icc):
        return None
    return float(max(-1.0, min(1.0, icc)))


def repeatability(measures: Dict[str, List[float]],
                  session_means: Optional[Dict[str, List[float]]] = None) -> RepeatabilityResult:
    """Repeatability across repeated measurements.

    ``measures`` maps subject id -> list of repeated values (same condition).
    ``session_means`` (optional) maps subject id -> per-session means, to
    derive within-session vs between-session CV.
    """
    res = RepeatabilityResult()
    values = [v for v in measures.values() if v]
    if not values:
        return res
    flat = np.concatenate([np.asarray(v, dtype=float) for v in values])
    res.n_subjects = len([v for v in measures.values() if v])
    res.n_measures = int(len(flat))
    res.grand_mean = float(np.mean(flat))
    res.mean_sd = float(np.mean([np.std(np.asarray(v)) for v in values]))
    if res.grand_mean != 0:
        res.mean_cv_pct = float(100.0 * res.mean_sd / abs(res.grand_mean))
    res.icc = icc2_1(measures)

    if session_means:
        within = []
        between = []
        for subj, sess in session_means.items():
            sess = [s for s in sess if s is not None and s == s]
            if len(sess) < 1:
                continue
            m = float(np.mean(sess))
            if m != 0:
                within.append(float(np.std(sess) / abs(m) * 100.0))
            if len(sess) >= 2:
                # Between-session: CV of session means vs overall mean.
                between.append(float(np.std(sess) / abs(np.mean(sess)) * 100.0) if np.mean(sess) != 0 else float("nan"))
        if within:
            res.within_session_cv_pct = float(np.mean([v for v in within if v == v]))
        if between:
            res.between_session_cv_pct = float(np.mean([v for v in between if v == v]))
    if res.icc is None and res.n_measures:
        res.notes.append("ICC requires >= 2 subjects with repeated measures; only CV reported.")
    return res
