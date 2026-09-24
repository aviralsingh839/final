# CHRONO-PCOS V8.2

**Low-cost longitudinal physiological phenotyping + periodic clinical imaging research prototype for PCOS-focused monitoring (research, not clinically validated).**

CHRONO-PCOS V8.2 is a low-cost, non-invasive, **longitudinal multimodal system** that investigates one question:

> **Can continuous, personalized physiological information collected between clinical assessments provide useful longitudinal context, and does combining it with periodic clinical information such as ultrasound improve PCOS-related risk phenotyping?**

It is **not a diagnostic device**, **not a smartwatch app**, and **not a general health tracker**. The wearable is only an acquisition device — the innovation is the longitudinal multimodal analytical framework: personal baseline, change detection, the "WHAT CHANGED?" evidence summary, clinician-facing reporting, and the fusion of continuous physiology with periodic clinical/ultrasound information.

> **Medical safety note:** PCOS diagnosis requires a clinician and accepted diagnostic criteria. All scores shown are research estimates. **No sensor measures hormones directly.** The app never changes, starts, stops or prescribes medication. **No ultrasound image is converted to a diagnosis** — image-derived features are UNKNOWN until a validated, labelled, patient-grouped dataset exists. **No cyst-rupture prediction exists or is claimed.**

---

## V8.2 changes (this release)

**V8.2 is a UI/UX and usability refinement of V8.1 — same engines, clearer presentation.**
Design principle: **"Simple outside. Sophisticated inside."**

1. **Four-area navigation.** The 10 technical tabs are reorganized into four top-level areas: **👤 Patient · 🩺 Clinician · 🔬 Research · ⚙ Settings**. Nothing was removed — every V8.1 module lives inside the appropriate section.
2. **Patient dashboard.** A new patient home screen answers **"How am I doing?"** first: physiological pattern (STABLE/CHANGED), data quality, baseline coverage, a plain-language **WHAT CHANGED?** list (❤️ HRV · 🏃 Activity · 📅 Cycle · 📝 Symptoms) and a care summary. Sections: Overview, My Baseline, My Timeline, Symptoms & Cycle, Care & Reminders, Reports.
3. **My Baseline in plain language.** Usual range · current value · status ("Below your usual range") per metric, with the physiological fingerprint and statistics behind **[TECHNICAL DETAILS]**.
4. **Clinician workspace.** Clinical Dashboard (What Changed since last visit, report history + compare, QR), Analysis (risk estimate + uncertainty + contributors + trend), Model Inputs (information used + provenance), Live Signals, Ultrasound & Imaging.
5. **Three information levels.** Level 1 (simple statement) on every main view; **[WHY?]** explanations and **[TECHNICAL DETAILS]** expanders for levels 2–3. Research-grade depth moved to the Research area.
6. **Centralized theme system with LIGHT default.** New token-based theme engine (`src/ui/theme.py`): clean light clinical look by default, optional dark mode, one-click switching that restyles charts, tables, dialogs and custom-painted widgets (gauge, radar, clock, fingerprint) without restart.
7. **Typography & readability.** Larger page titles, consistent heading hierarchy, 10.5–11pt minimum body/labels, accessible contrast in both themes, no information crammed into tiny labels, calm status colors (no alarming red unless warranted).
8. **Exhibition mode.** The judge demo is now a header button that seeds the clearly-labelled synthetic record, starts the demo stream and lands on the patient overview; the suggested 2–3 minute walk-through is documented in the tooltip and alert.
9. **Professional empty states & neutral language.** "Continue monitoring to establish a reliable personal baseline", "Not enough reliable data for an estimate", "Potential care-plan gap" — never fabricated values, never blame.
10. **CHRONO Model Lab (new, RESEARCH-only): controlled automated model training.** Upload a labelled dataset ZIP → safe extraction (no traversal/executables, nothing ever executed) → automatic **DATASET REPORT** (patients, classes, duplicates, corrupt, missing labels, imbalance, leakage risks; VALID/QUESTIONABLE/INVALID quality triage) → **patient-level splitting** with a hard leakage gate → configurable training (lightweight CPU backends; per-epoch validation, checkpoints, early stopping, resumable runs, live monitor) → untouched-test-set evaluation (AUROC/AUPRC/sens/spec/F1/confusion/calibration/CI — never accuracy alone, never fabricated) → **model registry** (`CHRONO-CV-NNN`, EXPERIMENT/CANDIDATE/APPROVED/REJECTED/RETIRED) → **human approval gate** (APPROVE / REJECT / KEEP CURRENT) → deployment + **rollback** + model cards + external validation. After approval the clinician ultrasound module consumes the model read-only, clearly labelled *APPROVED RESEARCH MODEL — not clinically validated*. See `docs/V8_2_MODEL_LAB_SPECIFICATION.md`.
11. **Version + report metadata updated** to V8.2 everywhere (window title, About, reports, model-registry summary).

