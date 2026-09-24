from src.models.anomaly_detector import Anomaly
from src.utils.history_store import HistoryStore


def test_session_and_feature_logging(tmp_path):
    db = HistoryStore(tmp_path / "test.db")
    sid = db.start_session(source="demo")
    assert sid > 0
    db.log_feature(sid, {"ts": 100.0, "hr": 72.0, "rmssd": 40.0, "risk": 25.0, "signal_quality": 0.8})
    db.log_feature(sid, {"ts": 110.0, "hr": 75.0, "rmssd": 42.0, "risk": 27.0, "signal_quality": 0.75})
    df = db.features_as_frame(since=0)
    assert len(df) == 2
    db.end_session(sid)
    sessions = db.session_summary()
    assert sessions and sessions[0]["id"] == sid
    counts = db.row_counts()
    assert counts["sessions"] >= 1 and counts["features"] >= 2


def test_logs_events_calibrations_anomalies(tmp_path):
    db = HistoryStore(tmp_path / "test.db")
    sid = db.start_session(source="serial:COM5")
    db.log_quality(sid, "warning", "sensor_status", "PPG absent")
    db.log_error(sid, "error", "serial lost")
    db.log_event(sid, "post_meal", "reset")
    db.log_calibration(300.0, 0.9, '{"hr_bpm": {}}')
    db.log_anomaly(sid, 123.0, Anomaly("hr_bpm", 120.0, 60.0, 90.0, 80.0, "HR high"))
    assert len(db.quality_log()) == 1
    assert len(db.error_log()) == 1
    assert db.events(kind="post_meal")
    assert len(db.calibration_history()) == 1
    assert len(db.anomalies()) == 1
    db.end_session(sid)


def test_csv_export(tmp_path):
    import time

    db = HistoryStore(tmp_path / "test.db")
    sid = db.start_session(source="demo")
    now = time.time()
    db.log_feature(sid, {"ts": now - 60.0, "hr": 72.0, "risk": 25.0})
    db.log_feature(sid, {"ts": now - 50.0, "hr": 75.0, "risk": 27.0})
    out = tmp_path / "export.csv"
    n = db.export_features_csv(out, days=30)
    assert n == 2
    assert out.exists()
