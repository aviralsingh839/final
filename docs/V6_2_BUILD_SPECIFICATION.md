# CHRONO-PCOS V6.2 — BUILD SPECIFICATION & DELIVERABLE

> *From "wearable → PCOS prediction" to "continuous measurement → personal
> baseline → longitudinal change detection → contextual interpretation →
> patient support → clinician-facing longitudinal evidence".*

This document records the complete V6.1 → V6.2 evolution: the audit, the
decisions, what was actually implemented, the judge-facing material, the
remaining weaknesses, and the next experiments. Everything here is consistent
with the code in the repository — no feature is described that does not exist,
and no performance number is claimed that was not measured.

**Status: RESEARCH PROTOTYPE — the live risk engine is a transparent FALLBACK
and the whole system is NOT clinically validated.**

---

## A. Complete gap analysis of V6.1 (verified against code, not docs)

| # | Area | V6.1 state (verified) | Gap / assessment |
|---|---|---|---|
| 1 | Hormone pathway | Headline risk already excludes hormone "twin" values (V6.0 fix) | ✅ KEEP — but hormone illustration still in Advanced tools; zero score effect, verified by test |
| 2 | Personal baseline | BaselineManager (5-min calm window, MAD ranges) exists and is wired | ⚠️ IMPROVE — baseline existed but there was **no per-metric "fingerprint" presentation** (baseline ± spread, current, deviation SD, persistence, slope, trend in one view) |
| 3 | Longitudinal change | ChangeDetector wired (single/persistent/progressive/recovery) | ⚠️ IMPROVE — existed but not summarized as "WHAT CHANGED SINCE LAST ASSESSMENT?" with evidence links |
| 4 | Cycle inputs | Patient Inputs tab (cycle day/length, irregularity, symptoms, BP, glucose, weight) | ✅ KEEP — strongest honest PCOS signal; already first-class |
| 5 | Data quality | SQI engine + withheld banner | ✅ KEEP — core V6 honesty; unchanged |
| 6 | Explainability | Contributors ("WHY DID THE ESTIMATE CHANGE?"), radar, explanation panel | ✅ KEEP — unchanged; wording already "contributed to the model estimate" |
| 7 | Care plan / adherence | **Absent** | ❌ ADD (MUST) — no medication plan recording, no taken/skipped/snoozed log, no adherence %, no reminders, no care-gap analysis |
| 8 | Clinical dashboard | **Absent** | ❌ ADD (MUST) — no clinician-facing view, no "what changed since last visit", no report history, no compare |
| 9 | Report history / compare | Weekly text+PDF export existed only | ⚠️ IMPROVE — no stored report history, no comparison across months |
| 10 | Ultrasound findings | DB table `ultrasound_observations` + `log_ultrasound()` existed but **no UI** | ⚠️ IMPROVE — dead code path; now exposed with clinical-entry UI + explicit "no rupture prediction" labeling |
| 11 | Care journey (OBSERVED/ASSOCIATED/UNKNOWN) | **Absent** | ❌ ADD (MUST) — the causal-honesty distinction the judges will probe |
| 12 | Hardware-agnostic design | Serial + TCP + demo only | ⚠️ IMPROVE — no manual wearable-style entry path; now added |
| 13 | Smartwatch comparison (Model A–D) | Ablation framework existed but only for the fallback engine's domains | ⚠️ IMPROVE — added a dedicated longitudinal-experiment framework, honestly PENDING |
| 14 | Judge demonstration | 60 s demo existed (history + baseline) | ⚠️ IMPROVE — no clinical-record flow; now seeds labelled demo visits/report/ultrasound/care plan |
| 15 | Docs | README described V6.0 accurately | ⚠️ IMPROVE — updated to V6.2 |
| 16 | Tests | 97 tests | ✅ — 12 new V6.2 tests added, 109 total |

**Verdict:** V6.1 was scientifically honest but still shaped like a
*single-screen wearable dashboard*. The gap was not measurement — it was the
**longitudinal story**: what changed, how long, what the care record says, and
what a clinician would see between visits. V6.2 fills exactly that gap.

