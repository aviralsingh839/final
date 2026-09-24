"""Ultrasound computer-vision module (CHRONO-PCOS V8.1).

Deliberately NOT an "ultrasound image → PCOS diagnosis" black box. The pipeline
is strictly:

    Ultrasound image
      → image-quality assessment
      → structured feature extraction (only where a validated model + dataset
        supports it; otherwise every value is UNKNOWN)
      → structured ultrasound features (MEASURED / CLINICALLY ENTERED /
        IMAGE-DERIVED / UNKNOWN provenance)
      → multimodal model (see src/models/fusion.py)

Design rules enforced in this module:

  * Every image-derived feature carries a documented provenance and an
    explicit confidence. If the module cannot determine a feature reliably,
    it returns UNKNOWN — it never hallucinates a value.
  * There is NO trained ovarian-detection model in this repository (no
    legitimate labelled ultrasound dataset is included), so all
    image-derived anatomical features are UNKNOWN by construction. The
    quality pipeline works on real images today; the feature pipeline is
    wired and pending data.
  * Patient-level splitting is the ONLY accepted validation strategy: images
    from the same patient must never leak across train/validation/test.
  * Quality assessment is performed with the Python standard library + PIL +
    numpy (no cv2 dependency required).

Nothing here diagnoses PCOS or predicts cyst rupture.
"""
from __future__ import annotations

import io
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

# ---------------------------------------------------------------------------
# provenance vocabulary (also used by the fusion layer)
# ---------------------------------------------------------------------------
MEASURED = "MEASURED"
PATIENT_REPORTED = "PATIENT-REPORTED"
CLINICALLY_ENTERED = "CLINICALLY-ENTERED"
IMAGE_DERIVED = "IMAGE-DERIVED"
MODEL_INFERRED = "MODEL-INFERRED"
UNKNOWN = "UNKNOWN"

PROVENANCE_LABELS = {
    MEASURED: "Directly measured by a sensor",
    PATIENT_REPORTED: "Reported by the patient",
    CLINICALLY_ENTERED: "Entered by a clinician",
    IMAGE_DERIVED: "Derived from an image by the computer-vision pipeline",
    MODEL_INFERRED: "Inferred by a model (never presented as measurement)",
    UNKNOWN: "Not determinable with current data",
}

QUALITY_INSUFFICIENT = "ULTRASOUND QUALITY INSUFFICIENT FOR ANALYSIS"


