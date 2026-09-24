"""Automated validation report.

Assembles a structured, dated report covering methodology, dataset description,
sensor/reference agreement, repeatability, model validation (LOSO), calibration,
ablation, leakage checks, uncertainty statistics, limitations (claim guard) and
a conclusion. Includes experiment date, software version and model versions.

All results come from the Validation Lab modules; synthetic data is explicitly
separated from real validation and never presented as clinical validity.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.models.registry import APP_VERSION
from src.utils.history_store import HistoryStore
from src.validation.agreement import AgreementResult, agreement
from src.validation.calibration import CalibrationResult, calibration
from src.validation.leakage import LeakageCheck, run_leakage_checks
from src.validation.losocv import LosoResult, leave_one_subject_out
from src.validation.prospective import ProspectiveSummary, ProspectiveValidator
from src.validation.repeatability import RepeatabilityResult
from src.validation.store import ValidationStore
from src.validation.versioning import snapshot_model_state

CLAIM_GUARD = [
    "Sensors do NOT directly measure hormones; every hormone value shown is a model estimate.",
    "The system is NOT a diagnostic device and does not diagnose PCOS/PCOD.",
    "A PCOS diagnosis requires appropriate clinical evaluation and testing by a qualified professional.",
    "Synthetic-data validation does NOT establish clinical validity.",
    "All values are educational estimates for a research demonstration.",
]

METHODOLOGY = [
    "Reference-device agreement: paired (sensor, reference) measurements; MAE, RMSE, bias, SD of differences, Pearson r, Bland-Altman 95% limits of agreement.",
    "SQI: per-sensor quality (PPG, ECG, GSR, IMU, temperature) with artifact detection (saturation, clipping, missing, motion, pressure) and an overall SQI; predictions are withheld below quality/confidence thresholds.",
    "Repeatability: repeated measures from the same subject under the same condition; mean, SD, CV and ICC(2,1), within- vs between-session CV.",
    "Model validation: leave-one-subject-out evaluation with strict subject-level separation; accuracy, precision, recall, specificity, F1, ROC-AUC, PR-AUC reported as mean ± SD across folds.",
    "Calibration: Brier score and Expected Calibration Error (ECE) with a reliability curve.",
    "Ablation: risk recomputed with each sensor modality removed and isolated to quantify per-modality contribution.",
    "Leakage detection: automated heuristic checks (subject train/test overlap, duplicate sessions/windows, future timestamps, normalization timing, label-in-features).",
    "Prospective validation: frozen model snapshot; predictions recorded before outcomes are known; outcomes entered later and compared.",
    "Model versioning: reproducible snapshots of app version, model registry, feature list, preprocessing configuration and engine weights.",
]


def _fmt_ts(ts: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))


def validation_report_text(
    db: HistoryStore,
    vstore: ValidationStore,
    agreement_by_metric: Optional[Dict[str, AgreementResult]] = None,
    repeatability_result: Optional[RepeatabilityResult] = None,
    loso_result: Optional[LosoResult] = None,
    calibration_result: Optional[CalibrationResult] = None,
    ablation_rows: Optional[List] = None,
    leakage_checks: Optional[List[LeakageCheck]] = None,
    prospective_summary: Optional[ProspectiveSummary] = None,
    uncertainty_text: str = "",
    dataset_text: str = "",
) -> str:
    lines: List[str] = []
    lines.append("CHRONO-PCOS Validation Report")
    lines.append("=" * 68)
    lines.append(f"Generated: {_fmt_ts(time.time())}")
    lines.append(f"Software version: {APP_VERSION}")
    snap = snapshot_model_state()
    model_line = "; ".join(f"{m['name']} v{m['version']}" for m in snap["models"])
    lines.append(f"Model versions: {model_line}")
    lines.append("")

    lines.append("1. Methodology")
    lines.append("-" * 68)
    lines.extend(f"  - {m}" for m in METHODOLOGY)
    lines.append("")

    lines.append("2. Dataset description")
    lines.append("-" * 68)
    lines.append(dataset_text or _dataset_description(db))
    lines.append("  Validation-data separation: software/unit tests, synthetic-data validation, real "
                 "physiological validation and clinical validation are kept strictly separate. Synthetic "
                 "data does NOT establish clinical validity.")
    lines.append("")

    lines.append("3. Sensor / reference comparison")
    lines.append("-" * 68)
    if agreement_by_metric:
        for metric, res in agreement_by_metric.items():
            lines.append(f"  {metric}: {res.summary()}")
    else:
        pairs = vstore.reference_pairs()
        if pairs:
            by_metric: Dict[str, List] = {}
            for p in pairs:
                by_metric.setdefault(p["metric"], []).append((p["sensor_value"], p["reference_value"]))
            for metric, pts in by_metric.items():
                lines.append(f"  {metric}: {agreement(pts).summary()}")
        else:
            lines.append("  No paired reference-device measurements recorded yet.")
    lines.append("")

    lines.append("4. Repeatability & reproducibility")
    lines.append("-" * 68)
    lines.append("  " + (repeatability_result.summary() if repeatability_result else "Not computed."))
    lines.append("")

    lines.append("5. Model validation (leave-one-subject-out)")
    lines.append("-" * 68)
    if loso_result:
        lines.append("  " + loso_result.summary().replace("\n", "\n  "))
        for note in loso_result.notes:
            lines.append(f"  NOTE: {note}")
    else:
        lines.append("  Not computed.")
    lines.append("")

    lines.append("6. Calibration")
    lines.append("-" * 68)
    if calibration_result:
        lines.append("  " + calibration_result.summary())
    else:
        lines.append("  Not computed (requires labelled predictions).")
    lines.append("")

    lines.append("7. Ablation study")
    lines.append("-" * 68)
    if ablation_rows:
        for row in ablation_rows:
            lines.append("  " + row.render())
    else:
        lines.append("  Not computed.")
    lines.append("")

    lines.append("8. Model / data-leakage checks")
    lines.append("-" * 68)
    checks = leakage_checks if leakage_checks is not None else run_leakage_checks(db)
    if checks:
        lines.extend("  " + c.render() for c in checks)
    else:
        lines.append("  No checks run.")
    lines.append("  NOTE: heuristic checks are evidence, not proof, of absence of leakage.")
    lines.append("")

    lines.append("9. Prediction uncertainty")
    lines.append("-" * 68)
    lines.append("  " + (uncertainty_text or "Not computed."))
    lines.append("")

    lines.append("10. Prospective validation")
    lines.append("-" * 68)
    if prospective_summary:
        lines.append("  " + prospective_summary.summary())
    else:
        lines.append("  Not started. Freeze the model, record predictions before outcomes, then label outcomes.")
    lines.append("")

    lines.append("11. Limitations & claim guard")
    lines.append("-" * 68)
    lines.extend(f"  - {c}" for c in CLAIM_GUARD)
    lines.append("")

    lines.append("12. Conclusion")
    lines.append("-" * 68)
    lines.append("  This report documents methodology and validation results for an educational "
                 "research demonstration. It is not a clinical validation study and confers no "
                 "diagnostic capability. Full reproducibility is available via the frozen model "
                 "snapshots and this report's dated metadata.")
    return "\n".join(lines)


def _dataset_description(db: HistoryStore) -> str:
    counts = db.row_counts()
    sessions = db.session_compare(limit=1000)
    subjects = len({(s.get("participant_id") or f"session#{s['id']}") for s in sessions})
    synthetic = sum(1 for s in sessions if (s.get("source") or "").startswith(("demo", "synth")))
    real = len(sessions) - synthetic
    return (
        f"  Sessions: {counts.get('sessions', 0)} (real {real}, clearly-synthetic {synthetic}) · "
        f"feature rows: {counts.get('features', 0)} · subjects: {subjects} · "
        f"calibrations: {counts.get('calibrations', 0)} · anomalies logged: {counts.get('anomalies', 0)}"
    )


def write_validation_report(path: Path | str, text: str) -> None:
    Path(path).write_text(text, encoding="utf-8")
