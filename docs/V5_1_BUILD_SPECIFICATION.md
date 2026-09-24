# CHRONO-PCOS V5.1 — BUILD SPECIFICATION & V5 AUDIT

**Prepared by:** multidisciplinary R&D review (biomedical engineering, wearable hardware, signal processing, ML, PCOS/reproductive health, digital health, embedded systems, regulatory/IP)
**Date:** 2026-08-17
**Scope:** audit of the existing V5 codebase, then a critical, evidence-driven redesign (V5.1) that serves one purpose only:

> **Estimate an individual's PCOS-related risk and identify when professional clinical evaluation may be appropriate, using inexpensive, non-invasive, longitudinal wearable data.**

This document does not claim to diagnose PCOS, does not fabricate results, and keeps every claim labeled as trained / internally validated / externally validated / clinically validated.

---

## 0. WHAT I ACTUALLY FOUND (verification of the current state)

The V5 repository is substantially larger and more honest than its README implies. Verified facts:

| Item | Verified state |
|---|---|
| Test suite | **84/84 tests pass** (`pytest` in ~4 s). |
| Trained artifacts | `models/pcos_risk_model.joblib` (Kaggle PCOS, 541 rows, patient-level 5-fold CV **ROC-AUC 0.959 / AP 0.932** — single-site referral cohort, **not** the live engine). `models/ppg_quality_model.joblib` (Wrist-PPG-during-exercise, 8 subjects, 903 windows, subject-level CV **AUC ≈ 0.62**). No `stress_model.joblib` / `sleep_model.joblib` / `hormone_models.joblib` exist → those modules run on fallback equations. |
| Live risk engine | `src/models/risk_engine.py` — a **hand-tuned logistic equation** with arbitrary weights (status correctly reported as `FALLBACK` in the Evidence Center). |
| Hormone twin | `src/models/hormone_estimator.py` — 8 hormones, reproductive hormones shown with confidence 15–25%. |
| Change detector | `src/models/change_detector.py` — implemented and tested, **but never called anywhere in the app**. |
| ECG checkpoint / insole / providers / BLE transport | Implemented as standalone modules + tests, **not wired into the dashboard**. |
| Menstrual/symptom UI | DB tables exist (`menstrual_cycle`, `symptoms`, `bp_readings`, `glucose_readings`, `ultrasound_observations`) but **no UI writes them**; only two spinboxes (cycle day, length) in the connection bar. |
| Data pipeline | Raw CSV (every 50 samples), features table (every 10 s), events/calibrations/anomalies/quality/error logs — all local SQLite. No cloud. |
| Public data on disk | Kaggle PCOS (xlsx + infertility + synthetic extension), Wrist-PPG-during-exercise (50 MB WFDB). WESAD/BIDSleep/MESA/MMASH/mcPHASES/NHANES/Pima are **absent** (registry entries only). |
| Real longitudinal wearable+PCOS dataset | **Does not exist anywhere in this project, and (honestly) barely exists in public research.** This is the central constraint of the whole redesign. |

**Biggest architectural gap:** the "continuous wearable" (ring) is firmware + protocol documentation, not a working end-to-end path. The app consumes USB serial or the ESP8266 TCP bridge only; there is no BLE client in the app, and the ring firmware has never been endurance-tested. The interface abstractions (`SensorProvider`, `Transport`, `LocalBuffer`) are skeletons.

---

## 1. V5 AUDIT (A)

### 1.1 Component-by-component classification

Legend: **KEEP** = keep as-is · **IMPROVE** = keep but fix/strengthen · **OPTIONAL** = keep out of the critical path · **REMOVE** = cut from the core product · **FUTURE** = explicitly defer to future research.