---

## B. What should be changed (the decisions)

1. Keep the honest risk engine, SQI/withhold, personal baseline, cycle log, explainability — they are V6's identity.
2. Add a **personal physiological fingerprint** presentation (baseline vs current vs deviation vs persistence vs slope) — the "what is normal for THIS person" visual.
3. Add a **WHAT CHANGED** engine — evidence-linked, category-tagged, "temporally associated with" wording.
4. Add a **CARE & ADHERENCE** module — recording only, never prescribing.
5. Add a **CLINICAL DASHBOARD** — what changed since last visit, report history, compare reports, ultrasound (clinical entry), notes, care journey.
6. Add **manual wearable-style entry** so the longitudinal framework is hardware-agnostic.
7. Add the **Model A–D longitudinal experiment framework** — pending, not fabricated.
8. Make **Judge Mode** demonstrate the full patient→clinician flow.

## C. Change categorization

| Priority | Change | Implemented? |
|---|---|---|
| **MUST HAVE** | Personal physiological fingerprint | ✅ |
| **MUST HAVE** | WHAT CHANGED engine (evidence-linked, no causality) | ✅ |
| **MUST HAVE** | Care & Adherence (record-only, taken/skipped/snoozed, reminders) | ✅ |
| **MUST HAVE** | Clinical dashboard + report history + compare | ✅ |
| **MUST HAVE** | OBSERVED / ASSOCIATED / UNKNOWN care journey | ✅ |
| **HIGH VALUE** | Hardware-agnostic manual readings | ✅ |
| **HIGH VALUE** | Model A–D longitudinal experiment framework (pending) | ✅ |
| **HIGH VALUE** | Ultrasound clinical-entry UI + research-only labeling | ✅ |
| **HIGH VALUE** | Judge Mode clinical-record demo | ✅ |
| **OPTIONAL** | Clinician notes | ✅ (cheap, useful) |
| **DO NOT ADD** | Rupture prediction, AI prescribing, hormone-as-measurement, disease modules, extra sensors | ❌ explicitly excluded |

---

## D. Final V6.2 architecture

```
SENSE ── CHRONO wearable (PPG + temp + IMU + optional GSR)
          │  or compatible device / manual entry        ← hardware-agnostic
          ▼
PERSONALIZE ── 5-min calm baseline → personal normal ranges
          ▼
TRACK ── feature log (offline SQLite, demo excluded)
          ▼
DETECT ── change detector (single / persistent / progressive / recovery)
          │  + personal physiological fingerprint (baseline | current | SD | persistence | slope)
          ▼
EXPLAIN ── WHAT CHANGED SINCE LAST ASSESSMENT? (evidence-linked, category-tagged)
          │  + risk contributors ("contributed to the model estimate")
          ▼
SUPPORT ── Care & Adherence (record an existing plan: taken/skipped/snoozed,
          │  adherence %, goals, appointment reminders — NEVER prescribes)
          ▼
REPORT ── periodic report → report history → COMPARE REPORTS
          ▼
CLINICAL REVIEW ── clinician dashboard: what changed since last visit,
          │  ultrasound (clinical entry), notes, CARE JOURNEY SUMMARY
          │  (OBSERVED / ASSOCIATED / UNKNOWN)
          ▼
CONTINUE MONITORING ── between visits, the longitudinal record keeps growing
```

Research question this architecture exists to test:

> *"How can inexpensive longitudinal physiological information make the period
> between clinical visits more informative?"*

Directly testable via the **Model A–D experiment** (clinical/cycle only vs
conventional snapshot wearable vs CHRONO longitudinal vs full multimodal),
which is deliberately **PENDING** until a labelled longitudinal PCOS dataset
exists.

---

## E–J. What was actually implemented (file map)

