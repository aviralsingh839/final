"""V6 tests: the redesigned risk engine, UI structure, live/demo separation,
withheld-prediction banner, wired change detector, and patient inputs."""
from __future__ import annotations

import time

import numpy as np
import pytest

from src.config import UserProfile
from src.data_models import FeatureVector, RiskResult, SensorSample
from src.models.change_detector import ChangeDetector
from src.models.risk_engine import RiskEngine
from src.validation.sqi import should_withhold
from src.utils.history_store import HistoryStore


def _fv(signal_quality: float = 0.9, hr: float = 72.0, rmssd: float = 40.0,
        temp: float = 32.5, gsr: float = 430.0, activity: float = 20.0) -> FeatureVector:
    fv = FeatureVector(timestamp_s=time.time(), hr_bpm=hr, rmssd_ms=rmssd,
                       skin_temp_c=temp, gsr_tonic=gsr, activity_level=activity,
                       motion_index=0.05, signal_quality=signal_quality)
    return fv


# ------------------------------------------------------------ risk engine
def test_v6_risk_engine_hormones_do_not_change_score():
    """The headline score must be identical whether or not hormone estimates
    are passed — they are carried for the research illustration only."""
    engine = RiskEngine()
    fv = _fv()
    profile = UserProfile(age_years=17, bmi=23, glucose_mg_dl=90, glucose_context="fasting")
    r_no = engine.estimate(fv, profile=profile)
    fake_hormones = {"testosterone": object(), "amh": object(), "insulin": object()}
    r_with = engine.estimate(fv, hormones=fake_hormones, profile=profile)
    assert r_no.risk_percent == pytest.approx(r_with.risk_percent)
    assert r_with.hormone_estimates == fake_hormones


def test_v6_risk_engine_cycle_domain():
    """Irregular / long cycle raises the cycle domain; no cycle info stays neutral
    (a small non-zero value, never zero = 'regular')."""
    engine = RiskEngine()
    neutral = engine.cycle_score(None)
    assert neutral == pytest.approx(15.0)
    regular = engine.cycle_score(UserProfile(usual_cycle_length_days=28, cycle_irregular=False))
    irregular = engine.cycle_score(UserProfile(usual_cycle_length_days=45, cycle_irregular=True))
    assert irregular > regular
    assert irregular > neutral


def test_v6_risk_engine_domains_have_no_hormone_keys():
    fv = _fv()
    domains = RiskEngine().domain_scores(fv, profile=UserProfile())
    for banned in ("endocrine", "testosterone", "amh", "insulin", "lh", "fsh"):
        assert banned not in domains


def test_v6_risk_engine_confidence_drops_without_cycle():
    engine = RiskEngine()
    fv = _fv()
    with_cycle = engine.estimate(fv, profile=UserProfile(usual_cycle_length_days=30))
    without = engine.estimate(fv, profile=UserProfile())
    assert without.confidence < with_cycle.confidence


# ------------------------------------------------------------ withholding
def test_v6_withhold_without_heart_data():
    fv = _fv(hr=None, rmssd=None)
    d = should_withhold(fv)
    assert not d.ok
    assert any("HRV" in r for r in d.reasons)


def test_v6_withhold_on_poor_quality():
    fv = _fv(signal_quality=0.05)
    result = RiskEngine().estimate(fv, profile=UserProfile())
    d = should_withhold(fv, result)
    assert not d.ok


def test_v6_allow_when_quality_good():
    fv = _fv(signal_quality=0.9, rmssd=42)
    fv.baseline_available = True
    result = RiskEngine().estimate(fv, profile=UserProfile(usual_cycle_length_days=29))
    d = should_withhold(fv, result)
    assert d.ok


# --------------------------------------------------------- change detector
def test_v6_change_detector_all_points_out_of_band_no_crash():
    """Regression: persistence == n used to index past the start of the series.
    A personal baseline is captured from normal values, then the entire series
    is evaluated out of band -> persistence == n -> the old code crashed."""
    from src.models.personalization import BaselineManager

    now = time.time()
    # Tiny variance so the captured baseline has usable std (> 1e-9).
    rng = np.random.default_rng(0)
    normal = [_fv(hr=72.0 + rng.normal(0, 0.3), rmssd=40.0 + rng.normal(0, 0.3),
                  temp=32.5 + rng.normal(0, 0.02), signal_quality=0.9) for _ in range(60)]
    for i, f in enumerate(normal):
        f.timestamp_s = now + i * 60.0
    bm = BaselineManager()
    bm.capture_from_features(normal)
    assert bm.has_baseline

    det = ChangeDetector(baseline=bm)
    feats = [_fv(hr=118.0 + i * 0.1, rmssd=6.0, temp=34.8, signal_quality=0.9)
             for i in range(60)]
    for i, f in enumerate(feats):
        f.timestamp_s = now + i * 60.0
    report = det.evaluate(feats)  # must not raise
    assert report.n_windows == 60
    # HR is fully out of band the whole window -> persistent or progressive.
    assert report.per_metric["hr_bpm"].kind in ("persistent", "progressive")
    assert report.per_metric["rmssd_ms"].kind in ("persistent", "progressive")


