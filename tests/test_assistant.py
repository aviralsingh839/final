"""Tests for the AI assistant: local grounded answers, context building, LLM fallback."""
from __future__ import annotations

import os
import time

import pytest

from src.config import UserProfile
from src.data_models import FeatureVector
from src.models.anomaly_detector import Anomaly
from src.models.assistant import AssistantContext, AssistantEngine, LLMAssistant
from src.models.hormone_estimator import HormoneEstimator
from src.models.personalization import BaselineManager
from src.models.recommendations import generate as generate_recommendations
from src.models.risk_engine import RiskEngine
from src.utils.history_store import HistoryStore


def _fv() -> FeatureVector:
    return FeatureVector(
        timestamp_s=time.time(),
        hr_bpm=84.0,
        rmssd_ms=26.0,
        spo2_pct=96.0,
        skin_temp_c=31.2,
        gsr_tonic=620.0,
        motion_index=0.3,
        activity_level=15.0,
        low_activity_risk=60.0,
        stress_index=62.0,
        acute_stress=62.0,
        chronic_stress=44.0,
        autonomic_imbalance=40.0,
        sleep_probability=35.0,
        sleep_status="wake",
        circadian_stability_index=42.0,
        circadian_disruption=58.0,
        temperature_rhythm_disruption=40.0,
        insulin_resistance_probability=64.0,
        metabolic_syndrome_proxy=35.0,
        signal_quality=0.8,
        anomaly_score=10.0,
        glucose_risk=20.0,
        mv_challenge_risk=30.0,
        voice_vasc_score=10.0,
    )


def _ctx(tmp_path=None) -> AssistantContext:
    fv = _fv()
    profile = UserProfile(age_years=17, bmi=26.0, glucose_mg_dl=95.0, glucose_context="fasting")
    hormones = HormoneEstimator()
    result = RiskEngine().estimate(fv, hormones.estimate(fv, profile), phase=hormones.phase(profile))
    recs = generate_recommendations(fv, profile, result)
    anomaly = Anomaly("hr_bpm", 128.0, 60.0, 90.0, 75.0,
                      "Heart rate outside personal range (128.0, expected 60.0-90.0)")
    return AssistantContext(fv=fv, profile=profile, result=result, anomalies=[anomaly],
                            recs=recs, live_mode="live")


def test_local_answers_grounded_in_data():
    engine = AssistantEngine()
    ctx = _ctx()

    ans, mode = engine.answer("why is my risk elevated?", ctx)
    assert mode == "local"
    assert "contributor" in ans or "domain" in ans or "risk" in ans

    ans, mode = engine.answer("how did I sleep?", ctx)
    assert "sleep" in ans.lower()

    ans, mode = engine.answer("any anomalies?", ctx)
    assert "128.0" in ans or "anomal" in ans.lower()

    ans, mode = engine.answer("is this real or demo data?", ctx)
    assert "live" in ans.lower()


def test_recommendations_question_uses_real_recs():
    engine = AssistantEngine()
    ctx = _ctx()
    ans, _ = engine.answer("what should I do today?", ctx)
    assert "[" in ans and "]" in ans  # priority tags from real recommendations


def test_no_data_handling():
    engine = AssistantEngine()
    ctx = AssistantContext(fv=None, result=None, live_mode="none")
    ans, _ = engine.answer("what is my risk?", ctx)
    assert "no live data" in ans.lower() or "connect" in ans.lower()


def test_baseline_answer_shows_ranges(tmp_path):
    rows = []
    for i in range(70):
        fv = _fv()
        fv.timestamp_s = time.time() - 70 + i
        fv.hr_bpm = 70.0 + (i % 5)
        fv.rmssd_ms = 42.0 + (i % 3)
        fv.skin_temp_c = 32.5
        fv.gsr_tonic = 450.0
        rows.append(fv)
    bm = BaselineManager(path=tmp_path / "b.json", history_path=tmp_path / "h.json")
    bm.capture_from_features(rows)
    ctx = _ctx()
    ctx.baseline = bm
    ans, _ = AssistantEngine().answer("what is my personal baseline?", ctx)
    assert "Personal baseline active" in ans
    assert "Heart rate" in ans


