"""Simple ECG processor for AD8232 analog signal.

This is only for beat timing / HRV education, not for ECG diagnosis.
"""
from __future__ import annotations

from collections import deque
from typing import Deque

import numpy as np

from src.config import MAX_HR_BPM, MIN_HR_BPM
from src.signal_processing.filters import DCBlocker, ExponentialSmoother
from src.signal_processing.hrv import hrv_time_domain
from src.utils.math_utils import clamp


class ECGProcessor:
    def __init__(self, history_s: float = 180.0, fs_hz: float = 50.0):
        self.fs_hz = fs_hz
        self.maxlen = int(history_s * fs_hz)
        self.times: Deque[float] = deque(maxlen=self.maxlen)
        self.raw: Deque[float] = deque(maxlen=self.maxlen)
        self.filt: Deque[float] = deque(maxlen=self.maxlen)
        self._dc = DCBlocker(r=0.985)
        self._smooth = ExponentialSmoother(alpha=0.45)

    def add_sample(self, timestamp_s: float, raw: int) -> None:
        if raw is None or raw < 0:
            return
        # Prime the DC blocker from the first sample to avoid a warm-up step
        # transient that would blind R-peak detection early in a session.
        if not self.times:
            self._dc.x_prev = float(raw)
            self._dc.y_prev = 0.0
        y = self._dc.update(float(raw))
        y = self._smooth.update(y)
        self.times.append(float(timestamp_s))
        self.raw.append(float(raw))
        self.filt.append(float(y))

    def _detect_r_peaks(self, window_s: float = 30.0) -> list[float]:
        if len(self.times) < int(5 * self.fs_hz):
            return []
        t = np.asarray(self.times, dtype=float)
        y = np.asarray(self.filt, dtype=float)
        mask = t >= (t[-1] - window_s)
        t, y = t[mask], y[mask]
        if y.size < 20 or np.std(y) < 1e-6:
            return []
        # AD8232 polarity can vary; use absolute robust derivative/envelope style.
        z = y - np.median(y)
        if abs(np.min(z)) > abs(np.max(z)):
            z = -z
        threshold = np.percentile(z, 92)
        min_dist = 60.0 / MAX_HR_BPM
        peaks = []
        last_t = -1e9
        for i in range(1, len(z) - 1):
            if z[i] > threshold and z[i] >= z[i - 1] and z[i] > z[i + 1] and (t[i] - last_t) >= min_dist:
                peaks.append(float(t[i]))
                last_t = float(t[i])
        return peaks

    def features(self) -> dict[str, float | None]:
        peaks = self._detect_r_peaks()
        quality = 0.0
        if len(peaks) >= 4:
            ibi = np.diff(peaks)
            ibi = ibi[(ibi >= 60.0 / MAX_HR_BPM) & (ibi <= 60.0 / MIN_HR_BPM)]
            if ibi.size >= 3:
                med = np.median(ibi)
                clean = ibi[np.abs(ibi - med) < 0.20 * med]
                hrv = hrv_time_domain(clean)
                quality = clamp(len(clean) / max(1, len(ibi)) * 0.8 + 0.2, 0.0, 1.0)
                return {
                    "ecg_hr_bpm": hrv.get("mean_hr_bpm"),
                    "ecg_rmssd_ms": hrv.get("rmssd_ms"),
                    "ecg_sdnn_ms": hrv.get("sdnn_ms"),
                    "ecg_quality": quality,
                }
        return {"ecg_hr_bpm": None, "ecg_rmssd_ms": None, "ecg_sdnn_ms": None, "ecg_quality": quality}
