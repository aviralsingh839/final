"""Tests for the V5 master-prompt modules: change detector, gradual baseline,
hardware ecosystem, digital-twin timeline, and manual-input storage."""
import time

from src.config import APP_VERSION, APP_VERSION_LABEL
from src.data_models import FeatureVector
from src.hardware.ecg_checkpoint import CheckpointHistory, ECGCheckpointSession, SimulatedECGCheckpoint
from src.hardware.insole import InsoleAnalyzer, SimulatedInsole
from src.hardware.simulators import DemoScenario, SimulatedRing
from src.hardware.transport import BlePacketProtocol, LocalBuffer
from src.models.change_detector import ChangeDetector
from src.models.personalization import BaselineManager
from src.models.timeline import build_timeline, timeline_text
from src.utils.history_store import HistoryStore


def _fv(ts: float, hr: float, q: float = 0.9, rmssd: float = 40.0,
        temp: float = 32.5, gsr: float = 450.0, activity: float = 10.0) -> FeatureVector:
    return FeatureVector(
        timestamp_s=ts, hr_bpm=hr, rmssd_ms=rmssd, skin_temp_c=temp,
        gsr_tonic=gsr, activity_level=activity, motion_index=0.05,
        signal_quality=q,
    )


# ------------------------------------------------------------- versioning
def test_versioning():
    assert APP_VERSION.startswith("8.")
    assert "not clinically validated" in APP_VERSION_LABEL.lower()


# ------------------------------------------------------- change detector
def test_change_detector_normal():
    det = ChangeDetector()
    feats = [_fv(100 + i * 60, 72.0) for i in range(40)]
    rep = det.evaluate(feats)
    assert rep.overall_kind == "normal"
    assert rep.per_metric["hr_bpm"].kind == "normal"


def test_change_detector_single_deviation():
    det = ChangeDetector()
    feats = [_fv(100 + i * 60, 72.0) for i in range(39)]
    feats.append(_fv(100 + 39 * 60, 125.0))
    rep = det.evaluate(feats)
    assert rep.per_metric["hr_bpm"].kind == "single"
    assert rep.overall_kind == "deviation"


def test_change_detector_persistent():
    det = ChangeDetector()
    feats = [_fv(100 + i * 60, 72.0) for i in range(5)]
    feats += [_fv(100 + (5 + i) * 60, 108.0) for i in range(30)]
    rep = det.evaluate(feats)
    assert rep.per_metric["hr_bpm"].kind == "persistent"
    assert rep.per_metric["hr_bpm"].persistence_points >= 3
    assert rep.contributors


def test_change_detector_progressive():
    det = ChangeDetector()
    feats = [_fv(100 + i * 60, 72.0 + 0.95 * i) for i in range(40)]  # ramp 72 -> 110
    rep = det.evaluate(feats)
    assert rep.per_metric["hr_bpm"].kind == "progressive"
    assert rep.per_metric["hr_bpm"].slope_per_day > 0


def test_change_detector_recovery():
    det = ChangeDetector()
    feats = [_fv(100 + i * 60, 72.0) for i in range(10)]
    feats += [_fv(100 + (10 + i) * 60, 108.0) for i in range(15)]
    feats += [_fv(100 + (25 + i) * 60, 72.0) for i in range(15)]
    rep = det.evaluate(feats)
    assert rep.per_metric["hr_bpm"].kind == "recovery"


def test_change_detector_never_alerts_on_noisy_single_reading():
    det = ChangeDetector()
    feats = [_fv(100 + i * 60, 72.0) for i in range(30)]
    feats += [_fv(100 + (30 + i) * 60, 125.0, q=0.15) for i in range(4)]
    rep = det.evaluate(feats)
    assert rep.overall_kind == "insufficient_quality"
    assert rep.per_metric["hr_bpm"].kind == "insufficient"


# ------------------------------------------------- gradual baseline update
def test_baseline_gradual_updates(tmp_path):
    mgr = BaselineManager(path=tmp_path / "b.json", history_path=tmp_path / "h.json")
    feats = [_fv(100 + i * 10, 70.0) for i in range(80)]
    mgr.capture_from_features(feats, min_samples=60)
    assert mgr.has_baseline
    med0 = mgr.baseline.stats["hr_bpm"].median

    # A run of outliers must NOT redefine the baseline.
    for i in range(60):
        mgr.update_observation(_fv(2000 + i * 10, 145.0))
    assert abs(mgr.baseline.stats["hr_bpm"].median - med0) < 1.0

    # Gradual drift follows slowly (far less than the raw +10 shift).
    for i in range(60):
        mgr.update_observation(_fv(3000 + i * 10, 80.0))
    moved = mgr.baseline.stats["hr_bpm"].median - med0
    assert 0.0 < moved < 6.0

    # Robust z-score works after updates.
    z = mgr.robust_zscore("hr_bpm", 90.0)
    assert z is not None and z > 0


