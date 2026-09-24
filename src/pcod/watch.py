"""Smartwatch link — ingest, validation, storage and simulation.

The companion accepts watch data through **three** paths, and treats all of
them identically once the data arrives:

1. **Web Bluetooth (BLE)** — the phone's or desktop's Chrome browser connects
   directly to the watch's standard *Heart Rate service* (`0x180D`) and
   *Battery service* (`0x180F`). No native Bluetooth driver is needed, which
   is what makes this work on an Android phone running Termux.
2. **HTTP ingest** — any watch, phone bridge, Wear OS app, Tasker profile or
   Gadgetbridge export can POST JSON to `/api/watch/ingest`.
3. **Simulated watch** — a labelled synthetic stream so the whole app is
   demonstrable without hardware. Clearly marked, never mixed with real data.

Honesty rules
-------------
* Out-of-range or impossible values are rejected, not clamped into plausibility.
* Consumer SpO₂ is stored as a *wellness estimate*; it never feeds a
  sleep-apnoea conclusion.
* Simulated data is tagged `source="simulated"` and is excluded from exports
  of real data.
"""
from __future__ import annotations

import json
import math
import random
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional

# Physiologically plausible acceptance ranges. Values outside these are
# rejected rather than silently corrected.
HR_RANGE = (25.0, 220.0)
SPO2_RANGE = (70.0, 100.0)
TEMP_RANGE = (20.0, 45.0)
RR_RANGE = (200.0, 2500.0)      # ms between beats

WINDOW_DAYS = 14                # days of data the app asks for before trusting trends
SAMPLES_PER_DAY_TARGET = 1      # at least one reading per day counts as a covered day


@dataclass
class WatchSample:
    """One reading from a watch, already normalised and validated."""

    ts: float
    hr_bpm: Optional[float] = None
    rr_ms: List[float] = field(default_factory=list)   # inter-beat intervals
    spo2_pct: Optional[float] = None                   # wellness estimate only
    steps: Optional[int] = None
    sleep_hours: Optional[float] = None
    wrist_temp_c: Optional[float] = None
    active_minutes: Optional[float] = None
    battery_pct: Optional[float] = None
    device: str = ""
    source: str = "ble"                                # ble | http | simulated | manual
    rejected: List[str] = field(default_factory=list)

    @property
    def rmssd_ms(self) -> Optional[float]:
        """Root mean square of successive differences — the standard short-term HRV metric."""
        rr = [x for x in self.rr_ms if RR_RANGE[0] <= x <= RR_RANGE[1]]
        if len(rr) < 3:
            return None
        diffs = [rr[i + 1] - rr[i] for i in range(len(rr) - 1)]
        return math.sqrt(sum(d * d for d in diffs) / len(diffs))

    def as_dict(self) -> dict:
        d = asdict(self)
        d["rmssd_ms"] = self.rmssd_ms
        return d


# --------------------------------------------------------------------------
def validate(sample: WatchSample) -> List[str]:
    """Return a list of rejection reasons (empty = accepted)."""
    problems: List[str] = []
    if sample.hr_bpm is not None and not (HR_RANGE[0] <= sample.hr_bpm <= HR_RANGE[1]):
        problems.append(f"heart rate {sample.hr_bpm} outside {HR_RANGE}")
        sample.hr_bpm = None
    if sample.spo2_pct is not None and not (SPO2_RANGE[0] <= sample.spo2_pct <= SPO2_RANGE[1]):
        problems.append(f"SpO2 {sample.spo2_pct} outside {SPO2_RANGE}")
        sample.spo2_pct = None
    if sample.wrist_temp_c is not None and not (TEMP_RANGE[0] <= sample.wrist_temp_c <= TEMP_RANGE[1]):
        problems.append(f"wrist temperature {sample.wrist_temp_c} outside {TEMP_RANGE}")
        sample.wrist_temp_c = None
    if sample.steps is not None and (sample.steps < 0 or sample.steps > 100_000):
        problems.append(f"step count {sample.steps} out of range")
        sample.steps = None
    if sample.sleep_hours is not None and not (0.0 <= sample.sleep_hours <= 24.0):
        problems.append(f"sleep {sample.sleep_hours} h out of range")
        sample.sleep_hours = None
    sample.rr_ms = [x for x in sample.rr_ms if RR_RANGE[0] <= x <= RR_RANGE[1]]
    sample.rejected = problems
    return problems