def test_context_text_is_compact_snapshot():
    engine = AssistantEngine()
    ctx = _ctx()
    text = engine.context_text(ctx)
    assert "Risk:" in text
    assert "Vitals:" in text
    assert "Glucose 95" in text
    assert "Personal baseline: not captured" in text


def test_llm_unconfigured_falls_back_to_local(monkeypatch, tmp_path):
    monkeypatch.delenv("CHRONO_LLM_URL", raising=False)
    monkeypatch.delenv("CHRONO_LLM_MODEL", raising=False)
    monkeypatch.delenv("CHRONO_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("CHRONO_LLM_API_KEY", raising=False)
    import src.models.assistant as A
    monkeypatch.setattr(A, "AI_CONFIG_PATH", tmp_path / "absent.json")
    llm = LLMAssistant()
    assert not llm.available
    assert llm.chat("hi", "ctx") is None
    engine = AssistantEngine()
    ans, mode = engine.answer("hello", _ctx())
    assert mode == "local"
    assert "Hi" in ans


def test_llm_provider_presets(monkeypatch, tmp_path):
    import src.models.assistant as A
    monkeypatch.setattr(A, "AI_CONFIG_PATH", tmp_path / "absent.json")
    monkeypatch.delenv("CHRONO_LLM_URL", raising=False)
    monkeypatch.delenv("CHRONO_LLM_MODEL", raising=False)
    monkeypatch.delenv("CHRONO_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("CHRONO_LLM_API_KEY", raising=False)

    llm = LLMAssistant(provider="groq")
    assert llm.available
    assert llm.provider == "groq"
    assert "api.groq.com" in llm.url
    assert llm.model == "llama-3.3-70b-versatile"

    llm = LLMAssistant(provider="ollama")
    assert llm.available
    assert llm.api_key is None
    assert "11434" in llm.url

    llm = LLMAssistant(provider="gemini")
    assert "generativelanguage.googleapis.com" in llm.url
    assert "gemini" in llm.model

    # An explicit URL overrides the preset.
    llm = LLMAssistant(provider="groq", url="http://127.0.0.1:9/v1/chat/completions")
    assert "127.0.0.1" in llm.url


def test_llm_config_file_roundtrip(monkeypatch, tmp_path):
    import src.models.assistant as A
    monkeypatch.delenv("CHRONO_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("CHRONO_LLM_URL", raising=False)
    monkeypatch.delenv("CHRONO_LLM_MODEL", raising=False)
    monkeypatch.delenv("CHRONO_LLM_API_KEY", raising=False)

    cfg_path = tmp_path / "ai_config.json"
    A.save_ai_config({"provider": "gemini", "url": "", "model": "gemini-2.0-flash", "api_key": "secret"}, cfg_path)
    llm = LLMAssistant(config_path=cfg_path)
    assert llm.available
    assert llm.provider == "gemini"
    assert llm.api_key == "secret"
    assert "googleapis.com" in llm.url

    # configure_llm persists and the mode label reflects it.
    engine = AssistantEngine()
    llm2 = engine.configure_llm(provider="ollama", model="llama3.2", api_key=None, persist=False)
    assert llm2.available and llm2.provider == "ollama"
    assert "Ollama" in engine.mode_label() or "ollama" in engine.mode_label()


def test_llm_failure_falls_back_to_local(monkeypatch, tmp_path):
    import src.models.assistant as A
    monkeypatch.setattr(A, "AI_CONFIG_PATH", tmp_path / "absent.json")
    monkeypatch.setenv("CHRONO_LLM_URL", "http://127.0.0.1:1/v1/chat/completions")  # nothing listens
    monkeypatch.setenv("CHRONO_LLM_MODEL", "test-model")
    engine = AssistantEngine()
    assert engine.llm.available
    ans, mode = engine.answer("hello", _ctx())  # connection refused -> local fallback
    assert mode == "local"
    assert "Hi" in ans


def test_whatif_question_points_to_lab():
    engine = AssistantEngine()
    ctx = _ctx()
    ans, _ = engine.answer("what if I sleep more and reduce stress?", ctx)
    assert "What-if Lab" in ans
    assert "lever" in ans.lower()


def test_trend_question_with_history(tmp_path):
    db = HistoryStore(path=tmp_path / "assistant_test.db")
    sid = db.start_session(source="test", participant_id="P1")
    now = time.time()
    for i in range(3):
        db.log_feature(sid, {
            "ts": now - (2 - i) * 86400.0,
            "hr": 72.0, "rmssd": 40.0, "spo2": 97.0, "skin_temp": 32.5, "gsr": 450.0,
            "motion": 0.1, "activity": 30.0, "stress": 30.0, "sleep_prob": 90.0,
            "circadian": 70.0, "risk": 30.0, "anomaly": 0.0, "signal_quality": 0.8,
        }, extra_json='{"health_score": 70}')
    db.end_session(sid, sample_count=3)

    from src.models.multi_day import MultiDayAnalyzer
    engine = AssistantEngine(history_store=db, multi_day=MultiDayAnalyzer(db))
    ctx = AssistantContext(fv=_fv(), result=_ctx().result, live_mode="live")
    ans, _ = engine.answer("summarize my week and any trends", ctx)
    assert "recorded day" in ans or "health score" in ans


def test_greeting_and_help():
    engine = AssistantEngine()
    ctx = AssistantContext(fv=None, result=None, live_mode="none")
    ans, _ = engine.answer("hello", ctx)
    assert "CHRONO-PCOS" in ans
    ans, _ = engine.answer("what can you do", ctx)
    assert "sleep" in ans.lower() and "risk" in ans.lower()


def test_metric_lookup():
    engine = AssistantEngine()
    ctx = _ctx()
    ans, mode = engine.answer("what is my heart rate?", ctx)
    assert mode == "local"
    assert "Heart rate:" in ans and "84" in ans
    ans, _ = engine.answer("is my stress high?", ctx)
    assert "Stress:" in ans and "62" in ans
    ans, _ = engine.answer("what is my glucose?", ctx)
    assert "glucose" in ans.lower() and "95" in ans


def test_followup_why_uses_memory():
    engine = AssistantEngine()
    ctx = _ctx()
    memory: dict = {}
    engine.answer("how did I sleep?", ctx, memory)
    assert memory.get("last_topic") == "sleep"
    ans, _ = engine.answer("why?", ctx, memory)
    assert "sleep" in ans.lower() or "Breakdown" in ans
    ans, _ = engine.answer("more", ctx, memory)
    assert "Breakdown" in ans or "sleep" in ans.lower()


def test_followup_what_about():
    engine = AssistantEngine()
    ctx = _ctx()
    memory = {"last_topic": "sleep"}
    ans, _ = engine.answer("and stress?", ctx, memory)
    assert "Stress" in ans and "62" in ans


def test_complaint_empathy():
    engine = AssistantEngine()
    ctx = _ctx()
    memory: dict = {}
    ans, _ = engine.answer("my sleep is bad", ctx, memory)
    assert "sorry" in ans.lower()
    assert "Sleep" in ans
    assert memory.get("complaints") == ["Sleep"]


def test_combined_topics():
    engine = AssistantEngine()
    ctx = _ctx()
    ans, _ = engine.answer("tell me about sleep and stress", ctx)
    assert "**Sleep**" in ans and "**Stress**" in ans


def test_compare_days(tmp_path):
    from src.models.multi_day import MultiDayAnalyzer
    db = HistoryStore(path=tmp_path / "assistant_compare.db")
    sid = db.start_session(source="test", participant_id="P2")
    now = time.time()
    for i in range(2):
        db.log_feature(sid, {
            "ts": now - (1 - i) * 86400.0,
            "hr": 72.0, "rmssd": 40.0, "spo2": 97.0, "skin_temp": 32.5, "gsr": 450.0,
            "motion": 0.1, "activity": 30.0, "stress": 30.0, "sleep_prob": 90.0,
            "circadian": 70.0, "risk": 30.0, "anomaly": 0.0, "signal_quality": 0.8,
        }, extra_json='{"health_score": 70}')
    db.end_session(sid, sample_count=2)
    engine = AssistantEngine(history_store=db, multi_day=MultiDayAnalyzer(db))
    ctx = AssistantContext(fv=_fv(), result=_ctx().result, live_mode="live")
    ans, _ = engine.answer("compare today vs yesterday", ctx)
    assert "Comparing" in ans and "→" in ans
