"""Train a PPG signal-quality / motion-artifact model from wrist PPG during exercise.

Data: `data/public/wrist_ppg_during_exercise/` - the PhysioNet "Wrist PPG During
Exercise" database (recorded by Corrado et al.; the PhysioNet page has been
withdrawn, the files are kept locally). It contains 19 recordings from 8
subjects (s1-s9, no s7) of chest ECG + wrist PPG + IMU during walking, running
and bike riding, 15 channels at 256 Hz.

Labels: for each 10 s window, the app-style PPG HR estimate (threshold +
refractory peak detection, identical math to src/signal_processing/ppg.py) is
compared against a reference HR from the chest ECG (bandpass + adaptive-threshold
R-peak detection, gated by a smoothness filter). A window is *usable* when
|PPG HR - ECG HR| <= 5 bpm. This is exactly the signal the app needs to decide
whether to keep a window ("collect only relevant data").

The classifier uses only features the live app can compute at runtime (see
src/utils/quality.ppg_window_features), so the saved model can be blended into
the app's `ppg_quality()` score.

Usage:
    python scripts/train_ppg_quality_model.py \
        --data data/public/wrist_ppg_during_exercise \
        --out models/ppg_quality_model.joblib

Notes:
- Validation is subject-level (GroupKFold over subjects), so the model is only
  ever tested on subjects it was not trained on.
- This is an educational/research artifact: the wrist-PPG sensor in the dataset
  differs from the MAX30102 the app uses, so the model is blended at 40% weight
  with the existing heuristic (see src/utils/quality.py).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # project root for src imports

import joblib
import numpy as np
import pandas as pd
from scipy.signal import butter, resample_poly, sosfiltfilt
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.metrics import average_precision_score, classification_report, roc_auc_score
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from src.signal_processing.filters import rolling_rms
from src.utils.quality import PPG_QUALITY_FEATURES, ppg_window_features

FS = 256
WIN_S = 10.0
STEP_S = 5.0
USABLE_TOLERANCE_BPM = 5.0
HR_MIN, HR_MAX = 45.0, 200.0


def read_record(rec_dir: Path, rec: str) -> tuple[np.ndarray, int, int]:
    """Read a WFDB 16-bit record. Returns (sig[n_samples, 15], fs, n_samples)."""
    with open(rec_dir / f"{rec}.hea") as f:
        lines = [l.strip() for l in f if l.strip()]
    n_sig = int(lines[0].split()[1])
    n_samp = int(lines[0].split()[3])
    raw = np.fromfile(rec_dir / f"{rec}.dat", dtype="<i2")
    sig = raw.reshape(-1, n_sig)
    return sig, FS, n_samp


def bandpass(x: np.ndarray, fs: float, lo: float, hi: float, order: int = 4) -> np.ndarray:
    return sosfiltfilt(butter(order, [lo, hi], btype="band", fs=fs, output="sos"), x)


ECG_IBI_CV_MAX = 0.10  # real QRS runs have low IBI CV; noise-triggered peaks do not


def ecg_peak_hr(x: np.ndarray, fs: float, thr_q: float = 97, thr_f: float = 0.5, ref_s: float = 0.24) -> float | None:
    """Median-IBI HR from bandpassed ECG with adaptive thresholding.

    Returns None unless the detected beats are regular (IBI CV <= ECG_IBI_CV_MAX),
    which filters noise-triggered detections on contaminated ECG segments.
    """
    k = int(0.08 * fs)
    mav = np.convolve(np.abs(x), np.ones(k) / k, mode="same")
    thr = np.percentile(mav, thr_q) * thr_f
    peaks: list[int] = []
    ref = int(ref_s * fs)
    for i in range(1, len(mav) - 1):
        if mav[i] > thr and mav[i] >= mav[i - 1] and mav[i] > mav[i + 1]:
            if not peaks or i - peaks[-1] > ref:
                peaks.append(i)
    if len(peaks) < 3:
        return None
    ibi = np.diff(peaks) / fs
    ibi = ibi[(ibi > 60 / HR_MAX) & (ibi < 60 / HR_MIN)]
    if len(ibi) < 2:
        return None
    med = np.median(ibi)
    ibi = ibi[np.abs(ibi - med) < 0.25 * med]
    if len(ibi) < 2:
        return None
    if np.std(ibi) / max(np.mean(ibi), 1e-9) > ECG_IBI_CV_MAX:
        return None
    hr = 60.0 / np.median(ibi)
    return hr if HR_MIN <= hr <= HR_MAX else None


def ecg_reference_hrs(sig: np.ndarray) -> tuple[np.ndarray, list[float]]:
    """Per-window ECG reference HR with regularity + smoothness gates.

    Returns (hrs aligned to window starts, window starts in seconds). Windows
    are dropped when the ECG beat detection is irregular (IBI CV too high - a
    sign of noise-triggered peaks), when HR deviates > 12 bpm from the local
    median (isolated spikes), or when no valid estimate exists.
    """
    ecg = sig[:, 0]
    ecg_f = bandpass(ecg, FS, 2.0, 25.0)
    starts = list(range(0, len(ecg_f) - int(WIN_S * FS), int(STEP_S * FS)))
    hrs: list[float | None] = []
    for s in starts:
        hrs.append(ecg_peak_hr(ecg_f[s:int(s + WIN_S * FS)], FS))
    hrs_arr = np.array([np.nan if h is None else h for h in hrs], dtype=float)
    # Local-median gate: reject isolated spikes (HR cannot jump 12+ bpm in 5 s
    # during steady-state exercise).
    n = len(hrs_arr)
    local_med = np.empty(n)
    for i in range(n):
        lo = max(0, i - 2)
        hi = min(n, i + 3)
        seg = hrs_arr[lo:hi]
        seg = seg[np.isfinite(seg)]
        local_med[i] = np.median(seg) if len(seg) else np.nan
    ok = np.isfinite(hrs_arr) & np.isfinite(local_med) & (np.abs(hrs_arr - local_med) <= 12.0)
    return hrs_arr[ok], [starts[i] / FS for i in range(n) if ok[i]]


def motion_index(sig: np.ndarray, start_s: float) -> float:
    """Replicate src.signal_processing.imu.IMUProcessor.features() motion index
    at the app's 50 Hz sampling (resampled from 256 Hz so the jerk term matches)."""
    ax, ay, az = sig[:, 5].astype(np.float64), sig[:, 6].astype(np.float64), sig[:, 7].astype(np.float64)
    gx, gy, gz = sig[:, 2].astype(np.float64), sig[:, 3].astype(np.float64), sig[:, 4].astype(np.float64)
    vm = np.sqrt(ax * ax + ay * ay + az * az)
    gyro = np.sqrt(gx * gx + gy * gy + gz * gz)
    s0 = int(start_s * FS)
    s1 = int((start_s + WIN_S) * FS)
    if s1 > len(vm):
        s1 = len(vm)
    vm_w = resample_poly(vm[s0:s1], 25, 128)  # ~50 Hz
    gy_w = resample_poly(gyro[s0:s1], 25, 128)
    acc_dyn = vm_w - 1.0
    jerk = np.diff(vm_w, prepend=vm_w[0])
    return float(rolling_rms(acc_dyn) + 0.3 * rolling_rms(jerk) + 0.002 * rolling_rms(gy_w))


