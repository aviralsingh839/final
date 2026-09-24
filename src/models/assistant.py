"""AI Assistant: a conversational layer over the explainable engine.

The assistant answers natural-language questions about the user's data. It
never invents numbers: every local answer is built from the *actual* computed
feature vector, risk result, personal baseline, recommendations, anomalies and
database history.

Local mode understands:
  * topics (risk, sleep, stress, circadian, glucose, hormones, ...) via
    weighted keyword scoring, combining topics when a question covers several;
  * metric lookups ("what is my HR?", "is my stress high?") with personal
    ranges and judgement;
  * follow-ups ("why?", "more", "and sleep?") using conversation memory;
  * complaints ("my sleep is bad", "I feel stressed") with empathy + advice;
  * comparisons ("compare today vs yesterday") from the stored history.

LLM mode (optional): if CHRONO_LLM_URL / CHRONO_LLM_MODEL are set, the question
plus a compact context snapshot go to an OpenAI-compatible chat endpoint (local
Ollama, OpenAI, ...) and are answered conversationally; any error falls back to
local mode automatically.

Educational tool: this is not medical advice and never claims to be.
"""
from __future__ import annotations

import json
import os
import re
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from src.config import UserProfile
from src.data_models import FeatureVector, RiskResult
from src.models.personalization import BaselineManager

# Free / local LLM providers supported by the settings dialog. ``url`` is the
# OpenAI-compatible chat endpoint; ``model`` is the default model name.
PROVIDERS: Dict[str, Dict[str, object]] = {
    "ollama": {
        "label": "Ollama — local & free (no key)",
        "url": "http://localhost:11434/v1/chat/completions",
        "model": "llama3.2", "free": True, "key": False,
    },
    "groq": {
        "label": "Groq Cloud — free tier",
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "model": "llama-3.3-70b-versatile", "free": True, "key": True,
    },
    "gemini": {
        "label": "Google Gemini — free tier",
        "url": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        "model": "gemini-2.0-flash", "free": True, "key": True,
    },
    "openrouter": {
        "label": "OpenRouter — free models",
        "url": "https://openrouter.ai/api/v1/chat/completions",
        "model": "meta-llama/llama-3.3-70b-instruct:free", "free": True, "key": True,
    },
    "openai": {
        "label": "OpenAI (paid)",
        "url": "https://api.openai.com/v1/chat/completions",
        "model": "gpt-4o-mini", "free": False, "key": True,
    },
    "custom": {
        "label": "Custom (OpenAI-compatible)",
        "url": "", "model": "", "free": False, "key": False,
    },
}

# Where the assistant persists its provider / key settings (local file inside
# the project's data directory; never uploaded anywhere).
AI_CONFIG_PATH = Path(__file__).resolve().parents[2] / "data" / "ai_config.json"


def load_ai_config(path: Optional[Path] = None) -> dict:
    """Read the saved assistant config; missing/corrupt file -> {}."""
    path = Path(path) if path else AI_CONFIG_PATH
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except Exception:
        pass
    return {}


def save_ai_config(data: dict, path: Optional[Path] = None) -> None:
    """Persist assistant config (provider, model, api key) locally."""
    path = Path(path) if path else AI_CONFIG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


# (intent, weight, keywords). Longer keywords score higher (more specific).
INTENTS: List[Tuple[str, float, Tuple[str, ...]]] = [
    ("greeting", 2.0, ("hi", "hello", "hey", "namaste", "good morning", "good evening", "yo")),
    ("thanks", 3.0, ("thank you", "thanks", "thank", "great job", "nice one", "appreciate")),
    ("help", 4.0, ("help", "what can you do", "what questions", "what should i ask", "how do i use", "commands", "what do you know")),
    ("compare", 6.0, ("compare", "versus", "difference", "changed since", "better than", "worse than", " vs ")),
    ("why", 6.5, ("why", "because", "driver", "contribut", "what changed my", "what made", "reason", "cause")),
    ("risk", 5.0, ("risk", "pcos", "pcod", "score", "chance", "probability of")),
    ("trend", 5.0, ("trend", "trajectory", "week", "7 day", "history", "summary", "last 7", "improving", "getting better", "getting worse", "progress", "over time")),
    ("sleep", 5.0, ("sleep", "tired", "insomnia", "rest", "nap", "bedtime", "awake")),
    ("stress", 5.0, ("stress", "anxious", "anxiety", "autonomic", "relax", "calm", "overwhelm")),
    ("anomaly", 5.0, ("anomal", "alert", "abnormal", "unusual", "warning", "outlier", "wrong with", "weird")),
    ("recommend", 5.0, ("recommend", "improve", "what should i do", "advice", "suggest", "how can i", "what can i do", "help me", "should i", "fix", "tips", "action plan", "what to do", "steps")),
    ("whatif", 6.5, ("what if", "simulate", "what would", "would happen", "if i ", "try changing", "try increasing", "try reducing", "suppose")),
    ("circadian", 5.0, ("circadian", "rhythm", "body clock", "biological clock", "internal clock", "csi")),
    ("baseline", 5.0, ("baseline", "personal", "normal range", "calibrat", "normal for me", "typical for me")),
    ("metabolic", 5.0, ("glucose", "sugar", "insulin", "metabolic", "diabetes", "carb", "eating")),
    ("hormone", 5.0, ("hormone", "testosterone", "estrogen", "lh", "fsh", "amh", "cortisol", "progesterone", "androgen", "endocrine", "ovarian")),
    ("health", 5.0, ("health", "overall", "fingerprint", "how am i doing", "composite")),
    ("bp", 5.0, ("blood pressure", "systolic", "diastolic", " bp")),
    ("confidence", 5.0, ("confiden", "uncertain", "reliable", "sure", "accurate", "trust", "trustworthy")),
    ("mode", 5.0, ("demo", "synthetic", "fake", "real data", "is this real")),
    ("about", 5.0, ("who are you", "what are you", "about you", "how do you work", "are you a robot")),
]

