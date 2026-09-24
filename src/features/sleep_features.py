"""Overnight sleep feature aggregation from 30-second epochs."""
from __future__ import annotations

from dataclasses import asdict
from typing import Iterable

import numpy as np
import pandas as pd

from src.data_models import FeatureVector, SleepMetrics


class SleepAnalyzer:
    """Aggregate feature history into approximate sleep-quality metrics."""

    def epochs_from_features(self, features: Iterable[FeatureVector], epoch_s: int = 30) -> pd.DataFrame:
        rows = [f.as_dict() for f in features]
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
        df["datetime"] = pd.to_datetime(df["timestamp_s"], unit="s")
        df = df.sort_values("timestamp_s")
        # Keep one sample per epoch by averaging numerical values.
        df["epoch"] = (df["timestamp_s"] // epoch_s).astype(int)
        numeric = df.select_dtypes(include=[np.number]).columns
        out = df.groupby("epoch")[numeric].mean().reset_index(drop=True)
        out["timestamp_s"] = df.groupby("epoch")["timestamp_s"].mean().values
        out["sleep"] = out["sleep_probability"] > 60.0
        out["restless"] = out["motion_index"] > np.nanpercentile(out["motion_index"].fillna(0), 80)
        return out

    def metrics(self, epoch_df: pd.DataFrame, epoch_s: int = 30) -> SleepMetrics:
        if epoch_df.empty or "sleep" not in epoch_df:
            return SleepMetrics()
        sleep = epoch_df["sleep"].astype(bool).values
        if sleep.sum() == 0:
            return SleepMetrics(time_in_bed_min=len(epoch_df) * epoch_s / 60.0)

        # Sleep onset: first 10-min segment with >=80% sleep epochs.
        win = max(1, int(10 * 60 / epoch_s))
        onset_idx = 0
        for i in range(0, max(1, len(sleep) - win)):
            if sleep[i : i + win].mean() >= 0.8:
                onset_idx = i
                break
        offset_idx = len(sleep) - 1
        for i in range(len(sleep) - win, 0, -1):
            if sleep[i : i + win].mean() >= 0.8:
                offset_idx = i + win
                break
        night = sleep[onset_idx:offset_idx]
        if night.size == 0:
            night = sleep
        tst_min = float(night.sum() * epoch_s / 60.0)
        tib_min = float(night.size * epoch_s / 60.0)
        eff = 100.0 * tst_min / max(tib_min, 1e-6)

        wake_transitions = int(np.sum((night[:-1] == True) & (night[1:] == False))) if night.size > 1 else 0
        restlessness = 0.0
        if "restless" in epoch_df:
            rest = epoch_df["restless"].astype(bool).values[onset_idx:offset_idx]
            restlessness = float(rest.mean() * 100.0) if rest.size else 0.0
        deep = float(np.nanmean(epoch_df.get("deep_sleep_probability", pd.Series([0])).values[onset_idx:offset_idx]))
        rem = float(np.nanmean(epoch_df.get("rem_probability", pd.Series([0])).values[onset_idx:offset_idx]))
        return SleepMetrics(
            sleep_duration_min=tst_min,
            time_in_bed_min=tib_min,
            sleep_efficiency_pct=float(eff),
            wake_frequency=wake_transitions,
            restlessness_pct=restlessness,
            deep_sleep_estimate_pct=deep,
            rem_probability_pct=rem,
            sleep_consistency_pct=0.0,
            circadian_disruption_pct=max(0.0, 100.0 - eff),
        )