| File | Change |
|---|---|
| `src/config.py` | V6.2.0 branding |
| `src/utils/history_store.py` | New tables: `care_medications`, `medication_log`, `care_goals`, `appointments`, `clinical_notes`, `visits`, `reports`; methods for each + `log_manual_vitals` (reuses an open `manual` session) |
| `src/models/fingerprint.py` | `FingerprintEngine` / `FingerprintReport` — per-metric baseline ± spread, current, deviation SD, persistence, slope, trend, quality |
| `src/models/what_changed.py` | `WhatChangedEngine` — category-tagged, evidence-linked items; markdown/plain renderers |
| `src/models/care_plan.py` | `CarePlanManager` — medications + adherence math, due reminders, goals, appointments, `care_gap_analysis` (OBSERVED/ASSOCIATED/UNKNOWN) |
| `src/models/clinical_record.py` | `ClinicalRecord` — visits, notes, ultrasound, report save, `compare_reports`, `what_changed_since_last_visit` |
| `src/validation/longitudinal_experiment.py` | Model A/B/C/D definitions + honest PENDING status |
| `src/ui/fingerprint_widget.py` | Fingerprint table widget |
| `src/ui/care_plan_tab.py` | Care & Adherence tab (meds + log buttons + adherence table, goals, appointments, reminders, safety disclaimer) |
| `src/ui/clinical_tab.py` | Clinical dashboard (What Changed / Report History + Compare / Ultrasound + Notes / Research Model A–D) |
| `src/ui/patient_inputs_tab.py` | Manual wearable-style readings group |
| `src/ui/main_window.py` | 9-tab structure, fingerprint + what-changed wiring, care reminders, Judge Mode clinical seeding |
| `tests/test_v6_2.py` (+ `test_v6.py` update) | 12 new tests; tab-structure assertions updated |

## K. Documented medical limitations

1. The live risk engine is a **fallback equation**, not a validated model — the dashboard says so.
2. No sensor measures hormones; hormone-like values are labelled illustrations with zero score effect.
3. The Model A–D experiment and any wearable accuracy claim are **PENDING** — no dataset in the repo validates the wearable.
4. Ultrasound findings are **clinically entered**; the wearable cannot visualize ovarian anatomy; **no rupture prediction exists**.
5. Care-plan module **records and reminds only** — it never changes/starts/stops medication.
6. No clinical diagnostic accuracy is claimed anywhere.

---

## Final architecture (one line)

SENSE → PERSONALIZE → TRACK → DETECT → EXPLAIN → SUPPORT → REPORT → CLINICAL REVIEW → CONTINUE MONITORING, with the wearable as a replaceable acquisition device and the longitudinal evidence as the innovation.

## New features (this release)

Personal physiological fingerprint · WHAT CHANGED SINCE LAST ASSESSMENT? · Care & Adherence (record-only) · Clinical Dashboard · Report history + COMPARE REPORTS · CARE JOURNEY SUMMARY (OBSERVED/ASSOCIATED/UNKNOWN) · manual wearable-style entry (hardware-agnostic) · Model A–D experiment framework · Judge Mode clinical flow.

## Removed / deliberately not added

Nothing working was removed. Deliberately NOT added: rupture prediction, AI prescribing, hormone-as-measurement, disease modules, extra sensors, generic smartwatch features.

---

## Innovation statement (one sentence)

> CHRONO-PCOS is not another wearable that predicts — it is a low-cost longitudinal phenotyping and clinical-support system that turns the weeks **between** clinical visits into structured, evidence-linked, clinically reviewable information, while refusing to overclaim anything it cannot measure.

---

## 30-second judge pitch

> "PCOS affects 1 in 10 women, diagnosis takes years, and clinics only see
> patients every few months. Between visits, nobody knows what happened. Our
> system is a ₹2,000 wrist pod that records heart rate, HRV, temperature,
> activity and cycle information continuously. It learns *your* normal range —
> not population averages — then watches for persistent, not single-day,
> changes. It produces a plain-language 'WHAT CHANGED?' summary, records
> adherence to the existing care plan without ever prescribing, and gives the
> clinician a timeline of evidence between visits. It is a research
> pre-screening system: it never diagnoses, it never invents numbers, and the
> moment signal quality is poor it refuses to show an estimate. The wearable
> is replaceable — the innovation is the longitudinal evidence."

