"""Generic sensor-provider interfaces (V5, sections 2-6 + 31).

A `SensorProvider` is the single contract the rest of the application uses,
regardless of the physical device behind it. Hardware can be swapped freely:

    MAX30102 ring   ->  RingPPGProvider  (PPG + IMU + temperature)
    AD8232 chest    ->  ChestECGProvider (ECG, periodic high-quality sessions)
    ...insole       ->  InsoleProvider   (pressure + IMU)
    GSR electrodes  ->  GSRProvider
    BP cuff         ->  BloodPressureProvider   (manual, timestamped)
    glucose meter   ->  GlucoseProvider         (manual, timestamped)

Providers declare the channels they emit (name -> (unit, description)) and
their nominal sampling rate, battery level and connection state. `read()`
yields channel dicts: {"ts": seconds, "seq": int, "battery_pct": ..., channels...}.

This is an interface + simulator layer. It does NOT claim to support any
specific commercial device - that would require real hardware drivers.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, Iterator, List

# channel name -> (unit, description)
ChannelSchema = Dict[str, tuple[str, str]]


class SensorProvider(ABC):
    """Base contract for every wearable / manual sensor source."""

    id: str = "provider"
    name: str = "Sensor"
    signal_types: List[str] = []
    fs_hz: float = 1.0                     # nominal sampling rate (0 = on-demand)
    channels: ChannelSchema = {}

    def __init__(self, battery_pct: float = 100.0):
        self.battery_pct = float(battery_pct)
        self.connected = False

    @abstractmethod
    def connect(self) -> bool:
        """Open the link; returns True on success."""

    def disconnect(self) -> None:
        self.connected = False

    @abstractmethod
    def read(self) -> Iterator[dict]:
        """Yield channel dicts: {"ts": float, "seq": int, ...channels}."""

    def status(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "signal_types": self.signal_types,
            "fs_hz": self.fs_hz,
            "battery_pct": self.battery_pct,
            "connected": self.connected,
            "channels": {k: v[0] for k, v in self.channels.items()},
        }


# ------------------------------------------------------------------ ring
class RingPPGProvider(SensorProvider):
    """Compact continuous wearable: PPG (IR/red), skin temperature, IMU."""

    id = "ring_ppg"
    name = "Smart ring (PPG + temperature + IMU)"
    signal_types = ["ppg", "temperature", "imu"]
    fs_hz = 50.0
    channels = {
        "ppg_ir": ("raw", "IR PPG channel"),
        "ppg_red": ("raw", "Red PPG channel"),
        "skin_temp_c": ("°C", "wrist/ring skin temperature"),
        "ax_g": ("g", "accelerometer x"),
        "ay_g": ("g", "accelerometer y"),
        "az_g": ("g", "accelerometer z"),
    }

    def connect(self) -> bool:
        self.connected = True
        return True

    def read(self) -> Iterator[dict]:
        yield {}


# ------------------------------------------------------------- chest ECG
class ChestECGProvider(SensorProvider):
    """Periodic high-quality ECG module (AD8232-style single lead).

    ECG is a periodic checkpoint measurement, not a 24/7 stream: the app uses
    it to validate PPG-derived HR/HRV and to build an ECG history.
    """

    id = "chest_ecg"
    name = "Chest ECG module"
    signal_types = ["ecg"]
    fs_hz = 256.0
    channels = {"ecg_raw": ("raw", "single-lead ECG amplitude")}

    def connect(self) -> bool:
        self.connected = True
        return True

    def read(self) -> Iterator[dict]:
        yield {}


# ------------------------------------------------------------- temperature
class SkinTempProvider(SensorProvider):
    id = "skin_temp"
    name = "Skin temperature sensor"
    signal_types = ["temperature"]
    fs_hz = 1.0
    channels = {"skin_temp_c": ("°C", "skin temperature")}

    def connect(self) -> bool:
        self.connected = True
        return True

    def read(self) -> Iterator[dict]:
        yield {}


# -------------------------------------------------------------------- GSR
class GSRProvider(SensorProvider):
    id = "gsr"
    name = "Galvanic skin response"
    signal_types = ["gsr"]
    fs_hz = 10.0
    channels = {"gsr_raw": ("raw", "EDA conductance")}

    def connect(self) -> bool:
        self.connected = True
        return True

    def read(self) -> Iterator[dict]:
        yield {}


# -------------------------------------------------------------------- IMU
class IMUProvider(SensorProvider):
    id = "imu"
    name = "Inertial measurement unit"
    signal_types = ["imu"]
    fs_hz = 50.0
    channels = {
        "ax_g": ("g", "accel x"), "ay_g": ("g", "accel y"), "az_g": ("g", "accel z"),
        "gx_dps": ("°/s", "gyro x"), "gy_dps": ("°/s", "gyro y"), "gz_dps": ("°/s", "gyro z"),
    }

    def connect(self) -> bool:
        self.connected = True
        return True

    def read(self) -> Iterator[dict]:
        yield {}


# ------------------------------------------------------------------ insole
class InsoleProvider(SensorProvider):
    id = "insole"
    name = "Smart insole (pressure + IMU)"
    signal_types = ["pressure", "imu"]
    fs_hz = 50.0
    channels = {
        "zones": ("raw × 8", "heel / midfoot / forefoot / toe, left+right"),
        "ax_g": ("g", "accel x"), "ay_g": ("g", "accel y"), "az_g": ("g", "accel z"),
    }

    def connect(self) -> bool:
        self.connected = True
        return True

    def read(self) -> Iterator[dict]:
        yield {}


# ------------------------------------------------------- manual (BP, glucose)
class BloodPressureProvider(SensorProvider):
    """Manual / cuff BP entry: on-demand, timestamped. Not continuous."""

    id = "bp"
    name = "Blood pressure (manual entry)"
    signal_types = ["bp"]
    fs_hz = 0.0
    channels = {"systolic": ("mmHg", "systolic"), "diastolic": ("mmHg", "diastolic"),
                "pulse": ("bpm", "optional pulse")}

    def connect(self) -> bool:
        self.connected = True
        return True

    def read(self) -> Iterator[dict]:
        yield {}


class GlucoseProvider(SensorProvider):
    """Manual glucose entry: on-demand, timestamped. Not continuous."""

    id = "glucose"
    name = "Blood glucose (manual entry)"
    signal_types = ["glucose"]
    fs_hz = 0.0
    channels = {"glucose": ("mg/dL", "glucose"), "context": ("str", "fasting / post-meal / other")}

    def connect(self) -> bool:
        self.connected = True
        return True

    def read(self) -> Iterator[dict]:
        yield {}
