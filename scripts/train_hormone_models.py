"""Train optional hormone regression models from public hormone datasets.

This script expects a pre-merged day-level CSV from mcPHASES/NHANES/MMASH with
columns such as:

    LH, E3G, PdG, glucose_mean, resting_hr, rmssd_ms, sleep_minutes,
    sleep_efficiency, stress_score, activity_minutes, cycle_day

It does not create synthetic hormone data. If these public datasets are not
available, the dashboard uses transparent physiology-based equations with wide
confidence intervals.

Usage:
    python scripts/train_hormone_models.py --csv data/processed/hormone_daylevel.csv --out models/hormone_models.joblib
"""
from __future__ import annotations

import argparse
from pathlib import Path

import joblib
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import KFold, cross_val_predict
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

TARGETS = ["LH", "E3G", "PdG", "insulin", "cortisol", "testosterone", "FSH", "estradiol", "progesterone", "AMH"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--out", default="models/hormone_models.joblib")
    args = ap.parse_args()
    df = pd.read_csv(args.csv)
    targets = [t for t in TARGETS if t in df.columns]
    if not targets:
        raise SystemExit("No hormone target columns found. Do not train on invented targets.")
    ignore = set(targets + ["id", "participant", "date"])
    features = [c for c in df.columns if c not in ignore and pd.api.types.is_numeric_dtype(df[c])]
    if not features:
        raise SystemExit("No numeric feature columns found.")
    models = {}
    for target in targets:
        sub = df[features + [target]].dropna(subset=[target])
        if len(sub) < 30:
            print(f"Skipping {target}: only {len(sub)} labeled rows")
            continue
        X = sub[features]
        y = sub[target]
        reg = Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
            ("model", RandomForestRegressor(n_estimators=300, min_samples_leaf=3, random_state=42)),
        ])
        cv = KFold(n_splits=min(5, len(sub)), shuffle=True, random_state=42)
        pred = cross_val_predict(reg, X, y, cv=cv)
        print(target, "MAE", mean_absolute_error(y, pred), "R2", r2_score(y, pred))
        reg.fit(X, y)
        models[target] = reg
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"models": models, "feature_names": features}, args.out)
    print("Saved", args.out)


if __name__ == "__main__":
    main()
