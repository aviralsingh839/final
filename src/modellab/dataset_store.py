"""Dataset intake, structure detection, inspection and versioning.

Supported structures (auto-detected):

  A) labels CSV (preferred)::

        images/patient001_img01.jpg ...
        labels.csv   with columns  image, patient_id, label
                     (flexible synonyms accepted, see COLUMN_SYNONYMS)

  B) class folders::

        PCOS/patient001_img01.jpg
        Normal/patient002_img01.jpg

     Label = folder name; patient id parsed from the ``<prefix>_`` filename
     pattern when present.

If neither structure can be interpreted, the import STOPS with
``DatasetStructureError`` explaining exactly what is missing — the system
never guesses labels.

Every imported dataset gets a version id ``DATASET-<NAME>-NNN``, the ZIP
sha256 hash, per-image hashes, an inspection report (counts, classes,
duplicates, corrupt images, missing labels, imbalance, leakage risks) and an
image-quality categorization (VALID / QUESTIONABLE / INVALID).
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

from src.modellab.safezip import IMAGE_EXTENSIONS, extract_dataset_zip

COLUMN_SYNONYMS = {
    "image": {"image", "filename", "file", "image_name", "img", "path", "image_path"},
    "patient_id": {"patient_id", "patient", "subject", "subject_id", "case_id", "pid"},
    "label": {"label", "class", "diagnosis", "target", "category", "y"},
}

PATIENT_PREFIX_RE = re.compile(r"^([A-Za-z]*\d+)[_\-]")

# Image-quality thresholds (research heuristics; questionable != deleted).
MIN_SIDE_PX = 64
BLUR_VARIANCE_MIN = 12.0
BRIGHTNESS_DARK = 18.0
BRIGHTNESS_BRIGHT = 238.0


class DatasetStructureError(Exception):
    """Structure could not be reliably interpreted — import must stop."""


@dataclass
class ImageRecord:
    image: str                       # path relative to dataset root
    patient_id: Optional[str] = None
    label: Optional[str] = None
    sha256: str = ""
    ahash: str = ""                  # 8x8 average hash (near-duplicate detection)
    width: int = 0
    height: int = 0
    fmt: str = ""
    quality: str = "VALID"           # VALID | QUESTIONABLE | INVALID
    issues: List[str] = field(default_factory=list)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _inspect_image(path: Path) -> Tuple[dict, str, List[str]]:
    """Return (properties, quality_class, issues). Never raises."""
    issues: List[str] = []
    props = {"width": 0, "height": 0, "fmt": "", "ahash": ""}
    try:
        from PIL import Image

        with Image.open(path) as im:
            im.verify()
        with Image.open(path) as im:
            props["fmt"] = (im.format or "").upper()
            props["width"], props["height"] = im.size
            gray = np.asarray(im.convert("L"), dtype=np.float64)
    except Exception as exc:  # corrupt / unreadable
        return props, "INVALID", [f"unreadable/corrupt image ({type(exc).__name__})"]

    # 8x8 average hash for near-duplicate detection.
    try:
        from PIL import Image

        with Image.open(path) as im:
            small = np.asarray(im.convert("L").resize((8, 8)), dtype=np.float64)
        props["ahash"] = "".join("1" if v > small.mean() else "0" for v in small.flatten())
    except Exception:
        pass

    quality = "VALID"
    if min(props["width"], props["height"]) < MIN_SIDE_PX:
        issues.append(f"low resolution ({props['width']}x{props['height']})")
        quality = "QUESTIONABLE"
    # Blur: variance of a simple Laplacian.
    if gray.size:
        lap = (np.abs(np.diff(gray, axis=0)).mean() + np.abs(np.diff(gray, axis=1)).mean())
        if lap < 1.0:
            issues.append("possible blur / very low detail")
            quality = "QUESTIONABLE"
        mean = float(gray.mean())
        if mean < BRIGHTNESS_DARK:
            issues.append(f"extremely dark (mean {mean:.0f})")
            quality = "QUESTIONABLE"
        elif mean > BRIGHTNESS_BRIGHT:
            issues.append(f"extremely bright (mean {mean:.0f})")
            quality = "QUESTIONABLE"
    return props, quality, issues


def _find_labels_csv(root: Path) -> Optional[Path]:
    candidates = sorted(root.rglob("*.csv")) + sorted(root.rglob("*.tsv"))
    preferred = [p for p in candidates if p.stem.lower() in ("labels", "label", "annotations", "metadata")]
    for p in preferred + candidates:
        try:
            cols = _read_header(p)
        except Exception:
            continue
        mapped = _map_columns(cols)
        if "image" in mapped and "label" in mapped:
            return p
    return None


def _read_header(path: Path) -> List[str]:
    delim = "\t" if path.suffix.lower() == ".tsv" else ","
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f, delimiter=delim)
        return next(reader)


def _map_columns(cols: List[str]) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    for col in cols:
        key = col.strip().lower()
        for canonical, synonyms in COLUMN_SYNONYMS.items():
            if key in synonyms and canonical not in mapping:
                mapping[canonical] = col
    return mapping


def _parse_labels_csv(path: Path) -> Tuple[List[dict], Dict[str, str]]:
    delim = "\t" if path.suffix.lower() == ".tsv" else ","
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, delimiter=delim)
        mapping = _map_columns(reader.fieldnames or [])
        if "image" not in mapping or "label" not in mapping:
            missing = [k for k in ("image", "label") if k not in mapping]
            raise DatasetStructureError(
                "Dataset structure could not be reliably interpreted.\n"
                f"The labels file {path.name!r} is missing required column(s): {', '.join(missing)}.\n"
                "Expected columns: image, label and optionally patient_id "
                "(synonyms such as filename/class/subject are accepted).")
        rows = []
        for row in reader:
            rows.append({
                "image": (row.get(mapping["image"]) or "").strip(),
                "label": (row.get(mapping["label"]) or "").strip() or None,
                "patient_id": (row.get(mapping.get("patient_id", "")) or "").strip() or None
                if "patient_id" in mapping else None,
            })
    return rows, mapping


def detect_structure(root: Path) -> Tuple[str, List[dict], List[str]]:
    """Return (structure_kind, raw_records, notes).  Raises DatasetStructureError."""
    notes: List[str] = []
    images = [p for p in root.rglob("*") if p.suffix.lower() in IMAGE_EXTENSIONS and p.is_file()]
    if not images:
        raise DatasetStructureError(
            "Dataset structure could not be reliably interpreted.\n"
            "No image files were found in the archive. Supported image formats: "
            + ", ".join(sorted(IMAGE_EXTENSIONS)) + ".")
    by_name: Dict[str, Path] = {}
    for p in images:
        by_name.setdefault(p.name, p)

    labels_csv = _find_labels_csv(root)
    if labels_csv is not None:
        rows, mapping = _parse_labels_csv(labels_csv)
        records = []
        unmatched = 0
        for row in rows:
            img_name = Path(row["image"].replace("\\", "/")).name
            path = by_name.get(img_name)
            if path is None:
                unmatched += 1
                continue
            pid = row["patient_id"]
            if pid is None:
                m = PATIENT_PREFIX_RE.match(img_name)
                pid = m.group(1) if m else None
            records.append({"path": path, "label": row["label"], "patient_id": pid})
        if unmatched:
            notes.append(f"{unmatched} row(s) in {labels_csv.name} reference images not present in the archive.")
        if not records:
            raise DatasetStructureError(
                "Dataset structure could not be reliably interpreted.\n"
                f"A labels file ({labels_csv.name}) was found but none of its image "
                "names match the image files in the archive.")
        listed = {Path(r["image"].replace("\\", "/")).name for r in rows}
        extra = [p for n, p in by_name.items() if n not in listed]
        if extra:
            notes.append(f"{len(extra)} image(s) have no row in {labels_csv.name} (imported without labels).")
            for p in extra:
                m = PATIENT_PREFIX_RE.match(p.name)
                records.append({"path": p, "label": None,
                                "patient_id": m.group(1) if m else None})
        return "labels_csv", records, notes

    # Class-folder layout: images grouped into per-class directories.
    class_dirs: Dict[str, List[Path]] = {}
    for p in images:
        parent = p.parent.name
        if parent and parent.lower() not in ("images", "image", "img", "data", root.name.lower()):
            class_dirs.setdefault(parent, []).append(p)
    if len(class_dirs) >= 2 and sum(len(v) for v in class_dirs.values()) >= 0.9 * len(images):
        records = []
        for label, paths in class_dirs.items():
            for p in paths:
                m = PATIENT_PREFIX_RE.match(p.name)
                records.append({"path": p, "label": label,
                                "patient_id": m.group(1) if m else None})
        notes.append("Structure detected: class folders (label = folder name).")
        return "class_folders", records, notes

    raise DatasetStructureError(
        "Dataset structure could not be reliably interpreted.\n"
        "Missing: a labels file (labels.csv with columns image,label[,patient_id]) "
        "or a class-folder layout (one sub-folder per class).\n"
        f"Found {len(images)} image(s) but no way to assign labels to them. "
        "The system will not guess labels.")


# ------------------------------------------------------------------ store --
class DatasetStore:
    """Imports, versions and persists datasets under ``<root>/datasets``."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.datasets_dir = self.root / "datasets"
        self.datasets_dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.root / "datasets.json"

    # ------------------------------------------------------------- index
    def _load_index(self) -> List[dict]:
        if self.index_path.exists():
            return json.loads(self.index_path.read_text(encoding="utf-8"))
        return []

    def _save_index(self, index: List[dict]) -> None:
        self.index_path.write_text(json.dumps(index, indent=1), encoding="utf-8")

    def list_datasets(self) -> List[dict]:
        return self._load_index()

    def get(self, dataset_id: str) -> Optional[dict]:
        for d in self._load_index():
            if d["id"] == dataset_id:
                return d
        return None

    def load_records(self, dataset_id: str) -> List[ImageRecord]:
        meta = self.get(dataset_id)
        if meta is None:
            raise KeyError(dataset_id)
        data = json.loads((Path(meta["dir"]) / "dataset.json").read_text(encoding="utf-8"))
        return [ImageRecord(**r) for r in data["records"]]

    # ------------------------------------------------------------ import
    def import_zip(self, zip_path: Path, name: str = "", source: str = "",
                   license_info: str = "") -> dict:
        """Full intake pipeline: safe-extract → detect structure → inspect.

        Returns the dataset metadata dict (also persisted).  Raises
        UnsafeZipError / DatasetStructureError on failure (nothing is kept).
        """
        zip_path = Path(zip_path)
        name_slug = re.sub(r"[^A-Za-z0-9]+", "", (name or zip_path.stem)).upper() or "DATASET"
        index = self._load_index()
        seq = len(index) + 1
        dataset_id = f"DATASET-{name_slug[:12]}-{seq:03d}"
        dest = self.datasets_dir / dataset_id

        try:
            extraction = extract_dataset_zip(zip_path, dest)
            kind, raw_records, notes = detect_structure(dest)
            records = self._inspect_records(dest, raw_records)
            report = build_report(records, notes + extraction.warnings)
        except Exception:
            shutil.rmtree(dest, ignore_errors=True)
            raise

        meta = {
            "id": dataset_id,
            "name": name or zip_path.stem,
            "source": source,
            "license": license_info,
            "imported_at": time.time(),
            "zip_hash": _sha256_file(zip_path),
            "structure": kind,
            "dir": str(dest),
            "n_images": report["n_images"],
            "n_patients": report["n_patients"],
            "classes": report["classes"],
            "has_patient_ids": report["patient_ids_available"],
        }
        (dest / "dataset.json").write_text(json.dumps({
            "meta": meta,
            "report": report,
            "records": [asdict(r) for r in records],
        }, indent=1), encoding="utf-8")
        index.append(meta)
        self._save_index(index)
        return meta

    def report(self, dataset_id: str) -> dict:
        meta = self.get(dataset_id)
        if meta is None:
            raise KeyError(dataset_id)
        data = json.loads((Path(meta["dir"]) / "dataset.json").read_text(encoding="utf-8"))
        return data["report"]

    # --------------------------------------------------------- inspection
    def _inspect_records(self, root: Path, raw_records: List[dict]) -> List[ImageRecord]:
        records: List[ImageRecord] = []
        for raw in raw_records:
            path: Path = raw["path"]
            props, quality, issues = _inspect_image(path)
            rec = ImageRecord(
                image=str(path.relative_to(root)),
                patient_id=raw.get("patient_id"),
                label=raw.get("label"),
                sha256=_sha256_file(path),
                ahash=props.get("ahash", ""),
                width=props.get("width", 0),
                height=props.get("height", 0),
                fmt=props.get("fmt", ""),
                quality=quality,
                issues=issues,
            )
            if rec.label is None:
                rec.issues.append("missing label")
            if rec.patient_id is None:
                rec.issues.append("missing patient id")
            records.append(rec)
        return records


