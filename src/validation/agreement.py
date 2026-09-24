"""Reference-device validation: agreement between dashboard sensors and a
commercial reference device (pulse oximeter, digital thermometer, ...).

Computes MAE, RMSE, bias, SD of differences, Pearson correlation and
Bland-Altman 95% limits of agreement for paired (sensor, reference)
measurements.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Tuple

import numpy as np

PairedPoint = Tuple[float, float]  # (sensor_value, reference_value)


@dataclass
class AgreementResult:
    n: int = 0
    mae: float = float("nan")
    rmse: float = float("nan")
    bias: float = float("nan")
    sd: float = float("nan")
    pearson_r: float = float("nan")
    loa_low: float = float("nan")
    loa_high: float = float("nan")
    points: List[PairedPoint] = field(default_factory=list)

    def summary(self) -> str:
        if self.n == 0:
            return "No paired measurements recorded yet."
        return (
            f"n={self.n} · MAE {self.mae:.2f} · RMSE {self.rmse:.2f} · "
            f"bias {self.bias:+.2f} ± {self.sd:.2f} · r={self.pearson_r:.3f} · "
            f"95% LoA [{self.loa_low:.2f}, {self.loa_high:.2f}]"
        )


def agreement(pairs: List[PairedPoint]) -> AgreementResult:
    """Agreement statistics for (sensor, reference) pairs."""
    if not pairs:
        return AgreementResult()
    sensor = np.array([p[0] for p in pairs], dtype=float)
    ref = np.array([p[1] for p in pairs], dtype=float)
    diff = sensor - ref
    n = len(pairs)
    res = AgreementResult(n=n)
    res.mae = float(np.mean(np.abs(diff)))
    res.rmse = float(np.sqrt(np.mean(diff ** 2)))
    res.bias = float(np.mean(diff))
    res.sd = float(np.std(diff, ddof=1)) if n > 1 else 0.0
    res.loa_low = res.bias - 1.96 * res.sd
    res.loa_high = res.bias + 1.96 * res.sd
    if n > 1:
        if np.std(sensor) > 0 and np.std(ref) > 0:
            res.pearson_r = float(np.corrcoef(sensor, ref)[0, 1])
        else:
            res.pearson_r = float("nan")
    res.points = list(zip(((s + r) / 2.0 for s, r in pairs), (float(d) for d in diff)))
    return res


def bland_altman_lines(res: AgreementResult) -> Tuple[float, float, float]:
    """(mean_bias, loa_low, loa_high) for drawing the Bland-Altman plot."""
    return res.bias, res.loa_low, res.loa_high
