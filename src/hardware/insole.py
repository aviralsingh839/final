"""Optional smart-insole module (V5, section 5).

A behavioural/biomechanical longitudinal signal - NOT a PCOS detector. The
insole provides 8 pressure zones (heel / medial midfoot / lateral midfoot /
forefoot / toe, left + right) plus a small IMU. From these we compute step
count, cadence, stance time, pressure distribution, left/right asymmetry,
gait consistency (stride-time CV) and walking duration.

`SimulatedInsole` generates a realistic walking pattern so the module can be
demonstrated without hardware.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator, List

import numpy as np

ZONE_NAMES = [
    "left_heel", "left_midfoot", "left_forefoot", "left_toe",
    "right_heel", "right_midfoot", "right_forefoot", "right_toe",
]
LEFT_ZONES = [0, 1, 2, 3]
RIGHT_ZONES = [4, 5, 6, 7]


@dataclass
class InsoleFrame:
    ts: float
    zones: List[float] = field(default_factory=lambda: [0.0] * 8)
    ax_g: float = 0.0
    ay_g: float = 0.0
    az_g: float = 1.0


@dataclass
class InsoleReport:
    n_frames: int = 0
    duration_s: float = 0.0
    step_count: int = 0
    cadence_steps_per_min: float = 0.0
    stance_time_s: float = 0.0
    walking_duration_s: float = 0.0
    activity_intensity: float = 0.0          # 0..1
    lr_asymmetry: float = 0.0                # |L-R| / (L+R), 0 = symmetric
    gait_consistency: float = 0.0            # 0..1 (1 - stride CV)
    gait_variability: float = 0.0            # stride-time CV
    pressure_distribution: dict = field(default_factory=dict)  # zone -> % of total

    def as_dict(self) -> dict:
        d = self.__dict__.copy()
        d["pressure_distribution"] = {k: round(v, 2) for k, v in self.pressure_distribution.items()}
        return d


class InsoleAnalyzer:
    """Step/gait analysis from pressure frames (heel-contact based)."""

    def __init__(self, heel_threshold: float = 120.0, fs_hz: float = 50.0):
        self.heel_threshold = heel_threshold
        self.fs_hz = fs_hz

    def analyze(self, frames: List[InsoleFrame]) -> InsoleReport:
        rep = InsoleReport(n_frames=len(frames))
        if len(frames) < 2:
            return rep
        rep.duration_s = frames[-1].ts - frames[0].ts
        total_pressure = np.asarray([f.zones for f in frames], dtype=float)
        if total_pressure.size == 0:
            return rep

        # Step detection: heel zone crossing above threshold = foot contact.
        left_heel = total_pressure[:, 0]
        right_heel = total_pressure[:, 4]
        left_contacts = self._contacts(left_heel, self.heel_threshold)
        right_contacts = self._contacts(right_heel, self.heel_threshold)
        rep.step_count = len(left_contacts) + len(right_contacts)
        rep.walking_duration_s = rep.duration_s

        # Cadence from inter-contact intervals (steps per minute).
        intervals = []
        prev = None
        for t in sorted(left_contacts + right_contacts):
            if prev is not None:
                intervals.append(t - prev)
            prev = t
        if intervals:
            rep.cadence_steps_per_min = 60.0 / (float(np.mean(intervals)) if np.mean(intervals) > 1e-6 else 1.0)
            cv = float(np.std(intervals) / max(np.mean(intervals), 1e-9))
            rep.gait_variability = cv
            rep.gait_consistency = max(0.0, 1.0 - cv)

        # Stance time: mean heel-contact duration.
        stance = []
        for contacts in (left_contacts, right_contacts):
            for t0 in contacts:
                # heel above threshold while walking in a window around t0
                idx = int(round((t0 - frames[0].ts) * self.fs_hz))
                if 0 <= idx < len(left_heel):
                    # rough stance: consecutive samples above threshold near contact
                    j = idx
                    while j < len(left_heel) and (left_heel[j] > self.heel_threshold or right_heel[j] > self.heel_threshold):
                        j += 1
                    stance.append((j - idx) / self.fs_hz)
        if stance:
            rep.stance_time_s = float(np.mean(stance))

        # Left/right asymmetry of total load (pressure-based, more meaningful
        # than contact counts for mild imbalances).
        l_load = float(total_pressure[:, LEFT_ZONES].sum())
        r_load = float(total_pressure[:, RIGHT_ZONES].sum())
        if l_load + r_load > 1e-9:
            rep.lr_asymmetry = abs(l_load - r_load) / (l_load + r_load)

        # Activity intensity: fraction of frames with any zone above threshold.
        active = float(np.mean(np.max(total_pressure, axis=1) > self.heel_threshold))
        rep.activity_intensity = float(np.clip(active, 0.0, 1.0))

        # Pressure distribution across zones.
        sums = total_pressure.sum(axis=0)
        tot = float(sums.sum())
        if tot > 1e-6:
            rep.pressure_distribution = {ZONE_NAMES[i]: float(sums[i] / tot * 100.0) for i in range(8)}
        return rep

    def _contacts(self, series: np.ndarray, threshold: float) -> List[float]:
        """Contact start times (rising edge above threshold), with refractory."""
        out = []
        above = False
        refractory = int(0.25 * self.fs_hz)  # 250 ms min between steps
        last = -1e9
        for i, v in enumerate(series):
            if v > threshold and not above and (i - last) > refractory:
                out.append(i)
                last = i
                above = True
            elif v <= threshold:
                above = False
        return [float(i) / self.fs_hz for i in out]


class SimulatedInsole:
    """Generates realistic walking pressure frames (demo / tests)."""

    def __init__(self, fs_hz: float = 50.0, cadence_steps_per_min: float = 100.0,
                 asymmetry: float = 0.0, battery_pct: float = 100.0):
        self.fs_hz = fs_hz
        self.cadence = cadence_steps_per_min
        self.asymmetry = asymmetry
        self.battery_pct = battery_pct
        self.rng = np.random.default_rng(11)

    def stream(self, duration_s: float, t0: float = 0.0) -> Iterator[InsoleFrame]:
        n = int(duration_s * self.fs_hz)
        step_period = 60.0 / self.cadence  # seconds per step (each foot)
        for i in range(n):
            t = t0 + i / self.fs_hz
            phase = (t % (2 * step_period)) / (2 * step_period)  # 0..1 per gait cycle
            zones = [0.0] * 8
            # Heel strike then forefoot/toe push-off per foot.
            left_cycle = (t % (2 * step_period)) / (2 * step_period)
            right_cycle = ((t + step_period) % (2 * step_period)) / (2 * step_period)
            for side, cycle in ((0, left_cycle), (4, right_cycle)):
                heel_amp = 320.0 if 0.0 <= cycle < 0.18 else 0.0
                ff_amp = 240.0 if 0.55 <= cycle < 0.85 else 0.0
                toe_amp = 180.0 if 0.70 <= cycle < 0.95 else 0.0
                mid = 0.3 * (heel_amp + ff_amp)
                zones[side + 0] = max(0, heel_amp + self.rng.normal(0, 12))
                zones[side + 1] = max(0, mid + self.rng.normal(0, 8))
                zones[side + 2] = max(0, ff_amp + self.rng.normal(0, 10))
                zones[side + 3] = max(0, toe_amp + self.rng.normal(0, 8))
            # Introduce a slight left/right imbalance if requested.
            if self.asymmetry > 0:
                zones[4:] = [z * (1.0 - self.asymmetry) for z in zones[4:]]
            yield InsoleFrame(
                ts=t, zones=zones,
                ax_g=self.rng.normal(0, 0.05),
                ay_g=self.rng.normal(0, 0.05),
                az_g=1.0 + self.rng.normal(0, 0.04),
            )
