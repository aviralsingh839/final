"""V5 wearable ecosystem: modular, swappable hardware providers.

The rest of the application talks to `SensorProvider` interfaces, never to a
specific commercial device, so a MAX30102 ring can be replaced by another PPG
sensor without rewriting the pipeline:

    Device -> Transport -> Parser/Validator -> Signal Processor

Providers are honest about what they produce: every `read()` yields a plain
dict of named channels with documented units. `simulators.py` provides the
hardware-free demo/replay implementations.
"""
from src.hardware.providers import (
    BloodPressureProvider,
    ChestECGProvider,
    GlucoseProvider,
    GSRProvider,
    IMUProvider,
    InsoleProvider,
    RingPPGProvider,
    SensorProvider,
    SkinTempProvider,
)
from src.hardware.transport import BlePacketProtocol, LocalBuffer, Transport
from src.hardware.insole import InsoleAnalyzer, InsoleFrame, InsoleReport, SimulatedInsole
from src.hardware.ecg_checkpoint import (
    CheckpointHistory,
    ECGCheckpointResult,
    ECGCheckpointSession,
    SimulatedECGCheckpoint,
)
from src.hardware.simulators import DemoScenario, SimulatedRing

__all__ = [
    "SensorProvider", "RingPPGProvider", "ChestECGProvider", "SkinTempProvider",
    "GSRProvider", "IMUProvider", "InsoleProvider", "BloodPressureProvider",
    "GlucoseProvider",
    "Transport", "LocalBuffer", "BlePacketProtocol",
    "InsoleAnalyzer", "InsoleFrame", "InsoleReport", "SimulatedInsole",
    "ECGCheckpointSession", "ECGCheckpointResult", "CheckpointHistory",
    "SimulatedECGCheckpoint", "SimulatedRing", "DemoScenario",
]
