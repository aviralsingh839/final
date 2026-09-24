"""Signal-quality scoring utilities.

`ppg_quality()` returns a 0-1 PPG quality score used for the app's overall
signal-quality gate. The base score is a transparent heuristic (amplitude,
saturation, motion). If a trained model exists at `models/ppg_quality_model.joblib`
(see scripts/train_ppg_quality_model.py), the score is blended with the model's
probability that the window's PPG HR estimate is reliable (|PPG HR - ECG HR| <= 5 bpm).

The model is trained on wrist-PPG-during-exercise data (different sensor and
sampling rate than the MAX30102), so it is only used as a soft correction term
(40% weight) and the heuristic always remains the dominant component.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from src.config import MAX_ADC_18BIT, MIN_IR_FINGER_PRESENT, PPG_FS_HZ, PPG_SATURATION_MARGIN
from src.utils.math_utils import clamp

_MODEL_PATH = Path(__file__).resolve().parents[2] / "models" / "ppg_quality_model.joblib"
_model_cache: dict = {}


# Feature order must match scripts/train_ppg_quality_model.py exactly.
PPG_QUALITY_FEATURES = [
    "ppg_amp",
    "ppg_amp_cv",
    "ppg_regularity",
    "ppg_dominant_hr_bpm",
    "ppg_band_power",
    "ppg_peak_rate",
    "ppg_hr_bpm",
    "ppg_ibi_rmssd_ms",
    "ppg_ibi_cv",
    "ppg_beat_consistency",
    "ppg_zero_cross_rate",
    "ppg_dom_peak_diff",
    "ppg_half_hr_diff",
    "motion_index",
    "ppg_quality_heuristic",
]


def _autocorr_hr(x: np.ndarray, fs_hz: float, lo_bpm: float = 40.0, hi_bpm: float = 210.0) -> tuple[float, float]:
    """Dominant HR (bpm) and regularity from the normalized autocorrelation of
    a band-passed signal. Returns (hr, regularity); regularity ~1 for a clean
    periodic pulse, ~0 for motion artifact."""
    y = x - np.mean(x)
    if np.std(y) < 1e-9 or len(y) < int(2 * fs_hz):
        return np.nan, np.nan
    lo = max(1, int(fs_hz * 60.0 / hi_bpm))
    hi = int(fs_hz * 60.0 / lo_bpm)
    if hi - lo < 2:
        return np.nan, np.nan
    ac = np.correlate(y, y, mode="full")[len(y) - 1:]
    ac = ac / max(ac[0], 1e-12)
    seg = ac[lo:hi + 1]
    k = int(np.argmax(seg))
    if k == 0 or k == len(seg) - 1:
        return np.nan, np.nan  # peak at edge: no clear periodicity
    a, b, c = seg[k - 1], seg[k], seg[k + 1]
    den = a - 2 * b + c
    d = 0.5 * (a - c) / den if abs(den) > 1e-9 else 0.0
    d = max(-1.0, min(1.0, d))
    lag = lo + k + d
    hr = 60.0 * fs_hz / lag
    if not (lo_bpm <= hr <= hi_bpm):
        return np.nan, np.nan
    return hr, float(seg[k])


def _heuristic_quality(ir_values, red_values=None, motion_index: float = 0.0) -> float:
    """Return 0-1 PPG quality based on amplitude, saturation, and motion.

    This is a heuristic, not a certified signal-quality index.
    """
    ir = np.asarray(ir_values, dtype=float)
    if ir.size < 10:
        return 0.0
    finite = np.isfinite(ir)
    if finite.mean() < 0.95:
        return 0.0
    ir = ir[finite]
    dc = float(np.median(ir))
    ac = float(np.percentile(ir, 95) - np.percentile(ir, 5))
    if dc < MIN_IR_FINGER_PRESENT:
        return 0.0
    amp_score = clamp((ac - 100.0) / 1500.0, 0.0, 1.0)
    saturation_score = 0.0 if dc > MAX_ADC_18BIT - PPG_SATURATION_MARGIN else 1.0
    motion_penalty = clamp(1.0 - motion_index / 1.5, 0.0, 1.0)
    return float(clamp(0.55 * amp_score + 0.30 * saturation_score + 0.15 * motion_penalty, 0.0, 1.0))


def _dc_block(x: np.ndarray, r: float = 0.97) -> np.ndarray:
    """Stateless version of src.signal_processing.filters.DCBlocker."""
    y = np.empty_like(x, dtype=float)
    x_prev, y_prev = 0.0, 0.0
    for i in range(len(x)):
        v = float(x[i])
        y_prev = v - x_prev + r * y_prev
        x_prev = v
        y[i] = y_prev
    return y


def _exp_smooth(x: np.ndarray, alpha: float = 0.35) -> np.ndarray:
    """Stateless version of src.signal_processing.filters.ExponentialSmoother."""
    y = np.empty_like(x, dtype=float)
    acc = float(x[0]) if len(x) else 0.0
    for i in range(len(x)):
        acc = alpha * float(x[i]) + (1.0 - alpha) * acc
        y[i] = acc
    return y


def _app_style_peaks(ir: np.ndarray, fs_hz: float) -> list[int]:
    """Replicate the peak detector used by src.signal_processing.ppg.PPGProcessor."""
    from src.config import MAX_HR_BPM

    if ir.size < int(3 * fs_hz):
        return []
    y = _dc_block(ir)
    y = _exp_smooth(y)
    y = y - np.median(y)
    noise = float(np.std(y))
    if noise < 1e-6:
        return []
    threshold = max(float(np.median(y) + 0.45 * noise), float(np.percentile(y, 60)))
    min_distance = 60.0 / MAX_HR_BPM
    peaks: list[int] = []
    last_peak = -10 ** 9
    for i in range(1, y.size - 1):
        if y[i] > threshold and y[i] >= y[i - 1] and y[i] > y[i + 1]:
            if i - last_peak >= int(min_distance * fs_hz):
                peaks.append(i)
                last_peak = i
            elif peaks:
                prev = peaks[-1]
                if y[i] > y[prev]:
                    peaks[-1] = i
                    last_peak = i
    return peaks


def ppg_window_features(ir_values, red_values=None, motion_index: float = 0.0, fs_hz: float = PPG_FS_HZ) -> dict:
    """Compute the feature vector consumed by the trained PPG-quality model.

    Mirrors the features the model was trained on; safe to call on live windows.
    NaN entries mean 'not available' (e.g. too few peaks) - the model pipeline
    imputes them.
    """
    ir = np.asarray(ir_values, dtype=float)
    feats: dict = {k: np.nan for k in PPG_QUALITY_FEATURES}
    feats["motion_index"] = float(motion_index)
    feats["ppg_quality_heuristic"] = _heuristic_quality(ir, red_values, motion_index)

    if ir.size < int(4 * fs_hz) or np.isfinite(ir).mean() < 0.9:
        return feats

    dc = float(np.median(ir))
    p5, p95 = float(np.percentile(ir, 5)), float(np.percentile(ir, 95))
    feats["ppg_amp"] = (p95 - p5) / max(dc, 1.0)

    ac = ir - dc
    abs_ac = np.abs(ac)
    mean_abs = float(np.mean(abs_ac))
    feats["ppg_amp_cv"] = float(np.std(abs_ac)) / max(mean_abs, 1e-9)

    # Autocorrelation-based pulse features (robust, sampling-rate friendly).
    n = len(ac)
    win = np.hanning(n)
    spec = np.abs(np.fft.rfft(ac * win)) ** 2
    freqs = np.fft.rfftfreq(n, 1.0 / fs_hz)
    band = (freqs >= 0.5) & (freqs <= 5.0)
    band_power = float(np.sum(spec[band]))
    feats["ppg_band_power"] = band_power / max(dc * dc, 1.0)

    # A light band-pass approximation via FFT masking, then autocorrelation HR.
    ac_bp = np.fft.irfft(np.where(band, np.fft.rfft(ac), 0.0), n)
    dom_hr, regularity = _autocorr_hr(ac_bp, fs_hz)
    feats["ppg_dominant_hr_bpm"] = dom_hr
    feats["ppg_regularity"] = regularity

    # Zero crossings of the AC signal per second.
    signs = np.sign(ac)
    feats["ppg_zero_cross_rate"] = float(np.sum(np.diff(signs) != 0)) / max(n / fs_hz, 1e-9)

    # App-style peak detection -> HR estimate and IBI variability.
    peaks = _app_style_peaks(ir, fs_hz)
    feats["ppg_peak_rate"] = len(peaks) / max(n / fs_hz, 1e-9)
    ibi: np.ndarray | None = None
    if len(peaks) >= 3:
        from src.signal_processing.hrv import clean_ibi_seconds

        ibi = np.diff(peaks) / fs_hz
        ibi = clean_ibi_seconds(ibi)
        if ibi.size:
            med = np.median(ibi)
            feats["ppg_hr_bpm"] = float(60.0 / med)
            feats["ppg_ibi_cv"] = float(np.std(ibi) / max(np.mean(ibi), 1e-9))
            feats["ppg_beat_consistency"] = float(np.mean(np.abs(ibi - med) <= 0.15 * med))
            diff = np.diff(ibi)
            if diff.size:
                feats["ppg_ibi_rmssd_ms"] = float(np.sqrt(np.mean(diff * diff)) * 1000.0)

    if np.isfinite(dom_hr) and np.isfinite(feats["ppg_hr_bpm"]):
        feats["ppg_dom_peak_diff"] = abs(float(dom_hr) - float(feats["ppg_hr_bpm"]))

    # Half-window HR stability (motion artifacts are transient).
    half = n // 2
    if half >= int(2 * fs_hz):
        h1, _ = _autocorr_hr(ac_bp[:half], fs_hz)
        h2, _ = _autocorr_hr(ac_bp[half:], fs_hz)
        if np.isfinite(h1) and np.isfinite(h2):
            feats["ppg_half_hr_diff"] = abs(float(h1) - float(h2))
    return feats


def _load_quality_model():
    if "loaded" in _model_cache:
        return _model_cache.get("model")
    if not _MODEL_PATH.exists():
        _model_cache["loaded"] = True
        _model_cache["model"] = None
        return None
    try:
        import joblib

        bundle = joblib.load(_MODEL_PATH)
        _model_cache["loaded"] = True
        _model_cache["model"] = bundle
        return bundle
    except Exception:
        _model_cache["loaded"] = True
        _model_cache["model"] = None
        return None


def ppg_quality(ir_values, red_values=None, motion_index: float = 0.0, fs_hz: float = PPG_FS_HZ) -> float:
    """Return 0-1 PPG quality based on the heuristic plus (when available) the
    trained model's estimate that the window's HR is reliable."""
    q = _heuristic_quality(ir_values, red_values, motion_index)
    if q <= 0.0:
        return 0.0
    bundle = _load_quality_model()
    if bundle is None:
        return q
    try:
        feats = ppg_window_features(ir_values, red_values, motion_index, fs_hz=fs_hz)
        # Only blend when the window actually produced a feature vector; for a
        # too-short / dead window the model would rely on imputed (median) values.
        n_finite = int(np.isfinite(list(feats.values())).sum())
        if n_finite < 8:
            return q
        import pandas as pd

        row = pd.DataFrame([[feats.get(f, np.nan) for f in bundle.get("feature_names", [])]],
                           columns=bundle.get("feature_names", []))
        p = float(bundle["model"].predict_proba(row)[0, 1])
        return float(clamp(0.6 * q + 0.4 * p, 0.0, 1.0))
    except Exception:
        return q


def completeness_score(*values) -> float:
    if not values:
        return 0.0
    return float(sum(v is not None and np.isfinite(v) for v in values) / len(values))
