"""Periodic ECG checkpoint workflow (V5, section 4).

A short, standardised ECG session (default suggested cadence: every 7 days,
configurable, and described as a *research monitoring checkpoint*, never a
required medical ECG). The session records 30-60 s of single-lead ECG,
computes HR / RR / HRV features, stores the result in a local history file,
and compares it against the wearer's previous checkpoints and personal
baseline.

This module does not diagnose arrhythmias and makes no medical claims.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import numpy as np

from src.config import DATA_DIR
from src.utils.math_utils import clamp


@dataclass
class ECGCheckpointResult:
    session_id: str
    started_at: float
    duration_s: float
    fs_hz: float
    n_samples: int
    quality: float                # 0..1
    hr_bpm: Optional[float]
    rmssd_ms: Optional[float]
    sdnn_ms: Optional[float]
    n_beats: int
    notes: str = ""

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def _bandpass(x: np.ndarray, fs: float, lo: float = 5.0, hi: float = 30.0) -> np.ndarray:
    """Butterworth bandpass (scipy if available, else a simple FIR fallback)."""
    try:
        from scipy import signal

        sos = signal.butter(2, [lo / (fs / 2), hi / (fs / 2)], btype="bandpass", output="sos")
        return signal.sosfiltfilt(sos, x)
    except Exception:
        # Light FIR approximation (moving average of differences) - adequate for
        # peak counting on clean demo/checkpoint signals.
        k = max(3, int(fs / hi))
        kernel = np.ones(k) / k
        d = np.diff(x, prepend=x[0])
        return np.convolve(d, kernel, mode="same")


class ECGCheckpointSession:
    """One 30-60 s recording. Feed samples, then call `complete()`."""

    def __init__(self, fs_hz: float = 256.0, session_id: Optional[str] = None):
        self.fs_hz = fs_hz
        self.session_id = session_id or time.strftime("ecg_%Y%m%d_%H%M%S")
        self.started_at = time.time()
        self._ts: List[float] = []
        self._raw: List[float] = []
        self.completed = False

    def add_sample(self, timestamp_s: float, raw: float) -> None:
        if raw is None or not np.isfinite(float(raw)):
            return
        self._ts.append(float(timestamp_s))
        self._raw.append(float(raw))

    def add_stream(self, samples: List[tuple]) -> None:
        for ts, raw in samples:
            self.add_sample(ts, raw)

    def complete(self) -> ECGCheckpointResult:
        y = np.asarray(self._raw, dtype=float)
        result = ECGCheckpointResult(
            session_id=self.session_id,
            started_at=self.started_at,
            duration_s=(self._ts[-1] - self._ts[0]) if len(self._ts) > 1 else 0.0,
            fs_hz=self.fs_hz,
            n_samples=len(self._raw),
            quality=0.0,
            hr_bpm=None,
            rmssd_ms=None,
            sdnn_ms=None,
            n_beats=0,
        )
        self.completed = True
        if len(y) < int(5 * self.fs_hz) or np.std(y) < 1e-6:
            result.notes = "Too little / flat signal."
            return result

        filt = _bandpass(y, self.fs_hz)
        peaks = self._r_peaks(filt)
        if len(peaks) >= 4:
            ibi = np.diff(peaks)
            ibi = ibi[(ibi >= 0.28) & (ibi <= 2.0)]  # 30-214 bpm
            if ibi.size >= 3:
                med = float(np.median(ibi))
                clean = ibi[np.abs(ibi - med) < 0.20 * med]
                result.n_beats = int(len(peaks))
                result.hr_bpm = 60.0 / med
                result.rmssd_ms = float(np.sqrt(np.mean(np.diff(clean) ** 2))) * 1000.0
                result.sdnn_ms = float(np.std(clean)) * 1000.0
                result.quality = clamp(len(clean) / max(1, len(ibi)) * 0.8 + 0.2, 0.0, 1.0)
        if result.quality < 0.5:
            result.notes = "Low quality: noisy or irregular signal - consider repeating."
        return result

    def _r_peaks(self, y: np.ndarray) -> np.ndarray:
        thr = np.percentile(y, 92)
        min_dist = int(0.28 * self.fs_hz)  # max 214 bpm
        peaks = []
        last = -1e9
        for i in range(1, len(y) - 1):
            if y[i] > thr and y[i] >= y[i - 1] and y[i] > y[i + 1] and (i - last) >= min_dist:
                peaks.append(i)
                last = i
        return np.asarray(peaks, dtype=float) / self.fs_hz


class CheckpointHistory:
    """Local JSON history of ECG checkpoints + comparison to the latest one."""

    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path else DATA_DIR / "ecg_checkpoints.json"
        self._entries: List[dict] = []
        self._load()

    def _load(self) -> None:
        try:
            if self.path.exists():
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    self._entries = data
        except Exception:
            self._entries = []

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._entries, indent=2), encoding="utf-8")

    def add(self, result: ECGCheckpointResult) -> None:
        self._entries.append(result.as_dict())
        self._entries.sort(key=lambda e: e["started_at"])
        if len(self._entries) > 200:
            self._entries = self._entries[-200:]
        self.save()

    def entries(self) -> List[dict]:
        return list(self._entries)

    def latest(self) -> Optional[dict]:
        return self._entries[-1] if self._entries else None

    def changes_from_previous(self) -> dict:
        """Deltas between the two most recent checkpoints (None when not enough)."""
        if len(self._entries) < 2:
            return {}
        prev, cur = self._entries[-2], self._entries[-1]
        out: dict = {}
        for key in ("hr_bpm", "rmssd_ms", "sdnn_ms", "quality"):
            if cur.get(key) is not None and prev.get(key) is not None:
                out[f"{key}_delta"] = round(float(cur[key]) - float(prev[key]), 2)
        out["days_between"] = round((cur["started_at"] - prev["started_at"]) / 86400.0, 1)
        return out


class SimulatedECGCheckpoint:
    """Synthetic single-lead ECG at a known HR (demo / tests)."""

    def __init__(self, fs_hz: float = 256.0, hr_bpm: float = 72.0, duration_s: float = 40.0):
        self.fs_hz = fs_hz
        self.hr_bpm = hr_bpm
        self.duration_s = duration_s

    def stream(self, t0: float = 0.0) -> List[tuple]:
        n = int(self.duration_s * self.fs_hz)
        out = []
        rng = np.random.default_rng(3)
        for i in range(n):
            t = t0 + i / self.fs_hz
            beat = (t * self.hr_bpm / 60.0) % 1.0
            # QRS-like pulse (sharp), slight P/T humps.
            qrs = np.exp(-((beat - 0.15) ** 2) / 0.0009)
            p = 0.06 * np.exp(-((beat - 0.0) ** 2) / 0.004)
            t_wave = 0.12 * np.exp(-((beat - 0.55) ** 2) / 0.01)
            raw = 400.0 + 260.0 * qrs + 60.0 * p + 40.0 * t_wave + rng.normal(0, 3.0)
            out.append((t, raw))
        return out
