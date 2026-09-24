"""Experimental VoxVasc / voice biomarker model.

This module must be presented as experimental. It does not measure androgen or
PCOS. It only reports a weak vocal feature score based on pitch and microphone
energy when optional MAX4466/laptop WAV features are available.
"""
from __future__ import annotations

import wave
from pathlib import Path
from typing import Tuple

import numpy as np

from src.utils.math_utils import clamp, sigmoid


def estimate_pitch_autocorr(signal: np.ndarray, fs: int, fmin: float = 80.0, fmax: float = 350.0) -> float | None:
    x = np.asarray(signal, dtype=float)
    if x.size < fs * 0.2:
        return None
    x = x - np.mean(x)
    if np.std(x) < 1e-6:
        return None
    # Use central 1 second max for speed.
    if x.size > fs:
        mid = x.size // 2
        x = x[mid - fs // 2 : mid + fs // 2]
    corr = np.correlate(x, x, mode="full")[len(x) - 1 :]
    min_lag = int(fs / fmax)
    max_lag = int(fs / fmin)
    if max_lag >= len(corr):
        max_lag = len(corr) - 1
    if min_lag >= max_lag:
        return None
    lag = min_lag + int(np.argmax(corr[min_lag:max_lag]))
    if lag <= 0:
        return None
    return float(fs / lag)


def wav_features(path: str | Path) -> dict[str, float | None]:
    with wave.open(str(path), "rb") as wf:
        fs = wf.getframerate()
        n = wf.getnframes()
        ch = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        raw = wf.readframes(n)
    if sampwidth == 1:
        x = np.frombuffer(raw, dtype=np.uint8).astype(float) - 128.0
    elif sampwidth == 2:
        x = np.frombuffer(raw, dtype=np.int16).astype(float)
    else:
        return {"pitch_hz": None, "rms": None, "jitter_proxy": None}
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    rms = float(np.sqrt(np.mean((x - np.mean(x)) ** 2)))
    pitch = estimate_pitch_autocorr(x, fs)
    return {"pitch_hz": pitch, "rms": rms, "jitter_proxy": None}


class VoiceVascEstimator:
    """Weak experimental score.

    Lower sustained pitch can be associated with androgen exposure across
    populations, but individual prediction is poor. This is kept at low weight.
    """

    def score(self, pitch_hz: float | None, mic_rms: float | None = None) -> tuple[float, str]:
        if pitch_hz is None or pitch_hz <= 0:
            return 0.0, "No valid voice pitch; VoxVasc score disabled."
        # For adolescent/adult female voices, sustained vowel F0 often falls roughly 165-255 Hz.
        # Low pitch alone is NOT PCOS-specific. The score is only a low-confidence proxy.
        low_pitch_score = 100.0 * sigmoid((190.0 - pitch_hz) / 18.0)
        energy_quality = 1.0 if mic_rms is None else clamp((mic_rms - 8.0) / 40.0, 0.0, 1.0)
        score = low_pitch_score * energy_quality
        explanation = (
            f"Experimental voice proxy: pitch ≈ {pitch_hz:.1f} Hz. "
            "Low pitch can increase this weak proxy, but it is not a hormone measurement."
        )
        return float(clamp(score, 0.0, 100.0)), explanation
