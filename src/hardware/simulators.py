"""Hardware-free wearable simulators (V5, sections 2 + 33).

The school-project demonstration must run without physical hardware. These
simulators generate realistic PPG / temperature / IMU / ECG / insole streams,
including scripted *scenarios* so the digital-twin behaviour can be shown:

  normal               - steady, healthy pattern
  gradual_change       - HR slowly rises (progressive trend)
  persistent_deviation - HR steps up and holds (persistent offset)
  sensor_failure       - PPG drops out mid-session (quality collapse)
  recovery             - a deviation that returns to baseline

Everything here is explicitly demo data, never training data.
"""
from __future__ import annotations

import math
import time
from enum import Enum
from typing import Iterator


class DemoScenario(str, Enum):
    NORMAL = "normal"
    GRADUAL_CHANGE = "gradual_change"
    PERSISTENT_DEVIATION = "persistent_deviation"
    SENSOR_FAILURE = "sensor_failure"
    RECOVERY = "recovery"

    @staticmethod
    def choices() -> list[str]:
        return [s.value for s in DemoScenario]


class SimulatedRing:
    """Smart-ring simulator: PPG (IR/red) + skin temperature + IMU + battery.

    Yields channel dicts shaped exactly like `RingPPGProvider.read()` output,
    so the pipeline treats it identically to a real device.
    """

    def __init__(self, fs_hz: float = 50.0, scenario: str = "normal",
                 battery_pct: float = 100.0, seed: int = 7):
        self.fs_hz = fs_hz
        self.scenario = DemoScenario(scenario) if isinstance(scenario, str) else scenario
        self.battery_pct = battery_pct
        self._rng = __import__("numpy").random.default_rng(seed)
        self._seq = 0

    def hr_profile(self, t: float, warmup_s: float = 60.0) -> float:
        """Heart-rate curve for the current scenario (bpm)."""
        base = 72.0 + 2.0 * math.sin(2 * math.pi * t / 40.0)
        if self.scenario == DemoScenario.GRADUAL_CHANGE:
            ramp = 72.0 + 28.0 * min(1.0, max(0.0, (t - warmup_s) / 240.0))
            return ramp + 2.0 * math.sin(2 * math.pi * t / 40.0)
        if self.scenario == DemoScenario.PERSISTENT_DEVIATION:
            step = 105.0 if t >= warmup_s else 72.0
            return step + 2.0 * math.sin(2 * math.pi * t / 40.0)
        if self.scenario == DemoScenario.RECOVERY:
            if t >= warmup_s and t < warmup_s + 120.0:
                return 105.0 + 2.0 * math.sin(2 * math.pi * t / 40.0)
            return base
        return base

    def stream(self, duration_s: float, t0: float | None = None) -> Iterator[dict]:
        t0 = t0 if t0 is not None else time.time()
        start = t0
        n = int(duration_s * self.fs_hz)
        for i in range(n):
            t = start + i / self.fs_hz
            elapsed = t - t0
            hr = self.hr_profile(elapsed)
            pulse_freq = hr / 60.0

            failed = (self.scenario == DemoScenario.SENSOR_FAILURE
                      and 90.0 <= elapsed < 150.0)
            if failed:
                # Sensor dropout: no optical signal (contact lost).
                ir, red = 0, 0
            else:
                ir = 48000 + 2500 * math.sin(2 * math.pi * pulse_freq * t) \
                     + 400 * math.sin(2 * math.pi * 2 * pulse_freq * t) \
                     + float(self._rng.normal(0, 120))
                red = 45000 + 2100 * math.sin(2 * math.pi * pulse_freq * t + 0.08) \
                      + float(self._rng.normal(0, 110))

            motion = 0.05 if hr < 95 else 0.20
            self._seq += 1
            yield {
                "ts": t,
                "seq": self._seq,
                "ppg_ir": int(max(0, ir)),
                "ppg_red": int(max(0, red)),
                "skin_temp_c": 32.6 + 0.2 * math.sin(2 * math.pi * t / 86400.0),
                "ax_g": float(self._rng.normal(0, motion)),
                "ay_g": float(self._rng.normal(0, motion)),
                "az_g": 1.0 + float(self._rng.normal(0, motion)),
                "battery_pct": max(0.0, self.battery_pct - 0.001 * i),
            }