## 2-minute demonstration script

1. **Connect** — press *Demo Mode*; header badge turns `DEMO MODE (SYNTHETIC)`. *(5 s)*
2. **Live physiology** — Live Wearable tab: PPG waveform, HR ~76 bpm, HRV, temperature with quality scores. *(15 s)*
3. **Personal baseline** — press *Capture baseline*; Longitudinal tab now shows the **fingerprint**: "HR 72 ± 4, current 76, +1.1 SD, stable". *(15 s)*
4. **Longitudinal change** — replay the recorded week; the change panel reports "HRV below personal baseline, persistent ~5 days, slope −1.4/day". *(20 s)*
5. **WHAT CHANGED?** — Overview shows evidence-linked items: cycle length 28→36 d (self-reported), HRV deviation, 3 missed-dose records. *(15 s)*
6. **Care & Adherence** — show the demo plan (Metformin twice daily), taken/skipped log, adherence 92%, "potential care-plan gap" wording. *(10 s)*
7. **Clinical Dashboard** — *WHAT CHANGED SINCE LAST VISIT?*, report history, **COMPARE REPORTS** (month 1 vs now: risk 41→55%, improved/worsened/stable), ultrasound clinical entry, CARE JOURNEY SUMMARY with OBSERVED/ASSOCIATED/UNKNOWN. *(20 s)*
8. **Honesty** — remove the sensor: the banner shows **PREDICTION WITHHELD — INSUFFICIENT SIGNAL QUALITY**; the disclaimer is permanent. *(10 s)*

---

## Top 20 questions a national judge may ask — with answers

1. **Is this a diagnosis?** No. It is a research/pre-screening estimate. Diagnosis requires a clinician, accepted criteria and lab/clinical assessment — the disclaimer is permanent in the UI.
2. **Can PPG measure hormones?** No. No sensor here measures testosterone/AMH/insulin. Hormone-like values are labelled illustrations that demonstrably do not affect the score (there is a test for this).
3. **Where did your risk equation come from?** It is a transparent fallback with defensible domains (cycle regularity, metabolic tendency, autonomic load, sleep, circadian, temperature rhythm, activity, optional BP/glucose). It is honestly labelled FALLBACK until a trained, calibrated model exists.
4. **Is your 0.959 AUC real?** It is a clinical-variable model on a single referral cohort — a model-development result on a public dataset, **never** wearable accuracy. The wearable itself has no validated accuracy yet.
5. **Why should I believe your confidence numbers?** They are computed from signal quality, baseline availability, CI width, feature completeness and cycle information — every component is shown, and confidence is low without longitudinal data.
6. **What happens with one abnormal reading?** Nothing — the change detector requires persistence (multiple out-of-band points) and quality gates; the fingerprint ignores single spikes.
7. **Can you detect a "persistent change"?** Yes — persistence in points and hours, slope per day, and classification into single / persistent / progressive / recovery with a quality gate.
8. **Does your system claim the wearable caused anything?** No — wording is "temporally associated with", and the CARE JOURNEY SUMMARY forces an OBSERVED / ASSOCIATED / UNKNOWN split.
9. **Can your system prescribe or change medication?** No — the care module only records adherence to an existing plan and flags "potential care-plan gaps". There is no prescribe/change API.
10. **What about data leakage in validation?** The validation tab uses subject-level splitting (GroupKFold/LOSO), temporal holdouts, leakage checks; the Model A–D experiment refuses to run without `subject_id` + verified labels.
11. **Why is the Model A–D experiment empty?** Because no public longitudinal wearable + PCOS dataset exists. Fabricating numbers would destroy credibility; the framework is built and honestly PENDING.
12. **What is your actual innovation?** The longitudinal framework: personal baseline, change engine, WHAT CHANGED summary, report comparison, and clinician timeline between visits — not the hardware.
13. **Can it work with any wearable?** Yes — manual wearable-style entry is a first-class path; the longitudinal engine does not care about the acquisition device.
14. **What about ultrasound / cysts?** Ultrasound findings are clinically entered (the wearable cannot see the ovaries) and labelled RESEARCH ONLY — no rupture prediction exists.
15. **Is the data private?** Fully offline-first, local SQLite, user-controlled export, no cloud dependency; demo data is labelled and excluded from real analysis.
16. **Cost?** Prototype BOM ≈ ₹1,200–2,900; scaled ≈ ₹805–1,370 (see `docs/V5_BILL_OF_MATERIALS.md`) — "maximum useful PCOS information per rupee".
17. **Why a wrist pod, not a ring?** Ring is a future miniaturization; the pod is cheaper, more comfortable for long wear, and easier to manufacture/repair by a student team.
18. **Is this a smartwatch app?** No — no notifications feed, no general fitness features; the UI is a research/clinical platform with exactly one medical mission.
19. **What would make it clinically valid?** A consented pilot (N≈20–30, 8–12 weeks, adult/teacher/clinician oversight + ethics approval) with verified labels, then the Model A–D experiment with leakage-proof validation.
20. **What is your biggest weakness?** No validated longitudinal dataset yet — the honest answer is that the central question is *being tested*, not yet *answered*.

