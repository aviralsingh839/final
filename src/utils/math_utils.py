"""Small numerical helpers."""
from __future__ import annotations

import math
from typing import Iterable

import numpy as np


def sigmoid(x: float | np.ndarray) -> float | np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(x, -60, 60)))


def clamp(x: float, low: float, high: float) -> float:
    if x is None or math.isnan(float(x)):
        return low
    return float(max(low, min(high, x)))


def safe_mean(values: Iterable[float], default: float = 0.0) -> float:
    arr = np.asarray([v for v in values if v is not None and np.isfinite(v)], dtype=float)
    if arr.size == 0:
        return default
    return float(np.mean(arr))


def safe_std(values: Iterable[float], default: float = 0.0) -> float:
    arr = np.asarray([v for v in values if v is not None and np.isfinite(v)], dtype=float)
    if arr.size < 2:
        return default
    return float(np.std(arr, ddof=1))


def zscore(value: float | None, baseline: float, scale: float, clip: float = 4.0) -> float:
    if value is None or not np.isfinite(value) or scale <= 0:
        return 0.0
    return float(np.clip((value - baseline) / scale, -clip, clip))


def rescale_0_100(x: float, low: float, high: float) -> float:
    if high <= low:
        return 0.0
    return clamp(100.0 * (x - low) / (high - low), 0.0, 100.0)