def from_payload(payload: dict, source: str = "http") -> WatchSample:
    """Build a validated sample from a JSON dict.

    Tolerates the field names several common bridges use.
    """
    p = payload or {}

    def pick(*names):
        for n in names:
            if n in p and p[n] is not None:
                return p[n]
        return None

    def as_float(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    rr = pick("rr_ms", "rri", "ibi_ms", "rr_intervals") or []
    if isinstance(rr, str):
        try:
            rr = json.loads(rr)
        except (ValueError, TypeError):
            rr = []
    rr = [as_float(x) for x in rr] if isinstance(rr, list) else []
    rr = [x for x in rr if x is not None]

    s = WatchSample(
        ts=as_float(pick("ts", "timestamp", "time")) or time.time(),
        hr_bpm=as_float(pick("hr_bpm", "hr", "heart_rate", "bpm")),
        rr_ms=rr,
        spo2_pct=as_float(pick("spo2_pct", "spo2", "oxygen", "sat")),
        steps=int(as_float(pick("steps", "step_count")) or 0) if pick("steps", "step_count") is not None else None,
        sleep_hours=as_float(pick("sleep_hours", "sleep", "sleep_h")),
        wrist_temp_c=as_float(pick("wrist_temp_c", "skin_temp_c", "temperature", "temp_c")),
        active_minutes=as_float(pick("active_minutes", "active_min", "exercise_minutes")),
        battery_pct=as_float(pick("battery_pct", "battery", "batt")),
        device=str(pick("device", "device_name", "source_device") or ""),
        source=source,
    )
    validate(s)
    return s


# --------------------------------------------------------------------------
class WatchStore:
    """Append-only local store of watch samples (JSON, offline)."""

    MAX_SAMPLES = 20000

    def __init__(self, path: str | Path | None = None):
        from src.config import DATA_DIR
        self.path = Path(path) if path else DATA_DIR / "pcod" / "watch_samples.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.samples: List[WatchSample] = []
        self._load()

    # ------------------------------------------------------------ persistence
    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text())
        except (ValueError, OSError):
            return
        for item in raw[-self.MAX_SAMPLES:]:
            s = WatchSample(**{k: v for k, v in item.items()
                               if k in WatchSample.__dataclass_fields__})
            self.samples.append(s)

    def save(self) -> None:
        data = [asdict(s) for s in self.samples[-self.MAX_SAMPLES:]]
        self.path.write_text(json.dumps(data))

    # ----------------------------------------------------------------- ingest
    def add(self, sample: WatchSample) -> dict:
        problems = validate(sample)
        if sample.hr_bpm is None and sample.spo2_pct is None and not sample.rr_ms \
                and sample.steps is None and sample.sleep_hours is None:
            return {"accepted": False, "reason": "No usable measurement in the payload.",
                    "rejected": problems}
        self.samples.append(sample)
        if len(self.samples) > self.MAX_SAMPLES:
            self.samples = self.samples[-self.MAX_SAMPLES:]
        self.save()
        return {"accepted": True, "rejected": problems, "sample": sample.as_dict()}

    # ------------------------------------------------------------------ views
    def latest(self) -> Optional[WatchSample]:
        return self.samples[-1] if self.samples else None

    def latest_dict(self) -> Optional[dict]:
        s = self.latest()
        return s.as_dict() if s else None

    def within(self, seconds: float) -> List[WatchSample]:
        cutoff = time.time() - seconds
        return [s for s in self.samples if s.ts >= cutoff]

    def covered_days(self) -> int:
        days = {time.strftime("%Y-%m-%d", time.localtime(s.ts)) for s in self.samples}
        return len(days)

    def sufficiency(self) -> float:
        return min(1.0, self.covered_days() / float(WINDOW_DAYS))

    def summary(self) -> dict:
        last = self.latest()
        day = self.within(86400)
        hrs = [s.hr_bpm for s in day if s.hr_bpm is not None]
        rmssds = [s.rmssd_ms for s in day if s.rmssd_ms is not None]
        steps = sum(s.steps or 0 for s in day)
        sleeps = [s.sleep_hours for s in day if s.sleep_hours is not None]
        spo2s = [s.spo2_pct for s in day if s.spo2_pct is not None]
        temps = [s.wrist_temp_c for s in day if s.wrist_temp_c is not None]

        def mean(xs):
            return sum(xs) / len(xs) if xs else None

        return {
            "connected": last is not None,
            "device": last.device if last else "",
            "source": last.source if last else "",
            "last_update_s_ago": (time.time() - last.ts) if last else None,
            "samples_total": len(self.samples),
            "samples_24h": len(day),
            "covered_days": self.covered_days(),
            "window_days": WINDOW_DAYS,
            "sufficiency": round(self.sufficiency(), 3),
            "latest": last.as_dict() if last else None,
            "hr_mean_24h": mean(hrs),
            "hr_min_24h": min(hrs) if hrs else None,
            "hr_max_24h": max(hrs) if hrs else None,
            "rmssd_mean_24h": mean(rmssds),
            "steps_24h": steps or None,
            "sleep_hours_latest": sleeps[-1] if sleeps else None,
            "sleep_hours_mean_24h": mean(sleeps),
            "spo2_mean_24h": mean(spo2s),
            "wrist_temp_mean_24h": mean(temps),
        }

    def clear(self, source_filter: str | None = None) -> int:
        before = len(self.samples)
        if source_filter:
            self.samples = [s for s in self.samples if s.source != source_filter]
        else:
            self.samples = []
        self.save()
        return before - len(self.samples)


