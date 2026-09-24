"""Heart-rate variability feature extraction."""
from __future__ import annotations

from collections import deque
from typing import Deque, Iterable

import numpy as np

from src.config import MAX_IBI_S, MIN_IBI_S


def clean_ibi_seconds(ibi_s: Iterable[float]) -> np.ndarray:
    arr = np.asarray(list(ibi_s), dtype=float)
    arr = arr[np.isfinite(arr)]
    arr = arr[(arr >= MIN_IBI_S) & (arr <= MAX_IBI_S)]
    if arr.size < 3:
        return arr
    med = np.median(arr)
    arr = arr[np.abs(arr - med) < 0.25 * med]
    return arr


def hrv_time_domain(ibi_s: Iterable[float]) -> dict[str, float | None]:
    nn = clean_ibi_seconds(ibi_s)
    if nn.size < 3:
        return {"rmssd_ms": None, "sdnn_ms": None, "pnn50_pct": None, "mean_hr_bpm": None}
    diff = np.diff(nn)
    rmssd_ms = float(np.sqrt(np.mean(diff * diff)) * 1000.0)
    sdnn_ms = float(np.std(nn, ddof=1) * 1000.0) if nn.size > 1 else None
    pnn50_pct = float(np.mean(np.abs(diff) > 0.050) * 100.0) if diff.size else None
    mean_hr_bpm = float(60.0 / np.median(nn))
    return {
        "rmssd_ms": rmssd_ms,
        "sdnn_ms": sdnn_ms,
        "pnn50_pct": pnn50_pct,
        "mean_hr_bpm": mean_hr_bpm,
    }


class HRVBuffer:
    def __init__(self, max_beats: int = 600):
        self.ibi_s: Deque[float] = deque(maxlen=max_beats)

    def add_ibi(self, ibi_s: float) -> None:
        if MIN_IBI_S <= ibi_s <= MAX_IBI_S:
            if self.ibi_s:
                last = self.ibi_s[-1]
                if abs(ibi_s - last) > 0.35 * last:
                    return
            self.ibi_s.append(float(ibi_s))

    def features(self, last_n_beats: int = 80) -> dict[str, float | None]:
        return hrv_time_domain(list(self.ibi_s)[-last_n_beats:])
