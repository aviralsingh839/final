import time

import numpy as np

from src.data_models import FeatureVector
from src.models.anomaly_detector import AnomalyDetector
from src.models.personalization import BaselineManager


def _mk(t: float, hr: float, temp: float = 32.5) -> FeatureVector:
    f = FeatureVector(timestamp_s=t, hr_bpm=hr, rmssd_ms=40.0, skin_temp_c=temp,
                      gsr_tonic=450.0, motion_index=0.05)
    return f


def test_no_anomaly_within_baseline(tmp_path):
    base = BaselineManager(path=tmp_path / "b.json", history_path=tmp_path / "h.json")
    features = []
    t0 = time.time()
    for i in range(120):
        f = _mk(t0 + i, 72 + np.random.normal(0, 1.5))
        f.signal_quality = 0.8
        features.append(f)
    base.capture_from_features(features)
    det = AnomalyDetector(base)
    det.evaluate(_mk(t0 + 200, 73.0), now=t0 + 200)
    anomalies, score = det.evaluate(_mk(t0 + 201, 72.5), now=t0 + 201)
    assert not anomalies
    assert score == 0.0


def test_hr_outlier_raises_anomaly(tmp_path):
    base = BaselineManager(path=tmp_path / "b.json", history_path=tmp_path / "h.json")
    features = []
    t0 = time.time()
    for i in range(120):
        f = _mk(t0 + i, 72 + np.random.normal(0, 1.5))
        f.signal_quality = 0.8
        features.append(f)
    base.capture_from_features(features)
    det = AnomalyDetector(base)
    det.evaluate(_mk(t0 + 200, 72.0), now=t0 + 200)
    anomalies, score = det.evaluate(_mk(t0 + 201, 120.0), now=t0 + 201)
    assert anomalies, "expected an anomaly for a large HR deviation"
    assert score > 0.0
    assert any(a.signal == "hr_bpm" for a in anomalies)
