"""Multimodal fusion layer with provenance (CHRONO-PCOS V8.1).

Combines heterogeneous inputs into one feature context, tracking for every
value:

  * provenance   — MEASURED | PATIENT-REPORTED | CLINICALLY-ENTERED |
                   IMAGE-DERIVED | MODEL-INFERRED | UNKNOWN
  * quality      — 0..1 signal quality where known
  * source       — which subsystem produced it

Inputs are NOT treated as equally reliable: a fusion weight is computed per
group, so a missing or low-quality modality simply lowers that group's
influence rather than corrupting the rest. This is the missing-data-aware
design the system needs because most patients will not have every modality
(BP without glucose, wearable without GSR, ultrasound only periodically).

Nothing here infers unmeasured biology: MODEL-INFERRED values are explicitly
labelled and never promoted to measurements.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from src.models.ultrasound_cv import (
    CLINICALLY_ENTERED,
    IMAGE_DERIVED,
    MEASURED,
    MODEL_INFERRED,
    PATIENT_REPORTED,
    PROVENANCE_LABELS,
    UNKNOWN,
)

GROUP_ORDER = [
    "clinical",        # age, BMI, cycle characteristics, symptoms
    "wearable",        # HR, HRV, temperature, activity, GSR
    "longitudinal",    # baseline deviations, persistence, slopes, change points
    "metabolic",       # BP, glucose (optional manual)
    "ecg",             # periodic ECG checkpoints
    "ultrasound",      # structured ultrasound features (periodic)
    "adherence",       # care-plan adherence
]


@dataclass
class FusionFeature:
    key: str
    label: str
    value: Optional[float]
    group: str
    provenance: str = UNKNOWN
    quality: float = 0.0          # 0..1
    source: str = ""
    unit: str = ""

    def as_dict(self) -> dict:
        return {
            "key": self.key, "label": self.label, "value": self.value,
            "group": self.group, "provenance": self.provenance,
            "quality": self.quality, "source": self.source, "unit": self.unit,
        }


@dataclass
class FusionContext:
    """A provenance-aware snapshot of everything known about a patient."""

    built_at: float = field(default_factory=time.time)
    features: List[FusionFeature] = field(default_factory=list)

    # ------------------------------------------------------------- access
    def by_group(self, group: str) -> List[FusionFeature]:
        return [f for f in self.features if f.group == group]

    def get(self, key: str) -> Optional[FusionFeature]:
        for f in self.features:
            if f.key == key:
                return f
        return None

    def present_groups(self) -> List[str]:
        seen: List[str] = []
        for f in self.features:
            if f.value is not None and f.group not in seen:
                seen.append(f.group)
        return [g for g in GROUP_ORDER if g in seen]

    def missing_groups(self) -> List[str]:
        return [g for g in GROUP_ORDER if g not in self.present_groups()]

    # ------------------------------------------------------ group weights
    def group_weights(self) -> Dict[str, float]:
        """Reliability-weighted group influence, in 0..1.

        Weight = mean quality of present values in the group, scaled by
        coverage (fraction of expected features present). Missing groups get
        zero weight — they cannot drag the estimate down, but their absence is
        visible in `missing_groups()` and lowers overall confidence.
        """
        from collections import Counter

        expected: Dict[str, int] = {}
        present: Dict[str, int] = Counter()
        quality_sum: Dict[str, float] = Counter()
        for f in self.features:
            expected[f.group] = expected.get(f.group, 0) + 1
            if f.value is not None:
                present[f.group] += 1
                quality_sum[f.group] += f.quality
        weights: Dict[str, float] = {}
        for g in GROUP_ORDER:
            if g not in expected or present[g] == 0:
                weights[g] = 0.0
                continue
            coverage = present[g] / expected[g]
            avg_q = quality_sum[g] / present[g]
            weights[g] = round(coverage * avg_q, 3)
        return weights

    def overall_quality(self) -> float:
        """Mean quality of present features (0..1), 0.0 when nothing present."""
        vals = [f.quality for f in self.features if f.value is not None]
        return round(sum(vals) / len(vals), 3) if vals else 0.0

    def coverage(self) -> float:
        """Fraction of registered features that currently carry a value."""
        if not self.features:
            return 0.0
        present = sum(1 for f in self.features if f.value is not None)
        return round(present / len(self.features), 3)

    def provenance_summary(self) -> List[dict]:
        """Counts per provenance category, for the transparency panel."""
        from collections import Counter

        c: Counter = Counter()
        for f in self.features:
            c[f.provenance] += 1
        return [{"provenance": k, "label": PROVENANCE_LABELS.get(k, k),
                 "count": c[k]} for k in
                (MEASURED, PATIENT_REPORTED, CLINICALLY_ENTERED,
                 IMAGE_DERIVED, MODEL_INFERRED, UNKNOWN) if c[k]]

    # ------------------------------------------------------------ display
    def summary_text(self) -> str:
        lines = [
            "MULTIMODAL FUSION CONTEXT",
            "=" * 46,
            f"Groups present: {', '.join(self.present_groups()) or 'none'}",
            f"Groups missing: {', '.join(self.missing_groups()) or 'none'}",
            f"Overall data quality: {self.overall_quality():.2f}",
            f"Coverage: {self.coverage():.0%}",
            "",
        ]
        for g in GROUP_ORDER:
            feats = self.by_group(g)
            if not feats:
                continue
            lines.append(f"[{g.upper()}]")
            for f in feats:
                val = "—" if f.value is None else (
                    f"{f.value:.2f} {f.unit}".strip() if isinstance(f.value, float)
                    else f"{f.value} {f.unit}".strip())
                lines.append(
                    f"  {f.label}: {val}  ({f.provenance}, quality {f.quality:.2f})")
            lines.append("")
        lines.append("Provenance legend: " + "; ".join(
            f"{k}={PROVENANCE_LABELS[k]}" for k in
            (MEASURED, PATIENT_REPORTED, CLINICALLY_ENTERED, IMAGE_DERIVED,
             MODEL_INFERRED, UNKNOWN)))
        lines.append("Nothing here is presented as a measurement unless its "
                     "provenance says MEASURED.")
        return "\n".join(lines)


class FusionEngine:
    """Builds a FusionContext from whatever subsystems are available."""

    def __init__(self):
        self._builders: List[str] = []

    # ------------------------------------------------------------ builders
    def add_clinical(self, ctx: FusionContext, profile: Optional[object] = None,
                     cycle: Optional[dict] = None,
                     symptoms: Optional[List[dict]] = None) -> None:
        p = profile
        if p is not None:
            for key, label, val in (
                    ("age", "Age (years)", p.age_years if getattr(p, "age_years", None) else None),
                    ("bmi", "BMI", getattr(p, "bmi", None)),
                    ("cycle_length", "Usual cycle length (days)",
                     getattr(p, "usual_cycle_length_days", None)),
                    ("cycle_irregular", "Self-reported cycle irregularity",
                     (1.0 if getattr(p, "cycle_irregular", None) else
                      0.0 if getattr(p, "cycle_irregular", None) is False else None))):
                if val is not None:
                    ctx.features.append(FusionFeature(
                        key=key, label=label, value=val, group="clinical",
                        provenance=PATIENT_REPORTED, quality=0.7,
                        source="UserProfile"))
        if cycle:
            for key, label, val in (
                    ("cycle_day", "Cycle day", cycle.get("cycle_day")),
                    ("cycle_length_actual", "Recorded cycle length",
                     cycle.get("cycle_length"))):
                if val is not None:
                    ctx.features.append(FusionFeature(
                        key=key, label=label, value=val, group="clinical",
                        provenance=PATIENT_REPORTED, quality=0.8,
                        source="cycle log"))
        if symptoms:
            sev = [s.get("severity") for s in symptoms if s.get("severity") is not None]
            if sev:
                ctx.features.append(FusionFeature(
                    key="symptom_severity", label="Mean symptom severity (0-10)",
                    value=sum(sev) / len(sev), group="clinical",
                    provenance=PATIENT_REPORTED, quality=0.6,
                    source="symptom log"))

    def add_wearable(self, ctx: FusionContext, row: Optional[dict] = None,
                     quality: float = 0.0) -> None:
        """Add one wearable feature row (MEASURED provenance)."""
        if not row:
            return
        for key, label, unit in (
                ("hr", "Heart rate", "bpm"),
                ("rmssd", "HRV RMSSD", "ms"),
                ("skin_temp", "Skin temperature", "°C"),
                ("activity", "Activity", ""),
                ("gsr", "GSR", "")):
            v = row.get(key)
            if v is None:
                ctx.features.append(FusionFeature(
                    key=key, label=label, value=None, group="wearable",
                    provenance=MEASURED, quality=0.0, source="wearable", unit=unit))
            else:
                ctx.features.append(FusionFeature(
                    key=key, label=label, value=float(v), group="wearable",
                    provenance=MEASURED, quality=quality, source="wearable", unit=unit))

    def add_longitudinal(self, ctx: FusionContext, fingerprint: Optional[dict] = None,
                         change: Optional[object] = None) -> None:
        """Add personal-baseline deviation and change-point features.

        These are MODEL-INFERRED statistics of real measurements — never raw
        measurements themselves.
        """
        if fingerprint:
            for m in ("hr", "rmssd", "skin_temp", "activity"):
                d = (fingerprint.get(m) or {})
                dev = d.get("deviation_sd")
                if dev is not None:
                    ctx.features.append(FusionFeature(
                        key=f"{m}_dev_sd", label=f"{m.upper()} deviation from baseline (SD)",
                        value=float(dev), group="longitudinal",
                        provenance=MODEL_INFERRED, quality=0.8,
                        source="personal fingerprint"))
                persist = d.get("persistence_days")
                if persist is not None:
                    ctx.features.append(FusionFeature(
                        key=f"{m}_persist_days",
                        label=f"{m.upper()} deviation persistence (days)",
                        value=float(persist), group="longitudinal",
                        provenance=MODEL_INFERRED, quality=0.8,
                        source="personal fingerprint"))
        if change is not None:
            cp = getattr(change, "change_point_count", None)
            if cp is not None:
                ctx.features.append(FusionFeature(
                    key="change_points", label="Detected change points (window)",
                    value=float(cp), group="longitudinal",
                    provenance=MODEL_INFERRED, quality=0.8,
                    source="change detector"))

    def add_metabolic(self, ctx: FusionContext, bp: Optional[dict] = None,
                      glucose: Optional[dict] = None) -> None:
        if bp and bp.get("systolic"):
            ctx.features.append(FusionFeature(
                key="systolic_bp", label="Systolic BP", value=float(bp["systolic"]),
                group="metabolic", provenance=PATIENT_REPORTED, quality=0.7,
                source="manual BP", unit="mmHg"))
        if glucose and glucose.get("value") is not None:
            ctx.features.append(FusionFeature(
                key="glucose", label="Glucose", value=float(glucose["value"]),
                group="metabolic", provenance=PATIENT_REPORTED, quality=0.7,
                source="manual glucose", unit="mg/dL"))

    def add_ecg(self, ctx: FusionContext, ecg_features: Optional[dict] = None) -> None:
        if not ecg_features:
            return
        for key, label in (("hr", "ECG heart rate"), ("rmssd", "ECG HRV RMSSD")):
            v = ecg_features.get(key)
            ctx.features.append(FusionFeature(
                key=f"ecg_{key}", label=label,
                value=float(v) if v is not None else None,
                group="ecg", provenance=MEASURED, quality=0.9,
                source="periodic ECG checkpoint", unit="ms" if key == "rmssd" else "bpm"))

    def add_ultrasound(self, ctx: FusionContext,
                       us: Optional[dict] = None) -> None:
        """Add structured ultrasound features (CLINICALLY-ENTERED or IMAGE-DERIVED).

        Values that are UNKNOWN are registered as present-but-unknown so the
        coverage accounting is honest about the missing modality.
        """
        if not us:
            return
        src = us.get("source") or UNKNOWN
        # Accept both the canonical provenance value ("CLINICALLY-ENTERED") and
        # the HistoryStore shorthand ("clinical").
        prov = CLINICALLY_ENTERED if src in (CLINICALLY_ENTERED, "clinical") else IMAGE_DERIVED
        # Accept both key styles: StructuredFeatures.as_dict() uses
        # "us_cyst_size_mm"; HistoryStore.ultrasound_history() rows use
        # "cyst_size_mm".
        for key, alt, label, unit in (
                ("us_cyst_size_mm", "cyst_size_mm", "Largest cyst (mm)", "mm"),
                ("us_volume_cc", "volume_cc", "Ovarian volume (cc)", "cc")):
            v = us.get(key, us.get(alt))
            ctx.features.append(FusionFeature(
                key=key, label=label,
                value=float(v) if v is not None else None,
                group="ultrasound", provenance=prov, quality=0.85,
                source="ultrasound exam", unit=unit))
        morph = us.get("morphology")
        ctx.features.append(FusionFeature(
            key="us_morphology", label="Morphology",
            value=None if morph in (None, UNKNOWN) else 1.0,
            group="ultrasound", provenance=prov, quality=0.85,
            source="ultrasound exam", unit=""))

    def add_adherence(self, ctx: FusionContext,
                      meds: Optional[List[dict]] = None) -> None:
        if not meds:
            return
        pct = [m.get("adherence_pct") for m in meds
               if m.get("adherence_pct") is not None]
        if pct:
            ctx.features.append(FusionFeature(
                key="medication_adherence", label="Medication adherence (%)",
                value=sum(pct) / len(pct), group="adherence",
                provenance=PATIENT_REPORTED, quality=0.6,
                source="care-plan log", unit="%"))

    # --------------------------------------------------------------- build
    def build(self, profile=None, cycle=None, symptoms=None, wearable=None,
              wearable_quality: float = 0.0, fingerprint=None, change=None,
              bp=None, glucose=None, ecg=None, ultrasound=None,
              adherence=None) -> FusionContext:
        ctx = FusionContext()
        self.add_clinical(ctx, profile, cycle, symptoms)
        self.add_wearable(ctx, wearable, wearable_quality)
        self.add_longitudinal(ctx, fingerprint, change)
        self.add_metabolic(ctx, bp, glucose)
        self.add_ecg(ctx, ecg)
        self.add_ultrasound(ctx, ultrasound)
        self.add_adherence(ctx, adherence)
        return ctx
