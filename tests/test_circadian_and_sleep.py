import time

import numpy as np

from src.data_models import FeatureVector
from src.features.circadian_features import CircadianAnalyzer
from src.models.sleep_model import SleepEstimator


def test_circadian_metrics_include_hrv_and_gsr():
    t0 = time.time()
    features = []
    for i in range(24 * 60):
        hour = (i / 60.0) % 24.0
        f = FeatureVector(
            timestamp_s=t0 + i * 60.0,
            hr_bpm=60.0 + 15.0 * np.sin(2 * np.pi * hour / 24.0),
            rmssd_ms=40.0 + 15.0 * np.sin(2 * np.pi * hour / 24.0),
            skin_temp_c=32.0 + 1.0 * np.sin(2 * np.pi * (hour - 6) / 24.0),
            gsr_tonic=450.0 + 80.0 * np.sin(2 * np.pi * (hour - 12) / 24.0),
            activity_level=40.0,
            sleep_probability=80.0 if (hour >= 22 or hour <= 7) else 20.0,
            lux=200.0 if 7 <= hour <= 18 else 1.0,
        )
        features.append(f)
    m = CircadianAnalyzer().analyze(features)
    assert m.hrv_r2 > 0.3
    assert m.gsr_r2 > 0.3
    assert m.stability_index > 0


def test_sleep_window_narrows_prior():
    """A user-entered window that is narrower than the default 22-07 prior lowers
    the sleep probability outside the window (e.g. late evening before a late
    sleep onset) and keeps it inside the window."""
    est = SleepEstimator()
    fv = FeatureVector(hr_bpm=60, rmssd_ms=55, motion_index=0.02, gsr_tonic=400,
                       temp_slope_c_per_min=0.0, spo2_pct=97)
    default_late = est.estimate_epoch(fv, hour_of_day=23.0)["sleep_probability"]
    windowed_late = est.estimate_epoch(fv, hour_of_day=23.0, sleep_onset_h=2.0, wake_h=6.0)["sleep_probability"]
    assert windowed_late < default_late
    inside = est.estimate_epoch(fv, hour_of_day=4.0, sleep_onset_h=2.0, wake_h=6.0)["sleep_probability"]
    assert inside >= 90.0
