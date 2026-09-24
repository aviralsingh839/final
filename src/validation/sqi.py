"""Signal quality indices (SQI) and the confidence-based decision layer.

Feature: compute quality scores per sensor (PPG, ECG, GSR, IMU, temperature),
detect motion artifacts / clipping / saturation / missing samples / noise, and
calculate an overall SQI. The decision layer withholds predictions when quality
is insufficient instead of showing a number.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from src.data_models import FeatureVector, RiskResult, SensorSample
from src.utils.math_utils import clamp

MAX_ADC_18BIT = 262143
SATURATION_MARGIN = 4000

# Decision-layer defaults (educational tool, conservative but not medical).
MIN_SQI = 0.40          # overall SQI below this -> withhold
MIN_CONFIDENCE = 25.0   # risk-engine confidence below this -> withhold
MAX_CI_WIDTH = 65.0     # 90% CI wider than this -> withhold
REQUIRED_HRV = True     # no HRV -> withhold (PPG-derived risk depends on it)


@dataclass
class SensorSQI:
    name: str
    score: float              # 0..1, 1 = excellent
    present: bool = True
    issues: List[str] = field(default_factory=list)

    @property
    def grade(self) -> str:
        if not self.present:
            return "missing"
        if self.score >= 0.7:
            return "good"
        if self.score >= 0.4:
            return "fair"
        return "poor"


def per_sensor_sqi(sample: Optional[SensorSample], fv: Optional[FeatureVector]) -> List[SensorSQI]:
    """Per-sensor quality from the live sample + feature vector.

    Checks presence, saturation/clipping, finger-pressure artifacts, motion and
    plausible physiological ranges. Missing sensors score 0 with 'missing'.
    """
    out: List[SensorSQI] = []

    # PPG (drives HR / HRV / SpO2).
    ppg_issues: List[str] = []
    ppg_present = sample is not None and sample.ir is not None and sample.ir > 0
    if not ppg_present:
        ppg_issues.append("missing")
    if ppg_present and sample.ir >= MAX_ADC_18BIT - SATURATION_MARGIN:
        ppg_issues.append("IR saturation / clipping")
    if sample is not None and sample.fsr_raw is not None and sample.fsr_raw >= 0 and sample.fsr_raw > 800:
        ppg_issues.append("high finger pressure (FSR)")
    ppg_score = fv.signal_quality if fv is not None and fv.signal_quality is not None else (1.0 if ppg_present else 0.0)
    if ppg_issues and "missing" not in ppg_issues:
        ppg_score = min(ppg_score, 0.45)
    out.append(SensorSQI("PPG", clamp(ppg_score, 0.0, 1.0), ppg_present, ppg_issues))

    # ECG (optional channel).
    ecg_present = sample is not None and sample.ecg_raw is not None and sample.ecg_raw >= 0
    ecg_score = fv.ecg_quality if fv is not None else 0.0
    ecg_issues = [] if ecg_present else ["missing"]
    if sample is not None and sample.ecg_raw is not None and sample.ecg_raw >= MAX_ADC_18BIT - SATURATION_MARGIN:
        ecg_issues.append("clipping")
    out.append(SensorSQI("ECG", clamp(ecg_score, 0.0, 1.0) if ecg_present else 0.0, ecg_present, ecg_issues))

    # GSR.
    gsr_present = fv is not None and fv.gsr_tonic is not None and fv.gsr_tonic > 0
    gsr_issues = [] if gsr_present else ["missing"]
    out.append(SensorSQI("GSR", 1.0 if gsr_present else 0.0, gsr_present, gsr_issues))

    # IMU / motion.
    imu_present = fv is not None and fv.motion_index is not None and fv.motion_index == fv.motion_index
    imu_issues = [] if imu_present else ["missing"]
    if sample is not None and sample.ax_g is not None and abs(sample.ax_g) > 4.0:
        imu_issues.append("strong motion / artifact risk")
    out.append(SensorSQI("IMU", 1.0 if imu_present else 0.0, imu_present, imu_issues))

    # Skin temperature.
    temp_issues: List[str] = []
    temp_present = fv is not None and fv.skin_temp_c is not None and fv.skin_temp_c == fv.skin_temp_c
    temp_score = 1.0
    if temp_present:
        if not (25.0 <= fv.skin_temp_c <= 40.0):
            temp_issues.append("implausible range")
            temp_score = 0.3
    else:
        temp_issues.append("missing")
    out.append(SensorSQI("Temperature", temp_score if temp_present else 0.0, temp_present, temp_issues))

    return out


def overall_sqi(sensors: List[SensorSQI]) -> float:
    """Overall SQI: mean of present sensors (missing sensors do not drag it down)."""
    present = [s for s in sensors if s.present]
    if not present:
        return 0.0
    return float(sum(s.score for s in present) / len(present))


@dataclass
class Decision:
    """Outcome of the confidence-based decision layer."""
    ok: bool
    reasons: List[str] = field(default_factory=list)

    @property
    def message(self) -> str:
        return "Insufficient data for reliable estimation." if not self.ok else "OK"


def should_withhold(fv: Optional[FeatureVector], result: Optional[RiskResult] = None,
                    min_sqi: float = MIN_SQI, min_confidence: float = MIN_CONFIDENCE,
                    max_ci_width: float = MAX_CI_WIDTH, require_hrv: bool = REQUIRED_HRV) -> Decision:
    """Decide whether a risk number may be shown.

    Withholds (returns ok=False) when: signal quality too low, required sensors
    missing, data duration insufficient (no HRV yet), or model uncertainty too
    high (wide CI / low confidence).
    """
    reasons: List[str] = []
    if fv is None:
        return Decision(False, ["no live feature vector"])
    if fv.signal_quality is None or fv.signal_quality < min_sqi:
        reasons.append(f"signal quality too low ({fv.signal_quality:.2f})")
    if fv.hr_bpm is None and fv.rmssd_ms is None:
        reasons.append("no PPG-derived heart data yet")
    if require_hrv and fv.rmssd_ms is None:
        reasons.append("HRV unavailable (not enough clean beats)")
    if result is not None:
        if result.confidence is not None and result.confidence < min_confidence:
            reasons.append(f"model confidence too low ({result.confidence:.0f}%)")
        if result.ci_low is not None and result.ci_high is not None and (result.ci_high - result.ci_low) > max_ci_width:
            reasons.append(f"confidence interval too wide ({result.ci_low:.0f}–{result.ci_high:.0f})")
    return Decision(not bool(reasons), reasons)
