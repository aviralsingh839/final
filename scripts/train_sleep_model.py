"""Train sleep/wake model from an epoch-level public sleep dataset export.

Because PhysioNet/NSRR datasets have different formats, first export a CSV with
one row per 30-second epoch and columns similar to:

    hr_bpm, rmssd_ms, motion_index, spo2_pct, temp_slope_c_per_min, gsr_tonic, hour, sleep_label

`sleep_label` should be 1 for sleep and 0 for wake. If sleep stages are present,
map N1/N2/N3/REM to 1 and Wake to 0.

Usage:
    python scripts/train_sleep_model.py --csv data/processed/sleep_epochs.csv --out models/sleep_model.joblib
"""
from __future__ import annotations

import argparse
from pathlib import Path

import joblib
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.metrics import classification_report, roc_auc_score
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--out", default="models/sleep_model.joblib")
    args = ap.parse_args()
    df = pd.read_csv(args.csv)
    target = "sleep_label"
    if target not in df.columns:
        raise SystemExit("CSV must contain sleep_label column.")
    feature_names = [c for c in ["hr_bpm", "rmssd_ms", "motion_index", "spo2_pct", "temp_slope_c_per_min", "gsr_tonic", "hour"] if c in df.columns]
    if not feature_names:
        raise SystemExit("No expected feature columns found.")
    X = df[feature_names]
    y = df[target].astype(int)
    clf = Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("scaler", StandardScaler()),
        ("model", RandomForestClassifier(n_estimators=300, min_samples_leaf=5, random_state=42, class_weight="balanced")),
    ])
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    proba = cross_val_predict(clf, X, y, cv=cv, method="predict_proba")[:, 1]
    print("CV ROC-AUC:", roc_auc_score(y, proba))
    print(classification_report(y, proba >= 0.5))
    clf.fit(X, y)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": clf, "feature_names": feature_names}, args.out)
    print("Saved", args.out)


if __name__ == "__main__":
    main()
