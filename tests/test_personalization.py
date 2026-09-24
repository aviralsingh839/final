import time

import numpy as np

from src.data_models import FeatureVector
from src.models.personalization import BaselineManager


def _make_features(n: int = 300, hr: float = 72.0, jitter: float = 2.0):
    t0 = time.time()
    out = []
    for i in range(n):
        f = FeatureVector(
            timestamp_s=t0 + i,
            hr_bpm=float(hr + np.random.normal(0, jitter)),
            rmssd_ms=float(40 + np.random.normal(0, 4)),
            skin_temp_c=float(32.5 + np.random.normal(0, 0.05)),
            gsr_tonic=float(450 + np.random.normal(0, 20)),
            activity_level=10.0,
            signal_quality=0.8,
        )
        out.append(f)
    return out


def test_capture_baseline_creates_ranges(tmp_path):
    mgr = BaselineManager(path=tmp_path / "baseline.json", history_path=tmp_path / "history.json")
    bl = mgr.capture_from_features(_make_features())
    assert mgr.has_baseline
    assert "hr_bpm" in bl.stats
    rng = mgr.normal_range("hr_bpm")
    assert rng is not None and rng[0] < 72.0 < rng[1]
    assert abs(mgr.zscore("hr_bpm", 72.0)) < 1.0
    assert len(mgr.history()) == 1


def test_baseline_persists(tmp_path):
    path = tmp_path / "baseline.json"
    hpath = tmp_path / "history.json"
    mgr = BaselineManager(path=path, history_path=hpath)
    mgr.capture_from_features(_make_features())
    mgr2 = BaselineManager(path=path, history_path=hpath)
    assert mgr2.has_baseline
    assert abs(mgr2.normal_range("hr_bpm")[0] - mgr.normal_range("hr_bpm")[0]) < 1e-3


def test_capture_requires_samples(tmp_path):
    mgr = BaselineManager(path=tmp_path / "b.json", history_path=tmp_path / "h.json")
    try:
        mgr.capture_from_features([FeatureVector(timestamp_s=time.time(), hr_bpm=70)], min_samples=60)
        assert False, "expected ValueError"
    except ValueError:
        pass