# (keywords, feature attr, label, decimals)
METRICS: List[Tuple[Tuple[str, ...], str, str, int]] = [
    (("heart rate variability", "hrv", "rmssd"), "rmssd_ms", "HRV (RMSSD)", 1),
    (("heart rate", "pulse", "bpm", "hr"), "hr_bpm", "Heart rate", 0),
    (("skin temperature", "skin temp", "temperature", "temp"), "skin_temp_c", "Skin temperature", 1),
    (("oxygen saturation", "spo2", "oxygen"), "spo2_pct", "SpO2", 0),
    (("blood pressure", "systolic", "diastolic", "bp"), "bp", "Blood pressure", 0),
    (("insulin resistance", "insulin"), "insulin_resistance_probability", "Insulin resistance", 0),
    (("glucose", "sugar"), "glucose", "Glucose", 0),
    (("circadian", "body clock", "biological clock"), "circadian_stability_index", "Circadian stability", 0),
    (("stress", "anxiety", "anxious"), "stress_index", "Stress", 0),
    (("sleep",), "sleep_probability", "Sleep", 0),
    (("activity",), "activity_level", "Activity", 0),
    (("motion",), "motion_index", "Motion", 0),
    (("gsr", "sweat", "skin conductance"), "gsr_tonic", "GSR tonic", 0),
]

COMBINABLE = {"sleep", "stress", "circadian", "metabolic", "hormone", "health", "baseline"}
# Intent names whose answer handler has a different method name.
_ALIASES = {"why": "_drivers", "thanks": "_thanks"}
TITLES = {
    "sleep": "Sleep", "stress": "Stress", "circadian": "Circadian rhythm",
    "metabolic": "Metabolic / glucose", "hormone": "Hormones", "health": "Daily health",
    "baseline": "Personal baseline",
}
FOLLOWUP_WHY = {"why", "why?", "why is that", "why so", "why is that?", "because", "explain"}
FOLLOWUP_MORE = {"more", "more details", "tell me more", "elaborate", "explain more", "details", "go deeper"}
_COMPLAINT_WORDS = r"(bad|poor|terrible|worse|not good|unstable|off|broken|awful|horrible|struggling|messed up)"
COMPLAINT_RE = re.compile(
    r"\bmy ([a-z][a-z ]{0,29}?)\b (is|are) " + _COMPLAINT_WORDS + r"\b")
COMPLAINT_RE2 = re.compile(
    r"\b(?:is )?my ([a-z][a-z ]{0,29}?)\b " + _COMPLAINT_WORDS + r"\b")
FEEL_RE = re.compile(r"\bi (feel|am feeling|am) (stressed|anxious|tired|sleepy|unwell|sick|dizzy)\b")
METRIC_GATE = ("what is", "what's", "whats", "how is", "how's", "hows", "is my", "are my", "my ")


def _fmt(v, nd: int = 1) -> str:
    return f"{v:.{nd}f}" if isinstance(v, (int, float)) else str(v)


def _num(v, nd: int = 0) -> str:
    """Format a possibly-None numeric as text, showing '--' when missing."""
    if v is None:
        return "--"
    try:
        if isinstance(v, float) and (v != v):  # NaN
            return "--"
        return f"{v:.{nd}f}"
    except (TypeError, ValueError):
        return str(v)


@dataclass
class AssistantContext:
    """Snapshot of live state handed to the assistant for one question."""

    fv: Optional[FeatureVector] = None
    profile: Optional[UserProfile] = None
    result: Optional[RiskResult] = None
    baseline: Optional[BaselineManager] = None
    anomalies: List = field(default_factory=list)
    recs: List = field(default_factory=list)
    live_mode: str = "none"  # "live" | "demo" | "replay" | "none"


