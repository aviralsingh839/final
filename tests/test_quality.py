import numpy as np

from src.utils.quality import PPG_QUALITY_FEATURES, ppg_quality, ppg_window_features


def _pulse_window(dc=60000.0, amp=4000.0, hr_bpm=72.0, fs=50.0, seconds=12.0, seed=0):
    rng = np.random.RandomState(seed)
    t = np.arange(0, seconds, 1 / fs)
    sig = dc + amp * np.sin(2 * np.pi * hr_bpm / 60.0 * t) + 0.2 * amp * np.sin(2 * np.pi * 2 * hr_bpm / 60.0 * t)
    return sig + rng.randn(len(t)) * amp * 0.02


def test_ppg_quality_bounded():
    for sig in [_pulse_window(), np.array([60000.0] * 600), np.array([1000.0] * 600), np.array([60000.0] * 50)]:
        q = ppg_quality(sig, None, motion_index=0.1, fs_hz=50.0)
        assert 0.0 <= q <= 1.0


def test_ppg_quality_orders_clean_above_noisy():
    fs = 50.0
    t = np.arange(0, 12, 1 / fs)
    dc = 60000.0
    clean = dc + 4000 * np.sin(2 * np.pi * 1.2 * t)
    rng = np.random.RandomState(1)
    noisy = dc + 2500 * np.sin(2 * np.pi * 1.2 * t) + rng.randn(len(t)) * 6000
    q_clean = ppg_quality(clean, None, motion_index=0.02, fs_hz=fs)
    q_noisy = ppg_quality(noisy, None, motion_index=0.6, fs_hz=fs)
    assert q_clean > q_noisy


def test_ppg_window_features_shape_and_hr():
    fs = 50.0
    f = ppg_window_features(_pulse_window(fs=fs), None, motion_index=0.02, fs_hz=fs)
    assert list(f.keys()) == PPG_QUALITY_FEATURES
    assert abs(f["ppg_dominant_hr_bpm"] - 72.0) < 6.0
    assert f["ppg_regularity"] > 0.5


def test_ppg_quality_short_window_falls_back_to_heuristic():
    # Too short for the model feature vector; must still return a bounded score.
    q = ppg_quality(np.array([60000.0] * 100), None, fs_hz=50.0)
    assert 0.0 <= q <= 1.0