# --------------------------------------------------------------------------
class SimulatedWatch:
    """A clearly-labelled synthetic watch for demonstration and testing.

    It is NOT patient data and is excluded from real exports.
    """

    def __init__(self, seed: int = 11, device: str = "CHRONO Demo Watch"):
        self.rng = random.Random(seed)
        self.device = device
        self.t = 0.0
        self.battery = 82.0

    def sample(self, ts: Optional[float] = None) -> WatchSample:
        self.t += 1.0
        phase = (self.t // 180) % 3          # rest / stress / movement
        base_hr = 68.0 if phase == 0 else 92.0 if phase == 1 else 104.0
        hr = base_hr + 3.0 * math.sin(self.t / 12.0) + self.rng.gauss(0, 1.2)
        # ~25 ms of beat-to-beat variation gives a resting RMSSD in the 25-45 ms
        # range typical of a healthy adult, rather than an implausibly flat trace.
        rr = []
        for _ in range(20):
            rr.append(60000.0 / max(35.0, hr) + self.rng.gauss(0, 25.0))
        spo2 = 97.5 + self.rng.gauss(0, 0.5)
        steps = self.rng.randint(0, 60) if phase != 2 else self.rng.randint(40, 180)
        self.battery = max(3.0, self.battery - 0.002)
        s = WatchSample(
            ts=ts if ts is not None else time.time(),
            hr_bpm=round(hr, 1),
            rr_ms=[round(x, 1) for x in rr],
            spo2_pct=round(min(100.0, spo2), 1),
            steps=steps,
            sleep_hours=round(7.2 + self.rng.gauss(0, 0.8), 2) if phase == 0 else None,
            wrist_temp_c=round(32.4 + self.rng.gauss(0, 0.18), 2),
            active_minutes=round(abs(self.rng.gauss(6, 4)), 1),
            battery_pct=round(self.battery, 1),
            device=self.device,
            source="simulated",
        )
        validate(s)
        return s

    def backfill_days(self, days: int = 14, per_day: int = 4) -> List[WatchSample]:
        """Generate a plausible multi-day history so trend views are populated."""
        out: List[WatchSample] = []
        now = time.time()
        for d in range(days, 0, -1):
            for k in range(per_day):
                ts = now - d * 86400 + k * 3600 * 5
                s = self.sample(ts=ts)
                if k == 0:
                    s.sleep_hours = round(6.5 + self.rng.gauss(0, 1.1), 2)
                    s.steps = self.rng.randint(2500, 9000)
                out.append(s)
        return out


# --------------------------------------------------------------------------
# BLE service map used by the browser-side Web Bluetooth client.
# --------------------------------------------------------------------------
BLE_SERVICES = {
    "heart_rate": {"uuid": "0x180D", "characteristic": "0x2A37",
                   "measures": ["hr_bpm", "rr_ms"], "notify": True},
    "battery": {"uuid": "0x180F", "characteristic": "0x2A19",
                "measures": ["battery_pct"], "notify": False},
    "pulse_oximeter": {"uuid": "0x1822", "characteristic": "0x2A5F",
                       "measures": ["spo2_pct"], "notify": True},
    "health_thermometer": {"uuid": "0x1809", "characteristic": "0x2A1C",
                           "measures": ["wrist_temp_c"], "notify": True},
}
