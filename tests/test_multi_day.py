import time

from src.models.multi_day import MultiDayAnalyzer
from src.utils.history_store import HistoryStore


def test_weekly_profile_and_trajectory(tmp_path):
    db = HistoryStore(tmp_path / "test.db")
    sid = db.start_session(source="demo")
    now = time.time()
    # 4 days, 8 samples/day, HR rising ~1 bpm/day.
    for day in range(4):
        base = day * 86400.0
        for hour in range(0, 24, 3):
            ts = now - 3 * 86400.0 + base + hour * 3600.0
            db.log_feature(sid, {
                "ts": ts, "hr": 70.0 + day, "rmssd": 42.0, "skin_temp": 32.5 + hour / 100.0,
                "activity": 30.0, "sleep_prob": 95.0 if (hour == 3 or hour == 6) else 20.0,
                "circadian": 60.0 + day, "stress": 30.0, "risk": 30.0 + day, "signal_quality": 0.8,
            })
    db.end_session(sid)

    profile = MultiDayAnalyzer(db).build_profile(days=7)
    assert len(profile.days) >= 3
    hr_by_day = profile.metric_series("mean_hr")
    assert hr_by_day[0] < hr_by_day[-1]
    assert "mean_hr" in profile.trajectory
    assert profile.trajectory["mean_hr"] > 0.5  # rising ~1 bpm/day