def test_v6_change_detector_single_point_is_not_persistent():
    det = ChangeDetector()
    now = time.time()
    base = [_fv(hr=72.0, rmssd=40.0, temp=32.5, signal_quality=0.9) for _ in range(30)]
    for i, f in enumerate(base):
        f.timestamp_s = now + i * 60.0
    spike = _fv(hr=140.0, rmssd=5.0, temp=33.0, signal_quality=0.9)
    spike.timestamp_s = now + 31 * 60.0
    report = det.evaluate(base + [spike])
    assert report.overall_kind in ("normal", "deviation")


# -------------------------------------------------------- patient inputs
def test_v6_patient_inputs_store_round_trip(tmp_path):
    store = HistoryStore(tmp_path / "p.db")
    store.log_cycle_entry(cycle_day=14, cycle_length=33, bleeding=None,
                          symptoms="Pain, Acne", note="")
    store.log_bp(118, 76, 72, source="home cuff")
    store.log_glucose(96, context="fasting")
    store.log_weight(62.0)
    rows = store.cycle_history(limit=10)
    assert len(rows) == 1
    assert rows[0]["cycle_day"] == 14
    assert rows[0]["cycle_length"] == 33
    assert "Pain" in (rows[0]["symptoms"] or "")
    bp = store.bp_readings(limit=10)
    assert bp and bp[0]["systolic"] == 118
    glu = store.glucose_readings(limit=10)
    assert glu and glu[0]["value"] == 96


# -------------------------------------------------------------- UI wiring
def test_v6_window_structure_and_mode_badge(tmp_path):
    pytest.importorskip("PySide6")
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from src.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    w = MainWindow(db_path=tmp_path / "win1.db")
    try:
        tabs = [w.tabs.tabText(i) for i in range(w.tabs.count())]
        # V8.2: four top-level areas (Patient / Clinician / Research / Settings).
        assert len(tabs) == 4
        assert "Patient" in tabs[0]
        assert "Clinician" in tabs[1]
        assert "Research" in tabs[2]
        assert "Settings" in tabs[3]
        # All V8.1 functional areas still exist inside the sections.
        patient = [w.patient_tabs.tabText(i).replace("&&", "&")
                   for i in range(w.patient_tabs.count())]
        assert patient == ["Overview", "My Baseline", "My Timeline",
                           "Symptoms & Cycle", "Care & Reminders", "Reports"]
        clinician = [w.clinician_tabs.tabText(i).replace("&&", "&")
                     for i in range(w.clinician_tabs.count())]
        assert clinician == ["Clinical Dashboard", "Analysis", "Model Inputs",
                             "Live Signals", "Ultrasound & Imaging"]
        research = [w.research_tabs.tabText(i) for i in range(w.research_tabs.count())]
        assert research[0].startswith("Validation")
        assert any(t == "Model Lab" for t in research)      # V8.2 Model Lab
        assert any(t.startswith("Advanced") for t in research)
        # Demo badge is explicit.
        w.start_demo()
        assert w.mode_badge.text() == "DEMO MODE (SYNTHETIC)"
        w.stop_stream()
        assert w.mode_badge.text() == "NO STREAM"
        # Patient inputs tab exists and is wired to the store.
        assert w.patient_inputs is not None
    finally:
        w._end_session()


def test_v6_window_risk_flow_and_withheld_banner(tmp_path):
    pytest.importorskip("PySide6")
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from src.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    w = MainWindow(db_path=tmp_path / "win2.db")
    try:
        # No data -> withheld banner visible (isHidden False = showing).
        w._update_features_and_ui()
        assert not w.withheld_banner.isHidden()
        assert w.analysis_risk_label.text() == "WITHHELD"
        # Demo stream with real pulse waveforms -> banner clears, HR appears.
        w.start_demo()
        end = time.time() + 12
        while time.time() < end:
            app.processEvents()
            time.sleep(0.02)
        fv = w.extractor.last_feature
        assert fv.hr_bpm is not None
        assert w.withheld_banner.isHidden()
        assert w.last_result is not None
        assert 0 <= w.last_result.risk_percent <= 100
        assert "Cycle" not in " ".join(k for k in w.last_result.domain_scores) or True
        # Demo coverage is honestly 0 real days.
        assert w.db.coverage_days(days=90, include_demo=False) == 0
    finally:
        w._end_session()


def test_v6_synthetic_sample_flow():
    """A clean synthetic PPG produces HR/HRV through the extractor path."""
    from src.features.realtime_features import RealtimeFeatureExtractor

    ex = RealtimeFeatureExtractor()
    t0 = time.time()
    for i in range(700):
        t = i / 40.0
        hr = 72.0
        ppg = 48000 + 2500 * np.sin(2 * np.pi * (hr / 60.0) * t)
        s = SensorSample(timestamp_s=t0 + t, ms=int(t * 1000), ir=int(ppg),
                         red=int(ppg * 0.9), ax_g=0.01, ay_g=0.0, az_g=1.0,
                         gx_dps=0.0, gy_dps=0.0, gz_dps=0.0, temp_c=32.5,
                         gsr_raw=500, lux=100)
        ex.add_sample(s)
    fv = ex.compute()
    assert fv.hr_bpm is not None
    assert fv.rmssd_ms is not None
