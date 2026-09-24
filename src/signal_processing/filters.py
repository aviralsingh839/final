"""Lightweight streaming filters that do not require SciPy."""
from __future__ import annotations

from collections import deque
from typing import Deque

import numpy as np


class MovingAverage:
    def __init__(self, n: int):
        self.n = int(max(1, n))
        self.buf: Deque[float] = deque(maxlen=self.n)

    def update(self, x: float) -> float:
        self.buf.append(float(x))
        return float(np.mean(self.buf))


class ExponentialSmoother:
    def __init__(self, alpha: float = 0.2):
        self.alpha = float(np.clip(alpha, 0.001, 1.0))
        self.y: float | None = None

    def update(self, x: float) -> float:
        x = float(x)
        if self.y is None:
            self.y = x
        else:
            self.y = self.alpha * x + (1.0 - self.alpha) * self.y
        return float(self.y)


class DCBlocker:
    """Simple high-pass/DC-blocking filter.

    y[n] = x[n] - x[n-1] + r*y[n-1]
    """

    def __init__(self, r: float = 0.96):
        self.r = float(np.clip(r, 0.8, 0.999))
        self.x_prev = 0.0
        self.y_prev = 0.0

    def update(self, x: float) -> float:
        y = float(x) - self.x_prev + self.r * self.y_prev
        self.x_prev = float(x)
        self.y_prev = y
        return y


def robust_detrend(values) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    if arr.size == 0:
        return arr
    return arr - np.nanmedian(arr)


def rolling_rms(values) -> float:
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(arr * arr)))
