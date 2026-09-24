"""Section 2 — PCOD / PMOS complication detection (CHRONO-PCOS V9.0).

This is a **screening-status engine**, not a risk predictor. For each
complication domain it answers one question:

    "According to the current guideline, is an assessment due, overdue,
     up to date, or not indicated — and what would resolve it?"

It deliberately does NOT output a single "your complication risk is 42%"
number. Fabricating one would be unsupportable from wearable data plus a few
manual entries. Instead each domain reports:

    status · why · what to do · what the guideline says · citation

Status vocabulary
-----------------
ACTION_NEEDED  a signal is present that warrants clinical assessment now
DUE            the guideline interval has elapsed
OVERDUE        well past the interval
UP_TO_DATE     assessed within the interval
UNKNOWN        never assessed — no value recorded, never assumed normal
NOT_INDICATED  the guideline explicitly advises against routine screening
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Dict, List, Optional

from src.pcod import evidence as ev

ACTION_NEEDED = "ACTION_NEEDED"
DUE = "DUE"
OVERDUE = "OVERDUE"
UP_TO_DATE = "UP_TO_DATE"
UNKNOWN = "UNKNOWN"
NOT_INDICATED = "NOT_INDICATED"

STATUS_LABELS = {
    ACTION_NEEDED: "Assessment needed now",
    DUE: "Screening due",
    OVERDUE: "Screening overdue",
    UP_TO_DATE: "Up to date",
    UNKNOWN: "Not assessed yet",
    NOT_INDICATED: "Routine screening not recommended",
}

# Screening intervals in days, taken from the cited recommendations.
GLUCOSE_INTERVAL_DAYS = 365 * 3      # 1-3 years; 1 year if risk factors present
GLUCOSE_INTERVAL_HIGH_RISK_DAYS = 365
LIPID_INTERVAL_DAYS = 365 * 2
BP_INTERVAL_DAYS = 365               # at each visit, minimum 6-12 months
WEIGHT_INTERVAL_DAYS = 365
MENTAL_HEALTH_INTERVAL_DAYS = 365


def _parse_date(value) -> Optional[date]:
    if value in (None, "", "None"):
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _days_since(value, today: Optional[date] = None) -> Optional[int]:
    d = _parse_date(value)
    if d is None:
        return None
    return (today or date.today() - d).days if False else ((today or date.today()) - d).days


@dataclass
class ClinicalInputs:
    """Manual / clinical entries for Section 2. Everything optional."""

    age_years: Optional[float] = None
    bmi: Optional[float] = None
    waist_cm: Optional[float] = None
    systolic_bp: Optional[float] = None
    diastolic_bp: Optional[float] = None
    asian_ethnicity: Optional[bool] = None      # lowers the BMI action threshold to 23

    # Metabolic labs
    fasting_glucose_mg_dl: Optional[float] = None
    ogtt_2h_mg_dl: Optional[float] = None
    hba1c_pct: Optional[float] = None
    total_cholesterol_mg_dl: Optional[float] = None
    ldl_mg_dl: Optional[float] = None
    hdl_mg_dl: Optional[float] = None
    triglycerides_mg_dl: Optional[float] = None
    alt_u_l: Optional[float] = None

    # History
    family_history_t2dm: Optional[bool] = None
    family_history_premature_cvd: Optional[bool] = None
    personal_history_gestational_diabetes: Optional[bool] = None
    acanthosis_nigricans: Optional[bool] = None
    current_smoker: Optional[bool] = None
    moderate_activity_min_per_week: Optional[float] = None
    pregnant: Optional[bool] = None
    gestation_weeks: Optional[float] = None
    trying_to_conceive: Optional[bool] = None
    months_trying_to_conceive: Optional[float] = None
    amenorrhoea_days: Optional[int] = None
    abnormal_uterine_bleeding: Optional[bool] = None

    # Symptom screens
    snoring: Optional[bool] = None
    witnessed_apnoea: Optional[bool] = None
    daytime_somnolence: Optional[bool] = None
    phq9_score: Optional[int] = None
    gad7_score: Optional[int] = None

    # When things were last checked
    last_glucose_test_date: Optional[str] = None
    last_lipid_test_date: Optional[str] = None
    last_bp_date: Optional[str] = None
    last_weight_date: Optional[str] = None
    last_mental_health_screen_date: Optional[str] = None
    last_liver_test_date: Optional[str] = None

    def to_dict(self) -> dict:
        return self.__dict__.copy()

    @classmethod
    def from_dict(cls, d: dict) -> "ClinicalInputs":
        known = {k: v for k, v in (d or {}).items() if k in cls.__dataclass_fields__}
        return cls(**known)


@dataclass
class DomainResult:
    key: str
    label: str
    status: str
    why: str
    action: str
    signals: List[str] = field(default_factory=list)
    evidence_ids: List[str] = field(default_factory=list)
    interval_note: str = ""
    watch_support: str = ""

    def as_dict(self) -> dict:
        return {
            "key": self.key, "label": self.label, "status": self.status,
            "status_label": STATUS_LABELS.get(self.status, self.status),
            "why": self.why, "action": self.action, "signals": self.signals,
            "evidence_ids": self.evidence_ids, "interval_note": self.interval_note,
            "watch_support": self.watch_support,
            "citations": ev.citations_for(self.evidence_ids),
        }


@dataclass
class ComplicationResult:
    domains: List[DomainResult]
    counts: Dict[str, int]
    watch_note: str
    disclaimer: str

    def as_dict(self) -> dict:
        return {
            "domains": [d.as_dict() for d in self.domains],
            "counts": self.counts,
            "watch_note": self.watch_note,
            "disclaimer": self.disclaimer,
        }


# --------------------------------------------------------------------------
def _bmi_threshold(c: ClinicalInputs) -> float:
    return 23.0 if c.asian_ethnicity is True else 25.0


def _glucose_risk_factor_count(c: ClinicalInputs) -> tuple[int, List[str]]:
    n, reasons = 0, []
    thr = _bmi_threshold(c)
    if c.bmi is not None and c.bmi >= thr:
        n += 1
        reasons.append(f"BMI {c.bmi:.1f} (action threshold {thr:g} for your population group)")
    if c.waist_cm is not None and c.waist_cm >= 80.0:
        n += 1
        reasons.append(f"waist {c.waist_cm:.0f} cm (central adiposity)")
    if c.family_history_t2dm is True:
        n += 1
        reasons.append("family history of type 2 diabetes")
    if c.personal_history_gestational_diabetes is True:
        n += 1
        reasons.append("personal history of gestational diabetes")
    if c.acanthosis_nigricans is True:
        n += 1
        reasons.append("acanthosis nigricans")
    if c.age_years is not None and c.age_years > 40:
        n += 1
        reasons.append(f"age {c.age_years:.0f}")
    if c.current_smoker is True:
        n += 1
        reasons.append("current smoking")
    if c.systolic_bp is not None and c.systolic_bp >= 130:
        n += 1
        reasons.append(f"systolic BP {c.systolic_bp:.0f} mmHg")
    if c.moderate_activity_min_per_week is not None and c.moderate_activity_min_per_week < 150:
        n += 1
        reasons.append(f"{c.moderate_activity_min_per_week:.0f} min/week activity (target 150–300)")
    return n, reasons


def _interval_status(last_date, interval_days: int, today: date) -> tuple[str, Optional[int]]:
    """Return (status, days_since)."""
    ds = _days_since(last_date, today)
    if ds is None:
        return UNKNOWN, None
    if ds <= interval_days:
        return UP_TO_DATE, ds
    if ds <= interval_days * 1.5:
        return DUE, ds
    return OVERDUE, ds


# --------------------------------------------------------------------------
# Domain evaluators
# --------------------------------------------------------------------------
def _domain_glucose(c: ClinicalInputs, today: date) -> DomainResult:
    rf_n, rf_reasons = _glucose_risk_factor_count(c)
    interval = GLUCOSE_INTERVAL_HIGH_RISK_DAYS if rf_n > 0 else GLUCOSE_INTERVAL_DAYS
    status, ds = _interval_status(c.last_glucose_test_date, interval, today)
    signals: List[str] = []
    if rf_reasons:
        signals.append("Risk factors: " + "; ".join(rf_reasons) + ".")
    if rf_n > 0:
        signals.append("Higher-risk profile — reassess annually rather than every 3 years.")

    abnormal = []
    if c.fasting_glucose_mg_dl is not None:
        v = c.fasting_glucose_mg_dl
        if v >= 126:
            abnormal.append(f"fasting glucose {v:.0f} mg/dL (≥126 = diabetes range)")
        elif v >= 100:
            abnormal.append(f"fasting glucose {v:.0f} mg/dL (100–125 = impaired fasting glucose)")
        else:
            signals.append(f"Fasting glucose {v:.0f} mg/dL.")
    if c.ogtt_2h_mg_dl is not None:
        v = c.ogtt_2h_mg_dl
        if v >= 200:
            abnormal.append(f"2-hour OGTT {v:.0f} mg/dL (≥200 = diabetes range)")
        elif v >= 140:
            abnormal.append(f"2-hour OGTT {v:.0f} mg/dL (140–199 = impaired glucose tolerance)")
        else:
            signals.append(f"2-hour OGTT {v:.0f} mg/dL.")
    if c.hba1c_pct is not None:
        v = c.hba1c_pct
        if v >= 6.5:
            abnormal.append(f"HbA1c {v:.1f}% (≥6.5% = diabetes range)")
        elif v >= 5.7:
            abnormal.append(f"HbA1c {v:.1f}% (5.7–6.4% = prediabetes range)")
        else:
            signals.append(f"HbA1c {v:.1f}%.")

    if abnormal:
        status = ACTION_NEEDED
        signals = abnormal + signals

    if ds is not None:
        interval_note = f"Last tested {ds} days ago; guideline interval {interval // 365} year(s)."
    else:
        interval_note = "No previous test date recorded."

    return DomainResult(
        key="glucose",
        label="Impaired glucose tolerance and type 2 diabetes",
        status=status,
        why=("Glycaemic status should be assessed at diagnosis in ALL people with PMOS/PCOS "
             "regardless of age and BMI, because the risk of impaired fasting glucose, impaired "
             "glucose tolerance and type 2 diabetes is increased."),
        action=("75 g oral glucose tolerance test (preferred). HbA1c or fasting glucose are "
                "alternatives where OGTT is unavailable or declined, recognising they detect "
                "less dysglycaemia in this population."),
        signals=signals,
        evidence_ids=["cx.glucose.all", "cx.glucose.interval", "cx.glucose.ogtt", "cx.glucose.riskfactors"],
        interval_note=interval_note,
        watch_support=("Wearables cannot measure glucose. Activity and sleep patterns are "
                       "supportive context only."),
    )


def _domain_lipids(c: ClinicalInputs, today: date) -> DomainResult:
    status, ds = _interval_status(c.last_lipid_test_date, LIPID_INTERVAL_DAYS, today)
    signals: List[str] = []
    abnormal = []
    if c.ldl_mg_dl is not None:
        v = c.ldl_mg_dl
        if v >= 160:
            abnormal.append(f"LDL-C {v:.0f} mg/dL (high)")
        else:
            signals.append(f"LDL-C {v:.0f} mg/dL.")
    if c.hdl_mg_dl is not None:
        v = c.hdl_mg_dl
        if v < 50:
            abnormal.append(f"HDL-C {v:.0f} mg/dL (low for women)")
        else:
            signals.append(f"HDL-C {v:.0f} mg/dL.")
    if c.triglycerides_mg_dl is not None:
        v = c.triglycerides_mg_dl
        if v >= 150:
            abnormal.append(f"triglycerides {v:.0f} mg/dL (≥150)")
        else:
            signals.append(f"triglycerides {v:.0f} mg/dL.")
    if c.total_cholesterol_mg_dl is not None:
        v = c.total_cholesterol_mg_dl
        if v >= 200:
            abnormal.append(f"total cholesterol {v:.0f} mg/dL (≥200)")
        else:
            signals.append(f"total cholesterol {v:.0f} mg/dL.")
    if abnormal:
        status = ACTION_NEEDED
        signals = abnormal + signals
    if not signals and not abnormal:
        signals.append("No lipid values recorded.")

    return DomainResult(
        key="lipids",
        label="Dyslipidaemia",
        status=status,
        why=("All people with PMOS/PCOS, regardless of age and BMI, should have a lipid profile "
             "at diagnosis; frequency thereafter depends on the result and on global "
             "cardiovascular risk."),
        action="Fasting lipid profile: total cholesterol, LDL-C, HDL-C, triglycerides.",
        signals=signals,
        evidence_ids=["cx.lipids.all"],
        interval_note=("Last tested " + f"{ds} days ago; review roughly every 2 years when normal."
                       if ds is not None else "No previous test date recorded."),
        watch_support="Not measurable by a wearable.",
    )


def _domain_blood_pressure(c: ClinicalInputs, today: date) -> DomainResult:
    status, ds = _interval_status(c.last_bp_date, BP_INTERVAL_DAYS, today)
    signals: List[str] = []
    if c.systolic_bp is not None and c.diastolic_bp is not None:
        s, d = c.systolic_bp, c.diastolic_bp
        if s >= 140 or d >= 90:
            status = ACTION_NEEDED
            signals.append(f"Blood pressure {s:.0f}/{d:.0f} mmHg — at or above 140/90.")
        elif s >= 130 or d >= 85:
            signals.append(f"Blood pressure {s:.0f}/{d:.0f} mmHg — elevated (130–139/85–89); recheck and monitor.")
        else:
            signals.append(f"Blood pressure {s:.0f}/{d:.0f} mmHg — within the normal range.")
    else:
        signals.append("No blood-pressure values recorded.")

    return DomainResult(
        key="blood_pressure",
        label="Hypertension",
        status=status,
        why=("Blood pressure should be measured at initial diagnosis and at each visit, with a "
             "minimum review interval of 6–12 months, and during oral contraceptive therapy."),
        action="Measure blood pressure; if persistently ≥140/90, clinical assessment and management.",
        signals=signals,
        evidence_ids=["cx.bp.each.visit", "cx.cvd.riskfactors"],
        interval_note=("Last measured " + f"{ds} days ago; review at least every 6–12 months."
                       if ds is not None else "No previous measurement date recorded."),
        watch_support=("Some watches estimate BP, but they require cuff calibration and are not a "
                       "substitute for a measured reading."),
    )


def _domain_weight(c: ClinicalInputs, today: date) -> DomainResult:
    status, ds = _interval_status(c.last_weight_date, WEIGHT_INTERVAL_DAYS, today)
    thr = _bmi_threshold(c)
    signals: List[str] = []
    if c.bmi is not None:
        if c.bmi >= thr:
            signals.append(f"BMI {c.bmi:.1f} — at or above the {thr:g} action threshold for your population group.")
            if status in (UNKNOWN, UP_TO_DATE):
                status = DUE
        else:
            signals.append(f"BMI {c.bmi:.1f} — below the {thr:g} action threshold.")
    if c.waist_cm is not None:
        signals.append(f"Waist circumference {c.waist_cm:.0f} cm.")
    if c.moderate_activity_min_per_week is not None:
        m = c.moderate_activity_min_per_week
        signals.append(
            f"Moderate activity {m:.0f} min/week — target 150–300 min/week for health, "
            "250 min/week if weight loss is the goal."
        )
    if not signals:
        signals.append("No weight, waist or activity values recorded.")

    return DomainResult(
        key="weight",
        label="Overweight, obesity and central adiposity",
        status=status,
        why=("Weight, BMI and waist circumference should be assessed at each visit, with a minimum "
             "review interval of 6–12 months."),
        action=(f"Lifestyle first: 150–300 min/week moderate (or 75–150 min/week vigorous) activity, "
                f"plus muscle-strengthening. If BMI ≥ {thr:g}, a 5% weight loss in 6 months is a common target."),
        signals=signals,
        evidence_ids=["cx.weight.each.visit", "cx.glucose.riskfactors"],
        interval_note=("Last recorded " + f"{ds} days ago; review every 6–12 months."
                       if ds is not None else "No previous measurement date recorded."),
        watch_support=("Step count, active minutes and resting HR are genuinely useful here — this "
                       "is the domain a wearable supports best."),
    )


def _domain_cvd(c: ClinicalInputs, today: date) -> DomainResult:
    factors: List[str] = []
    thr = _bmi_threshold(c)
    if c.bmi is not None and c.bmi >= thr:
        factors.append("overweight/obesity")
    if c.current_smoker is True:
        factors.append("current smoking")
    if c.systolic_bp is not None and c.systolic_bp >= 130:
        factors.append("elevated blood pressure")
    if c.triglycerides_mg_dl is not None and c.triglycerides_mg_dl >= 150:
        factors.append("raised triglycerides")
    if c.hdl_mg_dl is not None and c.hdl_mg_dl < 50:
        factors.append("low HDL-C")
    if c.family_history_premature_cvd is True:
        factors.append("family history of premature cardiovascular disease")
    if c.family_history_t2dm is True:
        factors.append("family history of type 2 diabetes")
    if c.moderate_activity_min_per_week is not None and c.moderate_activity_min_per_week < 150:
        factors.append("less than 150 min/week activity")
    if c.hba1c_pct is not None and c.hba1c_pct >= 5.7:
        factors.append("dysglycaemia")
    if c.fasting_glucose_mg_dl is not None and c.fasting_glucose_mg_dl >= 100:
        factors.append("impaired fasting glucose")

    # A risk-factor review is only meaningfully "done" if enough of the inputs
    # that make it up have actually been recorded. Otherwise it is UNKNOWN,
    # never silently "no risk factors".
    recorded = sum(1 for v in (
        c.bmi, c.systolic_bp, c.ldl_mg_dl, c.hdl_mg_dl, c.triglycerides_mg_dl,
        c.current_smoker, c.moderate_activity_min_per_week,
        c.family_history_t2dm, c.family_history_premature_cvd,
    ) if v is not None)
    assessed = recorded >= 4
    if not assessed:
        status = UNKNOWN
    elif len(factors) >= 3:
        status = ACTION_NEEDED
    elif factors:
        status = DUE
    else:
        status = UP_TO_DATE
    return DomainResult(
        key="cardiovascular",
        label="Cardiovascular risk",
        status=status,
        why=("All people with PMOS/PCOS should have individual cardiovascular risk factors assessed "
             "at initial diagnosis. Conventional risk calculators have NOT been validated in this "
             "population, so they must not be read as a definitive individual risk figure."),
        action=("Ask your clinician for a formal risk-factor review at diagnosis and periodically "
                "afterwards. Address smoking, blood pressure, lipids, weight and activity."),
        signals=([f"{len(factors)} risk factor(s) present: " + ", ".join(factors) + "."]
                 if factors else
                 ([f"{recorded} risk-factor inputs recorded and none are raised — review complete "
                   "on the information entered."] if assessed
                  else [f"Only {recorded} of 9 risk-factor inputs recorded — not enough to call this reviewed."])),
        evidence_ids=["cx.cvd.riskfactors", "cx.cvd.calculators", "cx.lipids.all"],
        interval_note="Review at initial diagnosis and periodically thereafter.",
        watch_support=("Resting HR, HRV and activity trends are supportive context. They are not a "
                       "validated cardiovascular risk score."),
    )


def _domain_osa(c: ClinicalInputs, today: date) -> DomainResult:
    symptoms: List[str] = []
    if c.snoring is True:
        symptoms.append("snoring")
    if c.witnessed_apnoea is True:
        symptoms.append("witnessed pauses in breathing")
    if c.daytime_somnolence is True:
        symptoms.append("daytime sleepiness/fatigue")

    if symptoms:
        status = ACTION_NEEDED
    elif c.snoring is False and c.daytime_somnolence is False and c.witnessed_apnoea is False:
        status = UP_TO_DATE
    else:
        status = UNKNOWN

    return DomainResult(
        key="osa",
        label="Obstructive sleep apnoea",
        status=status,
        why=("Prevalence is roughly four-fold higher in this population. Screening is by SYMPTOM "
             "assessment only; routine screening of people without symptoms is not recommended."),
        action=("If snoring, witnessed apnoeas or daytime somnolence are present, ask about referral "
                "for sleep assessment. Lifestyle modification alongside."),
        signals=([f"Symptoms reported: {', '.join(symptoms)}."]
                 if symptoms else
                 (["Symptoms asked and none reported."] if status == UP_TO_DATE
                  else ["Symptom questions not answered yet."])),
        evidence_ids=["cx.osa.symptoms", "cx.spo2.caveat"],
        interval_note="Annual symptomatic review.",
        watch_support=("Wrist SpO₂ and sleep-staging on consumer wearables are wellness estimates. "
                       "They cannot rule sleep apnoea in or out."),
    )


def _domain_mental_health(c: ClinicalInputs, today: date) -> DomainResult:
    status, ds = _interval_status(c.last_mental_health_screen_date, MENTAL_HEALTH_INTERVAL_DAYS, today)
    signals: List[str] = []
    if c.phq9_score is not None:
        v = c.phq9_score
        band = ("minimal" if v < 5 else "mild" if v < 10 else "moderate" if v < 15
                else "moderately severe" if v < 20 else "severe")
        signals.append(f"PHQ-9 {v} ({band}).")
        if v >= 10:
            status = ACTION_NEEDED
    else:
        signals.append("No PHQ-9 score recorded.")
    if c.gad7_score is not None:
        v = c.gad7_score
        band = ("minimal" if v < 5 else "mild" if v < 10 else "moderate" if v < 15 else "severe")
        signals.append(f"GAD-7 {v} ({band}).")
        if v >= 10:
            status = ACTION_NEEDED
    else:
        signals.append("No GAD-7 score recorded.")

    return DomainResult(
        key="mental_health",
        label="Depression and anxiety",
        status=status,
        why=("Depressive and anxiety symptoms are significantly increased in this population "
             "(odds ratios around 2.6 and 2.7 in adults) and should be screened for in ALL people "
             "with PMOS/PCOS using regionally validated tools."),
        action=("Complete a validated tool such as PHQ-9 and GAD-7, then discuss the result — "
                "psychological assessment and therapy as indicated."),
        signals=signals,
        evidence_ids=["cx.mental.all"],
        interval_note=("Last screened " + f"{ds} days ago; re-screen at least annually."
                       if ds is not None else "No previous screen date recorded."),
        watch_support=("Sleep disruption, low HRV and low activity can be conversation starters. "
                       "They are not a depression or anxiety screen."),
    )


def _domain_liver(c: ClinicalInputs, today: date) -> DomainResult:
    signals: List[str] = []
    metabolic = (
        (c.bmi is not None and c.bmi >= _bmi_threshold(c))
        or (c.hba1c_pct is not None and c.hba1c_pct >= 5.7)
        or (c.triglycerides_mg_dl is not None and c.triglycerides_mg_dl >= 150)
    )
    if c.alt_u_l is not None:
        signals.append(f"ALT {c.alt_u_l:.0f} U/L recorded.")
    if metabolic:
        signals.append(
            "Metabolic risk features present (adiposity / dysglycaemia / raised triglycerides) — "
            "guidance is to be AWARE of NAFLD here, but still not to screen routinely."
        )
    else:
        signals.append("No metabolic risk features recorded.")
    # Stays NOT_INDICATED either way: current guidance advises against routine
    # screening regardless of risk profile. That is a real recommendation, not
    # a gap in this app.
    status = NOT_INDICATED
    return DomainResult(
        key="liver",
        label="Non-alcoholic fatty liver disease (NAFLD)",
        status=status,
        why=("Be aware of increased NAFLD risk in people with metabolic syndrome or type 2 diabetes, "
             "but routine screening is NOT currently recommended and routine review is not "
             "recommended."),
        action=("No routine screening. Lifestyle modification, and hepatology review if NAFLD is "
                "found incidentally."),
        signals=signals or ["No liver-related entries recorded."],
        evidence_ids=["cx.nafld.awareness"],
        interval_note="Routine review is not recommended by current guidance.",
        watch_support="Not measurable by a wearable.",
    )


def _domain_endometrial(c: ClinicalInputs, today: date) -> DomainResult:
    signals: List[str] = []
    status = NOT_INDICATED
    if c.abnormal_uterine_bleeding is True:
        status = ACTION_NEEDED
        signals.append("Unexpected or abnormal uterine bleeding reported — this should be assessed.")
    if c.amenorrhoea_days is not None and c.amenorrhoea_days > 90:
        status = ACTION_NEEDED
        signals.append(f"{c.amenorrhoea_days} days without a period (prolonged amenorrhoea > 90 days).")
    if status == NOT_INDICATED:
        signals.append("No bleeding concerns recorded.")

    return DomainResult(
        key="endometrial",
        label="Endometrial hyperplasia and cancer",
        status=status,
        why=("Premenopausal risk is increased while absolute risk remains low. Routine ultrasound "
             "screening for endometrial thickness in asymptomatic women is NOT recommended."),
        action=("Report any unexpected bleeding or spotting promptly. Prolonged amenorrhoea "
                "(>90 days) warrants clinical assessment, where inducing a withdrawal bleed every "
                "3–4 months is one option used in practice."),
        signals=signals,
        evidence_ids=["cx.endometrial.bleeding"],
        interval_note="No routine screening; assess on symptoms.",
        watch_support=("Cycle-length tracking from the watch or app can help you spot prolonged "
                       "amenorrhoea earlier — that is its only role here."),
    )


def _domain_reproductive(c: ClinicalInputs, today: date) -> DomainResult:
    signals: List[str] = []
    status = UNKNOWN
    if c.pregnant is True:
        status = ACTION_NEEDED
        gw = f" at {c.gestation_weeks:.0f} weeks" if c.gestation_weeks else ""
        signals.append(f"Currently pregnant{gw} — PMOS/PCOS is regarded as a high-risk pregnancy condition.")
        if c.gestation_weeks is not None and 24 <= c.gestation_weeks <= 28:
            signals.append("24–28 weeks is the window for gestational diabetes screening.")
    elif c.trying_to_conceive is True:
        months = c.months_trying_to_conceive
        signals.append(
            f"Trying to conceive"
            + (f" for {months:.0f} months." if months is not None else ".")
        )
        status = ACTION_NEEDED if (months is not None and months >= 12) else DUE
        if c.bmi is not None and c.bmi >= _bmi_threshold(c):
            signals.append(
                "Excess weight adversely affects clinical pregnancy, miscarriage and live-birth "
                "rates, so weight support matters before and during fertility treatment."
            )
    else:
        status = NOT_INDICATED
        signals.append(
            "Not currently pregnant and not recorded as trying to conceive, so no fertility or "
            "pregnancy assessment is indicated right now."
        )
        if c.amenorrhoea_days is not None and c.amenorrhoea_days > 90:
            signals.append(
                f"Note: {c.amenorrhoea_days} days without a period is recorded, which also shows up "
                "under the endometrial item above."
            )

    return DomainResult(
        key="reproductive",
        label="Fertility and pregnancy",
        status=status,
        why=("Chronic anovulation is the main cause of infertility in this condition, and PMOS/PCOS "
             "should be considered a high-risk condition in pregnancy — gestational diabetes, "
             "hypertensive disorders of pregnancy and preterm birth risk are increased."),
        action=("If trying to conceive without success for 12 months or more (or 6 months if over 35), "
                "ask for a fertility referral. If pregnant, ensure GDM screening at 24–28 weeks and "
                "enhanced monitoring."),
        signals=signals,
        evidence_ids=["cx.pregnancy.highrisk", "cx.infertility.anovulation"],
        interval_note="Assess at diagnosis and at each life-stage change.",
        watch_support=("Cycle-length and temperature trends can support cycle awareness. They do not "
                       "confirm ovulation — that needs a luteal progesterone test."),
    )


# --------------------------------------------------------------------------
def evaluate(c: ClinicalInputs, today: Optional[date] = None,
             watch_device: str = "") -> ComplicationResult:
    today = today or date.today()
    builders = [
        _domain_glucose,
        _domain_lipids,
        _domain_blood_pressure,
        _domain_weight,
        _domain_cvd,
        _domain_osa,
        _domain_mental_health,
        _domain_liver,
        _domain_endometrial,
        _domain_reproductive,
    ]
    domains = [b(c, today) for b in builders]
    counts: Dict[str, int] = {}
    for d in domains:
        counts[d.status] = counts.get(d.status, 0) + 1

    watch_note = (
        f"Smartwatch connected: {watch_device}. " if watch_device else "No smartwatch connected. "
    ) + ("Watch data supports the activity, sleep and cycle-awareness domains only. It cannot "
         "measure glucose, lipids, blood pressure, liver tests or mood, and it never replaces them.")

    disclaimer = (
        "This is a screening checklist built from published guideline recommendations, not a "
        "diagnosis and not an individual risk score. Every 'assessment needed' item is a prompt to "
        "speak with a clinician, who decides what to test and when. Nothing here starts, stops or "
        "changes treatment."
    )
    return ComplicationResult(domains=domains, counts=counts,
                              watch_note=watch_note, disclaimer=disclaimer)


# Ordering used by the UI when surfacing "what to do first".
STATUS_PRIORITY = [ACTION_NEEDED, OVERDUE, DUE, UNKNOWN, UP_TO_DATE, NOT_INDICATED]