**What V8.2 does NOT change:** the signal-processing, baseline, change-detection, risk, fusion, ultrasound-CV, validation and reporting engines are untouched; all V8.1 honesty rules (withheld predictions, UNKNOWN-by-design image features, DEMO exclusion) are preserved.

---

## V8.1 changes

The V8.1 release added the **periodic clinical imaging** and **multimodal fusion** layer on top of the V6.2 longitudinal core:

1. **Ultrasound computer-vision module** (new). An image pipeline with a hard **quality gate** (resolution, corruption, blur) that says *"ULTRASOUND QUALITY INSUFFICIENT FOR ANALYSIS"* rather than forcing a prediction. Structured features (ovary/cyst/follicle/morphology) carry documented provenance and confidence; **without a validated labelled ultrasound dataset every image-derived value is UNKNOWN — nothing is hallucinated.** Clinically entered findings pass through with CLINICALLY-ENTERED provenance.
2. **Patient-level dataset schema + integrity checks** (new). Documents exactly what a legitimate ultrasound dataset must contain (`patient_id`, `image_path`, `label`, `exam_date`), and enforces **train/validation/test splits at the patient level** so images from one patient never leak across partitions. No dataset is included or fabricated.
3. **Multimodal fusion layer with provenance** (new engine + tab). Every input is tagged **MEASURED / PATIENT-REPORTED / CLINICALLY-ENTERED / IMAGE-DERIVED / MODEL-INFERRED** with a quality score; missing modalities are listed explicitly and get zero weight (they never drag the estimate down, but their absence lowers confidence).
4. **Longitudinal-information experiment extended to Model A–E** (new). Adds *Model D: clinical/cycle + longitudinal + ultrasound-derived* and *Model E: full multimodal* — directly testing whether **ultrasound-derived information adds additional value** beyond longitudinal physiology. Honestly **PENDING** — no results are fabricated.
5. **Digital-first, infrastructure-adaptive reporting** (new). A **one-page clinical summary** (text/PDF, refuses to spill past one page) for print fallback, and a **full longitudinal HTML report** accessible through a **QR code** whose payload is a *randomized de-identified record token* (e.g. `CP-9F3A2B7C`) — no PII is encoded. QR + report access is also wired into the Clinical Dashboard.
6. **Dependency-free QR encoder** (new). A from-scratch QR codec (byte mode, versions 1–3, EC levels L/M, Reed–Solomon EC, mask selection) with **zero external dependencies** — the QR/report path works on any machine, offline. Verified by round-trip re-reads and RS syndrome checks in the test suite.
7. **Ultrasound longitudinal comparison** (new). Descriptive previous→current comparison of recorded examinations (measurements, direction of change) — temporal association is never claimed as causation.
8. **Hardware-agnostic entry preserved.** Manual wearable-style readings and manual clinical measurements still run the longitudinal engine without CHRONO hardware.

**What is NOT in the V8.1 core:** cancer detection, cyst-rupture prediction, general disease detection, diabetes diagnosis, unrelated disease modules, unnecessary sensors, AI-doctor behavior, autonomous treatment changes, unsupported hormone measurement. Those are future-research territory only.

---

## What it does

- Reads wearable packets (USB serial or ESP8266 Wi-Fi bridge; BLE client remains a planned milestone):
  - **PPG** (MAX30102): pulse waveform, HR, HRV, pulse amplitude, SpO₂ estimate (educational only)
  - **Skin temperature** (DS18B20): baseline, daily rhythm, deviations
  - **IMU** (MPU6050): motion, activity level, low-activity risk
  - **GSR** (optional): tonic/phasic arousal
  - **Periodic ECG** (AD8232, optional checkpoint): HR/HRV reference, PPG validation
  - Manual inputs: **BP, glucose, menstrual cycle, symptoms, weight, wearable-style readings**