# ------------------------------------------------------------- local engine
class LocalAssistant:
    """Deterministic, fully-offline answers grounded in the live state."""

    def __init__(self, history_store=None, multi_day=None):
        self.history_store = history_store
        self.multi_day = multi_day

    # ------------------------------------------------------------ helpers
    @staticmethod
    def _has(q: str, key: str) -> bool:
        if len(key) <= 3:
            return re.search(r"(?<![a-z0-9])" + re.escape(key) + r"(?![a-z0-9])", q) is not None
        return key in q

    @classmethod
    def _extract_metrics(cls, q: str) -> List[Tuple[str, str, int]]:
        found = []
        for keys, attr, label, nd in METRICS:
            if any(cls._has(q, k) for k in keys):
                found.append((attr, label, nd))
        return found

    def _score(self, q: str) -> Tuple[Optional[Tuple[str, float]], Optional[Tuple[str, float]]]:
        scored = []
        for name, weight, keys in INTENTS:
            s = sum(weight * (1.0 + min(len(k), 12)) for k in keys if self._has(q, k))
            if s > 0:
                scored.append((name, s))
        scored.sort(key=lambda x: x[1], reverse=True)
        if not scored:
            return None, None
        return scored[0], (scored[1] if len(scored) > 1 else None)

    def topic_of(self, question: str) -> str:
        """Intent only (used to remember context after an LLM answer)."""
        q = question.strip().lower()
        best, _ = self._score(q)
        return best[0] if best else ""

    def _answer_for(self, topic: str, ctx: AssistantContext) -> Optional[str]:
        if topic in ("metric", "complaint", "none", "fallback"):
            return None  # special topics are not standalone answers
        fn = getattr(self, _ALIASES.get(topic, f"_{topic}"), None)
        return fn(ctx) if callable(fn) else self._fallback(ctx)

    # ------------------------------------------------------------ routing
    def answer(self, question: str, ctx: AssistantContext,
               memory: Optional[dict] = None) -> Tuple[str, str]:
        """Return (answer_text, topic) for the question; remembers the topic."""
        memory = memory if memory is not None else {}
        text, topic = self._answer_impl(question, ctx, memory)
        memory["last_topic"] = topic
        return text, topic

    def _answer_impl(self, question: str, ctx: AssistantContext,
                     memory: dict) -> Tuple[str, str]:
        q = question.strip().lower()
        if not q:
            return self._help(), "help"

        # 1) Follow-ups ("why?", "more", "and sleep?") use the conversation.
        follow = self._followup(q, ctx, memory)
        if follow:
            return follow

        # 2) Complaints get empathy + data + advice.
        if "my " in q:
            c = self._complaint(q, ctx, memory)
            if c:
                return c

        # 3) Action questions should route to advice, not metric values.
        if not any(k in q for k in ("should i do", "recommend", "improve", "what can i do", "how can i")):
            if any(g in q for g in METRIC_GATE):
                metrics = self._extract_metrics(q)
                if len(metrics) == 1:
                    memory["last_metric"] = (metrics[0][0], metrics[0][1], metrics[0][2])
                    return self._metric(metrics[0][0], metrics[0][1], metrics[0][2], ctx), "metric"
                if len(metrics) >= 2:
                    memory["last_metric"] = (metrics[0][0], metrics[0][1], metrics[0][2])
                    return self._combined_metrics(metrics, ctx), "metric"

        has_data = ctx.fv is not None and ctx.result is not None
        if not has_data and not any(k in q for k in ("demo", "synthetic", "what is", "who", "about", "help", "hi", "hello", "hey")):
            return ("No live data yet — connect the Arduino/Wi-Fi bridge or press "
                    "Demo Mode in the top bar, then ask me about your risk, sleep, "
                    "stress, anomalies or recommendations."), "none"

        best, second = self._score(q)
        if best is None:
            return self._fallback(ctx), "fallback"
        if second is not None and second[1] >= 0.6 * best[1] and {best[0], second[0]} <= COMBINABLE:
            return self._combined(best[0], second[0], ctx), best[0]
        return self._answer_for(best[0], ctx), best[0]

    def _followup(self, q: str, ctx: AssistantContext, memory: dict) -> Optional[Tuple[str, str]]:
        last = memory.get("last_topic") or ""
        if not last:
            return None
        stripped = q.strip("?.! ")
        if stripped in FOLLOWUP_WHY or stripped in FOLLOWUP_MORE:
            return self._deep(last, ctx, memory), last
        m = re.fullmatch(r"(?:and|what about|how about|what is|how is)[ \t]+([a-z][a-z ]{1,40}?)[!?.]*", q)
        if m:
            phrase = m.group(1).strip()
            metrics = self._extract_metrics(phrase)
            if metrics:
                attr, label, nd = metrics[0]
                return f"Regarding {label}:\n\n" + self._metric(attr, label, nd, ctx), "metric"
            topic = self.topic_of(phrase)
            if topic and topic not in ("greeting", "thanks", "help"):
                return f"Regarding {phrase}:\n\n" + self._answer_for(topic, ctx), topic
        return None

    # ------------------------------------------------------------ metric / compare / complaints
    def _metric(self, attr: str, label: str, nd: int, ctx: AssistantContext) -> str:
        fv = ctx.fv
        if attr == "glucose":
            g = ctx.profile.glucose_mg_dl if ctx.profile else None
            if g is None:
                return ("No glucose reading entered yet. Type it in the top bar "
                        "(e.g. 95 mg/dL) and ask again.")
            return (f"Latest glucose: {g:.0f} mg/dL ({ctx.profile.glucose_context}). "
                    "Educational reference: fasting ~70–100, 2 h post-meal < 140.")
        if attr == "bp":
            return self._bp(ctx)
        if fv is None or getattr(fv, attr) is None:
            return f"No live {label.lower()} reading yet — connect a stream first."
        v = getattr(fv, attr)
        line = f"{label}: {_num(v, nd)}"
        rng = None
        if ctx.baseline is not None and ctx.baseline.has_baseline:
            rng = ctx.baseline.normal_range(attr)
        if rng is not None:
            inside = rng[0] <= v <= rng[1]
            line += f" (personal range {rng[0]:.1f}–{rng[1]:.1f} — {'inside your range' if inside else 'OUTSIDE your personal range'})."
        else:
            line += " (no personal baseline yet — compared against population defaults)."
        judgement = self._metric_judgement(attr, v)
        if judgement:
            line += " " + judgement
        return line

    def _metric_judgement(self, attr: str, v: float) -> str:
        if attr == "hr_bpm":
            return "Typical resting HR for adults is ~60–100 bpm." if 55 <= v <= 100 else \
                ("Low resting HR — fine for athletes, otherwise worth watching." if v < 55 else
                 "Elevated — usually stress, caffeine, or movement.")
        if attr == "rmssd_ms":
            return "Higher HRV generally means a more relaxed, recovered state."
        if attr == "skin_temp_c":
            return "Typical wrist skin temperature is ~30–34 °C."
        if attr == "spo2_pct":
            return "SpO₂ ≥ 95% is typical at rest (educational estimate)."
        if attr == "stress_index":
            return "High" if v > 70 else "Moderate" if v > 45 else "Low" + " right now."
        if attr == "sleep_probability":
            return "Likely awake" if v < 40 else "Drowsy/transitional" if v < 60 else "Likely asleep" + " right now."
        if attr == "circadian_stability_index":
            return "Good rhythm" if v >= 60 else "Disrupted rhythm" + "."
        if attr == "activity_level":
            return "Low" if v < 15 else "Moderate" if v < 45 else "Active" + "."
        if attr == "motion_index":
            return "Calm" if v < 0.2 else "Moving" + "."
        if attr == "insulin_resistance_probability":
            return "Higher values point to a stronger insulin-resistance tendency (educational estimate)."
        return ""

    def _combined_metrics(self, metrics, ctx: AssistantContext) -> str:
        lines = []
        for attr, label, nd in metrics:
            lines.append("• " + self._metric(attr, label, nd, ctx))
        return "Here are the values you asked about:\n" + "\n".join(lines)

    def _complaint(self, q: str, ctx: AssistantContext, memory: dict) -> Optional[str]:
        phrase = None
        m = COMPLAINT_RE.search(q) or COMPLAINT_RE2.search(q)
        if m:
            phrase = m.group(1).strip()
        else:
            f = FEEL_RE.search(q)
            if f:
                phrase = f.group(2).strip()
        if not phrase:
            return None
        metrics = self._extract_metrics(phrase)
        if not metrics:
            return (f"I'm sorry you're feeling this way. I don't track \"{phrase}\" directly, "
                    "but ask me about sleep, stress, heart rate, glucose or any metric I do "
                    "measure, and I'll show the numbers plus what usually helps.")
        attr = metrics[0][0]
        label = metrics[0][1]
        memory.setdefault("complaints", []).append(label)
        advice = {
            "sleep_probability": "Consistent sleep/wake times and a cooler, dark room are the biggest levers — check the Sleep + Circadian tab and set your sleep window.",
            "stress_index": "Slow breathing (4 s in, 6 s out) for a few minutes usually moves the stress index within minutes.",
            "hr_bpm": "If it's elevated, check sensor fit and sit still for a minute before trusting the reading.",
            "glucose": "Re-check context (fasting vs post-meal) and retest — timing matters a lot.",
        }.get(attr, "Let's look at the numbers, then I can suggest concrete steps — ask \"what should I do?\".")
        return (f"I'm sorry — that's not a fun way to feel. Let's look at the data.\n\n"
                + self._metric(attr, label, metrics[0][2], ctx) + "\n\n" + advice), "complaint"

    def _compare(self, ctx: AssistantContext) -> str:
        if self.multi_day is None:
            return "No history module available for comparison."
        try:
            profile = self.multi_day.build_profile(days=7, trajectory_days=30)
        except Exception:
            return "Could not build the history yet — keep recording sessions."
        if len(profile.days) < 2:
            return ("I need at least 2 recorded days to compare. Keep running sessions "
                    "(or load a demo week in the History tab).")
        prev, last = profile.days[-2], profile.days[-1]
        rows = []
        for label, a, b, higher_better in [
            ("Daily health score", prev.health_score, last.health_score, True),
            ("Mean risk %", prev.mean_risk, last.mean_risk, False),
            ("Circadian stability", prev.circadian_stability, last.circadian_stability, True),
            ("Mean stress", prev.mean_stress, last.mean_stress, False),
            ("Night sleep prob %", prev.night_sleep_prob, last.night_sleep_prob, True),
        ]:
            if a is None or b is None:
                continue
            d = b - a
            arrow = "↑" if d > 0.05 else "↓" if d < -0.05 else "→"
            good = "better" if ((d > 0) == higher_better and abs(d) > 0.05) else \
                "worse" if ((d < 0) == higher_better and abs(d) > 0.05) else "unchanged"
            rows.append(f"{label}: {a:.0f} → {b:.0f} ({arrow} {abs(d):.1f}, {good})")
        if not rows:
            return "No comparable metrics across those two days yet."
        return f"Comparing {prev.date} vs {last.date}:\n" + "\n".join(rows) + \
            "\n\nFor health/circadian/sleep, higher is better; for risk and stress, lower is better."

    def _deep(self, topic: str, ctx: AssistantContext, memory: Optional[dict] = None) -> str:
        memory = memory if memory is not None else {}
        if topic == "metric":
            lm = memory.get("last_metric")
            if lm:
                return "Here's more on that value:\n\n" + self._metric(lm[0], lm[1], lm[2], ctx)
            return "Which value would you like more detail on? Ask e.g. \"what is my HR?\"."
        base = self._answer_for(topic, ctx)
        if base is None:
            return self._fallback(ctx)
        extra = {
            "risk": self._risk_deep,
            "sleep": lambda c: ("Breakdown: probability %.0f%%, deep %.0f%%, REM %.0f%%. "
                                "Estimates come from HR/HRV slowing, temperature drop and reduced motion. "
                                "Set your sleep/wake times on the Sleep + Circadian tab — it sharpens "
                                "every sleep-based estimate." % (c.fv.sleep_probability,
                                c.fv.deep_sleep_probability or 0, c.fv.rem_probability or 0)),
            "stress": lambda c: ("It's built from HRV suppression and GSR rise. Acute = the last few "
                                 "minutes, chronic = the recent trend. A 4-in/6-out breathing minute "
                                 "usually moves it. Use the Live Signals tab to watch it in real time."),
            "anomaly": lambda c: ("Check sensor fit first (fingertip PPG especially), then re-measure. "
                                  "A genuine outlier outside your personal range gets logged in "
                                  "Diagnostics so we can spot patterns."),
            "circadian": lambda c: ("The CSI blends HR, HRV, temperature, GSR, activity, sleep timing "
                                    "and optional light exposure rhythms. The biggest single fix is "
                                    "consistent sleep/wake times."),
            "metabolic": lambda c: ("Insulin resistance tendency comes mostly from resting physiology, "
                                    "autonomic balance and glucose context. The metabolic-challenge tab "
                                    "compares pre/post-meal responses — trends matter more than a single "
                                    "number."),
            "hormones": lambda c: ("Hormone values are digital-twin estimates from physiology, glucose, "
                                   "cycle phase and uncertainty models — not blood tests. Confidence is "
                                   "deliberately low (wide CI); insulin and cortisol are the most reliable, "
                                   "the rest are exploratory."),
            "health": lambda c: ("The daily health score blends autonomic balance, circadian stability, "
                                 "sleep regularity, stress response and activity consistency. Any single "
                                 "low component pulls it down — ask about each to see where you lose "
                                 "points."),
            "whatif": lambda c: ("Use the What-if Lab tab to simulate: pick an intervention (e.g. "
                                 "better sleep, more activity), set a strength, and it recomputes the "
                                 "risk estimate and shows which domains move most."),
            "baseline": self._baseline_deep,
            "trend": self._trend_deep,
        }.get(topic)
        if extra:
            return base + "\n\n" + extra(ctx)
        return base + "\n\n(That's all the detail I have for this topic — try a more specific question.)"

    def _risk_deep(self, ctx: AssistantContext) -> str:
        r = ctx.result
        if r is None:
            return "No risk estimate yet."
        lines = ["Contribution breakdown (weighted, largest first):"]
        for label, pts, _key in r.contributions[:8]:
            lines.append(f"• {label}: +{pts:.1f} pts")
        lines.append("The top item is your biggest lever — ask \"what should I do?\" for steps, "
                     "or try the What-if Lab to simulate changes.")
        return "\n".join(lines)

    def _baseline_deep(self, ctx: AssistantContext) -> str:
        fv = ctx.fv
        bm = ctx.baseline
        if bm is None or not bm.has_baseline:
            return ("Capture a baseline and I can tell you exactly where you sit. Sit still "
                    "for 5 calm minutes, then press \"Capture baseline\".")
        lines = ["Your current position vs your personal baseline:"]
        for attr, label in [("hr_bpm", "HR"), ("rmssd_ms", "RMSSD"), ("skin_temp_c", "Temp"), ("gsr_tonic", "GSR")]:
            z = bm.zscore(attr, getattr(fv, attr) if fv else None)
            rng = bm.normal_range(attr)
            if rng is not None:
                pos = "inside" if (rng[0] <= getattr(fv, attr) <= rng[1]) else "outside"
                lines.append(f"• {label}: {_num(getattr(fv, attr), 1)} vs range {rng[0]:.1f}–{rng[1]:.1f} ({pos}); "
                             f"z-score {_num(z, 1)}")
        return "\n".join(lines)

    def _trend_deep(self, ctx: AssistantContext) -> str:
        if self.multi_day is None:
            return "No history module available."
        try:
            profile = self.multi_day.build_profile(days=7, trajectory_days=30)
        except Exception:
            return "Could not build the history yet."
        if not profile.trajectory:
            return "Not enough history for trajectory slopes yet."
        items = "\n".join(f"• {k}: {v:+.2f}/day" for k, v in list(profile.trajectory.items())[:6])
        return "Long-term trajectory (30-day slope per day):\n" + items

    # ------------------------------------------------------------ answers
    def _greeting(self, ctx: AssistantContext) -> str:
        mode = ctx.live_mode
        status = {"live": "a live sensor stream is connected", "demo": "demo (synthetic) data is running",
                  "replay": "a recorded session is being replayed", "none": "no stream is connected yet"}.get(mode, mode)
        return (f"Hi! I'm your CHRONO-PCOS assistant. Right now {status}. "
                "Try asking: \"why is my risk elevated?\", \"how did I sleep?\", "
                "\"what is my heart rate?\", \"compare today vs yesterday\", or "
                "\"what should I do?\" — and after any answer, say \"why?\" or \"more\" "
                "to go deeper.")

    def _help(self) -> str:
        return (
            "I can answer questions about your live data. Try:\n"
            "• \"What is my risk?\" / \"why is my risk elevated?\"\n"
            "• \"How did I sleep?\" / \"how is my stress?\" / \"what is my HR?\"\n"
            "• \"Any anomalies or warnings?\"\n"
            "• \"What should I do to improve?\"\n"
            "• \"Summarize my week\" / \"compare today vs yesterday\"\n"
            "• \"How is my circadian rhythm?\" / \"my personal baseline?\"\n"
            "• \"Is this real or demo data?\" / \"how confident is this?\"\n\n"
            "After any answer, say \"why?\" or \"more\" to go deeper, or \"and sleep?\" "
            "to continue on another topic."
        )

    def _risk(self, ctx: AssistantContext) -> str:
        r = ctx.result
        fv = ctx.fv
        if r is None:
            return "No risk estimate yet — connect a stream and give it a few seconds."
        lines = [f"Estimated PCOD/PCOS risk: **{r.risk_percent:.1f}%** ({r.category}).",
                 f"Confidence: {r.confidence:.0f}% · 90% interval {r.ci_low:.1f}–{r.ci_high:.1f}%."]
        doms = sorted(r.domain_scores.items(), key=lambda kv: kv[1], reverse=True)
        top = ", ".join(f"{k.replace('_', ' ')} {v:.0f}" for k, v in doms[:3])
        lines.append(f"Highest domain scores: {top}.")
        if fv is not None:
            lines.append(f"Current heart rate {_num(fv.hr_bpm)} bpm, HRV {_num(fv.rmssd_ms)} ms, "
                         f"skin temp {_num(fv.skin_temp_c, 1)} °C, stress {_num(fv.stress_index)}.")
        lines.append("This is an educational estimate from your sensor data — not a diagnosis.")
        return "\n".join(lines)

    def _drivers(self, ctx: AssistantContext) -> str:
        r = ctx.result
        if r is None or not r.contributions:
            return "No risk breakdown available yet."
        lines = ["Main contributors to your current risk estimate (largest first):"]
        for i, (label, _score, key) in enumerate(r.contributions[:6], 1):
            val = r.domain_scores.get(key)
            val_txt = f"{val:.0f}/100" if val is not None else "n/a"
            lines.append(f"{i}. {label} — domain score {val_txt}")
        lines.append("Tip: ask \"what should I do?\" for concrete steps, or use the "
                     "What-if Lab tab to simulate changes.")
        return "\n".join(lines)

    def _trend(self, ctx: AssistantContext) -> str:
        if self.multi_day is None:
            return "No multi-day history module available."
        try:
            profile = self.multi_day.build_profile(days=7, trajectory_days=30)
        except Exception:
            return "Could not build the multi-day profile yet — keep collecting sessions."
        if not profile.days:
            return "No recorded history yet. Run a few sessions (or load a demo week " \
                   "in the History tab) and I can summarize your trends."
        last = profile.days[-1]
        first = profile.days[0]
        lines = [f"Over the last {len(profile.days)} recorded day(s), here's the picture:"]
        if last.health_score is not None:
            trend = "↗ improving" if last.health_score > (first.health_score or 0) else "↘ declining"
            lines.append(f"• Daily health score: {last.health_score:.0f} ({trend} from {first.health_score:.0f} "
                         f"{first.date} to {last.date}).")
        if last.mean_risk is not None:
            lines.append(f"• Mean estimated risk: {last.mean_risk:.0f}% on {last.date}.")
        if last.circadian_stability is not None:
            lines.append(f"• Circadian stability: {last.circadian_stability:.0f}.")
        if last.mean_stress is not None:
            lines.append(f"• Mean stress: {last.mean_stress:.0f}.")
        if last.night_sleep_prob is not None:
            lines.append(f"• Night sleep probability: {last.night_sleep_prob:.0f}%.")
        if profile.trajectory:
            items = ", ".join(f"{k} {v:+.2f}/day" for k, v in list(profile.trajectory.items())[:4])
            lines.append(f"Long-term trajectory (30-day slopes): {items}.")
        lines.append("Full detail is on the History + Trends tab.")
        return "\n".join(lines)

    def _sleep(self, ctx: AssistantContext) -> str:
        fv = ctx.fv
        if fv is None:
            return "No live data yet."
        status = fv.sleep_status or "unknown"
        lines = [f"Sleep estimate: {status} (probability {fv.sleep_probability:.0f}%)."]
        if fv.deep_sleep_probability or fv.rem_probability:
            lines.append(f"Deep {fv.deep_sleep_probability:.0f}% · REM {fv.rem_probability:.0f}%.")
        lines.append("Estimates are derived from HR/HRV, temperature and motion — set your "
                     "sleep/wake times on the Sleep + Circadian tab to sharpen them.")
        return "\n".join(lines)

    def _stress(self, ctx: AssistantContext) -> str:
        fv = ctx.fv
        if fv is None:
            return "No live data yet."
        level = "high" if fv.stress_index > 70 else "moderate" if fv.stress_index > 45 else "low"
        lines = [f"Stress index: {fv.stress_index:.0f}/100 ({level})."]
        if fv.acute_stress or fv.chronic_stress:
            lines.append(f"Acute {fv.acute_stress:.0f} · chronic {fv.chronic_stress:.0f} · "
                         f"autonomic imbalance {fv.autonomic_imbalance:.0f}.")
        lines.append("Stress is estimated from HRV and GSR; deep breathing usually lowers "
                     "the index within minutes.")
        return "\n".join(lines)

    def _anomalies(self, ctx: AssistantContext) -> str:
        if not ctx.anomalies:
            if ctx.fv is not None and ctx.fv.anomaly_score:
                return f"No current anomalies — your anomaly score is {ctx.fv.anomaly_score:.0f}/100 (0 = normal)."
            return "No anomalies detected right now. I'll flag anything that strays beyond your personal range."
        lines = [f"{len(ctx.anomalies)} active anomaly/ies:"]
        for a in ctx.anomalies[:5]:
            sev = "high" if a.severity >= 60 else "moderate"
            lines.append(f"• {a.description} (severity {a.severity:.0f}, {sev})")
        lines.append("Note: educational outlier detection, not a medical alert.")
        return "\n".join(lines)

    def _recommend(self, ctx: AssistantContext) -> str:
        if ctx.recs:
            lines = ["Here's what I'd suggest, highest priority first:"]
            for i, rec in enumerate(ctx.recs[:5], 1):
                lines.append(f"{i}. [{rec.priority}] {rec.text}")
            lines.append("These follow the Explainable AI recommendations — try the What-if "
                         "Lab to simulate their effect before changing habits.")
            return "\n".join(lines)
        if ctx.fv is None:
            return "No live data yet — connect a stream first, then ask me for recommendations."
        return "Recommendations appear here once the risk estimate is running. Ask again in a moment."

    def _whatif(self, ctx: AssistantContext) -> str:
        r = ctx.result
        if r is None:
            return "No risk estimate yet — connect a stream first, then ask \"what if\" questions."
        top = sorted(r.domain_scores.items(), key=lambda kv: kv[1], reverse=True)[:3]
        doms = ", ".join(f"{k.replace('_', ' ')} ({v:.0f})" for k, v in top)
        lines = [
            f"Your biggest levers right now are {doms}.",
            "I can't run full simulations here, but the What-if Lab tab can: pick an "
            "intervention (better sleep, more activity, stress relief, glucose control...), "
            "set the strength, and it recomputes the risk and shows which domains move most.",
            "Short version of what usually helps most: fix sleep timing first, then add "
            "movement, then lower stress — in that order.",
        ]
        return "\n".join(lines)

    def _circadian(self, ctx: AssistantContext) -> str:
        fv = ctx.fv
        if fv is None:
            return "No live data yet."
        good = fv.circadian_stability_index >= 60
        return (f"Circadian stability index: {fv.circadian_stability_index:.0f}/100 "
                f"({'good rhythm' if good else 'disrupted rhythm'}). Disruption score "
                f"{fv.circadian_disruption:.0f}; temperature rhythm disruption "
                f"{fv.temperature_rhythm_disruption:.0f}. Regular sleep/wake timing is the "
                "biggest lever to improve it.")

    def _baseline(self, ctx: AssistantContext) -> str:
        bm = ctx.baseline
        if bm is None or not bm.has_baseline:
            return ("No personal baseline yet. Sit still for 5 calm minutes, then press "
                    "\"Capture baseline\" (or the physical BASELINE button). Until then I "
                    "compare against population defaults.")
        b = bm.baseline
        lines = [f"Personal baseline active (captured {b.duration_s:.0f}s, quality {b.quality:.2f}):"]
        for metric, label in [("hr_bpm", "Heart rate"), ("rmssd_ms", "HRV RMSSD"),
                              ("skin_temp_c", "Skin temp"), ("gsr_tonic", "GSR")]:
            rng = bm.normal_range(metric)
            if rng is not None:
                lines.append(f"• {label}: {rng[0]:.1f}–{rng[1]:.1f}")
        lines.append("Anomaly detection and risk confidence now use YOUR ranges, not population defaults.")
        return "\n".join(lines)

    def _metabolic(self, ctx: AssistantContext) -> str:
        fv = ctx.fv
        if fv is None:
            return "No live data yet."
        lines = [f"Insulin resistance tendency: {fv.insulin_resistance_probability:.0f}/100 · "
                 f"metabolic syndrome proxy {fv.metabolic_syndrome_proxy:.0f}/100."]
        g = ctx.profile.glucose_mg_dl if ctx.profile else None
        if g:
            lines.append(f"Latest glucose: {g:.0f} mg/dL ({ctx.profile.glucose_context}).")
        else:
            lines.append("Add a glucose reading in the top bar for a more complete metabolic picture.")
        return "\n".join(lines)

    def _hormones(self, ctx: AssistantContext) -> str:
        if ctx.result is None:
            return "No hormone estimates yet."
        est = ctx.result.hormone_estimates
        if not est:
            return "No hormone estimates available yet."
        top = sorted(est.values(), key=lambda h: h.value, reverse=True)[:4]
        lines = ["Estimated hormone tendencies (from physiology + cycle phase, NOT measured):"]
        for h in top:
            lines.append(f"• {h.name}: {h.value:.1f} (confidence {h.confidence:.0f}%)")
        lines.append("These are digital-twin estimates with wide confidence intervals — "
                     "the Hormone Twin tab explains the pathway.")
        return "\n".join(lines)

    def _health(self, ctx: AssistantContext) -> str:
        fv = ctx.fv
        if fv is None:
            return "No live data yet."
        from src.models.composite_scores import compute_scores
        s = compute_scores(fv)
        grade = "good" if s.daily_health_score >= 65 else "fair" if s.daily_health_score >= 45 else "needs attention"
        return (f"Daily health score: {s.daily_health_score:.0f}/100 ({grade}). It blends "
                f"autonomic balance {s.autonomic_balance:.0f}, circadian stability "
                f"{s.circadian_stability:.0f}, sleep regularity {s.sleep_regularity:.0f}, "
                f"stress response {s.stress_response:.0f} and activity consistency "
                f"{s.activity_consistency:.0f}.")

    def _bp(self, ctx: AssistantContext) -> str:
        p = ctx.profile
        if p is None or not (p.systolic_bp or p.diastolic_bp):
            return "No blood pressure entered. Type SYS/DIA in the top bar (e.g. 118 / 76)."
        sys, dia = p.systolic_bp, p.diastolic_bp
        txt = f"Blood pressure: {sys:.0f}/{dia:.0f} mmHg."
        if sys and dia:
            if sys >= 140 or dia >= 90:
                txt += " This is in the elevated/hypertensive range — worth checking with a professional."
            elif sys >= 120:
                txt += " Slightly elevated; re-measure after 5 calm minutes."
            else:
                txt += " Within the normal range for educational monitoring."
        txt += " Manual entry only — the cuff must not be wired to the Arduino."
        return txt

    def _confidence(self, ctx: AssistantContext) -> str:
        r = ctx.result
        if r is None:
            return "No estimate yet."
        why = []
        fv = ctx.fv
        if fv is not None:
            if not fv.baseline_available:
                why.append("no personal baseline captured")
            if fv.signal_quality is not None and fv.signal_quality < 0.5:
                why.append("signal quality is low")
        if ctx.profile is not None and not ctx.profile.glucose_mg_dl:
            why.append("no glucose reading")
        tail = f" To raise it: {', '.join(why)}." if why else ""
        return (f"Confidence: {r.confidence:.0f}% (90% interval {r.ci_low:.1f}–{r.ci_high:.1f}%)."
                f"{tail} A personal baseline and good signal quality matter most.")

    def _mode(self, ctx: AssistantContext) -> str:
        mode = ctx.live_mode
        if mode == "live":
            return "You're connected to a live sensor stream (serial or Wi-Fi bridge) — this is real recorded data."
        if mode == "demo":
            return ("Demo Mode is running: the stream is SYNTHETIC, generated for UI testing. "
                    "Do not treat it as real data. Connect the Arduino for real measurements.")
        if mode == "replay":
            return "A previously recorded session is being replayed onto the live dashboard — this is real recorded data from your database."
        return "No stream is connected yet."

    def _thanks(self, ctx: AssistantContext) -> str:
        return ("You're welcome! Ask me anything about your data — risk, sleep, stress, "
                "trends, or what to do next. Try \"why?\" after an answer to go deeper.")

    def _about(self, ctx: AssistantContext) -> str:
        return ("I'm the CHRONO-PCOS assistant. I answer questions about the dashboard's "
                "live data — risk estimate, what's driving it, sleep, stress, anomalies, "
                "trends and recommendations — always from real computed values. I can "
                "also compare days, look up any metric, and follow up on what we just "
                "discussed. If an LLM endpoint is configured I can answer conversationally "
                "over the same context.")

    def _fallback(self, ctx: AssistantContext) -> str:
        r = ctx.result
        head = f"Right now your estimated risk is {r.risk_percent:.1f}% ({r.category})." if r else \
            "I don't have a live estimate yet."
        return (head + " I can help with: risk & why, sleep, stress, anomalies, recommendations, "
                "circadian rhythm, personal baseline, glucose/metabolic, trends, or how confident "
                "the estimate is. Type \"help\" for examples.")

    def _combined(self, t1: str, t2: str, ctx: AssistantContext) -> str:
        return (f"**{TITLES[t1]}**\n{self._answer_for(t1, ctx)}\n\n"
                f"**{TITLES[t2]}**\n{self._answer_for(t2, ctx)}\n\n"
                "Tip: ask \"what should I do?\" for prioritized advice covering both.")


