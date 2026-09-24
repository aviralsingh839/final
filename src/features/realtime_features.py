"""Streaming feature extractor that fuses all signal processors."""
from __future__ import annotations

import time
from collections import deque
from typing import Deque, Optional

import numpy as np

from src.config import BASELINE_CAPTURE_S, BASELINE_MIN_SAMPLES, DEFAULT_PROFILE, UserProfile
from src.data_models import FeatureVector, SensorSample
from src.models.anomaly_detector import AnomalyDetector
from src.models.metabolic_model import MetabolicEstimator
from src.models.personalization import BaselineManager
from src.models.sleep_model import SleepEstimator
from src.models.stress_model import StressEstimator
from src.models.voice_vasc_model import VoiceVascEstimator
from src.utils.math_utils import clamp
from src.signal_processing.ecg import ECGProcessor
from src.signal_processing.gsr import GSRProcessor
from src.signal_processing.imu import IMUProcessor
from src.signal_processing.ppg import PPGProcessor
from src.signal_processing.temperature import TemperatureProcessor
from src.utils.quality import completeness_score


class RealtimeFeatureExtractor:
    def __init__(self, profile: UserProfile | None = None):
        self.profile = profile or DEFAULT_PROFILE
        self.ppg = PPGProcessor()
        self.imu = IMUProcessor()
        self.gsr = GSRProcessor()
        self.temp = TemperatureProcessor(history_s=24 * 3600)
        self.ecg = ECGProcessor()
        self.voice_vasc = VoiceVascEstimator()
        self.stress_model = StressEstimator()
        self.sleep_model = SleepEstimator()
        self.metabolic_model = MetabolicEstimator()
        self.baseline = BaselineManager()
        self.anomaly = AnomalyDetector(self.baseline)
        self.last_feature = FeatureVector(timestamp_s=time.time())
        self.last_lux: float | None = None
        self.last_sample: SensorSample | None = None
        self.feature_history: Deque[FeatureVector] = deque(maxlen=24 * 3600)
        self.start_time = time.time()
        self.sleep_onset_h: float | None = None
        self.wake_h: float | None = None
        self.auto_captured: bool = False
        self.last_capture_error: str | None = None
        self.last_anomalies: list = []
        # Real circadian metrics from CircadianAnalyzer (set by the 60 s timer).
        # None means "not yet computed" -> the UI shows a neutral 50, never a fake value.
        self.circadian_metrics = None

    def set_profile(self, profile: UserProfile) -> None:
        self.profile = profile

    def set_sleep_window(self, onset_h: float | None, wake_h: float | None) -> None:
        self.sleep_onset_h = onset_h
        self.wake_h = wake_h

    def capture_baseline(self, window_s: float = BASELINE_CAPTURE_S) -> bool:
        """Calibrate personalized normal ranges from recent history. Returns True on success."""
        now = time.time()
        rows = [f for f in self.feature_history if now - f.timestamp_s <= window_s]
        try:
            bl = self.baseline.capture_from_features(rows, min_samples=BASELINE_MIN_SAMPLES)
            self.auto_captured = False
            self.last_capture_error = None
            return True
        except ValueError as exc:
            self.last_capture_error = str(exc)
            return False

    def add_sample(self, sample: SensorSample) -> None:
        self.last_sample = sample
        self.ppg.add_sample(sample.timestamp_s, sample.ir, sample.red)
        self.imu.add_sample(sample.timestamp_s, sample.ax_g, sample.ay_g, sample.az_g, sample.gx_dps, sample.gy_dps, sample.gz_dps)
        self.gsr.add_sample(sample.timestamp_s, sample.gsr_raw)
        self.temp.add_sample(sample.timestamp_s, sample.temp_c)
        self.ecg.add_sample(sample.timestamp_s, sample.ecg_raw)
        self.last_lux = sample.lux if sample.lux is not None and sample.lux >= 0 else self.last_lux

    def compute(self) -> FeatureVector:
        now = time.time()
        imu_f = self.imu.features()
        ppg_f = self.ppg.features(motion_index=imu_f["motion_index"])
        gsr_f = self.gsr.features()
        temp_f = self.temp.features()
        ecg_f = self.ecg.features()

        # Use ECG beat timing for HR/HRV when quality is good; otherwise PPG.
        hr_best = ecg_f.get("ecg_hr_bpm") if (ecg_f.get("ecg_quality") or 0) > 0.55 else ppg_f.get("hr_bpm")
        rmssd_best = ecg_f.get("ecg_rmssd_ms") if (ecg_f.get("ecg_quality") or 0) > 0.55 else ppg_f.get("rmssd_ms")

        fv = FeatureVector(
            timestamp_s=now,
            hr_bpm=hr_best,
            spo2_pct=ppg_f.get("spo2_pct"),
            rmssd_ms=rmssd_best,
            sdnn_ms=ppg_f.get("sdnn_ms"),
            pnn50_pct=ppg_f.get("pnn50_pct"),
            ppg_pulse_amplitude=ppg_f.get("ppg_pulse_amplitude"),
            lux=self.last_lux,
            fsr_raw=self.last_sample.fsr_raw if self.last_sample else None,
            ecg_raw=self.last_sample.ecg_raw if self.last_sample else None,
            ecg_hr_bpm=ecg_f.get("ecg_hr_bpm"),
            ecg_rmssd_ms=ecg_f.get("ecg_rmssd_ms"),
            ecg_quality=ecg_f.get("ecg_quality") or 0.0,
            mic_rms=self.last_sample.mic_rms if self.last_sample else None,
            mic_pitch_hz=self.last_sample.mic_pitch_hz if self.last_sample else None,
            room_temp_c=self.last_sample.room_temp_c if self.last_sample else None,
            humidity_pct=self.last_sample.humidity_pct if self.last_sample else None,
            pressure_hpa=self.last_sample.pressure_hpa if self.last_sample else None,
            motion_index=imu_f["motion_index"],
            activity_level=imu_f["activity_level"],
            low_activity_risk=imu_f["low_activity_risk"],
            skin_temp_c=temp_f.get("skin_temp_c"),
            temp_slope_c_per_min=temp_f.get("temp_slope_c_per_min") or 0.0,
            gsr_tonic=gsr_f.get("gsr_tonic"),
            gsr_phasic_per_min=gsr_f.get("gsr_phasic_per_min") or 0.0,
        )
        fv.voice_vasc_score, _voice_note = self.voice_vasc.score(fv.mic_pitch_hz, fv.mic_rms)

        # Signal quality = mean over PRESENT sensors only. Optional channels
        # (ECG, GSR) must NEVER drag the score down when absent, and there is no
        # always-true term (motion is handled inside ppg_quality).
        quality_parts = [ppg_f.get("ppg_quality") or 0.0]
        if fv.ecg_quality > 0:
            quality_parts.append(float(fv.ecg_quality))
        if fv.skin_temp_c is not None:
            quality_parts.append(1.0)
        if fv.gsr_tonic is not None:
            quality_parts.append(1.0)
        fv.signal_quality = float(np.mean(quality_parts)) if quality_parts else 0.0
        fv.baseline_completeness = min(1.0, (now - self.start_time) / (5 * 60.0))

        # Sleep estimate.
        import datetime as _dt
        dt = _dt.datetime.fromtimestamp(now)
        hour = dt.hour + dt.minute / 60.0
        sleep_f = self.sleep_model.estimate_epoch(fv, hour_of_day=hour, sleep_onset_h=self.sleep_onset_h, wake_h=self.wake_h)
        fv.sleep_probability = float(sleep_f["sleep_probability"])
        fv.deep_sleep_probability = float(sleep_f["deep_sleep_probability"])
        fv.rem_probability = float(sleep_f["rem_probability"])
        fv.sleep_status = str(sleep_f["sleep_status"])

        # Circadian values come from the real CircadianAnalyzer (set by the
        # main window's 60 s timer). Until then the FeatureVector defaults (50)
        # stand as a neutral placeholder - never a fabricated constant.
        cm = self.circadian_metrics
        if cm is not None:
            fv.circadian_stability_index = float(cm.stability_index)
            fv.circadian_disruption = float(cm.disruption_score)
            if cm.temp_r2 > 0:
                fv.temperature_rhythm_disruption = clamp(100.0 - 100.0 * float(cm.temp_r2), 0.0, 100.0)
            else:
                fv.temperature_rhythm_disruption = 50.0

        # Stress.
        stress_f = self.stress_model.estimate(fv, gsr_z=gsr_f.get("gsr_z") or 0.0)
        fv.acute_stress = stress_f["acute_stress"]
        fv.chronic_stress = stress_f["chronic_stress"]
        fv.autonomic_imbalance = stress_f["autonomic_imbalance"]
        fv.stress_index = stress_f["stress_index"]

        # Metabolic.
        metabolic = self.metabolic_model.estimate(fv, self.profile)
        fv.glucose_risk = metabolic["glucose_risk"]
        fv.bp_risk = metabolic.get("bp_risk", 0.0)
        fv.systolic_bp = self.profile.systolic_bp
        fv.diastolic_bp = self.profile.diastolic_bp
        fv.insulin_resistance_probability = metabolic["insulin_resistance_probability"]
        fv.metabolic_syndrome_proxy = metabolic["metabolic_syndrome_proxy"]
        fv.inflammation_score = metabolic["inflammation_score"]

        # Feature completeness adjustment.
        c = completeness_score(fv.hr_bpm, fv.rmssd_ms, fv.skin_temp_c, fv.gsr_tonic, fv.spo2_pct)
        fv.signal_quality = 0.7 * fv.signal_quality + 0.3 * c

        # ---- Personal baseline: z-scores, availability, auto-calibration ----
        if self.baseline.has_baseline:
            fv.baseline_available = True
            fv.baseline_age_s = now - self.baseline.baseline.captured_at
            fv.baseline_completeness = 1.0
            fv.hr_zscore = self.baseline.zscore("hr_bpm", fv.hr_bpm)
            fv.rmssd_zscore = self.baseline.zscore("rmssd_ms", fv.rmssd_ms)
            fv.skin_temp_zscore = self.baseline.zscore("skin_temp_c", fv.skin_temp_c)
            fv.gsr_zscore = self.baseline.zscore("gsr_tonic", fv.gsr_tonic)
        else:
            elapsed = now - self.start_time
            if not self.auto_captured and elapsed >= BASELINE_CAPTURE_S:
                # Automatic baseline calibration after a calm 5-minute window.
                recent = [f for f in self.feature_history if now - f.timestamp_s <= BASELINE_CAPTURE_S]
                if recent and float(np.mean([f.signal_quality for f in recent])) >= 0.5:
                    self.auto_captured = self.capture_baseline()
                    fv.baseline_available = self.baseline.has_baseline
                    fv.baseline_completeness = 1.0 if self.baseline.has_baseline else fv.baseline_completeness

        # ---- FSR finger-pressure correction (feature 36) ----
        fsr = self.last_sample.fsr_raw if self.last_sample is not None else None
        if fsr is not None and fsr > 0:
            fv.fsr_pressure_index = clamp(fsr / 420.0, 0.4, 2.5)
            if fv.ppg_pulse_amplitude is not None:
                fv.ppg_pulse_amplitude_corrected = fv.ppg_pulse_amplitude / fv.fsr_pressure_index
            # Extreme pressure degrades PPG quality.
            if fv.fsr_pressure_index > 1.8 or fv.fsr_pressure_index < 0.5:
                fv.signal_quality = clamp(fv.signal_quality - 0.15, 0.0, 1.0)

        # ---- Real-time anomaly detection (features 10/28) ----
        anomalies, score = self.anomaly.evaluate(fv, now=now)
        fv.anomaly_score = score
        fv.anomalies = [a.description for a in anomalies]
        self.last_anomalies = anomalies

        self.last_feature = fv
        self.feature_history.append(fv)
        return fv

    def ppg_waveform(self, last_s: float = 20.0):
        return self.ppg.waveform(last_s=last_s)

    def history_arrays(self, attr: str, last_s: float = 180.0):
        if not self.feature_history:
            return np.array([]), np.array([])
        t = np.array([f.timestamp_s for f in self.feature_history])
        y = np.array([getattr(f, attr, np.nan) if getattr(f, attr, None) is not None else np.nan for f in self.feature_history], dtype=float)
        mask = t >= (t[-1] - last_s)
        return t[mask] - t[-1], y[mask]
