"""Synthetic live stream for UI demonstration only.

This is NOT a dataset and must not be used to train/validate medical models.
It is simply a hardware-free signal generator so the exhibition dashboard can
be tested before Arduino hardware is connected.
"""
from __future__ import annotations

import math
import time

import numpy as np
from PySide6.QtCore import QObject, QTimer, Signal

from src.data_models import SensorSample


class DemoSensorStream(QObject):
    sample_received = Signal(object)
    state_changed = Signal(str)
    error_received = Signal(str)

    def __init__(self, fs_hz: float = 50.0, parent=None):
        super().__init__(parent)
        self.fs_hz = fs_hz
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.t0 = time.time()
        self.i = 0
        self.rng = np.random.default_rng(7)
        self.mode = "rest"

    def start(self) -> None:
        self.t0 = time.time()
        self.i = 0
        self.timer.start(int(1000 / self.fs_hz))
        self.state_changed.emit("demo-running")

    def stop(self) -> None:
        self.timer.stop()
        self.state_changed.emit("demo-stopped")

    def write_command(self, command: str) -> None:
        # No hardware in demo mode.
        pass

    def _tick(self) -> None:
        now = time.time()
        t = now - self.t0
        # Cycle through rest, stress, movement every 2 minutes.
        phase = int(t // 120) % 3
        if phase == 0:
            hr = 72 + 3 * math.sin(2 * math.pi * t / 35)
            motion = 0.02
            gsr = 420 + 15 * math.sin(2 * math.pi * t / 50)
        elif phase == 1:
            hr = 90 + 5 * math.sin(2 * math.pi * t / 25)
            motion = 0.04
            gsr = 600 + 70 * abs(math.sin(2 * math.pi * t / 11))
        else:
            hr = 105 + 8 * math.sin(2 * math.pi * t / 20)
            motion = 0.35
            gsr = 520 + 40 * math.sin(2 * math.pi * t / 16)

        pulse_freq = hr / 60.0
        ppg = 48000 + 2500 * math.sin(2 * math.pi * pulse_freq * t) + 400 * math.sin(2 * math.pi * 2 * pulse_freq * t)
        ppg += self.rng.normal(0, 120)
        red = 45000 + 2100 * math.sin(2 * math.pi * pulse_freq * t + 0.08) + self.rng.normal(0, 110)
        ax = self.rng.normal(0, motion)
        ay = self.rng.normal(0, motion)
        az = 1.0 + self.rng.normal(0, motion)
        gx = self.rng.normal(0, motion * 25)
        gy = self.rng.normal(0, motion * 25)
        gz = self.rng.normal(0, motion * 25)
        temp = 32.6 + 0.25 * math.sin(2 * math.pi * t / (24 * 3600) - 1.0) + self.rng.normal(0, 0.02)
        sample = SensorSample(
            timestamp_s=now,
            ms=int(t * 1000),
            ir=int(max(0, ppg)),
            red=int(max(0, red)),
            ax_g=float(ax),
            ay_g=float(ay),
            az_g=float(az),
            gx_dps=float(gx),
            gy_dps=float(gy),
            gz_dps=float(gz),
            temp_c=float(temp),
            gsr_raw=int(gsr + self.rng.normal(0, 10)),
            lux=float(150 + 100 * math.sin(2 * math.pi * t / 240)),
            ecg_raw=int(512 + 120 * math.sin(2 * math.pi * pulse_freq * t + 0.2) + self.rng.normal(0, 8)),
            mic_raw=int(512 + self.rng.normal(0, 4)),
            mic_rms=float(20 + self.rng.normal(0, 2)),
            mic_pitch_hz=float(205 + 8 * math.sin(2 * math.pi * t / 40)),
            fsr_raw=int(420 + self.rng.normal(0, 15)),
            temp1_c=float(temp + 0.1 + self.rng.normal(0, 0.02)),
            room_temp_c=25.0,
            humidity_pct=48.0,
            pressure_hpa=1008.0,
            buttons=0,
            status=0,
            source="demo",
        )
        self.i += 1
        self.sample_received.emit(sample)