@dataclass
class ImageQualityReport:
    """Quality assessment of one ultrasound image."""

    ok: bool
    path: str
    width: int = 0
    height: int = 0
    format: str = ""
    corruption: str = ""          # "" | "unreadable" | "truncated" | ...
    blur_score: float = 0.0       # higher = sharper (variance of gradient)
    min_resolution_ok: bool = True
    issues: List[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        if self.ok:
            return (f"OK: {self.width}x{self.height} {self.format}, "
                    f"sharpness {self.blur_score:.1f}")
        return QUALITY_INSUFFICIENT + " — " + "; ".join(self.issues or ["unknown issue"])


@dataclass
class StructuredFeatures:
    """Structured ultrasound features with provenance and confidence.

    Every field defaults to UNKNOWN with confidence 0.0 — the honest state
    when no validated image model is available.
    """

    exam_ts: float
    source: str = CLINICALLY_ENTERED
    # ovary-level measurements (image-derived when a validated model exists)
    ovary_visible: str = UNKNOWN
    left_ovary_volume_cc: Optional[float] = None
    right_ovary_volume_cc: Optional[float] = None
    cyst_present: str = UNKNOWN
    cyst_size_mm: Optional[float] = None
    cyst_laterality: str = UNKNOWN
    morphology: str = UNKNOWN
    follicle_count_notes: str = UNKNOWN
    # provenance + confidence for the whole feature set
    provenance: str = UNKNOWN
    confidence: float = 0.0
    notes: str = ""

    def as_dict(self) -> dict:
        return {
            "exam_ts": self.exam_ts,
            "source": self.source,
            "ovary_visible": self.ovary_visible,
            "left_ovary_volume_cc": self.left_ovary_volume_cc,
            "right_ovary_volume_cc": self.right_ovary_volume_cc,
            "cyst_present": self.cyst_present,
            "cyst_size_mm": self.cyst_size_mm,
            "cyst_laterality": self.cyst_laterality,
            "morphology": self.morphology,
            "follicle_count_notes": self.follicle_count_notes,
            "provenance": self.provenance,
            "confidence": self.confidence,
            "notes": self.notes,
        }


@dataclass
class ExamComparison:
    """Descriptive comparison of two ultrasound examinations.

    Compares only what is actually recorded (clinician-entered or
    image-derived). Direction-of-change labels are descriptive — temporal
    association is never claimed as causation.
    """

    previous_ts: float
    current_ts: float
    rows: List[dict] = field(default_factory=list)  # {field, label, prev, curr, delta, direction}

    def summary_text(self) -> str:
        if not self.rows:
            return "No comparable ultrasound measurements between examinations."
        lines = [
            f"Ultrasound comparison: "
            f"{time.strftime('%Y-%m-%d', time.localtime(self.previous_ts))} → "
            f"{time.strftime('%Y-%m-%d', time.localtime(self.current_ts))}",
        ]
        for r in self.rows:
            lines.append(
                f"  {r['label']}: {r['prev']} → {r['curr']} ({r['direction']})")
        lines.append("Descriptive comparison of recorded findings — not a diagnosis.")
        return "\n".join(lines)


def _blur_score(gray: np.ndarray) -> float:
    """Variance-of-gradients sharpness proxy (higher = sharper)."""
    gx = np.abs(np.diff(gray.astype(np.float32), axis=1))
    gy = np.abs(np.diff(gray.astype(np.float32), axis=0))
    return float(np.mean(gx) + np.mean(gy))


class UltrasoundCV:
    """Ultrasound image pipeline: quality first, features only when supported.

    The anatomical feature extractor is intentionally gated: without a
    validated, labelled, patient-grouped ultrasound dataset no image-derived
    value is produced. `extract_features` therefore returns UNKNOWN features
    for any image, but keeps the quality gate live and meaningful.
    """

    MIN_WIDTH = 320
    MIN_HEIGHT = 240
    MIN_BLUR = 1.5            # below this, the image is too soft to analyse

    # ------------------------------------------------------------ quality
    def assess_quality(self, image_path: str | Path) -> ImageQualityReport:
        p = Path(image_path)
        issues: List[str] = []
        if not p.exists():
            return ImageQualityReport(ok=False, path=str(p),
                                      issues=["file not found"])
        try:
            from PIL import Image
            with Image.open(p) as im:
                fmt = im.format or ""
                w, h = im.size
                gray = np.asarray(im.convert("L").resize((min(w, 512), min(h, 512))))
        except Exception as exc:  # corrupt / truncated / unsupported
            return ImageQualityReport(
                ok=False, path=str(p),
                corruption=f"unreadable ({type(exc).__name__})",
                issues=[f"image could not be decoded: {type(exc).__name__}"])

        blur = _blur_score(gray)
        if w < self.MIN_WIDTH or h < self.MIN_HEIGHT:
            issues.append(f"resolution {w}x{h} below minimum {self.MIN_WIDTH}x{self.MIN_HEIGHT}")
        if blur < self.MIN_BLUR:
            issues.append(f"image too blurred/soft (sharpness {blur:.1f} < {self.MIN_BLUR})")
        return ImageQualityReport(
            ok=not issues, path=str(p), width=w, height=h, format=fmt or "?",
            blur_score=blur, min_resolution_ok=w >= self.MIN_WIDTH and h >= self.MIN_HEIGHT,
            issues=issues)

    # ----------------------------------------------------------- features
    def extract_features(self, image_path: str | Path,
                         clinician_entries: Optional[dict] = None) -> StructuredFeatures:
        """Structured features for one examination.

        `clinician_entries` may carry clinically entered values (cyst size,
        morphology, ...) — these are CLINICALLY-ENTERED, never IMAGE-DERIVED.
        Image-derived values are produced only when a validated model exists;
        today they are UNKNOWN.
        """
        quality = self.assess_quality(image_path)
        ce = clinician_entries or {}
        if not quality.ok:
            return StructuredFeatures(
                exam_ts=time.time(), source=CLINICALLY_ENTERED,
                provenance=UNKNOWN, confidence=0.0,
                notes=QUALITY_INSUFFICIENT + " — " + "; ".join(quality.issues))

        # Clinically entered values pass through with their own provenance.
        features = StructuredFeatures(
            exam_ts=time.time(),
            source=CLINICALLY_ENTERED if ce else IMAGE_DERIVED,
            cyst_size_mm=ce.get("cyst_size_mm"),
            morphology=ce.get("morphology") or UNKNOWN,
            cyst_laterality=ce.get("laterality") or UNKNOWN,
        )
        features.cyst_present = (
            "yes" if ce.get("cyst_present") is True
            else "no" if ce.get("cyst_present") is False else UNKNOWN)
        if ce:
            features.provenance = CLINICALLY_ENTERED
            features.confidence = float(ce.get("confidence", 0.8))
            features.notes = ("Values clinically entered. No image-derived "
                              "features available until a validated ultrasound "
                              "model + dataset exists (patient-level split).")
        else:
            features.provenance = IMAGE_DERIVED
            features.confidence = 0.0
            features.notes = (
                "IMAGE-DERIVED FEATURES PENDING: no validated, labelled, "
                "patient-grouped ultrasound dataset is included in this "
                "repository, so no anatomical feature is extracted from the "
                "image. Ovary/cyst/follicle values are UNKNOWN by design.")
        return features

    # ----------------------------------------------------- exam comparison
    def compare_exams(self, previous: Optional[dict],
                      current: Optional[dict]) -> Optional[ExamComparison]:
        """Compare two recorded examinations (image-derived or clinician-entered).

        `previous` / `current` are dicts from HistoryStore.ultrasound_history()
        or StructuredFeatures.as_dict(). Rows are emitted only for fields that
        exist on BOTH sides; missing data yields no row for that field.
        """
        if not previous or not current:
            return None
        prev_ts = float(previous.get("exam_ts", previous.get("ts", 0)))
        curr_ts = float(current.get("exam_ts", current.get("ts", 0)))
        comp = ExamComparison(previous_ts=prev_ts, current_ts=curr_ts)

        def fmt(v) -> str:
            if v is None:
                return "unknown"
            if isinstance(v, float):
                return f"{v:.1f}"
            return str(v)

        pairs = [
            ("cyst_size_mm", "Largest cyst size (mm)"),
            ("volume_cc", "Ovarian volume (cc)"),
        ]
        for key, label in pairs:
            p = previous.get(key)
            c = current.get(key)
            if p is None or c is None:
                continue
            delta = float(c) - float(p)
            direction = ("increased" if delta > 0.5 else
                         "decreased" if delta < -0.5 else "stable")
            comp.rows.append({
                "field": key, "label": label,
                "prev": fmt(p), "curr": fmt(c),
                "delta": round(delta, 2), "direction": direction,
            })
        for key, label in (("morphology", "Morphology"),
                           ("cyst_laterality", "Laterality")):
            p = previous.get(key)
            c = current.get(key)
            if p is None or c is None or p == UNKNOWN or c == UNKNOWN:
                continue
            direction = "unchanged" if str(p) == str(c) else "changed"
            comp.rows.append({
                "field": key, "label": label,
                "prev": fmt(p), "curr": fmt(c),
                "delta": None, "direction": direction,
            })
        return comp


# ---------------------------------------------------------------------------
# patient-level dataset schema + integrity checks (no data is fabricated)
# ---------------------------------------------------------------------------
REQUIRED_DATASET_COLUMNS = [
    "patient_id",        # grouping key — NEVER split within a patient
    "image_path",        # path to the ultrasound image
    "label",             # clinical reference label (e.g. PCOS per Rotterdam)
    "exam_date",         # ISO date of the examination
]
OPTIONAL_DATASET_COLUMNS = [
    "cyst_size_mm", "ovary_volume_cc", "morphology", "follicle_count",
    "image_quality", "reference_standard", "site",
]


class UltrasoundDataset:
    """Schema + integrity validation for a future legitimate ultrasound dataset.

    This class does NOT contain a dataset. It documents exactly what a
    legitimate dataset must look like and rejects anything that would produce
    an inflated result (e.g. image-level splits with patients in both
    train and test).
    """

    def __init__(self, records: Optional[List[dict]] = None):
        self.records = records or []

    def validate_schema(self) -> List[str]:
        """Return a list of schema violations (empty = schema OK)."""
        problems: List[str] = []
        if not self.records:
            problems.append("No records supplied (dataset not included in repository).")
            return problems
        first = self.records[0]
        for col in REQUIRED_DATASET_COLUMNS:
            if col not in first:
                problems.append(f"missing required column: {col}")
        # per-record checks
        for i, r in enumerate(self.records):
            if "patient_id" in r and not r.get("patient_id"):
                problems.append(f"record {i}: empty patient_id")
            if "label" in r and r.get("label") is None:
                problems.append(f"record {i}: missing label")
        return problems

    def patient_split(self, train_frac: float = 0.7, val_frac: float = 0.15,
                      seed: int = 42) -> dict:
        """Patient-level train/validation/test split (no intra-patient leakage).

        Returns a description of the split; the actual split requires the
        dataset to exist. This method never invents data.
        """
        patients = sorted({r.get("patient_id") for r in self.records if r.get("patient_id")})
        n = len(patients)
        if n == 0:
            return {"status": "PENDING",
                    "reason": "No dataset with patient_id supplied."}
        rng = np.random.default_rng(seed)
        shuffled = list(patients)
        rng.shuffle(shuffled)
        n_train = int(n * train_frac)
        n_val = int(n * val_frac)
        return {
            "status": "SCHEMA OK",
            "patients": n,
            "train_patients": sorted(shuffled[:n_train]),
            "val_patients": sorted(shuffled[n_train:n_train + n_val]),
            "test_patients": sorted(shuffled[n_train + n_val:]),
            "note": ("Split is at patient level. Images from one patient never "
                     "appear in more than one partition."),
        }

    @staticmethod
    def dataset_schema_doc() -> str:
        return (
            "ULTRASOUND DATASET SCHEMA (required for the CV feature pipeline)\n"
            "=================================================================\n"
            "Required columns:\n"
            "  patient_id    — grouping key; splitting happens ONLY on this\n"
            "  image_path    — path to each ultrasound image\n"
            "  label         — clinical reference label (e.g. PCOS per Rotterdam\n"
            "                  criteria, documented per site)\n"
            "  exam_date     — ISO date of examination\n"
            "Optional columns:\n"
            "  cyst_size_mm, ovary_volume_cc, morphology, follicle_count,\n"
            "  image_quality, reference_standard, site\n"
            "\n"
            "Validation requirements:\n"
            "  * split at PATIENT level (train/validation/test patients)\n"
            "  * one patient's images never span partitions\n"
            "  * reference standard documented; label provenance recorded\n"
            "  * ethics approval + consent documented for every image\n"
            "No dataset is currently included in this repository, and none is\n"
            "fabricated. Until a legitimate dataset exists, all image-derived\n"
            "features are UNKNOWN (see StructuredFeatures).\n")