- Computes per-sensor **signal quality** and a decision layer that **withholds the risk number** when quality/confidence is insufficient ("NO RELIABLE ESTIMATE").
- Builds a **personal baseline** and the **personal physiological fingerprint** from it.
- Runs a **longitudinal change detector** (single vs persistent vs progressive vs recovery, with quality gates).
- Produces the **WHAT CHANGED?** evidence-linked summary and the **CARE JOURNEY SUMMARY** (OBSERVED / ASSOCIATED / UNKNOWN).
- Runs the **ultrasound CV pipeline**: quality gate → structured features (UNKNOWN until a validated dataset exists) → exam comparison.
- Builds a **provenance-aware multimodal fusion context** from every available input group.
- Computes the **PCOS-related risk estimate** from defensible domains with confidence, CI, and explainable contributions.
- Records care-plan adherence and reminders **without any autonomous treatment decisions**.
- Generates **one-page clinical summaries** (text/PDF), **full longitudinal HTML reports**, **QR report tokens**, **report history**, and **report comparison** across visits.
- Runs **fully offline** (SQLite local database).
- Clearly-labelled **demo mode**, **Exhibition mode**, and **replay** of recorded sessions.

**Status labels used honestly:** the live risk engine remains a transparent **FALLBACK**; the ultrasound feature extractor is **PENDING DATA**; the Model A–E experiment is **PENDING**. Until validated models are connected, the whole system is a **RESEARCH PROTOTYPE**.

---

## Navigation (V8.2)

Four top-level areas — everything from V8.1 lives inside them:

| Area | Section | Purpose |
|---|---|---|
| **👤 Patient** | Overview | **"How am I doing?"** — personal status (pattern/quality/coverage), WHAT CHANGED?, care summary |
| | My Baseline | Usual ranges vs current values in plain language; fingerprint + statistics under TECHNICAL DETAILS |
| | My Timeline | Trends, 7-day profile + trajectory, session history, change analysis |
| | Symptoms & Cycle | Low-burden cycle / symptom / BP / glucose / weight / manual readings entry |
| | Care & Reminders | Medication plan + taken/skipped/snoozed log + adherence %, goals, appointment reminders |
| | Reports | Patient-facing monitoring summary (text/PDF) + data export |
| **🩺 Clinician** | Clinical Dashboard | WHAT CHANGED SINCE LAST VISIT, patient overview, report history + compare, ultrasound + notes, care journey, **QR report access**, Model A–E research |
| | Analysis | Headline risk estimate + confidence + CI, live vitals, contributors, longitudinal trend, withheld banner |
| | Model Inputs | Information used by the model with provenance + transparency box (measured / derived / not measured) |
| | Live Signals | Connection state, sensor cards, live PPG waveform |
| | Ultrasound & Imaging | **Ultrasound CV** (quality gate, structured features, exam comparison), **multimodal fusion context**, **one-page summary + full HTML report + QR token**, dataset requirements |
| **🔬 Research** | Validation & Model Performance | Model performance, leakage-safe validation, ablation, calibration |
| | Model Lab | **Controlled automated model training** — dataset ZIP intake + inspection, patient-level splitting, leakage gate, training monitor, evaluation, model comparison, registry, human approval gate, deployment + rollback, external validation, multimodal ablation (A–E) |
| | Advanced Tools | Experimental/legacy modules (hormone illustration, VoxVasc, metabolic challenge, what-if, assistant, evidence center, diagnostics, timeline, protocol) |
| **⚙ Settings** | — | Device connection (serial/Wi-Fi/demo), participant profile, **light/dark theme (light default)**, About |

---

## How to run

```bash
pip install -r requirements.txt

# Demo mode (synthetic stream, UI-only):
python -m src.app --demo

# Or:
python run_demo.py

# Live mode (USB serial or Wi-Fi bridge) — connect the wearable, then:
python -m src.app            # pick the serial port, or enter IP:port for the bridge
```

- **LIVE mode**: data arrives from the CHRONO wearable (serial or ESP8266 bridge). The header badge shows `LIVE MODE`.
- **DEMO mode**: clearly labelled synthetic stream (`DEMO MODE (SYNTHETIC)`), **excluded from real analysis and exports**.
- **Exhibition mode** (header button): a scripted 2–3 minute demonstration on labelled synthetic data — patient overview → baseline → timeline → What Changed → ultrasound → report + QR.

