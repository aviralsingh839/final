"""Section 1 — PCOD / PMOS detection (CHRONO-PCOS V9.0).

Implements the **evidence-based Rotterdam criteria** as refined by the 2023
International Evidence-based Guideline and carried forward unchanged into the
2026 PMOS renaming.

Honesty contract
----------------
* There are exactly three criteria. Each resolves to PRESENT, ABSENT or
  **UNKNOWN**. UNKNOWN is never silently counted as absent.
* A criterion that *cannot be established from a smartwatch* is reported as
  such explicitly. The watch contributes supportive longitudinal context
  (cycle length, activity, sleep, autonomic load) and nothing more.
* "Meets 2 of 3" is a **screening result that still requires a clinician**,
  because other causes must be excluded first. This module never emits a
  diagnosis.
* Where a threshold deliberately does not exist (AMH), no number is invented.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from src.pcod import evidence as ev

# ---------------------------------------------------------------- statuses
PRESENT = "PRESENT"
ABSENT = "ABSENT"
UNKNOWN = "UNKNOWN"

# Why a criterion could not be evaluated — surfaced verbatim in the UI.
REASON_NOT_MEASURED = "Not measured — no value recorded."
REASON_NEEDS_LAB = "Requires a laboratory test; a wearable cannot measure this."
REASON_NEEDS_SCAN = "Requires a pelvic ultrasound; a wearable cannot image the ovary."
REASON_AMH_ADOLESCENT = "AMH should not be used for diagnosis in adolescents."
REASON_NO_THRESHOLD = "No universal threshold exists — cut-offs are assay-specific."


@dataclass
class PatientInputs:
    """Everything Section 1 needs. All optional; unknown stays unknown."""

    age_years: Optional[float] = None
    years_post_menarche: Optional[float] = None
    # Cycle
    usual_cycle_length_days: Optional[int] = None
    cycles_last_year: Optional[int] = None
    days_since_last_period: Optional[int] = None
    longest_cycle_days: Optional[int] = None
    luteal_progesterone_nmol_l: Optional[float] = None
    on_hormonal_contraception: Optional[bool] = None
    # Clinical hyperandrogenism
    hirsutism: Optional[bool] = None          # e.g. Ferriman–Gallwey ≥ 4-6
    ferriman_gallwey: Optional[int] = None
    acne: Optional[bool] = None
    female_pattern_hair_loss: Optional[bool] = None
    # Biochemical hyperandrogenism
    total_testosterone_nmol_l: Optional[float] = None
    free_testosterone_pmol_l: Optional[float] = None
    free_androgen_index: Optional[float] = None
    androstenedione_nmol_l: Optional[float] = None
    dheas_umol_l: Optional[float] = None
    testosterone_assay: str = "unknown"       # lc_ms | immunoassay | unknown
    # Criterion 3 — morphology
    fnpo: Optional[int] = None                # follicle number per ovary
    fnps: Optional[int] = None                # follicle number per cross-section
    ovarian_volume_ml: Optional[float] = None
    ultrasound_route: str = "unknown"         # transvaginal | transabdominal | unknown
    amh_pmol_l: Optional[float] = None
    amh_ng_ml: Optional[float] = None
    amh_assay: str = "unknown"
    amh_lab_cutoff: Optional[float] = None    # the laboratory's own cut-off
    # Exclusion of other causes
    tsh_checked: Optional[bool] = None
    prolactin_checked: Optional[bool] = None
    ohp17_checked: Optional[bool] = None
    other_causes_excluded: Optional[bool] = None

    def to_dict(self) -> dict:
        return self.__dict__.copy()

    @classmethod
    def from_dict(cls, d: dict) -> "PatientInputs":
        known = {k: v for k, v in (d or {}).items() if k in cls.__dataclass_fields__}
        return cls(**known)


@dataclass
class WatchContext:
    """Supportive-only longitudinal context from the smartwatch.

    Every field is explicitly *not* diagnostic evidence for any criterion.
    """

    resting_hr_bpm: Optional[float] = None
    rmssd_ms: Optional[float] = None
    steps_last_24h: Optional[int] = None
    sleep_hours_last_night: Optional[float] = None
    spo2_pct: Optional[float] = None
    wrist_temp_delta_c: Optional[float] = None
    data_sufficiency: float = 0.0          # 0..1, days of data / days needed
    days_of_data: int = 0
    device_name: str = ""

    def to_dict(self) -> dict:
        return self.__dict__.copy()

    @classmethod
    def from_dict(cls, d: dict) -> "WatchContext":
        known = {k: v for k, v in (d or {}).items() if k in cls.__dataclass_fields__}
        return cls(**known)


@dataclass
class CriterionResult:
    key: str
    label: str
    status: str                              # PRESENT | ABSENT | UNKNOWN
    detail: str
    evidence_ids: List[str] = field(default_factory=list)
    sources: List[str] = field(default_factory=list)   # provenance labels
    blockers: List[str] = field(default_factory=list)  # what would resolve UNKNOWN

    def as_dict(self) -> dict:
        return {
            "key": self.key, "label": self.label, "status": self.status,
            "detail": self.detail, "evidence_ids": self.evidence_ids,
            "sources": self.sources, "blockers": self.blockers,
        }


@dataclass
class DetectionResult:
    life_stage: str
    criteria: List[CriterionResult]
    present_count: int
    unknown_count: int
    verdict: str                             # see VERDICT_* below
    headline: str
    explanation: str
    exclusions_complete: bool
    exclusions_missing: List[str]
    ultrasound_needed: bool
    watch_note: str
    citations: List[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "life_stage": self.life_stage,
            "criteria": [c.as_dict() for c in self.criteria],
            "present_count": self.present_count,
            "unknown_count": self.unknown_count,
            "verdict": self.verdict,
            "headline": self.headline,
            "explanation": self.explanation,
            "exclusions_complete": self.exclusions_complete,
            "exclusions_missing": self.exclusions_missing,
            "ultrasound_needed": self.ultrasound_needed,
            "watch_note": self.watch_note,
            "citations": self.citations,
        }


VERDICT_MEETS = "MEETS_CRITERIA"
VERDICT_NOT_MET = "DOES_NOT_MEET"
VERDICT_UNKNOWN = "CANNOT_BE_DETERMINED"

VERDICT_HEADLINES = {
    VERDICT_MEETS: "Screening result: meets 2 of 3 criteria — a clinician must confirm and exclude other causes.",
    VERDICT_NOT_MET: "Screening result: fewer than 2 of 3 criteria are present.",
    VERDICT_UNKNOWN: "Not enough information to apply the criteria.",
}


# --------------------------------------------------------------------------
def _life_stage(inp: PatientInputs) -> str:
    """adolescent | adult | unknown — drives thresholds and the 2-of-3 rule."""
    if inp.years_post_menarche is not None:
        if inp.years_post_menarche < 8:
            return "adolescent"
        return "adult"
    if inp.age_years is not None:
        return "adolescent" if inp.age_years < 18 else "adult"
    return "unknown"


def _cycle_threshold(inp: PatientInputs) -> Optional[int]:
    """Upper bound for a normal cycle length, in days, for this life stage."""
    ypm = inp.years_post_menarche
    if ypm is not None:
        if ypm < 1:
            return None          # irregular cycles are normal in year 1
        if ypm < 3:
            return 45
        return 35
    if inp.age_years is not None:
        return 35 if inp.age_years >= 18 else 45
    return 35


def _criterion_ovulatory(inp: PatientInputs, stage: str) -> CriterionResult:
    blockers: List[str] = []
    signals: List[str] = []
    status = UNKNOWN
    threshold = _cycle_threshold(inp)

    if inp.on_hormonal_contraception is True:
        signals.append("Currently on hormonal contraception — cycle pattern cannot be interpreted.")

    if threshold is None:
        return CriterionResult(
            key="ovulatory", label="Ovulatory dysfunction", status=UNKNOWN,
            detail=("Within the first year after menarche, irregular cycles are a normal part of "
                    "pubertal transition, so this criterion cannot be applied yet."),
            evidence_ids=["dx.cycles.adolescent"], sources=[],
            blockers=["Reassess once at least 1 year has passed since menarche."],
        )

    irregular = None
    if inp.usual_cycle_length_days is not None:
        cl = inp.usual_cycle_length_days
        irregular = cl < 21 or cl > threshold
        signals.append(f"Usual cycle length {cl} days (irregular = <21 or >{threshold} days).")
    if inp.cycles_last_year is not None and inp.cycles_last_year < 8:
        irregular = True
        signals.append(f"{inp.cycles_last_year} cycles in the last year (fewer than 8).")
    if inp.days_since_last_period is not None and inp.days_since_last_period > 90:
        irregular = True
        signals.append(f"{inp.days_since_last_period} days since the last period (any single cycle >90 days is irregular).")
    elif inp.longest_cycle_days is not None and inp.longest_cycle_days > threshold:
        irregular = True
        signals.append(f"Longest recorded cycle {inp.longest_cycle_days} days (> {threshold}).")

    if inp.luteal_progesterone_nmol_l is not None:
        ovulated = inp.luteal_progesterone_nmol_l > 15.0
        signals.append(
            f"Luteal progesterone {inp.luteal_progesterone_nmol_l} nmol/L — "
            + ("consistent with recent ovulation." if ovulated else "not consistent with recent ovulation.")
        )
        if ovulated and irregular is None:
            irregular = False

    if inp.on_hormonal_contraception is True and irregular is None:
        status = UNKNOWN
        blockers.append("Record cycle history off hormonal contraception (or ≥3 months after stopping).")
    elif irregular is True:
        status = PRESENT
    elif irregular is False:
        status = ABSENT
    else:
        status = UNKNOWN
        blockers.append("Record usual cycle length, number of cycles in the last year, or days since the last period.")
        blockers.append("If cycles look regular but ovulation is uncertain, a luteal-phase progesterone can confirm it.")

    if not signals:
        signals.append("No cycle information recorded.")

    return CriterionResult(
        key="ovulatory", label="Ovulatory dysfunction", status=status,
        detail=" ".join(signals),
        evidence_ids=["dx.cycles.adult", "dx.progesterone", "dx.cycles.adolescent"],
        sources=["PATIENT-REPORTED", "CLINICALLY-ENTERED"],
        blockers=blockers,
    )


def _criterion_hyperandrogenism(inp: PatientInputs, stage: str) -> CriterionResult:
    blockers: List[str] = []
    clinical: List[str] = []
    biochemical: List[str] = []
    clinical_present: Optional[bool] = None
    biochem_present: Optional[bool] = None

    # ---- clinical
    if inp.hirsutism is True or (inp.ferriman_gallwey is not None and inp.ferriman_gallwey >= 4):
        clinical_present = True
        fg = f" (Ferriman–Gallwey {inp.ferriman_gallwey})" if inp.ferriman_gallwey is not None else ""
        clinical.append(f"Hirsutism present{fg} — alone this predicts biochemical hyperandrogenism.")
    elif inp.hirsutism is False:
        clinical.append("Hirsutism recorded as absent.")
    weak = []
    if inp.acne is True:
        weak.append("acne")
    if inp.female_pattern_hair_loss is True:
        weak.append("female-pattern hair loss")
    if weak:
        clinical.append("Present but weak predictors on their own: " + ", ".join(weak) + ".")
    if clinical_present is None and not weak:
        blockers.append("Record a clinical examination for hirsutism, acne and female-pattern hair loss.")

    # ---- biochemical
    tt = inp.total_testosterone_nmol_l
    ft = inp.free_testosterone_pmol_l
    fai = inp.free_androgen_index
    if tt is not None or ft is not None or fai is not None:
        # Interpretation depends on the laboratory's own reference range for the
        # assay used. We do NOT hard-code a cut-off: we report what we know.
        parts = []
        if tt is not None:
            parts.append(f"total testosterone {tt} nmol/L")
        if ft is not None:
            parts.append(f"free testosterone {ft} pmol/L")
        if fai is not None:
            parts.append(f"FAI {fai}")
        biochemical.append("Measured: " + ", ".join(parts) + ".")
        biochemical.append(
            "Compare against YOUR laboratory's reference range and method"
            + (" (LC-MS/MS recorded)." if inp.testosterone_assay == "lc_ms"
               else " — note: direct immunoassay results are unreliable at female concentrations, LC-MS/MS is preferred."
               if inp.testosterone_assay == "immunoassay"
               else " — record whether LC-MS/MS was used, as assay method changes interpretation.")
        )
        biochem_present = None      # present/absent depends on the lab range, not on us
        blockers.append("Enter whether the result was above the laboratory's reference range to resolve this criterion.")
    elif inp.androstenedione_nmol_l is not None or inp.dheas_umol_l is not None:
        biochemical.append(
            "Second-line androgens recorded (androstenedione/DHEAS) — these have limited accuracy "
            "and poor sensitivity; total and free testosterone are preferred."
        )
        biochem_present = None
        blockers.append("Measure total and free testosterone (LC-MS/MS) — the guideline-preferred test.")
    else:
        biochemical.append(REASON_NEEDS_LAB)
        blockers.append("Blood test: total and free testosterone (or calculated free androgen index), ideally by LC-MS/MS.")
        if inp.on_hormonal_contraception is True:
            blockers.append("Where feasible, test at least 3 months after stopping hormonal contraception.")

    # ---- combine
    if clinical_present is True:
        status = PRESENT
    elif biochem_present is True:
        status = PRESENT
    elif clinical_present is False and biochem_present is False:
        status = ABSENT
    else:
        status = UNKNOWN

    return CriterionResult(
        key="hyperandrogenism",
        label="Clinical or biochemical hyperandrogenism",
        status=status,
        detail=" ".join(clinical + biochemical),
        evidence_ids=[
            "dx.hirsutism.predicts", "dx.acne.alopecia.weak",
            "dx.biochem.testosterone", "dx.biochem.lcms", "dx.hormonal.contraception",
        ],
        sources=["PATIENT-REPORTED", "CLINICALLY-ENTERED", "MEASURED"],
        blockers=blockers,
    )


def _criterion_morphology(inp: PatientInputs, stage: str) -> CriterionResult:
    blockers: List[str] = []
    findings: List[str] = []
    status = UNKNOWN
    # AMH is excluded only where we actually know the person is an adolescent.
    # An unrecorded life stage must not silently block the adult route.
    amh_allowed = stage != "adolescent"
    if stage == "unknown":
        blockers.append(
            "Record age and years since your first period — the thresholds and the 2-of-3 "
            "rule differ between adolescents and adults."
        )

    # ---- ultrasound
    fnpo = inp.fnpo
    fnps = inp.fnps
    ov = inp.ovarian_volume_ml
    if fnpo is not None:
        if fnpo >= 20:
            findings.append(f"FNPO {fnpo} follicles — at or above the adult threshold of 20 in one ovary.")
            status = PRESENT
        else:
            findings.append(f"FNPO {fnpo} — below the threshold of 20.")
            status = ABSENT
    if fnps is not None:
        if fnps >= 10:
            findings.append(f"FNPS {fnps} — at or above the threshold of 10.")
            status = PRESENT
        elif status != PRESENT:
            findings.append(f"FNPS {fnps} — below the threshold of 10.")
            status = ABSENT if status == UNKNOWN else status
    if ov is not None:
        if ov >= 10.0:
            findings.append(f"Ovarian volume {ov} mL — at or above the threshold of 10 mL.")
            status = PRESENT
        elif status != PRESENT:
            findings.append(f"Ovarian volume {ov} mL — below the threshold of 10 mL.")
            status = ABSENT if status == UNKNOWN else status

    if inp.ultrasound_route == "transabdominal" and fnpo is not None:
        findings.append(
            "Transabdominal route: ovarian volume or FNPS should be reported preferentially, "
            "because whole-ovary follicle counting is difficult this way."
        )

    # ---- AMH
    amh_val = inp.amh_pmol_l if inp.amh_pmol_l is not None else inp.amh_ng_ml
    if amh_val is not None:
        if not amh_allowed:
            findings.append(REASON_AMH_ADOLESCENT + " Value recorded but not used.")
            blockers.append("Use ultrasound findings, not AMH, in adolescents (or wait until adulthood).")
        elif inp.amh_lab_cutoff is not None:
            if amh_val >= inp.amh_lab_cutoff:
                findings.append(f"AMH {amh_val} at or above this laboratory's cut-off of {inp.amh_lab_cutoff}.")
                status = PRESENT
            else:
                findings.append(f"AMH {amh_val} below this laboratory's cut-off of {inp.amh_lab_cutoff}.")
                status = ABSENT if status == UNKNOWN else status
        else:
            findings.append(
                f"AMH {amh_val} recorded, but " + REASON_NO_THRESHOLD +
                " Cut-offs differ substantially between the Gen II, picoAMH, Elecsys and Access platforms."
            )
            blockers.append("Enter the AMH cut-off printed on your own laboratory report — no universal value exists.")

    if not findings:
        findings.append(REASON_NEEDS_SCAN)
        blockers.append("Pelvic ultrasound (FNPO ≥ 20, or ovarian volume ≥ 10 mL / FNPS ≥ 10 on older equipment).")
        if amh_allowed:
            blockers.append("Or, in adults, serum AMH interpreted against the laboratory's own cut-off.")
        else:
            blockers.append("AMH is not recommended in adolescents, so ultrasound is the route here.")

    return CriterionResult(
        key="morphology",
        label="Polycystic ovarian morphology (ultrasound or AMH)",
        status=status,
        detail=" ".join(findings),
        evidence_ids=[
            "dx.pcom.fnpo", "dx.pcom.ov", "dx.amh.adults",
            "dx.amh.not.adolescents", "dx.ultrasound.not.needed",
        ],
        sources=["IMAGE-DERIVED", "CLINICALLY-ENTERED"],
        blockers=blockers,
    )


# --------------------------------------------------------------------------
def evaluate(inp: PatientInputs, watch: WatchContext | None = None) -> DetectionResult:
    """Apply the criteria. Returns a screening result, never a diagnosis."""
    stage = _life_stage(inp)
    criteria = [
        _criterion_ovulatory(inp, stage),
        _criterion_hyperandrogenism(inp, stage),
        _criterion_morphology(inp, stage),
    ]
    present = sum(1 for c in criteria if c.status == PRESENT)
    absent = sum(1 for c in criteria if c.status == ABSENT)
    unknown = sum(1 for c in criteria if c.status == UNKNOWN)

    # ---- exclusion of other causes
    missing: List[str] = []
    checks = [
        ("Thyroid function (TSH)", inp.tsh_checked),
        ("Prolactin", inp.prolactin_checked),
        ("17-OH progesterone (non-classic CAH)", inp.ohp17_checked),
    ]
    if inp.other_causes_excluded is True:
        exclusions_complete = True
    else:
        for label, done in checks:
            if done is not True:
                missing.append(label)
        exclusions_complete = not missing

    # ---- verdict
    adolescent_rule = stage == "adolescent"
    if adolescent_rule:
        # Both hyperandrogenism AND ovulatory dysfunction are required.
        h = next(c for c in criteria if c.key == "hyperandrogenism")
        o = next(c for c in criteria if c.key == "ovulatory")
        if h.status == PRESENT and o.status == PRESENT:
            verdict = VERDICT_MEETS
        elif h.status == ABSENT or o.status == ABSENT:
            verdict = VERDICT_NOT_MET
        else:
            verdict = VERDICT_UNKNOWN
    else:
        if present >= 2:
            verdict = VERDICT_MEETS
        elif present + unknown >= 2:
            verdict = VERDICT_UNKNOWN
        else:
            verdict = VERDICT_NOT_MET

    # ---- is ultrasound actually needed?
    o = next(c for c in criteria if c.key == "ovulatory")
    h = next(c for c in criteria if c.key == "hyperandrogenism")
    m = next(c for c in criteria if c.key == "morphology")
    if not adolescent_rule and o.status == PRESENT and h.status == PRESENT:
        ultrasound_needed = False
    else:
        ultrasound_needed = m.status == UNKNOWN

    # ---- explanation
    bits: List[str] = []
    bits.append(
        f"Scored against the {'adolescent' if adolescent_rule else 'adult'} rule: "
        + ("BOTH hyperandrogenism and ovulatory dysfunction are required."
           if adolescent_rule else "at least 2 of the 3 criteria are required.")
    )
    bits.append(f"{present} present, {absent} absent, {unknown} unknown.")
    if verdict == VERDICT_MEETS and not exclusions_complete:
        bits.append(
            "Before this can be called PMOS/PCOS, other causes must still be excluded "
            + ("; ".join(missing) + "." if missing else ".")
        )
    if verdict == VERDICT_MEETS and exclusions_complete:
        bits.append("Other causes recorded as excluded — a clinician still confirms the diagnosis.")
    if not ultrasound_needed and o.status == PRESENT and h.status == PRESENT and not adolescent_rule:
        bits.append("With both irregular cycles and hyperandrogenism present, ultrasound is not necessary for diagnosis.")

    watch_note = _watch_note(watch)

    ids: List[str] = []
    for c in criteria:
        ids += c.evidence_ids
    ids += ["dx.rotterdam.2of3", "dx.adolescent.both", "dx.exclude.others", "cx.wearable.scope"]

    return DetectionResult(
        life_stage=stage,
        criteria=criteria,
        present_count=present,
        unknown_count=unknown,
        verdict=verdict,
        headline=VERDICT_HEADLINES[verdict],
        explanation=" ".join(bits),
        exclusions_complete=exclusions_complete,
        exclusions_missing=missing,
        ultrasound_needed=ultrasound_needed,
        watch_note=watch_note,
        citations=ev.citations_for(ids),
    )


def _watch_note(watch: WatchContext | None) -> str:
    if watch is None or not watch.device_name:
        return ("No smartwatch connected. Watch data is supportive longitudinal context only — "
                "it cannot establish or exclude any of the three criteria.")
    parts = [f"Smartwatch: {watch.device_name}."]
    if watch.days_of_data:
        parts.append(f"{watch.days_of_data} day(s) of data ({watch.data_sufficiency * 100:.0f}% of the 14-day window).")
    measured = []
    if watch.resting_hr_bpm is not None:
        measured.append(f"resting HR {watch.resting_hr_bpm:.0f} bpm")
    if watch.rmssd_ms is not None:
        measured.append(f"HRV (RMSSD) {watch.rmssd_ms:.0f} ms")
    if watch.steps_last_24h is not None:
        measured.append(f"{watch.steps_last_24h} steps/24 h")
    if watch.sleep_hours_last_night is not None:
        measured.append(f"sleep {watch.sleep_hours_last_night:.1f} h")
    if watch.spo2_pct is not None:
        measured.append(f"SpO₂ {watch.spo2_pct:.0f}% (wellness estimate, not medical grade)")
    if measured:
        parts.append("Latest: " + ", ".join(measured) + ".")
    parts.append("None of these measure hormones, glucose, lipids or ovarian morphology, "
                 "so watch data cannot establish or exclude any of the three criteria.")
    return " ".join(parts)