def build_dataset(rec_dir: Path) -> pd.DataFrame:
    records = sorted(p.name[:-4] for p in rec_dir.glob("*.hea"))
    rows: list[dict] = []
    for rec in records:
        sig, fs, _ = read_record(rec_dir, rec)
        subject = rec.split("_")[0]
        ref_hrs, starts = ecg_reference_hrs(sig)
        if not starts:
            print(f"  {rec}: no valid ECG reference windows, skipped")
            continue
        ref_map = dict(zip(starts, ref_hrs))
        n_win = 0
        for start_s in starts:
            s0 = int(start_s * FS)
            ppg = sig[s0:int(s0 + WIN_S * FS), 1].astype(float)
            feats = ppg_window_features(ppg, None, motion_index=motion_index(sig, start_s), fs_hz=float(FS))
            ppg_hr = feats.get("ppg_hr_bpm")
            ref = float(ref_map[start_s])
            if np.isnan(ppg_hr):
                usable = 0  # app could not estimate HR -> not useful
            else:
                usable = 1 if abs(ppg_hr - ref) <= USABLE_TOLERANCE_BPM else 0
            row = {f: feats.get(f) for f in PPG_QUALITY_FEATURES}
            row["usable"] = usable
            row["subject"] = subject
            row["record"] = rec
            row["ref_hr"] = ref
            rows.append(row)
            n_win += 1
        print(f"  {rec}: {n_win} windows (subject {subject})")
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/public/wrist_ppg_during_exercise")
    ap.add_argument("--out", default="models/ppg_quality_model.joblib")
    args = ap.parse_args()

    rec_dir = Path(args.data)
    print("Building windows from", rec_dir)
    df = build_dataset(rec_dir)
    if df.empty:
        raise SystemExit("No labeled windows produced - check the data path.")

    print(f"\nTotal windows: {len(df)}  usable: {int(df['usable'].sum())} "
          f"({100 * df['usable'].mean():.1f}%)  subjects: {df['subject'].nunique()}")
    per = df.groupby("record")["usable"].agg(["mean", "count"])
    for rec, row in per.iterrows():
        print(f"    {rec:28s} usable {100 * row['mean']:.0f}%  (n={int(row['count'])})")

    X = df[PPG_QUALITY_FEATURES]
    y = df["usable"].astype(int)
    groups = df["subject"].astype(str)

    pipeline = Pipeline([
        ("imp", SimpleImputer(strategy="median")),
        ("scaler", StandardScaler()),
        ("clf", RandomForestClassifier(
            n_estimators=400, min_samples_leaf=3, class_weight="balanced", random_state=42)),
    ])

    cv = GroupKFold(n_splits=5)
    oof = np.full(len(df), np.nan)
    aucs, aps = [], []
    for tr, te in cv.split(X, y, groups):
        m = Pipeline([
            ("imp", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
            ("clf", RandomForestClassifier(
                n_estimators=400, min_samples_leaf=3, class_weight="balanced", random_state=42)),
        ])
        m.fit(X.iloc[tr], y.iloc[tr])
        oof[te] = m.predict_proba(X.iloc[te])[:, 1]
        aucs.append(roc_auc_score(y.iloc[te], oof[te]))
        aps.append(average_precision_score(y.iloc[te], oof[te]))

    print(f"\nSubject-level 5-fold CV:  ROC-AUC {np.mean(aucs):.4f} +- {np.std(aucs):.4f}   "
          f"Avg precision {np.mean(aps):.4f} +- {np.std(aps):.4f}")
    print("Confusion at 0.5 threshold (pooled OOF):")
    print(classification_report(y, oof >= 0.5, target_names=["corrupt", "usable"], digits=3))
    keep_rate = float((oof >= 0.5).mean())
    print(f"Fraction of windows the model would keep: {100 * keep_rate:.1f}% "
          f"(vs {100 * df['usable'].mean():.1f}% truly usable)")

    pipeline.fit(X, y)
    importance = dict(zip(PPG_QUALITY_FEATURES, pipeline.named_steps["clf"].feature_importances_))
    top = sorted(importance.items(), key=lambda kv: -kv[1])[:5]
    print("Top features:", ", ".join(f"{k} ({v:.3f})" for k, v in top))

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    meta = {
        "dataset": "PhysioNet Wrist PPG During Exercise (retained locally)",
        "recordings": int(df["record"].nunique()),
        "subjects": int(df["subject"].nunique()),
        "windows": int(len(df)),
        "usable_rate": round(float(df["usable"].mean()), 4),
        "window_s": WIN_S,
        "label_rule": f"|app-style PPG HR - ECG HR| <= {USABLE_TOLERANCE_BPM} bpm (ECG gated by smoothness)",
        "cv_scheme": "5-fold GroupKFold by subject",
        "cv_roc_auc": round(float(np.mean(aucs)), 4),
        "cv_auc_std": round(float(np.std(aucs)), 4),
        "cv_average_precision": round(float(np.mean(aps)), 4),
        "cv_keep_rate_0_5": round(float(keep_rate), 4),
        "top_features": [k for k, _ in top],
        "notes": ("Educational artifact. Wrist PPG sensor differs from the MAX30102; "
                  "blended at 40% weight in src/utils/quality.ppg_quality."),
    }
    joblib.dump({"model": pipeline, "feature_names": PPG_QUALITY_FEATURES, "meta": meta}, args.out)

    from src.models.training_audit import record_training_audit

    record_training_audit({
        "model_id": "ppg_quality",
        "model_name": "PPG signal-quality model",
        "version": "1.0",
        "dataset_id": "wrist_ppg_exercise",
        "artifact": args.out,
        "feature_list": PPG_QUALITY_FEATURES,
        "preprocessing": "median imputation + standard scaling; ECG reference gated by IBI-CV and local-median smoothness",
        "hyperparameters": "RandomForest(400 trees, min_samples_leaf=3, class_weight=balanced)",
        "n_subjects": int(df["subject"].nunique()),
        "n_samples": int(len(df)),
        "split_scheme": "5-fold GroupKFold by subject",
        "random_seed": 42,
        "metrics": {"roc_auc": round(float(np.mean(aucs)), 4),
                     "average_precision": round(float(np.mean(aps)), 4),
                     "keep_rate_0_5": round(float(keep_rate), 4)},
    })

    print("\nSaved", args.out)
    print("Meta:", json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()
