"""Global configuration for CHRONO-PCOS.

The constants below are intentionally conservative because this is an
educational risk-estimation system, not a medical device.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# V8.2 branding. "Prototype" and "not clinically validated" are deliberate:
# this is a research/education platform, not a medical device.
# V8.2 is a UI/UX refinement of V8.1: same engines, clearer presentation
# ("simple outside, sophisticated inside").
APP_VERSION = "8.2.0"
APP_VERSION_LABEL = "V8.2 — Longitudinal Multimodal Phenotyping + Periodic Clinical Imaging Research Prototype (not clinically validated)"

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
MODEL_DIR = PROJECT_ROOT / "models"
LOG_DIR = DATA_DIR / "raw"

SERIAL_BAUD = 115200
SERIAL_TIMEOUT_S = 0.2

# Serial/network reconnect policy.
RECONNECT_RETRY_S = 3.0
STALE_DATA_TIMEOUT_S = 6.0

# ESP8266 Wi-Fi bridge default port.
WIFI_BRIDGE_DEFAULT_PORT = 7777

# Baseline calibration defaults.
BASELINE_CAPTURE_S = 300.0
BASELINE_MIN_SAMPLES = 60

# Feature-logging cadence in the offline database.
FEATURE_LOG_INTERVAL_S = 10.0

# Arduino sampling target. Actual packet rate may vary.
PPG_FS_HZ = 50.0
IMU_FS_HZ = 50.0
GSR_FS_HZ = 10.0
TEMP_FS_HZ = 1.0

# PPG/HR limits.
MIN_HR_BPM = 35.0
MAX_HR_BPM = 210.0
MIN_IBI_S = 60.0 / MAX_HR_BPM
MAX_IBI_S = 60.0 / MIN_HR_BPM

# Signal-quality thresholds.
MIN_IR_FINGER_PRESENT = 5000
MAX_ADC_18BIT = 262143
PPG_SATURATION_MARGIN = 4000

# Risk category thresholds.
RISK_LOW = 25.0
RISK_MEDIUM = 50.0
RISK_HIGH = 75.0

# Physiology normalization defaults. These are used only when a personal
# baseline is not yet available.
DEFAULT_RESTING_HR = 72.0
DEFAULT_RMSSD_MS = 42.0
DEFAULT_SKIN_TEMP_C = 32.5
DEFAULT_GSR_RAW = 450.0
DEFAULT_ACTIVITY = 0.10

# Dashboard update timing.
UI_PLOT_HISTORY_S = 180
RISK_UPDATE_INTERVAL_S = 2.0
FEATURE_UPDATE_INTERVAL_S = 1.0


@dataclass
class UserProfile:
    """Non-sensitive user inputs used by the educational risk engine.

    Avoid storing names or identifiers. BMI and cycle information are optional.
    The dashboard can run without these values, but confidence is lower.
    """

    age_years: float = 17.0
    bmi: float | None = None
    height_cm: float | None = None
    weight_kg: float | None = None
    waist_cm: float | None = None
    systolic_bp: float | None = None
    diastolic_bp: float | None = None
    cycle_day: int | None = None
    usual_cycle_length_days: int | None = None
    days_since_last_period: int | None = None
    years_post_menarche: float | None = None
    # V6: self-reported cycle irregularity (True/False/None=unknown). This is a
    # clinical-style input, never derived from sensors.
    cycle_irregular: bool | None = None
    glucose_mg_dl: float | None = None
    glucose_context: str = "unknown"  # fasting, 2hr, random, unknown
    time_since_meal_min: float | None = None


DEFAULT_PROFILE = UserProfile()
