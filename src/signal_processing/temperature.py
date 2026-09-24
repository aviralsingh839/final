"""Skin temperature trend extraction."""
from __future__ import annotations

from collections import deque
from typing import Deque

import numpy as np

from src.config import DEFAULT_SKIN_TEMP_C
from src.utils.math_utils import clamp


class TemperatureProcessor:
    def __init__(self, history_s: float = 24 * 3600):
        self.maxlen = int(history_s)  # 1 Hz expected
        self.times: Deque[float] = deque(maxlen=self.maxlen)
        self.temp: Deque[float] = deque(maxlen=self.maxlen)
        self.baseline = DEFAULT_SKIN_TEMP_C

    def add_sample(self, timestamp_s: float, temp_c: float) -> None:
        if not np.isfinite(temp_c) or temp_c < 15 or temp_c > 45:
            return
        self.times.append(float(timestamp_s))
        self.temp.append(float(temp_c))
        if len(self.temp) > 60:
            self.baseline = 0.999 * self.baseline + 0.001 * float(np.median(self.temp))

    def features(self, window_s: float = 300.0) -> dict[str, float | None]:
        if len(self.times) < 2:
            return {"skin_temp_c": None, "temp_slope_c_per_min": 0.0, "temp_stability": 0.0}
        t = np.asarray(self.times)
        y = np.asarray(self.temp)
        mask = t >= (t[-1] - window_s)
        tw = t[mask]
        yw = y[mask]
        if yw.size < 2:
            return {"skin_temp_c": float(y[-1]), "temp_slope_c_per_min": 0.0, "temp_stability": 0.0}
        # Linear slope in C/min.
        x_min = (tw - tw[0]) / 60.0
        if np.ptp(x_min) < 1e-6:
            slope = 0.0
        else:
            slope = float(np.polyfit(x_min, yw, 1)[0])
        stability = clamp(1.0 - float(np.std(yw)) / 0.5, 0.0, 1.0)
        return {
            "skin_temp_c": float(y[-1]),
            "temp_slope_c_per_min": slope,
            "temp_stability": stability,
        }
