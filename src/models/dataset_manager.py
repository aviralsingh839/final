"""Dataset manager (V5, item B).

Central registry of every dataset used or referenced by the project, with
provenance metadata (source URL, license, version, citation), sample counts,
available signals and labels, and automated quality checks:
  * duplicate subjects/records detection,
  * missing values,
  * impossible physiological values,
  * inconsistent units,
  * duplicate subjects across different datasets (never treat unrelated
    datasets' subjects as the same person).

Nothing here fabricates metadata: fields that are not verifiable are marked
'see source' / 'unknown' rather than guessed. The synthetic extension dataset
is always labelled SYNTHETIC.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from src.config import DATA_DIR


@dataclass
class DatasetInfo:
    id: str
    name: str
    source_url: str
    license: str
    version: str
    citation: str
    local_path: Optional[str]
    format: str
    signals: List[str] = field(default_factory=list)
    labels: List[str] = field(default_factory=list)
    status: str = "absent"  # present | absent | synthetic
    n_subjects: Optional[int] = None
    n_sessions: Optional[int] = None
    n_samples: Optional[int] = None
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id, "name": self.name, "source_url": self.source_url,
            "license": self.license, "version": self.version, "citation": self.citation,
            "local_path": self.local_path, "format": self.format,
            "signals": self.signals, "labels": self.labels, "status": self.status,
            "n_subjects": self.n_subjects, "n_sessions": self.n_sessions,
            "n_samples": self.n_samples, "notes": self.notes,
        }


# ---------------------------------------------------------------- registry
DATASET_REGISTRY: List[DatasetInfo] = [
    DatasetInfo(
        id="pcos_kaggle",
        name="Polycystic Ovary Syndrome (clinical, 541 patients)",
        source_url="https://www.kaggle.com/datasets/prasoonkottarathil/polycystic-ovary-syndrome-pcos",
        license="See source dataset page",
        version="2020-07",
        citation="Kaggle: Polycystic Ovary Syndrome (PCOS) dataset — PCOS_data_without_infertility.xlsx",
        local_path="data/public/PCOS_data_without_infertility.xlsx",
        format="xlsx",
        signals=["Age", "Weight", "Height", "BMI", "Blood Group", "Pulse", "RR", "Hb",
                 "Cycle", "HCG", "FSH", "LH", "TSH", "AMH", "PRL", "VitD3", "PRG", "RBS",
                 "BP", "Follicles", "Endometrium", "lifestyle flags"],
        labels=["PCOS (Y/N)"],
        status="present",
        n_subjects=541,
        n_sessions=541,
        n_samples=541,
        notes="One row per patient (clinical screening sheet).",
    ),
    DatasetInfo(
        id="pcos_infertility",
        name="PCOS infertility panel (same 541 patients)",
        source_url="https://www.kaggle.com/datasets/prasoonkottarathil/polycystic-ovary-syndrome-pcos",
        license="See source dataset page",
        version="2020-07",
        citation="Kaggle: Polycystic Ovary Syndrome (PCOS) dataset — PCOS_infertility.csv",
        local_path="data/public/PCOS_infertility.csv",
        format="csv",
        signals=["beta-HCG I", "beta-HCG II", "AMH"],
        labels=["PCOS (Y/N)"],
        status="present",
        n_subjects=541,
        n_sessions=541,
        n_samples=541,
        notes="Same patients as pcos_kaggle; subset of columns (redundant for the risk model).",
    ),
    DatasetInfo(
        id="pcos_extended",
        name="PCOS extended dataset (SYNTHETIC augmentation)",
        source_url="https://www.kaggle.com/datasets/prasoonkottarathil/polycystic-ovary-syndrome-pcos",
        license="See source dataset page",
        version="2024-01",
        citation="Kaggle: PCOS extended dataset (2000 rows, continuous-valued augmentation).",
        local_path="data/public/PCOS_extended_dataset.csv",
        format="csv",
        signals=["Same schema as pcos_kaggle"],
        labels=["PCOS (Y/N)"],
        status="synthetic",
        n_subjects=530,
        n_sessions=None,
        n_samples=2000,
        notes="SYNTHETIC: jittered copies of the same 530 of the 541 patients — not new patients. "
              "Excluded from training by default (see scripts/train_pcos_risk_model.py).",
    ),
    DatasetInfo(
        id="wrist_ppg_exercise",
        name="Wrist PPG During Exercise (PhysioNet)",
        source_url="https://physionet.org/content/wrist-ppg-during-exercise/1.0.0/",
        license="PhysioNet terms; original page withdrawn — treat as research-only",
        version="1.0.0",
        citation="PhysioNet: Wrist PPG During Exercise (Corrado et al.).",
        local_path="data/public/wrist_ppg_during_exercise",
        format="wfdb",
        signals=["chest_ecg", "wrist_ppg", "gyro x/y/z", "accel low-noise x/y/z",
                 "accel wide-range x/y/z", "mag x/y/z"],
        labels=["ECG R-peak annotations (atr; unusable in practice — see notes)"],
        status="present",
        n_subjects=8,
        n_sessions=19,
        n_samples=None,
        notes="8 subjects (s1-s9, no s7), 19 recordings at 256 Hz. The bundled .atr annotation "
              "intervals are not usable as HR ground truth (constant ~1100-1300 across walking, "
              "running and biking); the ECG channel itself is used as the reference instead.",
    ),
    DatasetInfo(
        id="wesad",
        name="WESAD (wearable stress and affect)",
        source_url="https://archive.ics.uci.edu/dataset/465/wesad+wearable+stress+and+affect+detection",
        license="See source",
        version="latest",
        citation="WESAD: Wearable Stress and Affect Detection, UCI ML Repository.",
        local_path=None,
        format="pkl",
        signals=["BVP", "EDA", "TEMP", "ACC", "ECG"],
        labels=["stress (baseline/stress/amusement)"],
        status="absent",
        notes="Not downloaded — stress model remains a transparent fallback until this is present.",
    ),
    DatasetInfo(
        id="pima",
        name="Pima Indians Diabetes",
        source_url="https://dataverse.harvard.edu/dataset.xhtml?persistentId=doi:10.7910/DVN/XFOZQR",
        license="See source",
        version="latest",
        citation="Pima Indians Diabetes, Harvard Dataverse.",
        local_path=None,
        format="csv",
        signals=["glucose", "bmi", "age", "bp", "skin", "insulin", "pedigree"],
        labels=["diabetes outcome"],
        status="absent",
        notes="Not downloaded; could support glucose/insulin-resistance priors.",
    ),
    DatasetInfo(
        id="bidsleep",
        name="PhysioNet BIDSleep (sleep HR+ACC+EEG)",
        source_url="https://physionet.org/content/bidsleep-dataset/1.0.0/",
        license="See source",
        version="1.0.0",
        citation="PhysioNet BIDSleep dataset.",
        local_path=None,
        format="bids",
        signals=["ECG", "ACC", "EEG"],
        labels=["sleep stages"],
        status="absent",
        notes="Not downloaded — sleep model remains a fallback until epoch-level export exists.",
    ),
]

_REGISTRY_INDEX = {d.id: d for d in DATASET_REGISTRY}


def get_dataset(dataset_id: str) -> Optional[DatasetInfo]:
    return _REGISTRY_INDEX.get(dataset_id)


def dataset_registry_summary() -> str:
    lines = ["Dataset registry:"]
    for d in DATASET_REGISTRY:
        loc = d.local_path or "—"
        counts = f"{d.n_subjects or '?'} subjects · {d.n_sessions or '?'} sessions · {d.n_samples or '?'} samples"
        lines.append(f"  [{d.status.upper():9s}] {d.id}: {d.name} ({counts}) — {loc}")
        if d.notes:
            lines.append(f"             note: {d.notes}")
    return "\n".join(lines)


# ------------------------------------------------------------------ hashes
def file_sha256(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def dataset_hashes(dataset_id: str) -> Dict[str, str]:
    """SHA-256 of the local files of a dataset (best effort)."""
    d = get_dataset(dataset_id)
    if d is None or not d.local_path:
        return {}
    base = Path(d.local_path)
    if not base.exists():
        return {}
    out: Dict[str, str] = {}
    if base.is_dir():
        for p in sorted(base.glob("*.hea")):
            out[p.name] = file_sha256(p)
    else:
        out[base.name] = file_sha256(base)
    return out


# ------------------------------------------------------------------ checks
PHYSIO_RANGES: Dict[str, tuple[float, float]] = {
    "age": (10, 90),
    "weight": (25, 250),
    "height": (120, 220),
    "bmi": (10, 70),
    "pulse": (30, 220),
    "rr": (4, 60),
    "hb": (5, 22),
    "fsh": (0, 60),
    "lh": (0, 60),
    "tsh": (0, 50),
    "amh": (0, 25),
    "prl": (0, 100),
    "vit": (0, 100),
    "prg": (0, 10),
    "rbs": (40, 500),
    "bp": (60, 220),
    "follicle": (0, 30),
    "endometrium": (0, 30),
    "spo2": (50, 100),
    "hr": (30, 220),
    "rmssd": (5, 200),
    "temp": (25, 45),
    "gsr": (0, 20000),
}


def _column_key(col: str) -> str:
    c = col.lower().replace(" ", "").replace("_", "")
    for key in ["endometrium", "follicle", "pulse", "spo2", "rmssd", "rbs", "vit", "amh",
                "tsh", "prl", "prg", "fsh", "lh", "hb", "bmi", "temp", "gsr", "hr", "rr",
                "bp", "height", "weight", "age"]:
        if key in c:
            return key
    return ""


def check_missing_values(df: pd.DataFrame) -> Dict[str, Any]:
    missing = df.isna().sum()
    missing = missing[missing > 0]
    return {
        "total_missing": int(missing.sum()),
        "columns": missing.astype(int).to_dict(),
        "rows_with_any_missing": int(df.isna().any(axis=1).sum()),
    }


def check_impossible_values(df: pd.DataFrame) -> List[Dict[str, Any]]:
    """Flag rows outside physiologically possible ranges (best-effort, heuristic)."""
    flags: List[Dict[str, Any]] = []
    for col in df.columns:
        key = _column_key(str(col))
        if not key:
            continue
        rng = PHYSIO_RANGES[key]
        series = pd.to_numeric(df[col], errors="coerce")
        bad = series[(series < rng[0]) | (series > rng[1])]
        if len(bad):
            flags.append({"column": str(col), "range": list(rng), "n_out_of_range": int(len(bad)),
                          "example_values": bad.dropna().head(3).tolist()})
    return flags


def check_duplicates(df: pd.DataFrame, id_col: Optional[str] = None) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    dup_rows = int(df.duplicated().sum())
    out["duplicate_rows"] = dup_rows
    if id_col and id_col in df.columns:
        ids = df[id_col]
        counts = ids.value_counts()
        dup_ids = counts[counts > 1]
        out["duplicate_subject_ids"] = int(dup_ids.sum() - len(dup_ids))
        out["n_unique_subjects"] = int(ids.nunique())
        if len(dup_ids):
            out["example_duplicated_ids"] = dup_ids.head(5).index.tolist()
    else:
        out["n_unique_subjects"] = None
    return out


def check_units(df: pd.DataFrame) -> List[Dict[str, Any]]:
    """Heuristic unit-consistency check: flag numeric columns whose values sit in
    the wrong unit band (e.g. height stored in feet, weight in pounds)."""
    flags: List[Dict[str, Any]] = []
    for col in df.columns:
        c = str(col).lower()
        series = pd.to_numeric(df[col], errors="coerce").dropna()
        if series.empty:
            continue
        med = float(series.median())
        if ("height" in c or "cm" in c) and 30 <= med <= 80:  # looks like inches/feet
            flags.append({"column": str(col), "suspected_unit_mismatch": f"median {med:.0f} looks like inches, expected cm (~120-220)"})
        if ("weight" in c) and 50 <= med <= 160 and med * 2.2 > 200:  # ambiguous kg vs lb
            flags.append({"column": str(col), "suspected_unit_mismatch": f"median {med:.0f} — verify kg vs lb"})
        if ("waist" in c or "hip" in c) and med < 20:  # inches are normal (25-45), cm are 60-120
            pass
        if ("bmi" in c) and med > 60:
            flags.append({"column": str(col), "suspected_unit_mismatch": f"median BMI {med:.0f} is implausibly high"})
    return flags


def _align_id_offset(sa: set, sb: set):
    """Return (aligned_b, offset). If the sorted ID lists differ by one constant
    offset, shift `sb` onto `sa` so same-cohort datasets are recognised as such.
    Never aligns when cardinalities differ (that would risk mixing unrelated
    datasets)."""
    if not sa or not sb or len(sa) != len(sb):
        return sb, None
    la, lb = sorted(sa), sorted(sb)
    offsets = {round(lb[i] - la[i], 6) for i in range(len(la))}
    if len(offsets) == 1 and offsets != {0}:
        off = offsets.pop()
        return {v - off for v in sb}, off
    return sb, None


def run_quality_checks(df: pd.DataFrame, id_col: Optional[str] = None) -> Dict[str, Any]:
    return {
        "missing": check_missing_values(df),
        "impossible_values": check_impossible_values(df),
        "duplicates": check_duplicates(df, id_col),
        "unit_checks": check_units(df),
    }


def load_dataset_frame(dataset_id: str) -> Optional[pd.DataFrame]:
    """Load a registered CSV/XLSX dataset (not WFDB) for quality checks."""
    d = get_dataset(dataset_id)
    if d is None or not d.local_path:
        return None
    p = Path(d.local_path)
    if not p.exists():
        return None
    try:
        if p.suffix.lower() == ".xlsx":
            xl = pd.ExcelFile(p)
            sheet = "Full_new" if "Full_new" in xl.sheet_names else xl.sheet_names[0]
            return pd.read_excel(p, sheet_name=sheet)
        if p.suffix.lower() == ".csv":
            return pd.read_csv(p)
    except Exception:
        return None
    return None


def check_cross_dataset_subject_overlap() -> List[Dict[str, Any]]:
    """Detect subjects shared between different datasets (they are the SAME patients
    only when explicitly documented — never merge unrelated datasets silently)."""
    results: List[Dict[str, Any]] = []
    pcos = load_dataset_frame("pcos_kaggle")
    ext = load_dataset_frame("pcos_extended")
    inf = load_dataset_frame("pcos_infertility")
    pairs = [
        ("pcos_kaggle", pcos, "pcos_infertility", inf),
        ("pcos_kaggle", pcos, "pcos_extended", ext),
    ]
    for id_a, df_a, id_b, df_b in pairs:
        if df_a is None or df_b is None:
            continue
        col_a = next((c for c in df_a.columns if "file no" in str(c).lower()), None)
        col_b = next((c for c in df_b.columns if "file no" in str(c).lower()), None)
        if col_a is None or col_b is None:
            continue
        sa = set(pd.to_numeric(df_a[col_a], errors="coerce").dropna())
        sb = set(pd.to_numeric(df_b[col_b], errors="coerce").dropna())
        # Different files may encode the same patients under an ID offset (the
        # infertility sheet uses 10001..10541 for the same 541 patients). Detect
        # a constant offset before claiming disjoint cohorts.
        aligned_sb, offset = _align_id_offset(sa, sb)
        overlap = sa & aligned_sb
        note = ("documented same-cohort overlap" if id_b == "pcos_infertility"
                else "SYNTHETIC extension reuses original patients — must never be treated as new subjects")
        if offset:
            note += f" (IDs aligned by constant offset {offset:+.0f})"
        results.append({
            "dataset_a": id_a, "dataset_b": id_b,
            "overlap_subjects": len(overlap),
            "ids_aligned_by_offset": bool(offset),
            "note": note,
        })
    return results