# ------------------------------------------------------------------ report --
def build_report(records: List[ImageRecord], notes: List[str]) -> dict:
    """Dataset inspection report — counts, duplicates, imbalance, warnings."""
    n_images = len(records)
    labels = [r.label for r in records if r.label]
    classes: Dict[str, int] = {}
    for lb in labels:
        classes[lb] = classes.get(lb, 0) + 1
    patients = {r.patient_id for r in records if r.patient_id}
    per_patient: Dict[str, int] = {}
    for r in records:
        if r.patient_id:
            per_patient[r.patient_id] = per_patient.get(r.patient_id, 0) + 1

    # Duplicates.
    by_hash: Dict[str, List[str]] = {}
    for r in records:
        by_hash.setdefault(r.sha256, []).append(r.image)
    exact_dups = {h: v for h, v in by_hash.items() if len(v) > 1}
    by_ahash: Dict[str, List[str]] = {}
    for r in records:
        if r.ahash:
            by_ahash.setdefault(r.ahash, []).append(r.image)
    near_dups = {h: v for h, v in by_ahash.items()
                 if len(v) > 1 and h not in {r.ahash for r in records if r.sha256 in exact_dups}}
    by_name: Dict[str, int] = {}
    for r in records:
        base = Path(r.image).name
        by_name[base] = by_name.get(base, 0) + 1
    repeated_names = {n: c for n, c in by_name.items() if c > 1}

    # Cross-patient duplicate hashes → leakage risk even with patient split.
    leakage_risks: List[str] = []
    for h, imgs in exact_dups.items():
        pids = {r.patient_id for r in records if r.sha256 == h and r.patient_id}
        if len(pids) > 1:
            leakage_risks.append(
                f"Identical image content under multiple patient ids ({', '.join(sorted(pids))}): "
                + ", ".join(imgs[:4]))

    corrupt = [r.image for r in records if r.quality == "INVALID"]
    questionable = [r.image for r in records if r.quality == "QUESTIONABLE"]
    missing_labels = [r.image for r in records if r.label is None]
    missing_pids = [r.image for r in records if r.patient_id is None]

    warnings: List[str] = list(notes)
    imbalance_ratio = None
    if len(classes) >= 2:
        counts = sorted(classes.values())
        imbalance_ratio = counts[-1] / max(1, counts[0])
        if imbalance_ratio >= 3.0:
            warnings.append(
                f"Severe class imbalance ({imbalance_ratio:.1f}:1). Consider class "
                "weighting or documented controlled augmentation — never blind duplication.")
    if missing_labels:
        warnings.append(f"{len(missing_labels)} image(s) have no label and will be excluded from training.")
    if missing_pids:
        warnings.append(f"{len(missing_pids)} image(s) have no patient id.")
    if not patients:
        warnings.append("No patient identifiers found: patient-level leakage cannot be reliably ruled out.")
    if exact_dups:
        warnings.append(f"{sum(len(v) - 1 for v in exact_dups.values())} exact duplicate image(s) detected.")
    if near_dups:
        warnings.append(f"{len(near_dups)} group(s) of suspiciously similar images detected (near duplicates).")
    if corrupt:
        warnings.append(f"{len(corrupt)} corrupt/unreadable image(s) — categorized INVALID (not deleted).")
    if leakage_risks:
        warnings.append("Potential data leakage detected: identical images appear under different patient ids.")

    dims: Dict[str, int] = {}
    fmts: Dict[str, int] = {}
    for r in records:
        if r.width and r.height:
            key = f"{r.width}x{r.height}"
            dims[key] = dims.get(key, 0) + 1
        if r.fmt:
            fmts[r.fmt] = fmts.get(r.fmt, 0) + 1

    return {
        "n_images": n_images,
        "n_patients": len(patients),
        "patient_ids_available": bool(patients) and len(missing_pids) == 0,
        "classes": classes,
        "images_per_patient": {
            "min": min(per_patient.values()) if per_patient else 0,
            "max": max(per_patient.values()) if per_patient else 0,
            "mean": round(sum(per_patient.values()) / len(per_patient), 2) if per_patient else 0,
        },
        "dimensions": dict(sorted(dims.items(), key=lambda kv: -kv[1])[:8]),
        "formats": fmts,
        "corrupt": corrupt,
        "questionable": questionable,
        "exact_duplicates": {h[:12]: v for h, v in exact_dups.items()},
        "near_duplicates": {h[:12]: v for h, v in list(near_dups.items())[:50]},
        "repeated_filenames": repeated_names,
        "missing_labels": missing_labels,
        "missing_patient_ids": missing_pids,
        "imbalance_ratio": imbalance_ratio,
        "leakage_risks": leakage_risks,
        "warnings": warnings,
    }
