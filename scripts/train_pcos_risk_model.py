"""Train the clinical PCOS risk baseline model from public PCOS data.

The real 541-patient Kaggle dataset ships with the repo under `data/public/`:

    python scripts/train_pcos_risk_model.py \
        --csv data/public/PCOS_data_without_infertility.xlsx \
        --out models/pcos_risk_model.joblib

`--csv` accepts one or more files; `.xlsx` files are read from their `Full_new`
sheet (falling back to the first sheet). The script cleans column names, fixes
the known "aborptions" typo, drops unnamed/identifier columns, and removes the
pregnancy-related columns (beta-HCG, Pregnant(Y/N), abortions) because they are
a pregnancy screen rather than a general PCOS screening feature and removing
them measurably improves held-out accuracy.

The extended Kaggle CSV (`PCOS_extended_dataset.csv`) is SYNTHETIC - it jitters
the continuous columns of the same 530 patients. It is not used by default:
it adds no new patients and does not improve real held-out accuracy. Pass
`--extended` to append it as optional augmentation anyway.

The trained bundle is used for feature-importance education and optional
calibration (see models/README.md). The live risk engine is a separate
physiological hybrid model, so retraining here never changes the dashboard.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # project root for src imports

import joblib
import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import ExtraTreesClassifier, RandomForestClassifier, VotingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

TARGET_CANDIDATES = ["PCOS (Y/N)", "pcos (y/n)", "PCOS Y/N", "pcos"]
# Pregnancy-screen columns: not available in general screening and empirically
# slightly *hurt* held-out AUC on the public dataset.
LEAKY_KEYWORDS = ("hcg", "beta", "pregnant", "abortion")


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [re.sub(r"\s+", " ", str(c)).strip() for c in df.columns]
    return df


def load_input(path: str) -> pd.DataFrame:
    path = str(path)
    if path.lower().endswith((".xlsx", ".xls")):
        xl = pd.ExcelFile(path)
        sheet = "Full_new" if "Full_new" in xl.sheet_names else xl.sheet_names[0]
        return pd.read_excel(path, sheet_name=sheet)
    return pd.read_csv(path)


def clean(df: pd.DataFrame, keep_patient_id: bool = False) -> pd.DataFrame:
    df = normalize_columns(df)
    # Known typo in the public Kaggle export.
    df = df.rename(columns={"No. of aborptions": "No. of abortions"})
    drop = [c for c in df.columns if c.lower().startswith("unnamed") or "sl." in c.lower()]
    if not keep_patient_id:
        drop += [c for c in df.columns if "file no" in c.lower()]
    df = df.drop(columns=[c for c in drop if c in df.columns], errors="ignore")
    for c in df.columns:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.drop_duplicates()
    return df


def find_target(df: pd.DataFrame) -> str:
    for c in df.columns:
        if c.lower() in TARGET_CANDIDATES:
            return c
    for c in df.columns:
        if "pcos" in c.lower() and "y" in c.lower():
            return c
    for c in df.columns:
        vals = set(pd.Series(df[c]).dropna().unique())
        if vals.issubset({0, 1, "0", "1", "Y", "N", "Yes", "No"}) and "pcos" in c.lower():
            return c
    raise SystemExit("Could not find the PCOS target column (expected e.g. 'PCOS (Y/N)').")


def make_voting_estimator():
    def _pipe():
        return Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
        ])

    lr = Pipeline([("pre", _pipe()), ("clf", LogisticRegression(max_iter=3000, C=0.5, class_weight="balanced"))])
    rf = Pipeline([("pre", _pipe()), ("clf", RandomForestClassifier(
        n_estimators=500, min_samples_leaf=2, max_features=0.5,
        class_weight="balanced_subsample", random_state=42))])
    et = Pipeline([("pre", _pipe()), ("clf", ExtraTreesClassifier(
        n_estimators=400, min_samples_leaf=2, max_features=0.5,
        class_weight="balanced_subsample", random_state=42))])
    return VotingClassifier([("lr", lr), ("rf", rf), ("et", et)], voting="soft")


def evaluate(X: pd.DataFrame, y: pd.Series, groups: pd.Series, real_mask: np.ndarray | None = None) -> tuple[float, float, float]:
    """Patient-level 5-fold CV of the soft-vote ensemble.

    If `real_mask` is given (extended mode), only real rows are scored; the
    synthetic rows of the held-out patients never appear in the test fold.
    """
    cv = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=42)
    proba = np.full(len(X), np.nan)
    for tr, te in cv.split(X, y, groups):
        m = make_voting_estimator().fit(X.iloc[tr], y.iloc[tr])
        proba[te] = m.predict_proba(X.iloc[te])[:, 1]
    eval_idx = np.arange(len(X)) if real_mask is None else np.where(real_mask)[0]
    if len(eval_idx) < 10:
        raise SystemExit("Too few rows to evaluate.")
    return (
        float(roc_auc_score(y.iloc[eval_idx], proba[eval_idx])),
        float(average_precision_score(y.iloc[eval_idx], proba[eval_idx])),
        float(np.mean(proba[eval_idx] >= 0.5) - y.iloc[eval_idx].mean()),
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", nargs="+", required=True,
                    help="One or more CSV/XLSX files with a 'PCOS (Y/N)' target column.")
    ap.add_argument("--extended", default=None,
                    help="Optional SYNTHETIC extended CSV to append for augmentation (off by default).")
    ap.add_argument("--out", default="models/pcos_risk_model.joblib")
    args = ap.parse_args()

    frames = []
    for p in args.csv:
        frames.append(clean(load_input(p), keep_patient_id=True))
    real = pd.concat(frames, ignore_index=True)
    real = real.drop_duplicates()

    target = find_target(real)
    real[target] = real[target].replace({"Y": 1, "N": 0, "Yes": 1, "No": 0})
    real = real[real[target].notna()]
    real[target] = real[target].astype(int)
    print(f"Real rows: {len(real)}  (target: {int((real[target] == 1).sum())} PCOS / "
          f"{int((real[target] == 0).sum())} no-PCOS)")

    leaky_dropped = [c for c in real.columns if any(k in c.lower() for k in LEAKY_KEYWORDS)]
    feat_cols = [c for c in real.columns if c not in (target, "Patient File No.")]
    feat_cols = [c for c in feat_cols if c not in leaky_dropped]

    real_X = real[feat_cols]
    y = real[target].astype(int)
    pid = real["Patient File No."].astype(str) if "Patient File No." in real.columns else pd.Series(range(len(real))).astype(str)

    X, groups, y_all, real_mask = real_X, pid, y, None
    if args.extended:
        ext = clean(load_input(args.extended), keep_patient_id=True)
        ext[target] = ext[target].replace({"Y": 1, "N": 0, "Yes": 1, "No": 0})
        ext = ext[ext[target].notna()]
        ext[target] = ext[target].astype(int)
        shared = [c for c in feat_cols if c in ext.columns]
        ext_X = ext[shared].reindex(columns=real_X.columns)
        X = pd.concat([real_X, ext_X], ignore_index=True)
        y_all = pd.concat([y, ext[target].astype(int)], ignore_index=True)
        ext_pid = ext["Patient File No."].astype(str) if "Patient File No." in ext.columns else pd.Series(range(len(ext), len(ext) + len(ext))).astype(str)
        groups = pd.concat([pid, ext_pid], ignore_index=True)
        real_mask = np.zeros(len(X), dtype=bool)
        real_mask[: len(real)] = True
        print(f"Extended (SYNTHETIC) augmentation rows: {len(ext)}")

    auc, ap, bias = evaluate(X, y_all, groups, real_mask)
    eval_note = "real rows only" if real_mask is not None else f"all {len(real)} real rows"
    print(f"\nPatient-level 5-fold CV (evaluated on {eval_note}):")
    print(f"  ROC-AUC       {auc:.4f}")
    print(f"  Avg precision {ap:.4f}")
    print(f"  mean pred - prevalence bias @0.5: {bias:+.4f}")
    print(f"Leaky columns dropped: {leaky_dropped or 'none'}")

    calibrated = CalibratedClassifierCV(make_voting_estimator(), method="isotonic", cv=3)
    calibrated.fit(X, y_all)

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    meta = {
        "dataset": [str(p) for p in args.csv],
        "extended_synthetic_used": bool(args.extended),
        "n_rows_train": int(len(X)),
        "n_real_rows": int(len(real)),
        "n_features": len(feat_cols),
        "leaky_columns_dropped": leaky_dropped,
        "cv_scheme": "5-fold stratified-group (patient-level)",
        "cv_evaluated_on": eval_note,
        "cv_roc_auc": round(auc, 4),
        "cv_average_precision": round(ap, 4),
        "notes": ("Extended dataset is synthetic (jittered copies of the same patients); "
                  "it is excluded by default because it does not improve real held-out accuracy."),
    }
    joblib.dump({
        "model": calibrated,
        "feature_names": feat_cols,
        "target": target,
        "meta": meta,
    }, args.out)

    from src.models.training_audit import record_training_audit

    record_training_audit({
        "model_id": "pcos_risk",
        "model_name": "PCOS clinical risk model",
        "version": "1.1",
        "dataset_id": "pcos_kaggle",
        "artifact": args.out,
        "feature_list": feat_cols,
        "preprocessing": "median imputation + standard scaling; leaky pregnancy columns removed",
        "hyperparameters": "LR(C=0.5, balanced) + RF(500, leaf 2) + ExtraTrees(400, leaf 2) soft vote, isotonic calibration cv=3",
        "n_subjects": int(len(real)),
        "n_samples": int(len(X)),
        "split_scheme": "5-fold stratified-group (patient-level)",
        "random_seed": 42,
        "metrics": {"roc_auc": round(auc, 4), "average_precision": round(ap, 4)},
    })

    print("\nSaved", args.out)
    print("Meta:", json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()