| Component | Verdict | Why |
|---|---|---|
| MAX30102 PPG (IR+red) | **KEEP** | HR/HRV are the highest-value continuous signals. Keep IR+red. |
| MPU6050/LSM6DS3 IMU | **KEEP** | Motion gating for PPG + activity/sleep. Cheapest way to make PPG trustworthy. |
| DS18B20 skin temperature | **IMPROVE** | Works on the bench; for skin contact use a small NTC or MAX30205 (see §4). DS18B20 TO-92 is clumsy inside a pod/ring. |
| GSR (optional) | **OPTIONAL** | Stress is mostly covered by HRV; GSR is the first sensor to cut if the ablation shows no gain. Keep behind the optional channel. |
| BH1750 light sensor | **OPTIONAL** | Minor circadian assist; not needed for the core model. |
| BME280 room T/H/P | **REMOVE (from core)** | Artifact correction is nice but the signal-to-cost value is low; room temp is captured with a $0.30 NTC in the pod anyway. Move to research. |
| FSR finger pressure | **REMOVE (from core)** | The "pressure correction" divides PPG amplitude by a linear pressure index; contact-pressure effects on PPG amplitude are non-monotonic and this is unvalidated. PPG amplitude is not in the risk equation. Cut it. |
| MAX4466 microphone / VoxVasc | **REMOVE (from core)** | A pitch-based "androgen proxy" is scientifically indefensible as an input to a PCOS risk score. The module itself admits it is weak. Move entirely to an "Experimental Lab" tab or FUTURE RESEARCH with zero weight in the risk equation. |
| AD8232 ECG (periodic) | **KEEP (periodic)** | Correct role: independent HR/HRV reference for validating PPG. Keep as a checkpoint, never continuous, never a diagnostic claim. **Fix the quality bug** (§1.3 #1) so ECG absence stops harming the score. |
| Smart insole | **FUTURE / REMOVE from core** | Behavioural gait signal with no direct PCOS claim; adds cost and complexity. Keep the code under research; do not build it for the competition. |
| Arduino Mega bench rig | **IMPROVE (bench only)** | Great for the lab demo; it is not the continuous wearable. Rebrand as the "bench/lab rig"; the wearable is the pod (§4). |
| ESP8266 Wi-Fi bridge | **OPTIONAL** | Useful bench convenience; not needed for the product. |
| Signal-quality heuristics (`utils/quality.py`) | **KEEP / IMPROVE** | Good skeleton. Needs the full engine in §5 (contact, packet loss, timestamps, disagreement). |
| SQI + withhold layer (`validation/sqi.py`) | **KEEP / IMPROVE** | Correct concept ("prediction temporarily unavailable"). Has a real bug (see §1.3 #1) and needs per-sensor contact detection. |
| Trained PPG-quality model | **KEEP (soft blend)** | AUC 0.62 on 8 subjects — honestly reported, keep at 40% blend. Do not overstate it. |
| Personal baseline (`personalization.py`) | **KEEP / IMPROVE** | Rolling median/MAD + EWMA + outlier rejection is the right design. Extend to time-of-day and cycle-phase stratification (§6). |
| Anomaly detector (`anomaly_detector.py`) | **KEEP** | Personal-baseline outlier layer is exactly right. Keep, and keep it clearly separate from PCOS-risk claims. |
| Change detector (`change_detector.py`) | **KEEP / WIRE IT IN** | Good design (single/persistent/progressive/recovery + quality gate). **It is dead code today** — it must be called in the app. Add CUSUM/EWMA on top (§8). |
| Risk engine (`risk_engine.py`) | **IMPROVE / REBUILD** | Hand-tuned equation with arbitrary weights; the `endocrine` domain (0.90 weight) is fed by hormone estimates with 15–25% confidence. This is the scientific weak link (see §1.2). |
| Hormone twin (`hormone_estimator.py`) | **REMOVE from core** | Estrogen/progesterone/testosterone/LH/FSH/AMH "levels" from PPG+temp+GSR are not scientifically defensible as displayed values. See §1.2 for the full argument and the replacement. |
| Metabolic model (`metabolic_model.py`) | **KEEP / IMPROVE** | Insulin-resistance proxy from manual glucose + BMI + sleep/stress is the most defensible metabolic feature. Keep, tighten. |
| Sleep estimator (`sleep_model.py`) | **IMPROVE** | Sleep/wake from HR+HRV+motion+time is defensible. **REMOVE the deep/REM "probabilities"** from the core display — they are not stagin-like estimates and invite exactly the "how do you know REM?" question. |
| Stress estimator (`stress_model.py`) | **KEEP** | Defensible autonomic estimate; motion gate is good. |
| Circadian analyzer (`circadian_features.py`) | **KEEP / IMPROVE** | Real cosinor fits exist. **The live feature extractor currently overrides this with a near-constant placeholder** (see §1.3 #4) — wire the real analyzer into the per-tick path. |
| MV-AST metabolic challenge | **REMOVE from core / FUTURE** | PPG-amplitude-ratio "insulin-mediated vasodilation index" is not validated; enters risk at 0.35 weight. Move to Experimental Lab. |
| What-if lab / recommendations | **OPTIONAL** | Nice UX; harmless if clearly labeled as heuristic projections. Keep, don't extend. |
| AI Assistant + LLM mode | **OPTIONAL** | Local grounded mode is fine. LLM mode sends health-derived context to external endpoints — make it explicit opt-in with a warning, default off (§14). |
| Validation Lab (reference pairs, repeatability, LOSO, calibration, leakage, prospective, versioning) | **KEEP** | This is genuinely the strongest part of V5. The honest-evidence culture (Evidence Center, model statuses, training audit, dataset registry) should be preserved and treated as the project's identity. |
| Cyst monitor (`cyst_event.py`) | **FUTURE (gated)** | Already correctly gated "NOT YET TRAINED". Keep only as a status card + schema; never a prediction. |
| Synthetic data / demo stream / judge demo | **KEEP (clearly labeled)** | Essential for the competition. Enforce a hard filter so synthetic rows never mix into real analysis (see §1.3 #5). |
| Digital Twin / Hormone Twin branding | **IMPROVE** | "Digital Twin" over-promises. Rebrand the *hormone* twin as "estimated physiological pattern" and keep the longitudinal profile concept (which is legitimate). |

### 1.2 The single most important scientific problem: the hormone twin + endocrine weight

The risk equation is:

```
z = -2.3 + 1.20·M + 0.90·H + 0.65·S + 0.60·C + 0.50·A + 0.45·G + 0.30·L + 0.20·T + 0.35·MH + 0.35·MV + 0.12·VV
```

where `H` (endocrine, weight **0.90**) is computed from insulin, testosterone, LH/FSH, progesterone, cortisol, AMH and an estrogen term — reproductive hormones estimated from skin temperature, GSR, HRV and time-of-day, with confidence 15–25% and 60–80% relative uncertainty. The numbers are internally honest (wide CIs, "estimated, not measured") but **scientifically they are near-arbitrary**: there is no validated non-invasive pathway from wrist PPG/temperature to testosterone, LH, FSH, or AMH. Feeding a 0.90-weighted domain with near-noise inputs does not add signal — it adds a noisy constant that inflates the risk number and gives judges the easiest possible attack ("you cannot measure AMH, so what is this number?").

**Recommended change (V5.1):**

1. **Remove individual reproductive-hormone values from the risk path.** Keep, at most, an explicitly-labeled *latent endocrine-pattern index* (a model-derived composite, e.g., "metabolic–endocrine pattern score 0–100", with a definition like "combines cycle irregularity, metabolic tendency and autonomic load").
2. Restructure the risk domains to what the sensors and inputs can actually support:
   - **Cycle irregularity** (from the user log — this is the single strongest, defensible PCOS signal; currently nearly absent from the app!),
   - **Metabolic tendency** (manual glucose + BMI + sleep + stress; defensible),
   - **Autonomic/stress** (HR/HRV; defensible research association),
   - **Sleep regularity** (sleep/wake from HR/HRV/motion/time),
   - **Circadian/temperature rhythm** (cosinor amplitude/acrophase/stability),
   - **Activity** (IMU),
   - optional **BP** and **glucose**.
3. Move all individual hormone values to an "Illustrative / research" tab with a permanent "cannot be measured by these sensors" banner, zero weight in risk.

This one change makes the system *stronger for competition judging*: the story becomes "we track physiological patterns plausibly associated with PCOS and combine them with the strongest clinical signal the user can give us (cycle regularity)" instead of "we estimate your hormones from your wrist."

### 1.3 Bugs, inconsistencies, and dead code found

| # | Issue | Severity |
|---|---|---|
| 1 | `src/features/realtime_features.py` (`compute()`): `signal_quality` is a mean of `[ppg_quality, ecg_quality, temp_present, gsr_present, motion>=0]`. `ecg_quality` is 0.0 when ECG is absent, and `motion>=0` is always 1.0. → **Missing optional ECG drags the overall SQI down** and can trigger the withhold gate even though ECG is explicitly optional. Fix: mean over *present* sensors, and drop the always-true motion term. | High |
| 2 | Mega firmware streams packets at **20 Hz** (`PACKET_PERIOD_MS 50`) while the ring streams at 50 Hz and the SQI feature math (`ppg_window_features`) assumes a fixed `fs_hz` (FFT bins, zero-crossing rate, sample-count peak distance). HR/HRV are timestamp-based (fine), but **SQI-model features computed on Mega data are mis-scaled**. Fix: the parser must carry the true device rate, or the ring is the only supported continuous source and the Mega is explicitly "bench only". | Medium |
| 3 | **`ChangeDetector` is never called** by the app — the flagship V5 "longitudinal change detector" exists only in tests. ECG checkpoint, insole, providers, transport are likewise unwired. The docs overstate integration. | High (claims vs reality) |
| 4 | In `realtime_features.compute()` the circadian index is a placeholder `50 + 20·min(completeness,1)` capped at 70 until the 60 s timer overwrites it; `temperature_rhythm_disruption` is 50→35 — effectively a constant — yet the risk equation gives the circadian domain **0.60 weight**. A constant term inflating every risk number is a bug by design. | High |
| 5 | `generate_week` writes synthetic rows into the **same SQLite DB** as real sessions. Rows are labeled synthetic, but the Research Lab then computes "model performance vs synthetic labels" in the same store. Enforce a hard `source='synthetic'` filter (or a separate DB) for anything labeled as analysis. | Medium |
| 6 | `_risk_from_scores` includes `mv` (0.35) and `vv` (0.12) terms that are 0 by default (challenge not run, voice off) — a constant offset in every baseline risk; `counterfactual_ablation` skips them, so the ablation table and the equation disagree. | Medium |
| 7 | The Kaggle model's **0.959 AUC is quoted in the README/models** as a headline. It is a single-site referral cohort, and it is **not** the live engine. Judges may read it as "this wearable achieves 96% AUC". Add an explicit line: "0.959 = clinical-variable model on one referral dataset; NOT the wearable pipeline; wearable performance is NOT YET VALIDATED." | Medium (claim hygiene) |
| 8 | `data/ai_config.json` stores API keys in plaintext; LLM mode sends context (health-derived numbers) to external endpoints. Opt-in today, but no warning. See §14. | Medium (privacy) |
| 9 | Deep/REM "probabilities" from HRV+time are presented in the sleep view; AMH (own README: "cannot be estimated in real time") is displayed. Both invite exactly the questions a judge should ask. | Medium (scientific) |
| 10 | `BaselineManager.update_observation` blends in `cur.std`/`cur.mad` fields that are never populated during capture (`MetricStats` created without MAD) — the rolling update path has latent bugs in the scale math (e.g., `cur.mad` starts 0 → first EWMA update multiplies by 0). Tests pass because they exercise the capture path more than the update path. | Low-Medium |

### 1.4 What is genuinely good and must be preserved

- The **evidence culture**: model statuses (TRAINED / NOT TRAINED / FALLBACK / NOT YET TRAINED), training audit JSONL, dataset registry with SHA-256 and synthetic separation, leakage checks, LOSO CV, calibration, Bland-Altman, prospective-validation scaffolding, claim guard. This is what separates this project from typical competition projects. **Keep every part of it.**
- The personal-baseline design (rolling median/MAD, outlier rejection).
- The withhold-the-number decision layer.
- The fully offline SQLite architecture.
- The 84-test suite. Add tests for every V5.1 change.

---

## 2. RECOMMENDED V5.1 ARCHITECTURE (B, matches §23 of the brief)

```
WEARABLE POD (wrist, §4)
  PPG (IR+red) · skin temp (NTC/MAX30205) · IMU · [optional GSR]
  BLE notify + on-board buffering (seq + CRC16) + battery %
        │  sync on reconnect
SIGNAL-QUALITY ENGINE (§5)
  per-sensor SQI · contact detection · motion gate · packet-loss /
  timestamp / sync checks · PPG↔ECG disagreement when ECG present
        │  quality-gated
ARTIFACT REMOVAL + FEATURE EXTRACTION (§7)
  night/rest windows → resting HR, HRV(RMSSD/SDNN), temp amplitude/
  acrophase/nadir, sleep/wake, activity, GSR tonic     (deep/REM: removed)
        │
PERSONAL BASELINE (§6)
  time-of-day × cycle-phase stratified medians/MAD
  → z-scores, deviation, rate-of-change, persistence, trajectory
        │
LONGITUDINAL CHANGE DETECTION (§8)
  CUSUM/EWMA change-points + single/persistent/progressive/recovery
  classifier (the existing ChangeDetector, now wired in)
        │
DAILY FEATURE TABLE (one row per day per person)
  absolute + baseline-deviation + trend + persistence features,
  with per-sensor availability masks (missing-data strategy, §9)
        │
TEMPORAL FUSION MODEL (§10)  ← LightGBM/XGBoost w/ temporal features
  subject-level GroupKFold + forward-chaining; calibrated probabilities;
  SHAP for explanations; ablation to decide which sensors stay
        │
PCOS-RELATED RISK ESTIMATE + UNCERTAINTY (§11)
  risk %, calibrated CI, coverage gate (≥7 days / ≥3 nights),
  OOD flag (Mahalanobis)
        │
EXPLAINABILITY (§12)
  top contributors · baseline vs current · "why did it change" ·
  data quality per sensor
        │
DASHBOARD (§16)
  Overview card (risk, confidence, data quality, coverage, contributors),
  Cycle Log (1-tap), Experimental Lab (VoxVasc/MV-AST/insole/cyst gated),
  Evidence Center (unchanged philosophy)
```

**Supporting inputs:** periodic ECG checkpoint (HR/HRV reference + validation of PPG) · manual BP · manual glucose · 1-tap cycle/symptom log · optional medication flag.

---

## 3. PRESERVE THE CORE HARDWARE (from the brief)

### 3.1 What we keep and why

| Sensor | Cost | Power | Info gain for PCOS-risk | Comfort | Reliability | Verdict |
|---|---|---|---|---|---|---|
| **PPG (MAX30102)** | $4–7 | 1–3 mA avg (duty-cycled) | **High** — resting HR + HRV + sleep/wake, the core longitudinal signals | High (small window) | Moderate — motion sensitive (that's why the quality engine exists) | **KEEP** |
| **Skin temp** (NTC $0.30 / MAX30205 $4) | $0.3–4 | <0.5 mA | **High** — circadian temperature rhythm (amplitude, acrophase, nadir) is a genuine, longitudinal, PCOS-adjacent signal; NOT claimed as core-BBT | High | High | **KEEP** |
| **IMU** (MPU6050/LSM6DS3) | $2–4 | 0.5–1 mA | **High** — motion gating for PPG (without it PPG is untrustworthy), activity, sleep/wake | High | High | **KEEP** |
| **GSR** (optional) | $3–6 | ~1 mA | **Low-Medium** — stress partially redundant with HRV; ablation decides | Medium (electrodes) | Low-Medium (contact drift) | **OPTIONAL** — include the channel, default off, cut if ablation says so |
| Light, BME280, FSR, mic, insole, second DS18B20 | — | — | Low / none for the core question | — | — | **REMOVE from core** |

**Rejected sensors:** any blood-glucose/lactate optical sensor (expensive, unvalidated at this price, not necessary), chest-strap HR (uncomfortable 24/7), EEG (irrelevant to the question, cost), core-body-temp ingestible/tympanic (not wearable), cuff BP on-device (manual input is enough).

### 3.2 The wearable requirement matrix (from the brief)

Lightweight ✓ (~30–40 g) · wireless ✓ (BLE) · rechargeable ✓ (Li-ion + pogo/TP4056) · comfortable for prolonged use ✓ (silicone strap, pod on the wrist) · inexpensive ✓ (₹1,200–2,500 prototype, §13) · easy to manufacture ✓ (3D-printed pod + strap, breakout boards) · easy to clean ✓ (sealed pod, wipeable strap) · resistant to motion artifacts ✓ (IMU-gated quality engine, night/rest windows) · local buffering ✓ (flash + seq/CRC16, sync on reconnect) · BLE/Wi-Fi ✓ (BLE primary, USB serial for bench) · usable without a laptop ✓ (buffers while away).

---

## 4. FORM-FACTOR EVALUATION AND RECOMMENDED DESIGN (C, D, E)

### 4.1 Comparison

| Criterion | Wrist band/pod | Finger ring | Finger clip | Upper-arm patch | Ear (bud/lobe) | Forearm pod + fingertip clip |
|---|---|---|---|---|---|---|
| PPG quality | Medium (motion, perfusion) | **High** (high perfusion, anchored) | **Very high** (best site) | Medium | High (lobe) | Very high |
| Motion artifact | Medium (mitigated by quality gate + night windows) | Low | High (knocked off) | **Low** | Low | Medium |
| Comfort 24/7 | **High** | High | Low | Medium (adhesion) | Medium | Low-Medium |
| Skin temp | Medium (wrist, ambient-coupled) | Low (finger, ambient-dominated) | Low | **High** (closer to core) | High (ear canal) | Medium |
| Battery life | **Best** (50–250 mAh, big pod) | Small cell, short | n/a (tethered) | Small | Small | Medium |
| Manufacturability (student team) | **Easiest** (breakout boards in a pod) | Hard (sizing, optical window, flex PCB) | Easy but not wearable | Medium (adhesive) | Medium | Medium |
| Cost | **Lowest** | Medium | Low | Medium | Medium | Medium |

**Primary recommendation: a wrist-worn pod** (a small smartwatch-style puck with no screen) worn on the underside of the wrist, with the PPG window and the temperature sensor pressed against the skin. Rationale:

1. It is the only form factor that scores well on **all** of: 24/7 comfort, battery, cost, and manufacturability by a school/startup team — and the scientific question is *longitudinal*, so wear time and data coverage matter more than the last 1% of PPG SNR.
2. The wrist site is adequate for the *features that matter* — resting HR, HRV, sleep/wake, temperature rhythm — **provided** the system leans on night/rest windows (low motion) and the quality engine rejects everything else. Wrist PPG during the day is treated as activity/lifestyle context, not as a source of precise HRV.
3. Manufacturing a ring that actually stays on a finger with correct optical contact is a flex-PCB + precision-enclosure problem; a pod + strap is a weekend 3D-print problem.

**Honest caveat (also a research opportunity):** the ring gives cleaner PPG/HRV. Therefore the recommended design keeps the *sensor stack identical* so a ring variant ("Phase-2 pod") is a drop-in mechanical change, and the ablation study (§11 of the brief → §17 of this doc) decides whether ring-class PPG quality is worth the manufacturing cost. The wrist pod is the primary, buildable-now form factor.

### 4.2 Exact hardware list (wrist pod, prototype)

| # | Part | Qty | ~Unit cost | Notes |
|---|---|---|---|---|
| 1 | ESP32-C3 module (or DevKit) | 1 | $3–5 | BLE + flash buffering; cheapest BLE-capable MCU with enough RAM |
| 2 | MAX30102 breakout | 1 | $4–7 | IR+red PPG; 0x57 |
| 3 | MPU6050 (or LSM6DS3) breakout | 1 | $2–4 | 6-axis; AD0→GND |
| 4 | MAX30205 (I2C, ±0.1 °C) **or** 10k NTC + 4.7k | 1 | $4 / $0.30 | skin temp; MAX30205 if budget allows, NTC otherwise |
| 5 | Li-ion 150–250 mAh + TP4056 + 3.3 V LDO (HT7333) | 1 | $2–4 | rechargeable; never raw 4.2 V into sensors |
| 6 | Slide switch + 100 nF decoupling | 2–4 | $1 | power isolation, I2C stability |
| 7 | 3D-printed pod + silicone strap | 1 | $1–3 | see §4.3 |
| 8 | [optional] GSR: 2 Ag/AgCl pads + op-amp stage | 1 | $3–5 | on strap inner face; default off |
| — | **Total (core)** | | **$14–27 (₹1,200–2,300)** | without GSR |

Bench/lab: existing Arduino Mega rig remains for the demo; ECG patch (AD8232, $5 + electrodes) for periodic checkpoints.

### 4.3 Physical design (E)

**Pod (45 × 30 × 14 mm, ~28 g):**
- Base: 3D-printed ABS/PA12, two halves. Lower half has a raised **optical boss** (soft silicone ring around the MAX30102 window) so the sensor is spring-loaded against the skin; a 1.5 mm clear epoxy window over the LED/PD aperture.
- Temperature: MAX30205/NTC mounted in a **metal button** (5 mm coin) pressed onto the skin through a 2 mm foam aperture that thermally insulates it from ambient; the pod's ambient NTC (0.30) reads room temperature for drift correction.
- IMU on the same rigid PCB as the MCU; battery on top separated by a 1 mm foam pad so its heat does not reach the temperature sensor.
- Electronics: one small 2-layer PCB (28 × 20 mm) — ESP32-C3 + MAX30102 + MPU6050 + MAX30205 + TP4056; through-hole breakout first, SMD when cost-optimizing.
- Sealing: seam-weld/silicone-pot the top half; **IP54**. Strap: 22 mm silicone, quick-release; pod removable for charging via **pogo pins** (no USB port in the pod).
- Cleaning: wipe strap with soap/water; pod surface with isopropyl; never submerge electronics.

**Firmware behavior (reuse `arduino/chrono_pcos_v5_ring` sketch as the base):**
- BLE notify service + **on-board buffering to LittleFS flash**: `(seq, ts, payload)` with CRC16-CCITT framing (reuse `BlePacketProtocol` framing on-device); sync on reconnect; report exact dropped counts (the `LocalBuffer` semantics, now real).
- Duty cycling: PPG+IMU bursts (e.g., 30 s every 5 min) during the day; **night mode** (wear-detected via IMU + clock) samples continuously at 25–50 Hz for sleep/HRV windows; temp at 1 Hz always (cheap); battery % via divider.
- Status bits: PPG absent / saturation / temp open / battery low / IMU fault — mirror the existing status-bit scheme so the parser keeps working.

---

## 5. SIGNAL-QUALITY ENGINE (F, §4 of the brief)

Keep the existing `sqi.py` decision layer and `quality.py` heuristics; add the missing pieces. Per-sensor SQI, all 0–1:

| Check | What it does | Gate |
|---|---|---|
| **PPG contact SQI** | IR DC in valid range; AC/DC ratio plausible; autocorrelation regularity; IBI plausibility (35–210 bpm, <25% median deviation); trained-model blend (existing, keep at 40%); **motion cross-check** (IMU) | if SQI < 0.4 → HR/HRV features = missing |
| **PPG↔ECG disagreement** | When a periodic ECG checkpoint exists, |PPG HR − ECG HR| > 5 bpm → PPG HR/HRV down-weighted until revalidated | only when ECG present |
| **Temperature validation** | Plausible range (25–40 °C); slew-rate limit (≤0.5 °C/min) to reject spikes; **ambient-coupling check** (skin temp tracks room temp with |corr|>0.8 → flagged "environmentally coupled, low info") | temp SQI < 0.4 → temperature features missing |
| **GSR contact** | Raw in valid band, <5% saturated/clipped, slow tonic drift < 20%/h (electrode drying → flag) | optional channel |
| **IMU sanity** | Finite, bounded (±16 g), no frozen axis; used for motion gating of PPG | gates PPG |
| **Packet loss** | Sequence gaps from the transport layer → coverage % and "dropped frames" surfaced honestly | shown in UI |
| **Timestamp validation** | monotonic, per-source rate within ±20% of nominal; device-ms vs host-clock drift correction; sync events logged | protects longitudinal integrity |
| **Sensor disagreement** | PPG vs ECG (above); temp0 vs temp1 (when 2 sensors); GSR vs stress expectation | flags |

**Overall decision (extend existing `should_withhold`):**
- `NO prediction` state when: core-SQI < 0.4, OR no HRV in the current window, OR CI too wide, OR longitudinal coverage < 7 days (see §11). The dashboard then says, exactly as the brief demands: **"Insufficient signal quality — prediction temporarily unavailable,"** with a per-sensor breakdown of *why*.
- **Bug fix #1 is part of this section:** SQI = mean over **present** sensors only; ECG absence must not penalize; motion term removed.

---

## 6. PERSONAL BASELINE / "DIGITAL TWIN" (I, §5 of the brief)

Keep the existing median/MAD/EWMA manager (it is good). Add:

1. **Stratified baselines**: maintain normal ranges per **time-of-day bin** (2 h bins; night vs day separate for HR/HRV because they are different physiologies) and per **cycle phase** (menses/follicular/ovulatory/luteal/unknown) when cycle data exists. A "deviation" is always computed against the right stratum, so a normal luteal temperature rise is not flagged as an anomaly.
2. **Metric set** per day (from night/rest windows where possible): resting HR (night 5th percentile), RMSSD, SDNN, temp nadir, temp amplitude (max−min), temp acrophase (cosinor), sleep onset/midpoint/wake, sleep duration, sleep regularity (SD of midpoint), activity, GSR tonic.
3. **Deviation features** for every metric (these become model inputs): absolute value, robust z vs baseline, abs change, pct change, **rate of change** (slope/day over 7 d), **persistence** (consecutive out-of-band days), **variability** (SD of daily values), **trajectory** (sign and slope), **circadian characteristics** (amplitude, acrophase stability).
4. **Explicit three-way distinction** (already the ChangeDetector's design — wire it in and surface it in the UI):
   - **Single-day deviation** (1 day, z > 3): informational, never a risk claim.
   - **Persistent deviation** (≥3 consecutive days, z > 2): feeds the model.
   - **Progressive change** (≥7 days with significant slope): feeds the model with higher weight.
   - One abnormal reading must never move the baseline (the existing |z|>3.5 rejection handles this — keep it).

---

## 7. FEATURE EXTRACTION PIPELINE (G, §6 of the brief)

**Raw → features, all computed in the app today (kept):** HR, RMSSD, SDNN, pNN50, pulse amplitude, SpO₂-est (display only, **not** a risk input), motion index, activity, skin temp + slope + stability, GSR tonic/phasic, sleep/wake probability, stress index, insulin-resistance proxy, glucose risk, BP risk.

**Added in V5.1:**
- Night-window aggregates (resting HR, RMSSD, SDNN) — the single most valuable longitudinal features.
- Temperature rhythm features: daily amplitude, acrophase, nadir, and their week-over-week stability.
- Cycle features: current phase, days since period, cycle-length irregularity (SD of last 6 lengths), bleeding-day count, symptom flags (pain, hirsutism, acne, weight change) as binary inputs.
- Baseline-deviation features (§6.3) for every core metric.
- **Explicitly removed from features:** deep/REM probabilities, VoxVasc score, MV-AST indices, FSR correction, SpO₂ (from risk), AMH and individual reproductive hormones (from risk).

---

## 8. CHANGE-POINT + ANOMALY DETECTION (J, §14–15 of the brief)

**Change-point layer (new, on top of the existing classifier):**
- **EWMA/CUSUM** on daily z-scores of resting HR, RMSSD, temp amplitude, cycle length — a CUSUM chart with control limits (±2σ, head-start) gives "the process mean shifted at day X" with an honest statistical basis.
- Keep the existing single/persistent/progressive/recovery classifier as the *semantic* layer on top of CUSUM events.
- **Do not overreact:** require ≥3 consecutive out-of-band days (already the design) and CUSUM signal persistence ≥ 5 days before "progressive change" is stated.

**Anomaly layer (keep, sharpen):**
- Keep personal-baseline outlier detection as-is (it correctly answers "unusual *for this person*").
- Add an optional **Isolation Forest / robust Mahalanobis** on daily feature vectors to flag multivariate outliers (e.g., a day where HR, temp, and GSR all shift together). Present it as "unusual pattern day", explicitly **not** "PCOS pattern".
- Keep the two concepts visually separate: "deviation from your normal" (anomaly) vs "PCOS-associated pattern" (risk model). The risk model consumes persistence and trend, never a single anomaly event.

---

## 9. MULTIMODAL FUSION + MISSING-DATA STRATEGY (K, §7 of the brief)

The model must work with any subset of sensors (A: wearable only; B: + cycle/symptoms; C: + BP/glucose; D: + periodic ECG). Design:

1. **Per-sensor availability mask** as model features: `has_ppg, has_temp, has_imu, has_gsr, has_cycle, has_glucose, has_bp, has_ecg` (and their SQI grades). The model explicitly learns what missing means instead of us pretending it doesn't.
2. **Imputation, in order:** (a) last valid personal value (carry-forward), (b) time-of-day/cycle-phase baseline median, (c) global median. Every imputed feature carries the mask flag.
3. **Quality-weighted fusion at the feature level:** if PPG SQI < 0.4, HR/HRV features are set to missing (not filled with garbage); if temp SQI low (ambient-coupled), temperature rhythm features are missing; etc.
4. **Training:** the GBDT sees the masks at train time, so it can learn "this person has no glucose → glucose contributes nothing" rather than "glucose = median".
5. **Configurations A–D are exercised in the ablation study (§17)** — the model is trained with and without each input group and the *measured* gain decides what ships.

---

## 10. ML ARCHITECTURE (H, §6 of the brief)

**Decision: gradient-boosted trees (LightGBM or XGBoost) on daily temporal features, with subject-level grouped CV and probability calibration. No Transformer, no deep temporal model, at this stage.**

Why (against the brief's checklist):

| Criterion | Reality | Choice |
|---|---|---|
| Dataset size | ~541 clinical rows; **zero** real longitudinal wearable+PCOS rows today | Trees need ~10–100× less data than deep nets |
| Computational requirements | Runs on a school laptop, offline | Trees are trivially deployable |
| Interpretability | SHAP on trees is standard, fast, and honest | Trees win |
| Overfitting risk | Small data + noisy sensors → deep models will memorize | Regularized GBDT with early stopping |
| Performance | With <1,000 samples, GBDT/trees are competitive or better than deep models in most tabular benchmarks | Trees win |
| Deployment feasibility | Desktop offline Python | Trees win |

**Staged plan (honest):**
- **Now:** GBDT on engineered daily features (absolute + deviation + trend + persistence + masks + cycle). Calibrated (isotonic) on validation folds. SHAP explanations.
- **When** a real longitudinal dataset reaches ~100+ subjects × 30+ days: evaluate a **temporal-CNN/GRU** baseline against the GBDT. Adopt deep temporal modeling **only if** it beats the GBDT by ≥0.02 AUROC with non-overlapping CIs. A Transformer is not on the table at any foreseeable dataset size for this project; if one is ever considered it must win the same head-to-head.
- The **live dashboard** keeps the explainable equation engine as a transparent fallback (`FALLBACK` status), but V5.1 adds a second mode: when a trained fusion model exists, the live risk comes from the **trained model with SHAP-derived contributions**, and the equation is only the no-model fallback. This is the key fix to the "0.96 AUC model that the app doesn't use" problem.

---

## 11. UNCERTAINTY STRATEGY (L, §13 of the brief)

Replace the "bootstrap of a hand-tuned equation with added Gaussian noise" with:

1. **Calibrated probabilities**: isotonic/Platt calibration on out-of-fold predictions; report Brier + ECE on the validation folds (the existing calibration module already does this — reuse it).
2. **Confidence intervals**: from the GBDT's out-of-fold prediction distribution (bootstrap or quantile regression) — i.e., *empirical* residual spread, not injected noise.
3. **Coverage gate (the most honest uncertainty display):**
   - < 7 days or < 3 nights of data → **"Insufficient longitudinal data — prediction unavailable"** (or a wide "preliminary" band).
   - 7–30 days → "preliminary, CI ±X".
   - > 30 days + ≥ 5 nights/week → "longitudinal estimate".
4. **OOD detection**: Mahalanobis distance in the feature space + per-feature plausibility; flag "inputs outside the model's training range — treat with caution."
5. **Never invent confidence.** The displayed confidence is a function of (calibration residual, coverage, SQI, missingness) computed from actual data.

---

## 12. EXPLAINABILITY (M, §16 of the brief)

- **Trained model mode:** SHAP values per prediction → top-5 contributing features, aggregated to sensor/domain level ("HRV trend +2.1", "cycle irregularity +1.8", ...).
- **Fallback equation mode:** exact per-domain contributions (the current `_contributions` — keep).
- **Temporal explanation** ("why did the risk change?"): compare the current day's features to the 7-day baseline-mean features; show which deviations moved and for how long (reuse the ChangeDetector output).
- **Dashboard answers the six questions** of the brief explicitly: (1) what changed, (2) how large, (3) how persistent, (4) which features contributed, (5) how confident, (6) is data quality sufficient.

---

## 13. DATASET & VALIDATION STRATEGY (N, §18–19 of the brief)

### 13.1 Existing datasets — honest assessment

| Dataset | Present? | n | What it can validate | What it CANNOT validate |
|---|---|---|---|---|
| Kaggle PCOS (clinical) | ✅ | 541 (1 site, referral) | Which *clinical* variables correlate with PCOS (feature relationships) | The wearable pipeline (no wearable data at all) |
| Wrist PPG during exercise | ✅ | 8 subjects, 19 recs | PPG motion-artifact / HR-reliability model (already done, AUC 0.62) | Anything PCOS-related |
| Synthetic week generator | ✅ | n/a | UI/demo only | **Nothing** — must never be cited as validation |
| WESAD | ❌ | — | stress model (once downloaded) | PCOS |
| BIDSleep / MESA | ❌ | — | sleep/wake from HR+ACC | PCOS |
| MMASH / mcPHASES / NHANES | ❌ | — | hormone priors, cycle rhythms (illustrative only) | wearable-PCOS prediction |
| **Real longitudinal wearable + PCOS labels** | ❌ | **0** | — | — |

**The decisive fact: there is no public dataset of continuous wearable (PPG+temp+IMU) data with PCOS outcomes.** Anyone claiming external validation of such a system is fabricating. The project's job is therefore to (a) validate each *sensor-level* model on public data, and (b) collect its own small pilot.

### 13.2 Staged research strategy

- **Phase 0 — per-signal models (public data):** PPG quality (done), stress (WESAD, once downloaded), sleep/wake (BIDSleep/MESA), temperature-rhythm physiology (MMASH/mcPHASES as *physiological context*, not PCOS proof).
- **Phase 1 — clinical-variable model (done, but relabel):** the Kaggle model tells us which *clinical* features matter (age, BMI, cycle, androgens, follicle count). Use it for feature-importance education only. Add the explicit disclaimer (§1.3 #7).
- **Phase 2 — own pilot (the only way forward):** N ≈ 20–30 consenting volunteers, 8–12 weeks, wrist pod + daily 1-tap cycle/symptom log + validated screening questionnaire (e.g., self-reported cycle regularity + modified Ferriman–Gallwey + BMI + acne) + optional clinician evaluation. Labels: PCOS-likely vs not, by predefined criteria. This is a school project, so frame it as a **research-pilot protocol** (ethics/consent form), not a clinical trial.
- **Phase 3 — external validation:** a second site/cohort before any claim beyond "internally validated pilot".

### 13.3 Validation methodology (keep and extend the existing lab)

- **Subject-level GroupKFold** (already the default — keep).
- **Forward-chaining temporal splits** (train on earlier days, test on later days) — new, essential for longitudinal claims.
- **Leakage checks** (already exist) — extend to "same-day windows of the same subject", "normalization fit on train only", "labels not derived from features".
- **Class imbalance** — the pilot will be ~20–30% positive; report AUPRC, not just AUROC; use balanced metrics.
- **Calibration** (Brier/ECE, reliability curves — exists).
- **Confidence intervals on all metrics** (bootstrap over folds/subjects).
- **Explicit labeling**: TRAINED / INTERNALLY VALIDATED (public-data sensor models + pilot LOSO) / EXTERNALLY VALIDATED (nothing qualifies yet) / CLINICALLY VALIDATED (never claimed).

---

## 14. PRIVACY & ETHICS (§21 of the brief)

- **Offline-first: keep.** All processing local; the DB stays on the machine.
- **Encryption at rest:** add optional SQLCipher (or document + provide `encrypt_db` utility); at minimum, the raw CSV export should not be written by default outside an explicit export action.
- **User controls:** export CSV/JSON (exists), **delete-my-data** button (add), device-unlink.
- **Consent:** first-run consent dialog for research use; anonymized research export strips participant ID and all free-text fields.
- **Optional LLM assistant:** default OFF; when enabled, show a warning that the context (health-derived values) is sent to a third-party endpoint; never include participant ID or free text; store no keys in the repo (`data/ai_config.json` is gitignored in practice — verify).
- **No cloud by default; no advertising; no third-party analytics.**

---

## 15. ECONOMIC FEASIBILITY (P, §20 of the brief)

### Prototype BOM (one unit, wrist pod)

| Item | ₹ | Notes |
|---|---|---|
| ESP32-C3 module | 300–450 | |
| MAX30102 breakout | 350–600 | |
| MPU6050 breakout | 180–350 | |
| MAX30205 (or NTC) | 330 / 25 | NTC if budget-tight |
| 200 mAh LiPo + TP4056 + LDO | 180–350 | |
| PCB (2-layer, 5 pcs) | 150–400 | ~₹30–80/board amortized |
| Pod 3D print + silicone strap | 100–250 | |
| Switch, caps, wires, epoxy | 100 | |
| **Total prototype** | **₹1,690–2,850 (~$20–34)** | one-off, breakout boards |

### Scaled product BOM (1,000 units)

| Item | ₹/unit |
|---|---|
| ESP32-C3 (bare) | 120–180 |
| MAX30102 (bare die/module) | 200–350 |
| LSM6DS3 (IMU) | 100–150 |
| NTC + thermistor circuit | 15–25 |
| 150 mAh LiPo | 80–120 |
| TP4056 + LDO + passives | 40–60 |
| PCB (panelized, 2-layer) | 60–120 |
| Enclosure (molded silicone + insert) | 80–150 |
| Assembly + test | 100–200 |
| **Total scaled** | **₹800–1,360 (~$10–16)** |

**Removable without hurting the core:** GSR channel (−₹150–300), second temperature sensor (−₹25), light sensor, BME280, FSR, insole, OLED, buttons, buzzer. **Keep: PPG + IMU + skin temp + MCU + battery + buffering.** That is "maximum useful PCOS information per rupee": ≈ ₹1,200 for the working wearable.

---

## 16. DASHBOARD CHANGES (Q, §12/§23 of the brief)

1. **Overview card** → a single "Longitudinal Assessment" panel:
   - Risk % (or "prediction temporarily unavailable"), calibrated CI, confidence (from §11), data quality per sensor (bars), **longitudinal coverage** (days, nights, weekly cadence).
   - **Top contributing factors** (SHAP/contributions) with the six explanation questions visible.
   - **Personal baseline vs current state** comparison table (metric, baseline, today, z, trend, persistence).
   - **"Why did the risk change?"** delta panel (this week vs last week by domain).
2. **Cycle Log** (new, 1-tap): "period started today", "cycle day (auto)", "symptoms today: pain / hair growth / acne / weight / none" (checkboxes), "medication: yes/no (optional name)" — ≤ 5 taps/day, 3 defaults. This is the highest-value user input and the least developed today.
3. **Experimental Lab** tab (rename of VoxVasc/MV-AST + insole + cyst status): everything explicitly "research only, zero weight in risk".
4. **Wire in the existing modules that are dead code:** ChangeDetector (Longitudinal tab), ECG checkpoint workflow (Validation tab), LocalBuffer stats (Diagnostics).
5. **Evidence Center**: unchanged philosophy; add the new fusion model + the explicit "wearable pipeline NOT YET VALIDATED" statement.
6. **Remove from core displays:** deep/REM probabilities, AMH, individual reproductive hormone numbers (move to illustrative tab).

---

## 17. ABLATION-STUDY PLAN (O, §17 of the brief)

Fixed protocol — subject-level 5-fold CV (and forward-chaining), ≥3 seeds, report mean±SD of **AUROC, AUPRC, sensitivity, specificity, F1, ECE** on the pilot data (and, for sensor-level claims, on the public datasets where they apply). No fabricated numbers; if a modality shows no gain, it is removed.

| Model | Inputs |
|---|---|
| A | PPG only (night resting HR, RMSSD, SDNN) |
| B | A + temperature rhythm (amplitude, acrophase, nadir stability) |
| C | B + IMU (activity, sleep/wake, motion-adjusted quality) |
| D | C + GSR |
| E | Wearable + cycle/symptom log |
| F | Wearable + BP/glucose |
| G | Full (C + cycle + BP/glucose + periodic-ECG-derived features when present) |

Decision rules: keep a modality if AUPRC gain ≥ 0.01 with non-overlapping CIs, else remove. A priori expectations (to be confirmed, not assumed): **cycle/symptoms (E) will add the most**; **GSR (D) is the most likely cut**; **ECG checkpoint features (G) will improve calibration more than discrimination**; BP/glucose will help only in the metabolic sub-group.

---

## 18. WHAT MUST NOT BE ADDED (S, §22 of the brief)

**Explicitly rejected from the V5.1 core** (all listed as FUTURE RESEARCH only if ever mentioned):
- Cancer detection, ovarian-cancer detection, cyst-rupture prediction (already gated — keep gated forever without real outcome data),
- Diabetes diagnosis, general disease detection, "health score"-style disease modules,
- Sensors without an ablation-demonstrated benefit (any new sensor must pass the §3.1 table),
- Voice-based androgen claims, "direct hormone measurement" claims,
- Transformers/deep models "because they sound advanced",
- Cloud dependence, mandatory accounts, advertising,
- Any synthetic-data validation presented as real,
- New UI features that don't serve the PCOS-risk objective.

---

## 19. STATE-COMPETITION DEMONSTRATION PLAN (R, §24 of the brief)

**60-second script (what the judge sees):**

1. **(0–10 s) Wear it.** Participant puts on the wrist pod; BLE connects; pod LED confirms; dashboard shows "Connected — CHRONO-RING, battery 87%".
2. **(10–20 s) Live data + quality.** Live PPG waveform, HR, temperature, IMU; **per-sensor SQI bars**; if the user moves, watch PPG quality drop and the system *say so* ("motion artifact — HRV temporarily unavailable") instead of printing a number.
3. **(20–30 s) Personal baseline.** One tap: "Capture baseline" → personal ranges appear (HR 68–76, RMSSD 38–52, temp rhythm ±0.8 °C). "Now every reading is compared to *your* normal, not a population average."
4. **(30–45 s) Longitudinal change.** Load the **clearly-labeled simulated 3-week scenario** (or the pilot's own anonymized data): resting HR drifts +8 bpm, temperature amplitude shrinks, cycle length becomes irregular. The ChangeDetector shows "persistent deviation (day 9–16)" and "progressive change (slope +0.9 bpm/day)".
5. **(45–55 s) Model updates + explanation.** Risk estimate appears with CI, confidence, **top-3 contributing factors** (cycle irregularity, HRV trend, temperature rhythm), and a **"why did it change"** panel: "your resting HR has been 8 bpm above your baseline for 6 days."
6. **(55–60 s) The disclaimer.** "This is a research/pre-screening tool, not a diagnosis. Nothing here is clinically validated. The model status board says exactly what is trained and what isn't — that honesty is the science."

**What the booth shows passively:** the Evidence Center (model statuses, evidence bars at honest levels), the 84-test suite badge, the ablation table (once real), the BOM poster, the "TRAINED / INTERNALLY VALIDATED / EXTERNALLY VALIDATED / CLINICALLY VALIDATED" ladder with the last two honestly empty.

---

## 20. DEVELOPMENT ROADMAP (T)

| Milestone | Scope | Effort |
|---|---|---|
| M0 — Fix the foundations | Bug fixes §1.3 (#1, #2, #4, #6), wire ChangeDetector into the app, hard synthetic filter, re-label Kaggle AUC | 1–2 weeks |
| M1 — Scientific rework | Remove hormone twin from risk path; restructure risk domains; remove deep/REM/AMH/VoxVasc/MV-AST from core displays (Experimental Lab tab); fix SQI semantics | 2–3 weeks |
| M2 — Wearable v1 | Wrist pod hardware + firmware (BLE + buffering + night mode) + app BLE client; bench tests (the §7 checklist in `docs/V5_BUILD_GUIDE.md` is reusable) | 4–8 weeks |
| M3 — Longitudinal engine | Stratified baselines, CUSUM/EWMA, daily feature table, missing-data masks, GBDT fusion + calibration + SHAP; ablation runner | 3–4 weeks |
| M4 — Cycle log + dashboard | 1-tap cycle/symptom/medication log; longitudinal assessment card; baseline-vs-current; experimental lab tab | 1–2 weeks |
| M5 — Pilot | Consent form, N=20–30 × 8–12 weeks, data collection protocol, LOSO + temporal validation, honest reporting | 8–12 weeks (parallel with M2–M4) |
| M6 — Competition hardening | 60-s demo script, judge Q&A, booth materials, evidence posters | 1 week |

---

## 21. FINAL DELIVERABLE — "V5.1 FINAL BUILD SPECIFICATION" (from the brief)

**Only the features that genuinely improve PCOS-related-risk estimation:**

1. **Wrist pod**: MAX30102 PPG + skin temp (NTC/MAX30205) + IMU, BLE + on-board buffering, 150–250 mAh LiPo. ₹1,200–2,500 prototype. GSR optional, ablation-gated.
2. **Signal-quality engine** with per-sensor SQI, contact detection, motion gate, packet-loss/timestamp/sync checks, PPG↔ECG disagreement, and a "prediction temporarily unavailable" state. SQI = mean over present sensors only.
3. **Night/rest-window features**: resting HR, RMSSD, SDNN, sleep/wake, temperature rhythm (amplitude/acrophase/nadir). No deep/REM staging, no SpO₂-in-risk.
4. **Personal baseline stratified by time-of-day and cycle phase**, with z/deviation/rate/persistence/trajectory features; single-day vs persistent vs progressive explicitly separated.
5. **Change detection wired in**: CUSUM/EWMA + the existing single/persistent/progressive/recovery classifier.
6. **Daily feature table + GBDT fusion** with per-sensor availability masks, subject-level CV + forward chaining, isotonic calibration, SHAP explanations. Equation engine retained only as the labeled `FALLBACK`.
7. **1-tap cycle/symptom/medication log** (the highest-value input; build it first among all new UI). Manual BP/glucose remain optional contextual inputs.
8. **Periodic ECG checkpoint** as HR/HRV reference and PPG validation only.
9. **Uncertainty that means something**: calibrated probabilities, empirical CIs, coverage gate (≥7 days / ≥3 nights), OOD flag. No invented confidence.
10. **Ablation-driven sensor retention**: anything that doesn't measurably help is removed (GSR and ECG are prime candidates for removal).
11. **Offline-first, consent, export/delete controls; optional LLM assistant default OFF.**
12. **Experimental Lab** holds VoxVasc, MV-AST, insole, cyst monitor, and hormone "twin" illustrations — zero weight in risk, clearly FUTURE RESEARCH.

**Removed from the core, explicitly:** individual reproductive-hormone displays (AMH/LH/FSH/estrogen/progesterone/testosterone), deep/REM staging, SpO₂ as a risk input, VoxVasc, MV-AST, FSR correction, insole, light/BME280 environment sensors, cyst anything beyond a gated status card, and all "wow factor" modules that do not serve the stated objective.

**The honest one-line summary for any judge:** *"We don't measure hormones and we don't diagnose PCOS. We track each person's longitudinal physiology, detect persistent changes from their own baseline, combine that with cycle regularity, and say — with calibrated confidence and explicit uncertainty — when professional evaluation may be worth considering. Everything we claim is labeled trained, internally validated, externally validated, or not validated at all."*
