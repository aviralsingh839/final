"""PPG processing: filtering, peak detection, HR and HRV."""
from __future__ import annotations

from collections import deque
from typing import Deque, Tuple

import numpy as np

from src.config import MAX_HR_BPM, MIN_HR_BPM, PPG_FS_HZ
from src.signal_processing.filters import DCBlocker, ExponentialSmoother
from src.signal_processing.hrv import hrv_time_domain
from src.signal_processing.spo2 import estimate_spo2
from src.utils.quality import ppg_quality


class PPGProcessor:
    def __init__(self, history_s: float = 180.0, fs_hz: float = PPG_FS_HZ):
        self.fs_hz = fs_hz
        self.maxlen = int(history_s * fs_hz)
        self.times: Deque[float] = deque(maxlen=self.maxlen)
        self.ir_raw: Deque[float] = deque(maxlen=self.maxlen)
        self.red_raw: Deque[float] = deque(maxlen=self.maxlen)
        self.ir_filt: Deque[float] = deque(maxlen=self.maxlen)
        self._dc = DCBlocker(r=0.97)
        self._smooth = ExponentialSmoother(alpha=0.35)
        self.last_peaks: list[float] = []
        self.last_ibi_s: list[float] = []

    def add_sample(self, timestamp_s: float, ir: int, red: int) -> None:
        # Prime the DC blocker from the first sample so its initial condition
        # does not create a synthetic step transient (which previously made the
        # peak detector blind for the first ~20 s of every session).
        if not self.times:
            self._dc.x_prev = float(ir)
            self._dc.y_prev = 0.0
        y = self._dc.update(float(ir))
        y = self._smooth.update(y)
        self.times.append(float(timestamp_s))
        self.ir_raw.append(float(ir))
        self.red_raw.append(float(red))
        self.ir_filt.append(float(y))

    def waveform(self, last_s: float = 20.0) -> Tuple[np.ndarray, np.ndarray]:
        if not self.times:
            return np.array([]), np.array([])
        t = np.asarray(self.times, dtype=float)
        y = np.asarray(self.ir_filt, dtype=float)
        mask = t >= (t[-1] - last_s)
        return t[mask] - t[-1], y[mask]

    def _detect_peaks(self, window_s: float = 20.0) -> list[float]:
        if len(self.times) < int(5 * self.fs_hz):
            return []
        t = np.asarray(self.times, dtype=float)
        y = np.asarray(self.ir_filt, dtype=float)
        mask = t >= (t[-1] - window_s)
        t = t[mask]
        y = y[mask]
        if y.size < 20:
            return []
        # Skip the warm-up segment (first 2 s) as a safety net against any
        # residual filter transient contaminating the median/percentile scale.
        warmup = int(2 * self.fs_hz)
        if y.size > warmup + 10:
            t, y = t[warmup:], y[warmup:]
        y = y - np.median(y)
        noise = np.std(y)
        if noise < 1e-6:
            return []
        threshold = max(np.median(y) + 0.45 * noise, np.percentile(y, 60))
        min_distance_s = 60.0 / MAX_HR_BPM
        peaks: list[float] = []
        last_peak_t = -1e9
        # Local maximum detection with refractory period.
        for i in range(1, y.size - 1):
            if y[i] > threshold and y[i] >= y[i - 1] and y[i] > y[i + 1]:
                if t[i] - last_peak_t >= min_distance_s:
                    peaks.append(float(t[i]))
                    last_peak_t = float(t[i])
                else:
                    # If the new peak is higher within refractory period, replace previous.
                    if peaks and y[i] > y[np.argmin(np.abs(t - peaks[-1]))]:
                        peaks[-1] = float(t[i])
                        last_peak_t = float(t[i])
        return peaks

    def features(self, motion_index: float = 0.0) -> dict[str, float | None]:
        peaks = self._detect_peaks()
        self.last_peaks = peaks
        if len(peaks) >= 3:
            ibi = np.diff(peaks)
            ibi = ibi[(ibi >= 60.0 / MAX_HR_BPM) & (ibi <= 60.0 / MIN_HR_BPM)]
            if ibi.size:
                med = np.median(ibi)
                ibi = ibi[np.abs(ibi - med) < 0.25 * med]
            self.last_ibi_s = ibi.tolist()
        else:
            self.last_ibi_s = []

        hrv = hrv_time_domain(self.last_ibi_s)
        hr = hrv.get("mean_hr_bpm")

        # SpO2 and pulse-envelope amplitude from recent 12-second window.
        n = int(12 * self.fs_hz)
        recent_ir = np.asarray(list(self.ir_raw)[-n:], dtype=float)
        recent_red = list(self.red_raw)[-n:]
        spo2, spo2_q = estimate_spo2(recent_red, recent_ir)
        if recent_ir.size >= 10:
            ppg_amp = float((np.percentile(recent_ir, 95) - np.percentile(recent_ir, 5)) / max(np.median(recent_ir), 1.0))
        else:
            ppg_amp = None
        q = ppg_quality(recent_ir, recent_red, motion_index=motion_index, fs_hz=self.fs_hz)
        q = float(0.7 * q + 0.3 * spo2_q)

        return {
            "hr_bpm": hr,
            "spo2_pct": spo2,
            "rmssd_ms": hrv.get("rmssd_ms"),
            "sdnn_ms": hrv.get("sdnn_ms"),
            "pnn50_pct": hrv.get("pnn50_pct"),
            "ppg_pulse_amplitude": ppg_amp,
            "ppg_quality": q,
        }
