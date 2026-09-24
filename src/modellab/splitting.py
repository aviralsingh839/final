"""Patient-level data splitting and leakage detection.

CRITICAL RULE: when patient identifiers exist, splitting happens at the
PATIENT level — images from one patient never cross split boundaries.
When they do not exist, an image-level split is produced together with an
explicit warning: "Patient-level leakage cannot be reliably ruled out."
The system never silently claims rigorous validation.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Dict, List

from src.modellab.dataset_store import ImageRecord


class LeakageError(Exception):
    """Potential data leakage detected — training must stop."""


@dataclass
class SplitResult:
    train: List[ImageRecord] = field(default_factory=list)
    val: List[ImageRecord] = field(default_factory=list)
    test: List[ImageRecord] = field(default_factory=list)
    patient_level: bool = False
    ratios: tuple = (0.7, 0.15, 0.15)
    seed: int = 42
    warnings: List[str] = field(default_factory=list)

    def summary(self) -> dict:
        def pat(rows):
            return len({r.patient_id for r in rows if r.patient_id})
        return {
            "patient_level": self.patient_level,
            "ratios": list(self.ratios),
            "seed": self.seed,
            "train_images": len(self.train), "train_patients": pat(self.train),
            "val_images": len(self.val), "val_patients": pat(self.val),
            "test_images": len(self.test), "test_patients": pat(self.test),
            "warnings": self.warnings,
        }


def usable_records(records: List[ImageRecord]) -> List[ImageRecord]:
    """Only labelled, non-INVALID images are usable for training."""
    return [r for r in records if r.label is not None and r.quality != "INVALID"]


def split_records(records: List[ImageRecord], ratios=(0.7, 0.15, 0.15),
                  seed: int = 42) -> SplitResult:
    rows = usable_records(records)
    if abs(sum(ratios) - 1.0) > 1e-6:
        raise ValueError("Split ratios must sum to 1.0")
    if len(rows) < 6:
        raise LeakageError("INSUFFICIENT DATA: fewer than 6 usable labelled images.")

    rng = random.Random(seed)
    result = SplitResult(ratios=tuple(ratios), seed=seed)
    pids = sorted({r.patient_id for r in rows if r.patient_id})
    have_all_pids = bool(pids) and all(r.patient_id for r in rows)

    if have_all_pids and len(pids) >= 3:
        result.patient_level = True
        shuffled = pids[:]
        rng.shuffle(shuffled)
        n = len(shuffled)
        n_train = max(1, round(n * ratios[0]))
        n_val = max(1, round(n * ratios[1]))
        n_train = min(n_train, n - 2)
        n_val = min(n_val, n - n_train - 1)
        train_p = set(shuffled[:n_train])
        val_p = set(shuffled[n_train:n_train + n_val])
        test_p = set(shuffled[n_train + n_val:])
        for r in rows:
            if r.patient_id in train_p:
                result.train.append(r)
            elif r.patient_id in val_p:
                result.val.append(r)
            else:
                result.test.append(r)
    else:
        result.patient_level = False
        result.warnings.append(
            "Patient-level leakage cannot be reliably ruled out: patient identifiers "
            "are missing or incomplete, so this is an image-level split.")
        shuffled = rows[:]
        rng.shuffle(shuffled)
        n = len(shuffled)
        n_train = max(1, int(n * ratios[0]))
        n_val = max(1, int(n * ratios[1]))
        result.train = shuffled[:n_train]
        result.val = shuffled[n_train:n_train + n_val]
        result.test = shuffled[n_train + n_val:]

    if not result.test or not result.val:
        raise LeakageError("INSUFFICIENT DATA: the split produced an empty validation or test set.")
    return result


def check_split_leakage(split: SplitResult) -> List[str]:
    """Return leakage findings; raise LeakageError if any critical one exists."""
    findings: List[str] = []

    # Same patient across splits (should be impossible for patient-level).
    def pids(rows):
        return {r.patient_id for r in rows if r.patient_id}
    for name_a, a, name_b, b in [("train", split.train, "val", split.val),
                                 ("train", split.train, "test", split.test),
                                 ("val", split.val, "test", split.test)]:
        shared = pids(a) & pids(b)
        if shared:
            findings.append(f"Patient(s) {sorted(shared)[:5]} appear in both {name_a} and {name_b}.")

    # Identical image hashes across splits.
    def hashes(rows) -> Dict[str, str]:
        return {r.sha256: r.image for r in rows}
    for name_a, a, name_b, b in [("train", split.train, "val", split.val),
                                 ("train", split.train, "test", split.test),
                                 ("val", split.val, "test", split.test)]:
        shared = set(hashes(a)) & set(hashes(b))
        if shared:
            findings.append(f"{len(shared)} identical image(s) shared between {name_a} and {name_b}.")

    # Near-duplicate (average-hash) images across train and eval splits.
    train_ahash = {r.ahash for r in split.train if r.ahash}
    for name, rows in (("val", split.val), ("test", split.test)):
        near = [r.image for r in rows if r.ahash and r.ahash in train_ahash
                and r.sha256 not in {t.sha256 for t in split.train}]
        if near:
            findings.append(
                f"{len(near)} suspiciously similar image(s) shared between train and {name} "
                f"(e.g. {near[0]}).")

    if findings:
        raise LeakageError("Potential data leakage detected.\n" + "\n".join(findings))
    return findings