Run the tests:

```bash
python -m pytest tests/ -q
```

---

## Testing

- **173 tests pass** (129 from ≤V8.1 + 10 V8.2 UI tests + 34 Model Lab tests).
- Model Lab tests cover: ZIP validation (traversal/absolute-path/executable rejection, zip-bomb guards), safe extraction, label parsing (both structures + synonyms), invalid-dataset stop-with-explanation, duplicate + cross-patient-leakage detection, patient-level splitting (reproducible, configurable ratios, no cross-split patients), leakage gate, preprocessing records (no val/test augmentation), training configuration + recommended settings, full training runs with real metrics, blocked training on leaky/missing datasets, graceful CNN refusal without GPU, checkpoint interruption + resume, registry statuses, comparison, approval/rejection/keep-current, cannot-approve-unevaluated, rollback + history, model loading only when approved, external-validation separation, honest dashboard counts, research-only placement, and a full UI end-to-end (upload → train → approve → ultrasound consumption → rollback).
- V8.2 tests cover: light-as-default + dark switching, token completeness across themes, four-area navigation, V8.1-widget survival after the reorganisation, patient-overview honesty (no fabricated values), calm STABLE/IMPROVED/CHANGED/REVIEW states, plain-language baseline ranges, exhibition-mode demo labelling, and provenance label coverage.
- V8.1 tests cover: QR encode→reverse-read round-trips across versions/levels, Reed–Solomon syndrome checks, QR capacity enforcement, PNG/SVG rendering, ultrasound quality gate (accepts sharp / rejects missing + blur), **UNKNOWN-by-design image features**, clinically-entered provenance pass-through, descriptive exam comparison, patient-level dataset split integrity, fusion provenance + missing-group weighting, one-page summary, full HTML report, report-token round-trip + expiry, ultrasound image logging, window tab structure, and Model A–E honesty.

---

## Honest limitations

1. **No Python BLE client yet** — the app consumes USB serial or the ESP8266 TCP bridge; the ESP32 BLE pod path is still a firmware/design milestone.
2. **The live risk engine is a transparent fallback equation**, not a trained + calibrated model. That requires labelled longitudinal wearable data, which does not exist publicly — the staged pilot (consent + ethics + oversight) is the only honest route.
3. **The ultrasound feature extractor produces UNKNOWN values by design** — there is no validated, labelled, patient-grouped ultrasound dataset in this repository, and none is fabricated. The quality gate runs on real images today; anatomical feature extraction is wired and pending data.
4. **The Model A–E experiment is PENDING** by design — no dataset in this repository can validate the wearable or the ultrasound path (the Kaggle cohort is a clinical-variable model-development set, never wearable accuracy; synthetic rows are excluded from real analysis).
5. **Cyst-related analysis is research-only**: no rupture prediction exists; ultrasound observations are clinically entered and the wearable cannot visualize ovarian anatomy.
6. **Care-plan reminders are bookkeeping only** — the app never makes treatment decisions.

---

## Documentation

- `docs/V8_2_MODEL_LAB_SPECIFICATION.md` — controlled automated model training: dataset workflow, supported formats, leakage prevention, training/evaluation pipeline, registry + approval gate + rollback, security, medical safety.
- `docs/V8_2_UI_UX_SPECIFICATION.md` — V8.1→V8.2 UI/UX gap analysis, four-area navigation architecture, three information levels, theme-token system, exhibition-mode flow, accessibility/typography rules.
- `docs/V8_1_BUILD_SPECIFICATION.md` — full V8.1 gap analysis, architecture, dataset requirements, patient-level validation strategy, ablation design, QR/printing architecture, privacy architecture, medical safety limitations, judge pitch + demo script, top-25 judge Q&A, weaknesses, next experiments, national-level scoring assessment.
- `docs/V6_2_BUILD_SPECIFICATION.md` — V6.2 gap analysis, architecture, judge pitch, Q&A, scoring.
- `docs/V6_IMPLEMENTATION_STATUS.md`, `docs/V6_BUILD_SPECIFICATION.md` — earlier V6 implementation status and hardware/ML plan.
- `docs/scientific_model.md`, `docs/validation.md`, `docs/V5_BILL_OF_MATERIALS.md` — scientific model, validation and BOM details.