# --------------------------------------------------------------- LLM client
class LLMAssistant:
    """OpenAI-compatible chat client with free-tier provider presets.

    Resolution order (first non-empty wins):
      1. explicit arguments
      2. environment variables (CHRONO_LLM_PROVIDER / URL / MODEL / API_KEY)
      3. the saved config file (data/ai_config.json, written by the UI dialog)
      4. the provider preset defaults
    """

    def __init__(self, provider: Optional[str] = None, url: Optional[str] = None,
                 model: Optional[str] = None, api_key: Optional[str] = None,
                 config_path: Optional[Path] = None):
        cfg = load_ai_config(config_path)
        provider = (provider or os.environ.get("CHRONO_LLM_PROVIDER") or cfg.get("provider") or "").strip() or None
        url = (url or os.environ.get("CHRONO_LLM_URL") or cfg.get("url") or "").strip() or None
        model = (model or os.environ.get("CHRONO_LLM_MODEL") or cfg.get("model") or "").strip() or None
        env_key = os.environ.get("CHRONO_LLM_API_KEY", "").strip() or None
        api_key = (api_key if api_key is not None else (env_key or cfg.get("api_key"))) or None

        preset = PROVIDERS.get((provider or "").lower())
        if preset:
            if not url:
                url = str(preset["url"]) or None
            if not model:
                model = str(preset["model"]) or None
        self.provider = provider or ("custom" if url else None)
        self.url = url
        self.model = model
        self.api_key = api_key

    @property
    def available(self) -> bool:
        return bool(self.url and self.model)

    def chat(self, question: str, context_text: str, timeout: int = 25) -> Optional[str]:
        """Return the LLM's answer, or None if not configured or on any error."""
        if not self.available:
            return None
        system = (
            "You are the CHRONO-PCOS assistant inside an educational physiological "
            "monitoring dashboard. Answer ONLY from the provided context snapshot; "
            "if the answer is not in the context, say so and suggest what data would "
            "help. Be concise, friendly and structured with short bullet points. End "
            "with the line: 'Educational tool — not medical advice.'"
        )
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": f"Context:\n{context_text}\n\nQuestion: {question}"},
            ],
            "temperature": 0.3,
            "max_tokens": 700,
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(
            self.url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            content = data["choices"][0]["message"]["content"]
            return content.strip() or None
        except Exception:
            return None


# ------------------------------------------------------------------ engine
class AssistantEngine:
    """Routes questions: LLM when available and healthy, otherwise local."""

    def __init__(self, history_store=None, multi_day=None, llm: Optional[LLMAssistant] = None):
        self.history_store = history_store
        self.multi_day = multi_day
        self.local = LocalAssistant(history_store=history_store, multi_day=multi_day)
        self.llm = llm if llm is not None else LLMAssistant()

    def mode_label(self) -> str:
        if self.llm.available:
            provider = self.llm.provider or "custom"
            return f"Local + LLM ({self.llm.model} · {provider})"
        return "Local grounded (offline)"

    def configure_llm(self, provider: Optional[str] = None, url: Optional[str] = None,
                      model: Optional[str] = None, api_key: Optional[str] = None,
                      persist: bool = True) -> LLMAssistant:
        """(Re)build the LLM client from dialog values and optionally save them."""
        self.llm = LLMAssistant(provider=provider, url=url, model=model, api_key=api_key)
        if persist:
            save_ai_config({
                "provider": provider or "",
                "url": url or "",
                "model": model or "",
                "api_key": api_key or "",
            })
        return self.llm

    def context_text(self, ctx: AssistantContext) -> str:
        """Compact structured snapshot for the LLM so it answers from real data."""
        lines: List[str] = []
        r = ctx.result
        fv = ctx.fv
        lines.append(f"Live mode: {ctx.live_mode}")
        if r is not None:
            lines.append(f"Risk: {r.risk_percent:.1f}% ({r.category}), confidence {r.confidence:.0f}%, "
                         f"90% interval {r.ci_low:.1f}-{r.ci_high:.1f}")
            doms = ", ".join(f"{k.replace('_', ' ')}={v:.0f}" for k, v in
                             sorted(r.domain_scores.items(), key=lambda kv: kv[1], reverse=True))
            lines.append(f"Domain scores: {doms}")
        if fv is not None:
            lines.append(f"Vitals: HR {_num(fv.hr_bpm)} bpm, HRV {_num(fv.rmssd_ms)} ms, SpO2 "
                         f"{_num(fv.spo2_pct)}%, skin temp {_num(fv.skin_temp_c, 1)} C, GSR {_num(fv.gsr_tonic)}, "
                         f"stress {_num(fv.stress_index)}, sleep {fv.sleep_status} {_num(fv.sleep_probability)}, "
                         f"circadian {_num(fv.circadian_stability_index)}, insulin resistance "
                         f"{_num(fv.insulin_resistance_probability)}, signal quality {_num(fv.signal_quality, 2)}, "
                         f"anomaly score {_num(fv.anomaly_score)}")
        bm = ctx.baseline
        if bm is not None and bm.has_baseline:
            ranges = []
            for metric, label in [("hr_bpm", "HR"), ("rmssd_ms", "RMSSD"), ("skin_temp_c", "Temp"), ("gsr_tonic", "GSR")]:
                rng = bm.normal_range(metric)
                if rng is not None:
                    ranges.append(f"{label} {rng[0]:.1f}-{rng[1]:.1f}")
            lines.append(f"Personal baseline ranges: {', '.join(ranges)}")
        else:
            lines.append("Personal baseline: not captured (population defaults in use)")
        if ctx.anomalies:
            lines.append("Active anomalies: " + "; ".join(a.description for a in ctx.anomalies[:4]))
        if ctx.recs:
            lines.append("Recommendations: " + " | ".join(f"[{rec.priority}] {rec.text}" for rec in ctx.recs[:5]))
        if ctx.profile is not None:
            p = ctx.profile
            lines.append(f"Profile: age {p.age_years:.0f}, BMI {p.bmi:.1f}" if p.bmi else
                         f"Profile: age {p.age_years:.0f}, BMI not set")
            if p.glucose_mg_dl:
                lines.append(f"Glucose {p.glucose_mg_dl:.0f} mg/dL ({p.glucose_context})")
            if p.systolic_bp:
                lines.append(f"BP {p.systolic_bp:.0f}/{p.diastolic_bp or 0:.0f}")
            if p.cycle_day:
                lines.append(f"Cycle day {p.cycle_day}, length {p.usual_cycle_length_days or 'unknown'}")
        lines.append("Note: all values are educational estimates from sensor data, not clinical results.")
        return "\n".join(lines)

    def answer(self, question: str, ctx: AssistantContext,
               memory: Optional[dict] = None) -> Tuple[str, str]:
        """Return (answer_text, mode) where mode is 'llm' or 'local'."""
        if self.llm.available:
            ctx_text = self.context_text(ctx)
            ans = self.llm.chat(question, ctx_text)
            if ans:
                return ans, "llm"
        text, _ = self.local.answer(question, ctx, memory)
        return text, "local"
