# CHRONO-PCOS V8.1 — Build Specification

**Periodic Clinical Imaging + Continuous Low-Cost Physiological Monitoring + Personal Baseline + Longitudinal Analysis + Cycle/Symptom Context + Multimodal AI + Patient Support + Clinician Longitudinal Reporting + Low-Infrastructure Deployment**

> Research prototype. NOT a diagnostic device. NOT clinically validated. No feature described here is claimed to have clinical accuracy — every unproven component is explicitly labelled PENDING or UNKNOWN.

---

## 0. Audit finding: what "V7" actually was

The repository on disk was audited byte-for-byte before any change. **There was no separate "V7" codebase on disk** — the project was the V6.2 implementation described in `docs/V6_2_BUILD_SPECIFICATION.md`. The V7 feature list in the request (QR system, printing system, ultrasound CV) existed **only as documentation**, not as code: a search for `qrcode|QRCode|qr_code|qrcodegen` across `src/` returned nothing, and no ultrasound image pipeline existed.

Therefore V8.1 was built **directly on the working V6.2 foundation** (109/109 tests passing at audit time). All working V6.2 functionality was preserved; the V7-described features were implemented fresh in code, honestly labelled. This document reports the actual state of the code, not the requested state.

---

## A. V7 (i.e. V6.2) architecture summary

```
WEARABLE (PPG + temp + IMU, optional GSR, periodic ECG)
        │  USB serial / ESP8266 TCP bridge (BLE: planned)
        ▼
PACKET VALIDATION → LOCAL SQLite STORE (offline-first)
        ▼
SIGNAL PROCESSING → FEATURES → SIGNAL QUALITY + WITHHOLD LAYER
        ▼
PERSONAL BASELINE → CHANGE DETECTOR → PERSONAL FINGERPRINT
        ▼
RISK ENGINE (transparent FALLBACK, uncertainty + explainability)
        ▼
USER DASHBOARD · CARE & ADHERENCE · CLINICAL DASHBOARD ·
WHAT CHANGED? · REPORT HISTORY + COMPARE · JUDGE MODE
```

Working and preserved: wearable acquisition, wireless communication (serial/TCP), personal baseline, longitudinal monitoring, change detection, cycle tracking, symptom tracking, user dashboard, clinical dashboard, report history, medication/appointment reminders, care-plan + adherence tracking, clinical data entry, digital reports, data-quality monitoring, validation infrastructure, demo/Judge Mode, offline SQLite.

**Weaknesses at audit (V8.1 gap analysis):**

| # | Gap in V6.2 | Severity |
|---|---|---|
| 1 | No ultrasound image pipeline of any kind — periodic clinical imaging was manual text entry only | MUST FIX |
| 2 | No QR / report-access system (described but absent) | MUST FIX |
| 3 | No printing story — only the old weekly text/PDF report | HIGH |
| 4 | No fusion layer tracking provenance (MEASURED / CLINICALLY-ENTERED / IMAGE-DERIVED / MODEL-INFERRED) | MUST FIX |
| 5 | Model A–D experiment only; ultrasound group missing | HIGH |
| 6 | No patient-level dataset schema for future imaging data | MUST FIX |
| 7 | UI had 8 primary tabs + Advanced; no ultrasound/fusion surface | HIGH |
| 8 | QR/print needed zero-dependency implementation (no network, no cv2/qrcode) | MUST FIX |

---

## B. V7 weaknesses (brutal, verified)

1. **"Continuous wearable → PCOS prediction" framing is not the innovation.** The wearable is a commodity sensor stack; nothing about it is defensible as the project's contribution. The longitudinal + clinical-fusion framework is.
2. **Ultrasound was a text box.** "Cyst 18 mm, morphology polycystic" entered manually — with no image, no quality gate, no provenance, no comparison. That could not be called "periodic clinical imaging."
3. **No provenance discipline.** The app tracked *some* inputs but had no explicit MEASURED / CLINICALLY-ENTERED / IMAGE-DERIVED / MODEL-INFERRED tagging, so a judge could not see at a glance that nothing is measured unless it is.
4. **No QR and no print-fallback report** despite the "digital-first" narrative — the story existed, the machinery did not.
5. **The Model A–D experiment was right but incomplete** for the V8.1 hypothesis: it could not answer "does ultrasound-derived information add additional value?"
6. **Everything honest about V6.2 was worth keeping**: the fallback-risk honesty, withholding, leakage-safe validation, OBSERVED/ASSOCIATED/UNKNOWN, no-fabrication culture. These are the identity of the project and were preserved unchanged.

