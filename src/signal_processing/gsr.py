"""GSR/EDA feature extraction.

Raw analog values are used because low-cost GSR modules differ electrically.
If you know the module resistor network, convert raw ADC to microsiemens and
change `raw_to_conductance` accordingly.
"""
from __future__ import annotations

from collections import deque
from typing import Deque

import numpy as np

from src.config import DEFAULT_GSR_RAW
from src.utils.math_utils import clamp, zscore


class GSRProcessor:
    def __init__(self, history_s: float = 600.0, fs_hz: float = 10.0):
        self.maxlen = int(history_s * fs_hz)
        self.times: Deque[float] = deque(maxlen=self.maxlen)
        self.raw: Deque[float] = deque(maxlen=self.maxlen)
        self.baseline = DEFAULT_GSR_RAW

    def add_sample(self, timestamp_s: float, raw: int) -> None:
        self.times.append(float(timestamp_s))
        self.raw.append(float(raw))
        if len(self.raw) > 50:
            # Slowly update resting baseline toward 20th percentile.
            p20 = float(np.percentile(np.asarray(self.raw), 20))
            self.baseline = 0.995 * self.baseline + 0.005 * p20

    def raw_to_conductance_proxy(self, raw: float) -> float:
        # For common modules, higher analog output often means lower resistance
        # or higher conductance, but verify your module. We use normalized proxy.
        return float(raw)

    def features(self, window_s: float = 60.0) -> dict[str, float | None]:
        if len(self.times) < 5:
            return {"gsr_tonic": None, "gsr_phasic_per_min": 0.0, "gsr_z": 0.0}
        t = np.asarray(self.times)
        raw = np.asarray(self.raw)
        mask = t >= (t[-1] - window_s)
        tw = t[mask]
        x = raw[mask]
        if x.size < 5:
            return {"gsr_tonic": None, "gsr_phasic_per_min": 0.0, "gsr_z": 0.0}
        tonic = float(np.median(x))
        dx = np.diff(x, prepend=x[0])
        # Count phasic responses as quick upward jumps above robust threshold.
        mad = np.median(np.abs(dx - np.median(dx))) + 1e-6
        events = int(np.sum(dx > (np.median(dx) + 4.0 * mad)))
        duration_min = max((tw[-1] - tw[0]) / 60.0, 1e-3)
        phasic_per_min = events / duration_min
        gsr_z = zscore(tonic, self.baseline, 80.0)
        return {
            "gsr_tonic": tonic,
            "gsr_phasic_per_min": float(clamp(phasic_per_min, 0.0, 60.0)),
            "gsr_z": gsr_z,
        }