---

## Biggest remaining weaknesses

1. **No validated longitudinal dataset** — the central question is unproven; the Model A–D experiment is PENDING by design.
2. **No Python BLE client** — the ESP32 BLE pod path is firmware + design, not yet live end-to-end.
3. **Fallback risk equation** — transparent and honest, but not trained/calibrated.
4. **Firmware rate mismatch** (20 Hz vs 50 Hz assumptions) documented, not yet fixed in firmware.
5. **Cyst module is architecture-only** — no validated outcome dataset, so no prediction.
6. **Adherence math is bookkeeping** — expected-dose counting assumes the recorded plan is correct.

## Exact experiments to run next

1. **Pilot protocol (the only honest path):** N≈20–30 participants (PCOS + control), 8–12 weeks of wearable + cycle + symptom logging, consent + adult/teacher/clinician oversight + institutional ethics approval; verified clinical labels.
2. **Model A–D** on that pilot with GroupKFold by subject, calibration, AUROC/AUPRC/sensitivity/specificity/F1 + confidence intervals.
3. **Ablation per sensor** (PPG / +temp / +IMU / +GSR) to decide which sensors earn their cost.
4. **BLE client + on-device buffering** so the ESP32 pod runs end-to-end.
5. **Firmware fix** for the 20 Hz vs 50 Hz sampling-rate mismatch.
6. **Report-compare validation** — a small user study: do clinicians find the WHAT CHANGED + COMPARE views useful and correct?

## National-level scoring assessment (self-assessment, honest)

| Criterion | Strength | Score (of 10) |
|---|---|---|
| Novelty | Longitudinal clinical-support framing; honest PENDING experiment | 8 |
| Social applicability | PCOS: 1-in-10 women, low-cost Indian context | 9 |
| Affordability | ~₹1,200–2,900 prototype, ~₹805–1,370 scaled | 9 |
| Usability | 30-second pitch, 2-minute demo, low-burden inputs | 8 |
| Comparative advantage | Between-visit evidence vs snapshot apps | 8 |
| Technical depth | Real DSP, quality engine, change detection, baseline, fusion plan | 8 |
| Scientific credibility | No fabricated numbers, leakage-safe validation plan, claim guard | 9 |
| Demonstrability | Full scripted demo incl. withheld state | 9 |
| Reproducibility | 109 automated tests, deterministic demo | 8 |
| Scalability | Hardware-agnostic, offline-first, staged pilot | 7 |
| **Overall** | Coherent longitudinal clinical-support system, not a feature zoo | **8.3** |

The scoring is a self-assessment for planning, not a guarantee — the 
single largest swing factor is the pilot dataset (criterion "evidence").
