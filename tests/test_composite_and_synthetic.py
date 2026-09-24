from src.data_models import FeatureVector
from src.models.composite_scores import compute_scores
from src.models.multi_day import MultiDayAnalyzer
from src.models.research import evaluate_synthetic
from src.utils.history_store import HistoryStore
from src.utils.synthetic import generate_week


def test_composite_scores_range():
    fv = FeatureVector(autonomic_imbalance=30.0, insulin_resistance_probability=40.0,
                       metabolic_syndrome_proxy=30.0, sleep_probability=80.0,
                       circadian_disruption=30.0, chronic_stress=35.0,
                       low_activity_risk=20.0, circadian_stability_index=70.0)
    s = compute_scores(fv)
    assert 0 <= s.daily_health_score <= 100
    assert set(s.fingerprint) == {"Autonomic balance", "Metabolic coordination", "Sleep regularity",
                                  "Stress response", "Activity consistency", "Circadian stability"}
    assert s.as_dict()["health"] == round(s.daily_health_score, 1)


def test_synthetic_week_feeds_history_and_research(tmp_path):
    db = HistoryStore(tmp_path / "test.db")
    sid, n = generate_week(db, days=7, patient=1, participant="P01")
    assert n == 7 * 24

    profile = MultiDayAnalyzer(db).build_profile(days=7)
    assert len(profile.days) == 7
    assert all(d.health_score is not None for d in profile.days)
    assert all(d.label == 1 for d in profile.days)
    assert "risk" in profile.trajectory

    report = evaluate_synthetic(db, days=14)
    assert report.n_labeled == n
    m = report.metrics
    assert m.total == n
    assert m.tp + m.fn == n  # all rows labelled 1
    assert report.ablation, "ablation should be computed"
