"""Latest clinical evidence registry (CHRONO-PCOS V9.0).

This module is the project's **"latest data"** layer. It is a structured,
offline, fully cited registry of the recommendations the two clinical sections
(PCOD detection and PCOD complication detection) implement.

Design rules
------------
1. Every fact carries a `source` with a real, resolvable URL and a year.
2. `last_verified` records when the project last checked the statement.
3. Guideline grades are preserved exactly as published:
       EBR = evidence-based recommendation
       CR  = clinical consensus recommendation
       PP  = practice point
4. Nothing is paraphrased into a stronger claim than the source makes.
5. Where evidence is absent (e.g. no AMH threshold), the entry says so
   explicitly rather than inventing a number.

COMPANION-ONLY: this is a reference layer for education and clinical
conversation. It does not diagnose and does not replace a clinician.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

# --------------------------------------------------------------------------
# Sources
# --------------------------------------------------------------------------
MONASH_2023_SUMMARY = "https://www.monash.edu/__data/assets/pdf_file/0003/3371133/PCOS-Guideline-Summary-2023.pdf"
MONASH_2023_FULL = "https://www.monash.edu/__data/assets/pdf_file/0003/3379521/Evidence-Based-Guidelines-2023.pdf"
ASRM_2023 = (
    "https://www.asrm.org/practice-guidance/practice-committee-documents/"
    "recommendations-from-the-2023-international-evidence-based-guideline-for-"
    "the-assessment-and-management-of-polycystic-ovary-syndrome/"
)
LANCET_2026_PMOS = "https://www.thelancet.com/journals/lancet/article/PIIS0140-6736(26)00717-8/fulltext"
ASRM_2026_PMOS = (
    "https://www.asrm.org/news-and-events/asrm-news/latest-news/"
    "may-27-2026-pcos-is-now-pmos-understanding-the-name-change/"
)
WHO_FACTSHEET = "https://www.who.int/news-room/fact-sheets/detail/polycystic-ovary-syndrome"
RCOG_GTG33 = "https://www.rcog.org.uk/media/qmtlp2b0/gtg_33.pdf"
AAFP_2023 = "https://www.aafp.org/afp/2023/0300/polycystic-ovary-syndrome"
ALLEN_2022 = "https://onlinelibrary.wiley.com/doi/10.1111/cen.14609"
NORDIC_2024 = "https://obgyn.onlinelibrary.wiley.com/doi/10.1111/aogs.14725"
STATPEARLS_PMOS = "https://www.ncbi.nlm.nih.gov/books/NBK459251/"
CCJM_2026 = "https://www.ccjm.org/content/93/3/176"
HOPKINS_PMOS = "https://www.hopkinsmedicine.org/health/conditions-and-diseases/polycystic-ovary-syndrome-pcos"

LAST_VERIFIED = "2026-09-25"


@dataclass
class Source:
    title: str
    org: str
    year: int
    url: str
    kind: str = "guideline"  # guideline | consensus | review | factsheet | reference


@dataclass
class EvidenceItem:
    """One citable recommendation used by the engine."""

    id: str
    topic: str                 # grouping key used by the UI
    statement: str             # the recommendation, in plain clinical language
    grade: str                 # EBR | CR | PP | CONSENSUS | FACT
    rec_id: str = ""           # published recommendation number, e.g. "1.4.4"
    sources: List[Source] = field(default_factory=list)
    applies_to: str = "adults"  # adults | adolescents | all
    note: str = ""
    last_verified: str = LAST_VERIFIED

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "topic": self.topic,
            "statement": self.statement,
            "grade": self.grade,
            "rec_id": self.rec_id,
            "sources": [s.__dict__ for s in self.sources],
            "applies_to": self.applies_to,
            "note": self.note,
            "last_verified": self.last_verified,
        }


# --------------------------------------------------------------------------
# Source objects (reused)
# --------------------------------------------------------------------------
S_GUIDELINE_2023 = Source(
    "International Evidence-based Guideline for the Assessment and Management of PCOS/PMOS (2023)",
    "Monash University / International PCOS Network (endorsed by 39+ organisations)",
    2023, MONASH_2023_FULL, "guideline",
)
S_ASRM_2023 = Source(
    "Recommendations from the 2023 International Evidence-based Guideline for PCOS",
    "ASRM", 2023, ASRM_2023, "guideline",
)
S_LANCET_2026 = Source(
    "Polyendocrine metabolic ovarian syndrome, the new name for polycystic ovary "
    "syndrome: a multistep global consensus process",
    "The Lancet (Teede, Khomami, Morman et al.) — DOI 10.1016/S0140-6736(26)00717-8",
    2026, LANCET_2026_PMOS, "consensus",
)
S_ASRM_2026 = Source(
    "PCOS is Now PMOS: Understanding the Name Change",
    "ASRM", 2026, ASRM_2026_PMOS, "consensus",
)
S_WHO = Source(
    "Polycystic ovary syndrome fact sheet",
    "World Health Organization", 2025, WHO_FACTSHEET, "factsheet",
)
S_RCOG = Source(
    "Long-term Consequences of Polycystic Ovary Syndrome, Green-top Guideline No. 33",
    "RCOG", 2014, RCOG_GTG33, "guideline",
)
S_AAFP = Source(
    "Polycystic Ovary Syndrome: Common Questions and Answers",
    "American Family Physician", 2023, AAFP_2023, "review",
)
S_ALLEN = Source(
    "Long-term health outcomes in young women with polycystic ovary syndrome: a narrative review",
    "Clinical Endocrinology (Allen et al.)", 2022, ALLEN_2022, "review",
)
S_NORDIC = Source(
    "International evidence-based guideline on assessment and management of PCOS — a Nordic perspective",
    "Acta Obstetricia et Gynecologica Scandinavica", 2024, NORDIC_2024, "review",
)
S_STATPEARLS = Source(
    "Polyendocrine Metabolic Ovarian Syndrome",
    "StatPearls / NCBI Bookshelf", 2025, STATPEARLS_PMOS, "reference",
)
S_CCJM = Source(
    "Polycystic ovary syndrome: an update on diagnosis and management",
    "Cleveland Clinic Journal of Medicine", 2026, CCJM_2026, "review",
)
S_HOPKINS = Source(
    "Polyendocrine Metabolic Ovarian Syndrome (PMOS)",
    "Johns Hopkins Medicine", 2026, HOPKINS_PMOS, "reference",
)


# --------------------------------------------------------------------------
# The registry
# --------------------------------------------------------------------------
def _build() -> List[EvidenceItem]:
    e: List[EvidenceItem] = []

    # ---------------------------------------------------------- naming / 2026
    e += [
        EvidenceItem(
            id="name.2026.pmos",
            topic="What this condition is called in 2026",
            statement=(
                "On 12 May 2026 an international consensus published in The Lancet renamed "
                "PCOS to PMOS — Polyendocrine Metabolic Ovarian Syndrome. The rename followed "
                "a multi-step process involving 56 organisations and more than 14,000 patients "
                "and health professionals."
            ),
            grade="CONSENSUS",
            sources=[S_LANCET_2026, S_ASRM_2026, S_HOPKINS],
            applies_to="all",
            note="Renaming only: ICD-10 E28.2 is unchanged and no patient needs re-diagnosis.",
        ),
        EvidenceItem(
            id="name.2026.unchanged",
            topic="What this condition is called in 2026",
            statement=(
                "The rename changed the name only. Diagnostic criteria (Rotterdam 2003 as "
                "updated by the 2023 International Guideline), treatments and screening "
                "recommendations are all unchanged. A three-year transition period runs to the "
                "2028 International Guideline update; ICD-10 E28.2 remains the code until ICD-11."
            ),
            grade="CONSENSUS",
            sources=[S_ASRM_2026, S_LANCET_2026],
            applies_to="all",
        ),
        EvidenceItem(
            id="name.2026.why",
            topic="What this condition is called in 2026",
            statement=(
                "The word 'polycystic' was misleading: the ovarian findings are arrested "
                "antral follicles, not true cysts, and many people with the condition have no "
                "cysts at all. The new name centres the endocrine, metabolic and ovarian "
                "features together."
            ),
            grade="CONSENSUS",
            sources=[S_LANCET_2026, S_ASRM_2026],
            applies_to="all",
        ),
        EvidenceItem(
            id="epi.prevalence",
            topic="How common it is",
            statement=(
                "PMOS/PCOS affects roughly 1 in 8 women of reproductive age — about 170 million "
                "people worldwide. The WHO estimates prevalence at 10–13%, and up to 70% of "
                "affected people remain undiagnosed."
            ),
            grade="FACT",
            sources=[S_WHO, S_ASRM_2026],
            applies_to="all",
        ),
    ]

    # ------------------------------------------------- SECTION 1 — detection
    e += [
        EvidenceItem(
            id="dx.rotterdam.2of3",
            topic="Diagnosis — the 2-of-3 rule",
            statement=(
                "In adults, diagnosis requires at least two of: (i) clinical or biochemical "
                "hyperandrogenism, (ii) ovulatory dysfunction, (iii) polycystic ovarian "
                "morphology on ultrasound OR elevated anti-Müllerian hormone — after other "
                "causes have been excluded."
            ),
            grade="EBR",
            rec_id="1.1",
            sources=[S_GUIDELINE_2023, S_ASRM_2023, S_NORDIC],
            applies_to="adults",
        ),
        EvidenceItem(
            id="dx.adolescent.both",
            topic="Diagnosis — the 2-of-3 rule",
            statement=(
                "In adolescents, BOTH hyperandrogenism and ovulatory dysfunction are required. "
                "Ultrasound and AMH are not recommended in adolescents because specificity is poor."
            ),
            grade="CR",
            rec_id="1.1",
            sources=[S_GUIDELINE_2023, S_ASRM_2023],
            applies_to="adolescents",
        ),
        EvidenceItem(
            id="dx.cycles.adult",
            topic="Criterion 1 — ovulatory dysfunction",
            statement=(
                "From 3 years post-menarche to perimenopause, irregular cycles are defined as "
                "<21 days or >35 days, or fewer than 8 cycles per year."
            ),
            grade="CR",
            rec_id="1.1.1",
            sources=[S_GUIDELINE_2023, S_ASRM_2023, S_CCJM],
            applies_to="adults",
            note="Also: any single cycle >90 days is irregular from 1 year post-menarche.",
        ),
        EvidenceItem(
            id="dx.cycles.adolescent",
            topic="Criterion 1 — ovulatory dysfunction",
            statement=(
                "Irregular cycles are normal in the first year post-menarche. From 1 to <3 years "
                "post-menarche the threshold is <21 or >45 days."
            ),
            grade="CR",
            rec_id="1.1.1",
            sources=[S_GUIDELINE_2023, S_NORDIC],
            applies_to="adolescents",
        ),
        EvidenceItem(
            id="dx.progesterone",
            topic="Criterion 1 — ovulatory dysfunction",
            statement=(
                "When cycles look regular but ovulation is uncertain, a luteal-phase serum "
                "progesterone confirms or excludes ovulation."
            ),
            grade="PP",
            sources=[S_GUIDELINE_2023, S_NORDIC],
            applies_to="adults",
        ),
        EvidenceItem(
            id="dx.hirsutism.predicts",
            topic="Criterion 2 — hyperandrogenism",
            statement=(
                "The presence of hirsutism alone should be considered predictive of biochemical "
                "hyperandrogenism in adults."
            ),
            grade="EBR",
            rec_id="1.3.1",
            sources=[S_GUIDELINE_2023, S_ASRM_2023],
            applies_to="adults",
        ),
        EvidenceItem(
            id="dx.acne.alopecia.weak",
            topic="Criterion 2 — hyperandrogenism",
            statement=(
                "Female-pattern hair loss and acne in isolation (without hirsutism) are "
                "relatively weak predictors of biochemical hyperandrogenism."
            ),
            grade="EBR",
            rec_id="1.3.2",
            sources=[S_GUIDELINE_2023, S_ASRM_2023],
            applies_to="adults",
        ),
        EvidenceItem(
            id="dx.biochem.testosterone",
            topic="Criterion 2 — hyperandrogenism",
            statement=(
                "Use total and free testosterone to assess biochemical hyperandrogenism; free "
                "testosterone may be estimated by the calculated free androgen index. If not "
                "elevated, androstenedione and DHEAS could be considered, but they have limited "
                "accuracy and poor sensitivity."
            ),
            grade="EBR",
            rec_id="1.2.1 / 1.2.2",
            sources=[S_GUIDELINE_2023, S_NORDIC],
            applies_to="adults",
        ),
        EvidenceItem(
            id="dx.biochem.lcms",
            topic="Criterion 2 — hyperandrogenism",
            statement=(
                "Liquid chromatography–mass spectrometry (LC-MS/MS) should be used for "
                "testosterone rather than direct immunoassays, whose sensitivity and accuracy "
                "are too poor at the low concentrations typical in women."
            ),
            grade="EBR",
            rec_id="1.2.3",
            sources=[S_NORDIC, S_GUIDELINE_2023],
            applies_to="all",
        ),
        EvidenceItem(
            id="dx.pcom.fnpo",
            topic="Criterion 3 — polycystic ovarian morphology",
            statement=(
                "Follicle number per ovary (FNPO) ≥ 20 in at least one ovary is the threshold "
                "for polycystic ovarian morphology in adults. FNPO is the most effective "
                "ultrasound marker."
            ),
            grade="CR",
            rec_id="1.4.1 / 1.4.4",
            sources=[S_GUIDELINE_2023, S_ASRM_2023],
            applies_to="adults",
        ),
        EvidenceItem(
            id="dx.pcom.ov",
            topic="Criterion 3 — polycystic ovarian morphology",
            statement=(
                "Ovarian volume ≥ 10 mL or follicle number per cross-section (FNPS) ≥ 10 in at "
                "least one ovary may be used when older technology or insufficient image quality "
                "prevents an accurate whole-ovary follicle count. Transabdominal ultrasound "
                "should primarily report ovarian volume or FNPS."
            ),
            grade="CR",
            rec_id="1.4.5 / 1.4.8",
            sources=[S_GUIDELINE_2023],
            applies_to="adults",
        ),
        EvidenceItem(
            id="dx.amh.adults",
            topic="Criterion 3 — AMH as an alternative",
            statement=(
                "Serum anti-Müllerian hormone could be used to define polycystic ovarian "
                "morphology in ADULTS, following the diagnostic algorithm. It should not be used "
                "as a single test, and it is influenced by age, BMI, ethnicity, combined oral "
                "contraceptive use and cycle day."
            ),
            grade="EBR",
            rec_id="1.5.1 / 1.5.3",
            sources=[S_GUIDELINE_2023, S_NORDIC],
            applies_to="adults",
            note=(
                "NO universal AMH threshold exists. Cut-offs are population- and assay-specific "
                "and differ substantially between the Gen II, picoAMH, Elecsys and Access "
                "platforms — a threshold from one assay does not transfer to another."
            ),
        ),
        EvidenceItem(
            id="dx.amh.not.adolescents",
            topic="Criterion 3 — AMH as an alternative",
            statement=(
                "AMH should not yet be used for diagnosis in adolescents."
            ),
            grade="EBR",
            rec_id="1.5.7",
            sources=[S_GUIDELINE_2023, S_NORDIC],
            applies_to="adolescents",
        ),
        EvidenceItem(
            id="dx.ultrasound.not.needed",
            topic="Diagnosis — simplified algorithm",
            statement=(
                "In patients with BOTH irregular menstrual cycles AND hyperandrogenism, an "
                "ovarian ultrasound is not necessary for diagnosis."
            ),
            grade="PP",
            rec_id="1.4.9",
            sources=[S_GUIDELINE_2023, S_ASRM_2023],
            applies_to="adults",
        ),
        EvidenceItem(
            id="dx.exclude.others",
            topic="Diagnosis — exclude other causes",
            statement=(
                "Other causes must be excluded: thyroid dysfunction (TSH), hyperprolactinaemia "
                "(prolactin), and non-classic congenital adrenal hyperplasia (17-OH progesterone); "
                "plus FSH and, if clinically indicated, Cushing's disease or androgen-secreting tumours."
            ),
            grade="CR",
            rec_id="1.6",
            sources=[S_GUIDELINE_2023, S_AAFP, S_ASRM_2023],
            applies_to="all",
        ),
        EvidenceItem(
            id="dx.hormonal.contraception",
            topic="Diagnosis — testing conditions",
            statement=(
                "Biochemical assessment of hyperandrogenism is unreliable on combined hormonal "
                "contraception; where feasible, test at least three months after stopping it."
            ),
            grade="PP",
            sources=[S_AAFP, S_GUIDELINE_2023],
            applies_to="all",
        ),
        EvidenceItem(
            id="dx.postmenopause",
            topic="Diagnosis — life stages",
            statement=(
                "Diagnosis could be considered after menopause if there is a past diagnosis, or a "
                "long-term history of oligo-amenorrhoea with hyperandrogenism and/or PCOM during "
                "the earlier reproductive years."
            ),
            grade="CR",
            rec_id="1.7.3",
            sources=[S_GUIDELINE_2023],
            applies_to="all",
        ),
    ]

    # ------------------------------------------- SECTION 2 — complications
    e += [
        EvidenceItem(
            id="cx.glucose.all",
            topic="Metabolic — glucose",
            statement=(
                "Glycaemic status should be assessed at diagnosis in ALL adults and adolescents "
                "with PMOS/PCOS, regardless of age and BMI, because the risk of impaired fasting "
                "glucose, impaired glucose tolerance and type 2 diabetes is increased."
            ),
            grade="EBR",
            rec_id="1.9.1 / 1.9.2",
            sources=[S_GUIDELINE_2023, S_ASRM_2023],
            applies_to="all",
        ),
        EvidenceItem(
            id="cx.glucose.interval",
            topic="Metabolic — glucose",
            statement=(
                "Glycaemic status should be reassessed every one to three years, based on "
                "additional individual diabetes risk factors."
            ),
            grade="CR",
            rec_id="1.9.3",
            sources=[S_GUIDELINE_2023],
            applies_to="all",
        ),
        EvidenceItem(
            id="cx.glucose.ogtt",
            topic="Metabolic — glucose",
            statement=(
                "A 75 g oral glucose tolerance test is the preferred screening test; HbA1c or "
                "fasting glucose are alternatives where OGTT is unavailable or declined, "
                "recognising they detect less dysglycaemia in this population."
            ),
            grade="CR",
            rec_id="1.9.4",
            sources=[S_GUIDELINE_2023, S_RCOG, S_ALLEN],
            applies_to="all",
        ),
        EvidenceItem(
            id="cx.glucose.riskfactors",
            topic="Metabolic — glucose",
            statement=(
                "Higher-risk groups warrant an OGTT specifically: BMI ≥ 25 kg/m² (≥ 23 kg/m² in "
                "Asian populations), central adiposity or increased waist circumference, "
                "substantial weight gain, acanthosis nigricans, family history of type 2 diabetes, "
                "personal history of gestational diabetes, high-risk ethnicity, age > 40 years, "
                "hypertension, smoking or physical inactivity."
            ),
            grade="CR",
            sources=[S_RCOG, S_ALLEN, S_STATPEARLS],
            applies_to="all",
            note="The Asian BMI cut-off of 23 kg/m² matters for the Indian population this app serves.",
        ),
        EvidenceItem(
            id="cx.lipids.all",
            topic="Cardiovascular — lipids",
            statement=(
                "All women with PMOS/PCOS, regardless of age and BMI, should have a lipid profile "
                "(total cholesterol, LDL-C, HDL-C and triglycerides) at diagnosis. Frequency "
                "thereafter depends on the presence of hyperlipidaemia and global cardiovascular risk."
            ),
            grade="CR",
            rec_id="1.8.3",
            sources=[S_GUIDELINE_2023, S_ASRM_2023],
            applies_to="all",
        ),
        EvidenceItem(
            id="cx.cvd.riskfactors",
            topic="Cardiovascular — risk assessment",
            statement=(
                "All women with PMOS/PCOS should be assessed for cardiovascular risk at initial "
                "diagnosis by assessing individual risk factors: obesity, lack of physical "
                "activity, cigarette smoking, family history of type 2 diabetes or premature CVD, "
                "dyslipidaemia, hypertension, impaired glucose tolerance and type 2 diabetes."
            ),
            grade="CR",
            rec_id="1.8.1",
            sources=[S_GUIDELINE_2023, S_RCOG],
            applies_to="all",
        ),
        EvidenceItem(
            id="cx.cvd.calculators",
            topic="Cardiovascular — risk assessment",
            statement=(
                "Conventional cardiovascular risk calculators have NOT been validated in women "
                "with PMOS/PCOS. They should be used with that limitation stated, not as a "
                "definitive individual risk figure."
            ),
            grade="CR",
            sources=[S_RCOG, S_GUIDELINE_2023],
            applies_to="all",
        ),
        EvidenceItem(
            id="cx.bp.each.visit",
            topic="Cardiovascular — blood pressure",
            statement=(
                "Blood pressure should be measured at initial diagnosis and at each visit, with a "
                "minimum review interval of 6–12 months, and during oral contraceptive therapy."
            ),
            grade="CR",
            rec_id="1.8.2",
            sources=[S_GUIDELINE_2023, S_RCOG, S_ALLEN],
            applies_to="all",
        ),
        EvidenceItem(
            id="cx.weight.each.visit",
            topic="Weight — BMI and waist",
            statement=(
                "Weight, BMI and waist circumference should be assessed at each visit, with a "
                "minimum review interval of 6–12 months. Adults should aim for 150–300 minutes of "
                "moderate-intensity activity or 75–150 minutes of vigorous activity weekly."
            ),
            grade="CR",
            rec_id="1.8.4 / 3.x",
            sources=[S_GUIDELINE_2023, S_ALLEN],
            applies_to="all",
            note="For weight loss, 250 min/week moderate or 150 min/week vigorous is suggested.",
        ),
        EvidenceItem(
            id="cx.osa.symptoms",
            topic="Sleep — obstructive sleep apnoea",
            statement=(
                "Screen for obstructive sleep apnoea by clinical symptom assessment only (snoring, "
                "witnessed apnoeas, daytime somnolence/fatigue) and refer when symptoms suggest it. "
                "Routine screening of asymptomatic women is not recommended."
            ),
            grade="CR",
            sources=[S_GUIDELINE_2023, S_RCOG, S_ALLEN, S_AAFP],
            applies_to="all",
            note="Prevalence of OSA is roughly four-fold higher in this population.",
        ),
        EvidenceItem(
            id="cx.mental.all",
            topic="Psychological — depression and anxiety",
            statement=(
                "Depressive and anxiety symptoms are significantly increased (odds ratios "
                "approximately 2.6 and 2.7 in adults) and should be screened for in ALL women with "
                "PMOS/PCOS using regionally validated tools, with psychological assessment and "
                "therapy as indicated."
            ),
            grade="CR",
            rec_id="1.10",
            sources=[S_GUIDELINE_2023, S_NORDIC, S_AAFP],
            applies_to="all",
        ),
        EvidenceItem(
            id="cx.nafld.awareness",
            topic="Liver — NAFLD",
            statement=(
                "Be aware of increased NAFLD risk in patients with metabolic syndrome or type 2 "
                "diabetes, but routine screening is NOT currently recommended and routine review "
                "is not recommended. Lifestyle modification, with hepatology review if identified "
                "incidentally."
            ),
            grade="PP",
            sources=[S_ALLEN, S_GUIDELINE_2023],
            applies_to="all",
            note="Some evidence suggests screening, if undertaken at all, is best considered in those with androgen excess.",
        ),
        EvidenceItem(
            id="cx.endometrial.bleeding",
            topic="Reproductive — endometrium",
            statement=(
                "Routine ultrasound screening for endometrial thickness in asymptomatic women is "
                "NOT recommended. Women should be counselled to report unexpected or abnormal "
                "uterine bleeding; prolonged amenorrhoea (>90 days) and thickened endometrium or "
                "polyps warrant further assessment."
            ),
            grade="PP",
            sources=[S_STATPEARLS, S_AAFP, S_GUIDELINE_2023],
            applies_to="all",
            note="Premenopausal endometrial cancer risk is increased, while absolute risk remains low.",
        ),
        EvidenceItem(
            id="cx.pregnancy.highrisk",
            topic="Reproductive — pregnancy",
            statement=(
                "PMOS/PCOS should be considered a high-risk condition in pregnancy. Gestational "
                "diabetes, hypertensive disorders of pregnancy and preterm birth risk are "
                "increased; women should be identified and monitored, with GDM screening at "
                "24–28 weeks' gestation."
            ),
            grade="CR",
            sources=[S_GUIDELINE_2023, S_ASRM_2023],
            applies_to="all",
        ),
        EvidenceItem(
            id="cx.infertility.anovulation",
            topic="Reproductive — fertility",
            statement=(
                "Chronic anovulation is the main cause of infertility in this condition. Weight, "
                "smoking and excess-weight counselling matter before and during fertility "
                "treatment because excess weight adversely affects clinical pregnancy, miscarriage "
                "and live-birth rates."
            ),
            grade="CR",
            sources=[S_STATPEARLS, S_GUIDELINE_2023],
            applies_to="all",
        ),
        EvidenceItem(
            id="cx.wearable.scope",
            topic="What a smartwatch can and cannot do",
            statement=(
                "Wearable sensors measure heart rate, heart-rate variability, activity, sleep "
                "duration and, on some devices, peripheral oxygen saturation and wrist skin "
                "temperature. They do NOT measure testosterone, AMH, glucose, lipids, insulin or "
                "ovarian morphology, and they cannot establish or exclude a PMOS/PCOS diagnosis."
            ),
            grade="FACT",
            sources=[S_GUIDELINE_2023, S_CCJM],
            applies_to="all",
            note=(
                "This app therefore uses watch data only as supportive longitudinal context and "
                "never as a substitute for the tests above."
            ),
        ),
        EvidenceItem(
            id="cx.spo2.caveat",
            topic="What a smartwatch can and cannot do",
            statement=(
                "Wrist SpO₂ from consumer wearables is an estimate for wellness use. It is not a "
                "medical-grade measurement and must not be used to rule out obstructive sleep apnoea."
            ),
            grade="FACT",
            sources=[S_GUIDELINE_2023],
            applies_to="all",
        ),
    ]
    return e


EVIDENCE: List[EvidenceItem] = _build()
EVIDENCE_BY_ID: Dict[str, EvidenceItem] = {i.id: i for i in EVIDENCE}


# --------------------------------------------------------------------------
# Headlines: the "latest data" summary the UI shows first
# --------------------------------------------------------------------------
HEADLINES = [
    {
        "date": "2026-05-12",
        "tag": "Name change",
        "headline": "PCOS is now PMOS — Polyendocrine Metabolic Ovarian Syndrome",
        "detail": (
            "A global consensus published in The Lancet renamed the condition on 12 May 2026 after "
            "a 14-year process involving 56 organisations and more than 14,000 patients and "
            "professionals. Criteria, treatment and ICD-10 E28.2 are unchanged; full implementation "
            "arrives with the 2028 guideline update."
        ),
        "sources": [S_LANCET_2026.__dict__, S_ASRM_2026.__dict__, S_HOPKINS.__dict__],
    },
    {
        "date": "2026-03-02",
        "tag": "Diagnosis",
        "headline": "Sequential diagnosis reaffirmed: clinical → biochemical → selective imaging",
        "detail": (
            "A 2026 review restates the 2023 approach: begin with clinical and biochemical "
            "assessment, then use ultrasound or AMH selectively in adults. In people with both "
            "irregular cycles and hyperandrogenism, neither ultrasound nor AMH is needed."
        ),
        "sources": [S_CCJM.__dict__, S_GUIDELINE_2023.__dict__],
    },
    {
        "date": "2025-07-07",
        "tag": "Complications",
        "headline": "Endometrial cancer: premenopausal risk raised, absolute risk low — no routine screening",
        "detail": (
            "Current guidance advises against routine endometrial-thickness screening in "
            "asymptomatic women; the emphasis is on reporting unexpected bleeding and assessing "
            "prolonged amenorrhoea."
        ),
        "sources": [S_STATPEARLS.__dict__, S_AAFP.__dict__],
    },
    {
        "date": "2024-11-20",
        "tag": "Diagnosis",
        "headline": "LC-MS/MS, not immunoassay, for testosterone",
        "detail": (
            "The Nordic perspective on the 2023 guideline stresses that direct immunoassays are too "
            "insensitive at the low testosterone concentrations typical in women, and that AMH "
            "cut-offs are population- and assay-specific."
        ),
        "sources": [S_NORDIC.__dict__, S_GUIDELINE_2023.__dict__],
    },
]


# --------------------------------------------------------------------------
# Access helpers
# --------------------------------------------------------------------------
def by_topic(topic: str) -> List[EvidenceItem]:
    return [i for i in EVIDENCE if i.topic == topic]


def topics() -> List[str]:
    seen: List[str] = []
    for i in EVIDENCE:
        if i.topic not in seen:
            seen.append(i.topic)
    return seen


def get(item_id: str) -> Optional[EvidenceItem]:
    return EVIDENCE_BY_ID.get(item_id)


def citations_for(ids: List[str]) -> List[dict]:
    """Resolve a list of evidence ids to compact citation dicts."""
    out: List[dict] = []
    for iid in ids:
        item = EVIDENCE_BY_ID.get(iid)
        if item is None:
            continue
        for s in item.sources:
            out.append({
                "evidence_id": item.id,
                "rec_id": item.rec_id,
                "grade": item.grade,
                "statement": item.statement,
                "title": s.title,
                "org": s.org,
                "year": s.year,
                "url": s.url,
            })
    return out


def as_dict() -> dict:
    return {
        "last_verified": LAST_VERIFIED,
        "topics": topics(),
        "items": [i.as_dict() for i in EVIDENCE],
        "headlines": HEADLINES,
    }


if __name__ == "__main__":  # pragma: no cover
    import json
    print(json.dumps(as_dict(), indent=2)[:2000])
    print(f"\n{len(EVIDENCE)} evidence items across {len(topics())} topics; verified {LAST_VERIFIED}")