---

## C. V8.1 architecture

```
                         CHRONO-PCOS V8.1
                            CHRONO-SENSE
                                │  continuous physiology
                                ▼
                         PERSONAL BASELINE
                                ▼
                        LONGITUDINAL ENGINE
            ┌───────────────┼────────────────┐
            ▼               ▼                ▼
     Physiology       Cycle/Symptoms    Care adherence
            └───────────────┼────────────────┘
                            ▼
                    CLINICAL DATA LAYER
           Ultrasound / BP / glucose / ECG / clinician info
                            ▼
                   ULTRASOUND CV LAYER
             (quality gate → structured features → comparison)
                            ▼
                   STRUCTURED FEATURES
            (provenance: MEASURED / PATIENT-REPORTED /
             CLINICALLY-ENTERED / IMAGE-DERIVED / MODEL-INFERRED)
                            ▼
                     MULTIMODAL FUSION
                            ▼
         ┌──────────────────┼──────────────────┐
         ▼                  ▼                  ▼
 User interpretation   Risk/phenotype    Clinical report
 (UNDERSTAND ME)       + uncertainty      (UNDERSTAND THE
 Lifestyle support /   + data quality     TIMELINE: WHAT CHANGED
 reminders             + coverage         SINCE LAST VISIT?)
                                          QR access · print fallback
```

---

## D. Every modification made

All changes were additions to the working V6.2 core; nothing working was removed.

1. `src/utils/qr_encoder.py` (new) — dependency-free QR codec.
2. `src/models/ultrasound_cv.py` (new) — ultrasound CV pipeline.
3. `src/models/fusion.py` (new) — provenance-aware multimodal fusion.
4. `src/models/longitudinal_report.py` (new) — one-page summary + full HTML report.
5. `src/ui/ultrasound_fusion_tab.py` (new) — Ultrasound + Fusion UI tab.
6. `src/utils/history_store.py` (modified) — `ultrasound_images` + `report_tokens` tables, token issue/resolve, image logging.
7. `src/validation/longitudinal_experiment.py` (modified) — Models A–E, ultrasound feature group.
8. `src/ui/clinical_tab.py` (modified) — QR report-access panel in the Clinical Dashboard.
9. `src/ui/main_window.py` (modified) — new "08 Ultrasound + Fusion" tab, renumbered Validation→09, Advanced→10, ultrasound input status, fusion context sync, V8 branding.
10. `src/config.py` (modified) — version 8.1.0.
11. `tests/test_v8_1.py` (new) — 20 tests.
12. `tests/test_v6.py`, `tests/test_v5_master.py`, `tests/test_v6_2.py` (modified) — version/tab-structure/model-set updates.
13. `README.md` (rewritten), `docs/V8_1_BUILD_SPECIFICATION.md` (this document).

## E. Files changed

- New: `src/utils/qr_encoder.py`, `src/models/ultrasound_cv.py`, `src/models/fusion.py`, `src/models/longitudinal_report.py`, `src/ui/ultrasound_fusion_tab.py`, `tests/test_v8_1.py`, `docs/V8_1_BUILD_SPECIFICATION.md`
- Modified: `src/utils/history_store.py`, `src/validation/longitudinal_experiment.py`, `src/ui/clinical_tab.py`, `src/ui/main_window.py`, `src/config.py`, `tests/test_v6.py`, `tests/test_v5_master.py`, `tests/test_v6_2.py`, `README.md`

## F. Features added