# ------------------------------------------------------------- hardware
def test_local_buffer_dedup_and_reorder():
    buf = LocalBuffer(maxlen=8)
    assert buf.push(3, b"c") is True
    assert buf.push(1, b"a") is True
    assert buf.push(2, b"b") is True
    assert buf.push(1, b"a-dup") is False  # duplicate
    ordered = buf.pull_ordered()
    assert [s for s, _ in ordered] == [1, 2, 3]
    assert buf.stats.duplicates == 1


def test_packet_protocol_crc():
    frame = BlePacketProtocol.encode(42, b"payload123")
    seq, payload = BlePacketProtocol.decode(frame)
    assert seq == 42 and payload == b"payload123"
    corrupted = bytearray(frame)
    corrupted[5] ^= 0xFF
    try:
        BlePacketProtocol.decode(bytes(corrupted))
        raise AssertionError("corrupted packet must be rejected")
    except ValueError:
        pass


def test_insole_analysis():
    sim = SimulatedInsole(cadence_steps_per_min=100, asymmetry=0.0)
    frames = list(sim.stream(duration_s=10.0))
    rep = InsoleAnalyzer().analyze(frames)
    assert rep.step_count > 10
    assert 70 <= rep.cadence_steps_per_min <= 130
    assert rep.lr_asymmetry < 0.15
    assert rep.walking_duration_s > 5.0
    # Asymmetric walking is detected.
    sim2 = SimulatedInsole(cadence_steps_per_min=100, asymmetry=0.4)
    rep2 = InsoleAnalyzer().analyze(list(sim2.stream(duration_s=10.0)))
    assert rep2.lr_asymmetry > 0.15


def test_ecg_checkpoint_session(tmp_path):
    sim = SimulatedECGCheckpoint(fs_hz=256.0, hr_bpm=72.0, duration_s=30.0)
    sess = ECGCheckpointSession(fs_hz=256.0)
    sess.add_stream(sim.stream())
    res = sess.complete()
    assert res.hr_bpm is not None and 68 <= res.hr_bpm <= 76
    assert res.quality > 0.5
    assert res.n_beats > 20
    # History comparison.
    hist = CheckpointHistory(tmp_path / "ecg.json")
    hist.add(res)
    assert hist.latest()["hr_bpm"] == res.hr_bpm
    assert hist.changes_from_previous() == {}
    hist.add(res)
    assert hist.changes_from_previous()["days_between"] == 0.0


def test_simulated_ring_scenarios():
    ring = SimulatedRing(scenario="gradual_change")
    assert ring.hr_profile(0.0) < 78
    assert ring.hr_profile(290.0) > 95

    fail_ring = SimulatedRing(scenario="sensor_failure")
    frames = list(fail_ring.stream(duration_s=130.0))
    dropouts = [f for f in frames if 90 <= f["ts"] - frames[0]["ts"] < 150 and f["ppg_ir"] == 0]
    assert dropouts, "sensor-failure scenario must produce PPG dropout"


# ------------------------------------------------------ timeline + store
def test_timeline_and_manual_tables(tmp_path):
    db = HistoryStore(tmp_path / "t.db")
    db.start_session(source="demo")
    db.log_calibration(duration_s=300, quality=0.9, stats_json="{}")
    db.log_anomaly(None, time.time(), type("A", (), {
        "signal": "hr_bpm", "value": 120.0, "expected_low": 60.0, "expected_high": 85.0,
        "severity": 70.0, "description": "HR outside personal range"}))
    db.log_bp(118, 76)
    db.log_glucose(92, context="fasting")
    db.log_weight(64.5)
    db.log_symptom("bloating", 4)
    db.log_cycle_entry(cycle_day=12, cycle_length=30)
    db.log_ultrasound(cyst_size_mm=28, morphology="simple")
    db.log_event(None, "ecg_checkpoint", "completed")

    events = build_timeline(db)
    kinds = {e.kind for e in events}
    assert {"session", "baseline", "anomaly", "bp", "glucose", "weight",
            "symptom", "cycle", "ultrasound", "ecg_checkpoint"} <= kinds
    assert timeline_text(events)

    # Round-trips.
    assert db.bp_readings()[0]["systolic"] == 118
    assert db.glucose_readings()[0]["context"] == "fasting"
    assert db.symptoms()[0]["severity"] == 4
    assert db.ultrasound_history()[0]["cyst_size_mm"] == 28
    counts = db.row_counts()
    assert counts["bp_readings"] == 1 and counts["ultrasound_observations"] == 1
