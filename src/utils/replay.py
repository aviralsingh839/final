"""Physiological signal replay (feature 61 / 8).

Plays back FeatureVectors stored in the local database on a timer so recorded
data can be re-animated on the live dashboard - useful for exhibitions and for
checking what a past session looked like.
"""
from __future__ import annotations

from typing import List, Optional

import pandas as pd
from PySide6.QtCore import QObject, QTimer, Signal

from src.data_models import FeatureVector


class FeatureReplay(QObject):
    step = Signal(object)  # FeatureVector
    finished = Signal()

    def __init__(self, features: List[FeatureVector], interval_ms: int = 250, parent=None):
        super().__init__(parent)
        self.features = features
        self.i = 0
        self.interval_ms = interval_ms
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)

    def start(self) -> None:
        self.i = 0
        self.timer.start(self.interval_ms)

    def stop(self) -> None:
        self.timer.stop()

    def _tick(self) -> None:
        if self.i >= len(self.features):
            self.timer.stop()
            self.finished.emit()
            return
        self.step.emit(self.features[self.i])
        self.i += 1


def features_from_frame(df: pd.DataFrame) -> List[FeatureVector]:
    """Convert a features table row (with optional extra_json) into FeatureVectors."""
    out: List[FeatureVector] = []
    if df.empty:
        return out
    import json

    for _, row in df.iterrows():
        fv = FeatureVector(
            timestamp_s=float(row.get("ts", 0.0)),
            hr_bpm=_opt(row.get("hr")),
            rmssd_ms=_opt(row.get("rmssd")),
            spo2_pct=_opt(row.get("spo2")),
            skin_temp_c=_opt(row.get("skin_temp")),
            gsr_tonic=_opt(row.get("gsr")),
            motion_index=_opt(row.get("motion")),
            activity_level=_opt(row.get("activity")),
            stress_index=_opt(row.get("stress")),
            sleep_probability=_opt(row.get("sleep_prob")),
            circadian_stability_index=_opt(row.get("circadian")),
            signal_quality=_opt(row.get("signal_quality")) or 0.0,
        )
        extra = row.get("extra_json")
        if isinstance(extra, str) and extra:
            try:
                d = json.loads(extra)
                fv.anomaly_score = float(d.get("anomaly_score", 0.0))
                fv.insulin_resistance_probability = float(d.get("insulin_resistance_probability", 0.0))
                fv.circadian_disruption = float(d.get("circadian_disruption", 50.0))
            except Exception:
                pass
        out.append(fv)
    return out


def _opt(v) -> Optional[float]:
    try:
        f = float(v)
        return f if f == f else None  # NaN -> None
    except (TypeError, ValueError):
        return None