- Ultrasound image-quality gate (resolution/corruption/blur) → "ULTRASOUND QUALITY INSUFFICIENT FOR ANALYSIS"
- Structured ultrasound features with provenance + confidence; UNKNOWN by design until a validated dataset exists
- Descriptive ultrasound exam comparison (previous → current)
- Patient-level dataset schema + split integrity checks
- Multimodal fusion context (provenance tags, per-group reliability weights, explicit missing modalities)
- One-page clinical summary (text + PDF, single-page enforced)
- Full longitudinal HTML report (timeline, cycle/symptom/adherence/ultrasound sections)
- QR report access (randomized de-identified token, PNG + SVG, dependency-free encoder)
- Model D (clinical/cycle + longitudinal + ultrasound) and Model E (full multimodal)
- Ultrasound input status on the PCOS Analysis tab

## G. Features removed

**None.** Every working V6.2 feature was preserved. The only "removals" were renumbering tabs (Validation 08→09, Advanced 09→10) and updating the header from "V6" to "V8".

## H. Features intentionally not added

- Ultrasound→PCOS black-box diagnosis (explicitly refused; pipeline is quality→features→fusion)
- Cyst-rupture prediction (no legitimate longitudinal outcome dataset; "seek medical evaluation" is the only guidance)
- Hormone measurement from images or PPG (still NOT MEASURED; illustration-only remains behind Advanced)
- Cancer / general-disease detection, diabetes diagnosis, unrelated modules
- New hardware sensors (the wearable stays PPG+temp+IMU, optional GSR, periodic ECG)
- Cloud deployment, remote servers, or anything that breaks offline-first operation
- Fabricated dataset rows, fabricated accuracy, fabricated validation

---

## I. Ultrasound CV architecture

```
Image file
  → assess_quality(): exists? decodable? resolution ≥ 320×240? blur score ≥ 1.5?
  → FAIL ⇒ "ULTRASOUND QUALITY INSUFFICIENT FOR ANALYSIS" (no features)
  → PASS ⇒ extract_features():
      • clinician_entries pass through with CLINICALLY-ENTERED provenance
      • image-derived anatomical features ⇒ UNKNOWN with confidence 0.0
        (no validated labelled patient-grouped dataset is included; none fabricated)
  → compare_exams(prev, curr): only fields present on both sides;
      direction labels: increased / decreased / stable / changed
  → log to ultrasound_images table (path, quality, features_json, provenance)
```

The module is deliberately honest about its two states: the **quality gate works on real images today**; the **feature extractor is wired and pending data**. A judge can import a real ultrasound image and see the quality verdict, the provenance table, and the explicit "IMAGE-DERIVED FEATURES PENDING" note — which is more credible than a fake "diagnosis."

## J. Dataset requirements

Documented in-app (Dataset Requirements tab) and in `ultrasound_cv.py`:

