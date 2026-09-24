"""IMU motion/activity feature extraction."""
from __future__ import annotations

from collections import deque
from typing import Deque

import numpy as np

from src.signal_processing.filters import rolling_rms
from src.utils.math_utils import clamp


class IMUProcessor:
    def __init__(self, history_s: float = 180.0, fs_hz: float = 50.0):
        self.maxlen = int(history_s * fs_hz)
        self.times: Deque[float] = deque(maxlen=self.maxlen)
        self.vm: Deque[float] = deque(maxlen=self.maxlen)
        self.gyro_vm: Deque[float] = deque(maxlen=self.maxlen)

    def add_sample(self, timestamp_s: float, ax_g: float, ay_g: float, az_g: float, gx: float, gy: float, gz: float) -> None:
        vm = float(np.sqrt(ax_g * ax_g + ay_g * ay_g + az_g * az_g))
        gyro_vm = float(np.sqrt(gx * gx + gy * gy + gz * gz))
        self.times.append(float(timestamp_s))
        self.vm.append(vm)
        self.gyro_vm.append(gyro_vm)

    def features(self, window_s: float = 10.0) -> dict[str, float]:
        if not self.times:
            return {"motion_index": 0.0, "activity_level": 0.0, "low_activity_risk": 0.0}
        t = np.asarray(self.times)
        vm = np.asarray(self.vm)
        gyro = np.asarray(self.gyro_vm)
        mask = t >= (t[-1] - window_s)
        vmw = vm[mask]
        gyw = gyro[mask]
        if vmw.size < 3:
            return {"motion_index": 0.0, "activity_level": 0.0, "low_activity_risk": 50.0}
        acc_dyn = vmw - 1.0
        jerk = np.diff(vmw, prepend=vmw[0])
        motion_index = rolling_rms(acc_dyn) + 0.3 * rolling_rms(jerk) + 0.002 * rolling_rms(gyw)
        # Activity level 0-100. 0.02g quiet, 0.4g active movement.
        activity_level = clamp((motion_index - 0.02) / 0.40 * 100.0, 0.0, 100.0)
        low_activity_risk = clamp(100.0 - activity_level, 0.0, 100.0)
        return {
            "motion_index": float(motion_index),
            "activity_level": float(activity_level),
            "low_activity_risk": float(low_activity_risk),
        }
