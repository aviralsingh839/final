"""Educational SpO2 estimation from red/IR PPG.

This is NOT a medical-grade pulse oximeter algorithm. Accurate SpO2 requires
proper optics, calibration, motion rejection, and validation.
"""
from __future__ import annotations

import numpy as np

from src.utils.math_utils import clamp


def estimate_spo2(red_values, ir_values) -> tuple[float | None, float]:
    red = np.asarray(red_values, dtype=float)
    ir = np.asarray(ir_values, dtype=float)
    mask = np.isfinite(red) & np.isfinite(ir)
    red = red[mask]
    ir = ir[mask]
    if red.size < 25 or ir.size < 25:
        return None, 0.0

    red_dc = float(np.median(red))
    ir_dc = float(np.median(ir))
    red_ac = float(np.percentile(red, 95) - np.percentile(red, 5)) / 2.0
    ir_ac = float(np.percentile(ir, 95) - np.percentile(ir, 5)) / 2.0
    if min(red_dc, ir_dc, red_ac, ir_ac) <= 0:
        return None, 0.0

    r = (red_ac / red_dc) / (ir_ac / ir_dc)
    # Common educational approximation; calibrate against a real oximeter if used.
    spo2 = 110.0 - 25.0 * r
    spo2 = clamp(spo2, 70.0, 100.0)

    quality = clamp(1.0 - abs(r - 0.7) / 1.2, 0.0, 1.0)
    return spo2, quality