- Required columns: `patient_id`, `image_path`, `label`, `exam_date`
- Optional: `cyst_size_mm`, `ovary_volume_cc`, `morphology`, `follicle_count`, `image_quality`, `reference_standard`, `site`
- Reference standard must be documented per site (e.g. Rotterdam criteria); label provenance recorded
- Ethics approval + consent documented for every image
- **Split at patient level only** (train/validation/test patients, one patient's images never span partitions)
- No dataset is currently included, and none is fabricated

## K. Data preprocessing pipeline

1. Raw image → decode (PIL) → grayscale → downscale cap (512px) → quality metrics
2. Quality gate → features (or UNKNOWN) → provenance + confidence attached
3. Fusion layer merges with wearable/longitudinal/cycle/symptom/metabolic/ECG/adherence groups, each carrying quality
4. Missing groups get zero weight; overall confidence reflects coverage

## L. Training pipeline

None runs today — **honestly**:

- The risk engine remains a transparent FALLBACK equation.
- The ultrasound feature extractor produces UNKNOWN until a validated dataset exists.
- When a legitimate dataset arrives, the training pipeline is: features → patient-level split → model comparison (A–E) → calibration → metrics with CIs. The experiment framework exists and is wired; the data does not.

## M. Patient-level validation strategy

- Splits are defined on `patient_id`, never on rows.
- `UltrasoundDataset.patient_split()` demonstrates train/val/test disjointness and is tested.
- The same discipline is required for the longitudinal experiment (subject-level GroupKFold); no model is evaluated without it.
- Every validation claim in the UI is labelled model-development vs clinical validation; the Kaggle cohort result is never wearable accuracy.

## N. Multimodal fusion strategy

- Groups: clinical, wearable, longitudinal, metabolic, ecg, ultrasound, adherence
- Provenance vocabulary: MEASURED / PATIENT-REPORTED / CLINICALLY-ENTERED / IMAGE-DERIVED / MODEL-INFERRED / UNKNOWN
- Group weight = coverage × mean quality; missing groups = 0 (never drag the estimate down)
- Missing modalities are listed explicitly and lower overall confidence — never silently imputed
- MODEL-INFERRED values are labelled and never promoted to measurements

## O. Ablation experiment design (Model A–E)

| Model | Inputs | Answers |
|---|---|---|
| A | Clinical / cycle only | conventional baseline |
| B | Clinical/cycle + conventional snapshot wearable | does a smartwatch-style day add value? |
| C | Clinical/cycle + CHRONO longitudinal features | do longitudinal features add value? |
| D | Clinical/cycle + longitudinal + ultrasound-derived | does ultrasound add additional value? |
| E | Full multimodal (A+B+C+D) | maximal model |

Metrics when data exists: AUROC, AUPRC, sensitivity, specificity, precision, recall, F1, calibration, CIs. **Current state: PENDING — no fabricated numbers.**

## P. UI changes

- New **08 Ultrasound + Fusion** primary tab (Ultrasound CV / Multimodal Fusion / Reporting + QR / Dataset Requirements)
- Clinical Dashboard gains a **QR report-access** panel
- PCOS Analysis gains an **ultrasound** model-input status row
- Validation 08→09, Advanced 09→10; header updated to "CHRONO-PCOS V8"
- Design language unchanged (research/health aesthetic, restrained colors, no smartwatch styling)

## Q. User dashboard description

"UNDERSTAND ME": personal baseline + current state + deviations + trends + cycle context + symptoms + lifestyle support + reminders + data quality + uncertainty; "WHY DID MY STATUS CHANGE?" with evidence-based observations (never hormone claims). Preserved from V6.2, unchanged in V8.1.

## R. Clinical dashboard description

"UNDERSTAND THE TIMELINE": patient overview, monitoring duration, coverage, personal baseline, longitudinal charts, symptom + cycle timelines, clinical measurements, ultrasound findings **+ image analysis results (quality verdict, provenance, UNKNOWN features)**, previous/current reports, model output + uncertainty, care-plan adherence, clinician notes, **QR report access**, and WHAT CHANGED SINCE LAST VISIT? with OBSERVED/ASSOCIATED/UNKNOWN care-journey separation.

## S. Report format

- **One-page clinical summary** (text + PDF): monitoring period, data quality, major changes, relevant clinical information, model estimate, uncertainty, clinical review note, disclaimer. The PDF writer **refuses to spill past one page** — concise by construction.
- **Full longitudinal HTML report**: de-identified participant, overview cards, personal fingerprint, change analysis, timeline sparklines, cycle/symptom timelines, ultrasound examinations, care-plan adherence, review note, safety footer.

## T. QR / printing architecture

- QR payload = randomized de-identified record token (`CP-` + 12 hex chars, e.g. `CP-9F3A2B7C`); **no PII encoded**
- Token stored in `report_tokens` with TTL (90 days default) → `resolve_report_token()` returns the report
- Encoder is dependency-free (own Reed–Solomon + matrix placement, versions 1–3, EC L/M), renders PNG + SVG; payload is also shown as plain text so a scan failure degrades to manual token entry
- Print path: one-page PDF summary; QR image printed beside it
- Three infrastructure tiers: full dashboard (computer) / QR access (smartphone) / printed one-page summary (limited infrastructure)

## U. Privacy architecture

- Local/offline SQLite; nothing transmitted
- Anonymized participant IDs; no names stored by default
- QR tokens randomized and expiry-dated; report content de-identified
- Role separation is conceptual (User vs Clinical dashboard) within a single local app
- Documented limitation: this is a local prototype — encryption-at-rest and multi-user access control remain future work; the app does not claim enterprise-grade privacy

## V. Medical safety limitations

- NOT A DIAGNOSTIC DEVICE · NOT A SUBSTITUTE FOR A DOCTOR · NOT A SUBSTITUTE FOR ULTRASOUND · NOT A SUBSTITUTE FOR CLINICAL TESTING
- Provides monitoring, estimation, longitudinal analysis, educational support, clinical-support information
- No hormone measurement; no diagnosis; no autonomous treatment decisions
- Cyst-complication content: EXPERIMENTAL RESEARCH MODULE only; no rupture prediction; concerning symptoms → seek medical evaluation
- Human research requires consent, adult/teacher/clinician oversight, institutional/ethics approval (documented in-app)

## W. Testing performed

`python -m pytest tests/ -q` → **129 passed** (109 pre-existing + 20 new V8.1). V8.1 coverage:
- QR: round-trip reverse-reads (v1–v3 × L/M), RS syndromes zero, capacity enforcement, PNG/SVG rendering
- Ultrasound CV: quality gate accept/reject, UNKNOWN-by-design features, clinical provenance pass-through, exam comparison, patient-level split disjointness
- Fusion: provenance tags, missing-group weighting, no false measurement claims
- Reporting: one-page summary, full HTML report, token round-trip + expiry, image logging
- UI: window constructs with all 10 tabs; fusion context builds
- Experiment: Models A–E present, PENDING, no fabricated numbers

Full end-to-end offscreen smoke tests passed: window boot, fusion build, QR report generation (HTML + PNG), one-page summary, ultrasound CV on a real generated image.

## X. Tests that still need real-world data

- Ultrasound feature extraction with real labelled images (currently asserts UNKNOWN — the honest state)
- Model A–E metrics with a labelled longitudinal PCOS dataset (currently asserts PENDING)
- Risk-engine calibration with clinical outcomes
- Real-world QR scan (phone) of the generated PNG/SVG (encoder self-tests pass; optical scanning is untested)
- Real wearable sessions over weeks/months (baseline drift, adherence behavior)

---

## Y. Final innovation statement

> **CHRONO-PCOS V8.1 investigates whether inexpensive continuous physiological monitoring — personalized through a per-person baseline and longitudinal change analysis — can make the period between clinical assessments more informative, and whether combining that continuous context with periodic clinical information (including ultrasound, entered through a quality-gated, provenance-tracked image pipeline) improves PCOS-related risk phenotyping.** The wearable is an acquisition device; the innovation is the longitudinal multimodal analytical framework, the evidence-linked "WHAT CHANGED?" summary, and the low-infrastructure digital-first reporting path (QR + one-page print fallback).

## Z. 30-second national judge pitch

> "Most PCOS tools take a snapshot: one visit, one ultrasound, one questionnaire. We ask a different question — what happens *between* visits? Our system runs a low-cost wearable that just collects PPG, temperature and movement. The real work is in our longitudinal engine: it learns *your* personal baseline, detects changes that persist for days, and tracks your cycle and symptoms. When you do get a clinical assessment, we add that information — including ultrasound images through a quality gate and a strict provenance system — and fuse everything into an explainable risk estimate with honest uncertainty. The wearable is not the innovation. The innovation is understanding what happened between visits — and we report it digitally with QR access or a one-page printed summary for clinics with minimal infrastructure."

## AA. 2-minute demonstration script

1. **30 s — Overview.** Open the app. Live/Demo badge visible. Headline risk card with confidence, data quality, coverage. "This is a research estimate, not a diagnosis."
2. **20 s — Longitudinal.** Personal fingerprint: baseline ± spread, current, deviation in SD, persistence in days for HR/HRV/temperature/activity.
3. **20 s — WHAT CHANGED?** Evidence-linked lines: physiology, cycle, symptoms, adherence, model — each with its source numbers, "temporally associated with" language.
4. **25 s — Ultrasound + Fusion.** Import an image → quality gate verdict ("OK" or "QUALITY INSUFFICIENT") → structured features panel showing UNKNOWN values with the honest "no validated dataset yet" note → fusion context showing provenance tags, group weights, missing modalities.
5. **25 s — Reporting.** Generate the one-page clinical summary → save PDF → generate the full HTML report → show the QR PNG → "the QR holds only a random token; no identifying information."
6. **5 s — Close.** "Not a diagnosis. Research prototype. The honest question is being tested."

## AB. 10-minute technical presentation structure

1. Problem: snapshot medicine, PCOS diagnosis delay, between-visit blindness (1.5 min)
2. Hypothesis + why longitudinal personalization (1 min)
3. System architecture (SENSE→PERSONALIZE→TRACK→DETECT→EXPLAIN→SUPPORT→INTEGRATE→REPORT→REVIEW) (1.5 min)
4. Signal quality + withholding discipline (1 min)
5. Ultrasound CV: quality gate, provenance, UNKNOWN-by-design, dataset requirements (1.5 min)
6. Multimodal fusion + Model A–E experiment design (1.5 min)
7. Validation strategy: patient-level splits, calibration, no fabrication (1 min)
8. Reporting: one-page summary, QR token, print fallback, privacy (1 min)
9. Honest limitations + next experiments (pilot) (30 s)

## AC/AD. Top 25 national-level judge questions and strong honest answers

1. **Does this diagnose PCOS?** No. It estimates risk and provides longitudinal context. Diagnosis requires a clinician and accepted criteria.
2. **How does the ultrasound part work?** Quality gate first; then structured features. Without a validated labelled dataset, image-derived features are UNKNOWN — we do not fabricate anatomy.
3. **Is the 0.959 AUC from the Kaggle dataset your accuracy?** No. That is a model-development result on a clinical-variable cohort — never wearable or ultrasound accuracy.
4. **Have you validated on patients?** Not yet. That requires an ethics-approved pilot; everything is labelled PENDING until then.
5. **Why no diagnosis from ultrasound?** A black box "image → diagnosis" would be unsupported and unsafe. We extract structured features with provenance and fuse them — and we refuse to produce values we cannot support.
6. **How do you avoid data leakage?** Patient-level splits only; train/val/test disjoint on patient_id; tested.
7. **Why is the QR safe?** The payload is a randomized token, not data. It expires and resolves locally to a de-identified report.
8. **What makes this novel?** Not the sensors — the between-visit longitudinal framework: personal baseline, persistent-change detection, evidence-linked summaries, and clinical fusion.
9. **Can you distinguish correlation from causation?** We never claim causation. "Temporally associated with" only; OBSERVED/ASSOCIATED/UNKNOWN is a hard separation.
10. **What if signal quality is bad?** The prediction is withheld with a visible banner. We never force a number.
11. **What if the patient has no ultrasound?** The system works without it — the fusion layer lists it as a missing modality and lowers confidence; no fabricated value.
12. **Does the wearable measure hormones?** No. Nothing measures hormones directly; hormone-like values are illustration-only and excluded from the score.
13. **Why one page for the printed report?** Clinicians read a page. Printing thousands of raw measurements helps nobody; the full detail lives in the digital report.
14. **Is this affordable?** The wearable is a low-cost ESP32-class sensor stack; the software runs offline on a laptop. BOM is documented in earlier docs.
15. **How does the change detector avoid reacting to noise?** Persistence and quality gates — a single abnormal reading never triggers a conclusion.
16. **What are the false-positive risks?** Real, and acknowledged: research estimates can mislead. The UI's withholding, confidence, and disclaimers are the mitigation; clinical validation is the only true answer.
17. **Why not more sensors?** Ablation discipline: we add only what the experiment shows adds information. More sensors ≠ better science.
18. **Can this replace a doctor?** No. It supports the interval between visits. Clinical decisions remain with professionals.
19. **How is the cycle info used?** Patient-reported cycle length/regularity is a defensible PCOS-relevant signal; it is PATIENT-REPORTED, never sensor-derived.
20. **What would convince you the approach works?** A pilot with labelled longitudinal data and Model A–E results with patient-level validation — showing longitudinal features add AUROC/AUPRC beyond snapshot inputs.
21. **Is the app offline?** Yes — local SQLite, no cloud dependency; a privacy feature and a deployment advantage.
22. **What about cyst rupture?** Explicitly research-only architecture; no prediction model exists or is claimed; concerning symptoms → seek medical evaluation.
23. **How do you print?** One-page PDF via Qt's built-in QPdfWriter, with the QR alongside. Print is a fallback, not the primary channel.
24. **Who is this for?** Students/researchers now; potentially low-resource clinics after clinical validation. Not for self-diagnosis.
25. **What is the single biggest weakness?** No validated dataset yet — the framework is complete and honest, but "does it work?" is not yet answered. That is precisely why everything is labelled PENDING.

## AE. Biggest remaining weaknesses

1. **No validated longitudinal + ultrasound dataset** — the central question is untested.
2. **No Python BLE client** — the ESP32 BLE pod path is still a firmware/design milestone; serial/TCP only.
3. **Risk engine is a transparent fallback equation**, not a trained, calibrated model.
4. **QR optical scanning untested on real phones** — encoder self-tests pass, but scanner interoperability needs a device test.
5. **Firmware rate mismatch** (20 Hz vs 50 Hz assumptions) documented, not fixed.
6. **Single-machine role separation** — user vs clinician is conceptual, not authenticated.
7. **Ultrasound CV feature extraction awaits data** — the honest UNKNOWN state is correct but unproven.

## AF. Exact experiments required before claiming clinical usefulness

1. **Ethics-approved pilot** (N≈20–30, 8–12 weeks, consent + adult/teacher/clinician oversight + institutional approval): wearable + cycle/symptom logs + periodic clinical assessments with ultrasound where clinically indicated.
2. **Model A–E comparison** on the pilot data with **patient-level splits**: report AUROC/AUPRC/sensitivity/specificity/F1/calibration with CIs per model.
3. **Ultrasound feature pipeline validation**: build/validate the image model on the collected labelled images; confirm features add value over clinical+longitudinal (Model D vs C).
4. **Per-sensor ablation** (PPG / +temp / +IMU / +GSR) to justify hardware choices.
5. **QR interoperability test** on 3–5 phone models.
6. **Calibration + uncertainty audit**: reliability diagrams, coverage of prediction intervals.
7. **Firmware rate fix + BLE client** to make the wearable path production-grade.

Until (2)–(4) produce honest results, every claim remains **NOT YET VALIDATED**.

## AG. Estimated national-level score

Honest self-assessment against typical national exhibition criteria (0–10):

| Criterion | Weight | Current | With strong validation |
|---|---|---|---|
| Novelty | 15% | 8.5 | 9.0 |
| Social applicability | 15% | 9.0 | 9.5 |
| User-friendliness | 10% | 8.0 | 8.5 |
| Comparative advantage | 10% | 8.0 | 9.0 |
| Environmental benefit | 5% | 7.5 | 8.0 |
| Technical depth | 15% | 8.5 | 9.5 |
| Demonstrability | 10% | 8.5 | 9.0 |
| Scientific honesty | 10% | 9.5 | 9.5 |
| Low cost | 5% | 8.5 | 8.5 |
| Scalability | 5% | 7.5 | 8.5 |
| **Weighted** | | **≈8.4/10** | **≈9.1/10** |

With future clinical validation (pilot results, BLE client, calibrated model): **≈9.3–9.5/10**, contingent on the experiment actually supporting the hypothesis. The single biggest swing factor is evidence — the framework is built; the numbers must be earned.

---

*End of V8.1 build specification. Nothing in this document claims clinical accuracy, real patients, real ultrasound images, or validated performance that has not been demonstrated. Every unproven component is labelled PENDING or UNKNOWN.*
