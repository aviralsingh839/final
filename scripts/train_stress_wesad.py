"""Train a wearable stress model from WESAD.

Place extracted WESAD folders under `data/public/WESAD/` so that subject pickle
files look like `data/public/WESAD/S2/S2.pkl`.

Usage:
    python scripts/train_stress_wesad.py --wesad data/public/WESAD --out models/stress_model.joblib
"""
from __future__ import annotations

import argparse
import pickle
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report, roc_auc_score
from sklearn.model_selection import GroupKFold, cross_val_predict
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


FS = {"BVP": 64, "EDA": 4, "TEMP": 4, "ACC": 32, "label": 700}


def window_stats(x: np.ndarray, prefix: str) -> dict[str, float]:
    x = np.asarray(x, dtype=float)
    if x.ndim == 2:
        mag = np.sqrt((x * x).sum(axis=1))
        x = mag
    x = x[np.isfinite(x)]
    if x.size == 0:
        return {f"{prefix}_mean": np.nan, f"{prefix}_std": np.nan, f"{prefix}_p95": np.nan}
    return {f"{prefix}_mean": float(np.mean(x)), f"{prefix}_std": float(np.std(x)), f"{prefix}_p95": float(np.percentile(x, 95))}


def load_subject(path: Path, win_s: int = 60, step_s: int = 30) -> pd.DataFrame:
    with open(path, "rb") as f:
        data = pickle.load(f, encoding="latin1")
    wrist = data["signal"]["wrist"]
    labels = np.asarray(data["label"])
    duration_s = len(labels) / FS["label"]
    rows = []
    for start in np.arange(0, duration_s - win_s, step_s):
        end = start + win_s
        lab = labels[int(start * FS["label"]): int(end * FS["label"])]
        lab = lab[(lab == 1) | (lab == 2) | (lab == 3)]
        if lab.size < 0.5 * win_s * FS["label"]:
            continue
        majority = int(pd.Series(lab).mode().iloc[0])
        if majority not in (1, 2):
            continue  # baseline vs stress only for binary model
        row = {"stress": 1 if majority == 2 else 0, "subject": path.parent.name}
        for sig in ["BVP", "EDA", "TEMP", "ACC"]:
            arr = np.asarray(wrist[sig])
            seg = arr[int(start * FS[sig]): int(end * FS[sig])]
            row.update(window_stats(seg, sig.lower()))
        # EDA phasic proxy.
        eda = np.asarray(wrist["EDA"])[int(start * FS["EDA"]): int(end * FS["EDA"])]
        if eda.size > 2:
            d = np.diff(eda.ravel())
            row["gsr_phasic_per_min"] = float(np.sum(d > np.percentile(d, 95)) / (win_s / 60))
        rows.append(row)
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wesad", required=True)
    ap.add_argument("--out", default="models/stress_model.joblib")
    args = ap.parse_args()
    files = sorted(Path(args.wesad).glob("S*/S*.pkl"))
    if not files:
        raise SystemExit("No WESAD S*/S*.pkl files found.")
    df = pd.concat([load_subject(p) for p in files], ignore_index=True)
    feature_names = [c for c in df.columns if c not in ("stress", "subject")]
    X = df[feature_names].replace([np.inf, -np.inf], np.nan).fillna(df[feature_names].median())
    y = df["stress"].astype(int)
    groups = df["subject"].astype(str)
    clf = Pipeline([("scaler", StandardScaler()), ("model", RandomForestClassifier(n_estimators=300, min_samples_leaf=4, random_state=42, class_weight="balanced"))])
    cv = GroupKFold(n_splits=min(5, groups.nunique()))
    proba = cross_val_predict(clf, X, y, groups=groups, cv=cv, method="predict_proba")[:, 1]
    print("Group CV ROC-AUC:", roc_auc_score(y, proba))
    print(classification_report(y, proba >= 0.5))
    clf.fit(X, y)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": clf, "feature_names": feature_names}, args.out)
    print("Saved", args.out)


if __name__ == "__main__":
    main()
