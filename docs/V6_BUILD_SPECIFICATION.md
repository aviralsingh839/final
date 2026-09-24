# CHRONO-PCOS V6 — MASTER BUILD SPECIFICATION & V5.1 AUDIT

**Prepared by:** multidisciplinary R&D team (biomedical, wearable, embedded, signal processing, ML, longitudinal modelling, reproductive health, digital health, device safety, data science, validation, human factors, Indian IP)
**Date:** 2026-08-17
**Status:** design specification — no fabricated evidence, no fabricated clinical accuracy, no fabricated validation

> **Mission (unchanged, non-negotiable):** a low-cost, non-invasive, longitudinal wearable-assisted system for **PCOS-related risk estimation and pre-screening research**. It does **not** diagnose PCOS. Every claim is labeled trained / internally validated / externally validated / clinically validated — and the last two are honestly empty today.

---

## PHASE 1 — COMPLETE V5.1 AUDIT

### 1.0 State of the repository (verified)

The uploaded project is byte-for-byte identical to the codebase audited previously (the V5.1 spec in `docs/V5_1_BUILD_SPECIFICATION.md` is a design document; none of its code changes were implemented). Verified facts that govern V6:

| Fact | Evidence |
|---|---|
| Test suite | 84/84 pass in ~4 s. |
| Trained artifacts | `pcos_risk_model.joblib` (Kaggle, 541 rows, patient-level CV AUC 0.959 — single-site referral cohort, **not** the live engine) · `ppg_quality_model.joblib` (8 subjects, subject-level CV AUC ≈ 0.62) · no stress/sleep/hormone artifacts. |
| Live risk engine | Hand-tuned logistic equation (`src/models/risk_engine.py`), status correctly shown as `FALLBACK`. |
| Hormone twin | 8 hormones from PPG/temp/GSR/time-of-day; reproductive hormones shown at 15–25% confidence. |
| Change detector | Implemented + tested, **never called by the app**. |
| ECG checkpoint / insole / providers / BLE transport | Standalone modules + tests, **not wired into the dashboard**. |
| Menstrual/symptom inputs | DB tables exist (`menstrual_cycle`, `symptoms`, `bp_readings`, `glucose_readings`, `ultrasound_observations`) but **no UI writes them**. |
| Real BLE path | **None.** App consumes USB serial or ESP8266 TCP bridge only. `requirements.txt` has no BLE library. |
| Wireless protocol | ASCII `$CP` (15 fields) / `$CP2` (25 fields), XOR CRC of payload; `ms` = device millis, `timestamp_s` = host time at parse. |
| Data pipeline | Raw CSV (every 50 samples) + SQLite features (10 s) + events/calibrations/anomalies/quality/error logs. Local only. |
| Public data on disk | Kaggle PCOS (xlsx + infertility + synthetic extension), Wrist-PPG-during-exercise. WESAD/BIDSleep/MESA/MMASH/mcPHASES/NHANES/Pima absent. |
| Real longitudinal wearable + PCOS dataset | **Does not exist anywhere.** This is the central constraint. |

### 1.1 Component classification

| Component | Verdict | Rationale |
|---|---|---|
| MAX30102 PPG (IR+red) | **KEEP** | HR/HRV are the highest-value continuous signals. |
| MPU6050/LSM6DS3 IMU | **KEEP** | Motion gating for PPG + activity/sleep; cheapest way to make PPG trustworthy. |
| Skin temperature (DS18B20) | **REWRITE** (sensor choice) | DS18B20 TO-92 is clumsy in a pod; switch to MAX30205 (±0.1 °C, I2C) or a 10 kΩ NTC for skin contact. |
| GSR (optional) | **OPTIONAL** | Stress largely redundant with HRV; ablation decides. Keep the channel, default off. |
| Light (BH1750) | **REMOVE** from core | Minor circadian assist, not needed. |
| BME280 room T/H/P | **REMOVE** from core | Replace with a $0.30 ambient NTC in the pod; keep in the Mega bench rig only. |
| FSR finger pressure | **REMOVE** | Linear "pressure correction" of PPG amplitude is unvalidated; PPG amplitude is not a risk input. |
| MAX4466 mic / VoxVasc | **REMOVE** from core | Pitch-based "androgen proxy" is scientifically indefensible in a risk score. Move to Experimental Lab / FUTURE RESEARCH, zero weight. |
| AD8232 ECG (periodic) | **KEEP** (periodic) | HR/HRV reference + PPG validation only. Fix the quality bug so its absence never penalizes the score. |
| Smart insole | **FUTURE RESEARCH** | Behavioural signal with no direct PCOS claim. Keep code; never mandatory (§25). |
| Arduino Mega rig | **IMPROVE** (bench only) | Fine for the lab; explicitly rebranded "bench rig", not the wearable. |
| ESP8266 Wi-Fi bridge | **OPTIONAL** | Bench convenience; not part of the product. |
| Packet parser + readers | **IMPROVE** | Solid CRC + auto-reconnect. Add sequence numbers, rate metadata, device-clock sync (§5). |
| BLE transport (`transport.py`, `LocalBuffer`) | **REWRITE** | Protocol-level skeleton; must become a real BLE client + on-device buffering (§5). |
| Signal-quality heuristics | **KEEP / IMPROVE** | Good base; add full engine (§6). |
| SQI + withhold layer | **IMPROVE** | Correct concept; fix the missing-ECG penalty bug; add contact/ambient checks. |
| Personal baseline | **KEEP / IMPROVE** | Rolling median/MAD + EWMA + outlier rejection is right. Add time-of-day and cycle-phase stratification (§8). |
| Anomaly detector | **KEEP** | Personal-baseline outlier layer — keep, never equate with PCOS (§14). |
| Change detector | **KEEP / WIRE IN** | Good single/persistent/progressive/recovery design; today it is dead code. Add CUSUM/EWMA on top (§13). |
| Risk engine (equation) | **REWRITE** | Hand-tuned weights + 0.90-weight endocrine domain fed by 15–25% confidence hormone estimates = scientifically indefensible. Replaced by a trained, calibrated pipeline with the equation demoted to a clearly-labeled no-model fallback (§15). |
| Hormone twin | **REMOVE** from core | Estrogen/progesterone/testosterone/LH/FSH/AMH "levels" cannot be derived from these sensors. Replace with a labeled "model-derived physiological state" index (§11, §24). |
| Metabolic model | **KEEP / IMPROVE** | Insulin-resistance proxy from manual glucose + BMI + sleep/stress is the most defensible metabolic feature. |
| Sleep estimator | **IMPROVE** | Sleep/wake from HR+HRV+motion+time is defensible. **Remove deep/REM "probabilities"** — not stage estimates, invites the obvious question. |
| Stress estimator | **KEEP** | Defensible autonomic estimate; motion gate good. |
| Circadian analyzer | **KEEP / IMPROVE** | Real cosinor fits exist but the live path overrides them with a near-constant placeholder — wire the real analyzer into the per-tick path. |
| MV-AST metabolic challenge | **REMOVE** from core | PPG-amplitude-ratio "vasodilation index" unvalidated; → Experimental Lab / FUTURE. |
| What-if lab / recommendations | **OPTIONAL** | Harmless if labeled heuristic; don't extend. |
| AI Assistant (LLM) | **OPTIONAL** | Local grounded mode fine. LLM mode sends health-derived context to third parties → explicit opt-in, default off, warning (§28). |
| Validation Lab + Evidence Center + audits + dataset registry | **KEEP** | The strongest part of the project. Preserve entirely; this is V6's identity. |
| Cyst monitor | **FUTURE (gated)** | Already correctly "NOT YET TRAINED". Status card + schema only, forever, until real outcome data. |
| Synthetic data / demo / judge demo | **KEEP (hard-separated)** | Essential for the competition; must live behind a separate DEMO MODE wall (§30). |
| "Digital Twin / Hormone Twin" branding | **IMPROVE** | Over-promises. Rebrand as "longitudinal physiology profile" + "model-derived physiological states". |

### 1.2 Confirmed bugs and unfinished modules (all carried into V6 work)

1. `realtime_features.compute()`: overall SQI = mean of `[ppg_quality, ecg_quality, temp_present, gsr_present, motion>=0]` → missing **optional** ECG drags SQI down and can wrongly trigger the withhold gate; `motion>=0` is always 1.0 (dead weight).
2. Mega firmware sends packets at **20 Hz** while the SQI feature math assumes 50 Hz (FFT bins, zero-crossing rate) → mis-scaled features on Mega data. Ring/Mega rate must be carried in the protocol.
3. `ChangeDetector`, ECG checkpoint, providers, insole, BLE transport: **unwired** — docs overstate integration.
4. Circadian index placeholder (`50 + 20·completeness`, capped 70) and constant `temperature_rhythm_disruption` (50→35) yet 0.60 risk weight — a constant inflating every risk number.
5. Synthetic rows share the same SQLite DB as real sessions; the Research Lab reports "performance vs synthetic labels" in the same store → enforce a hard source separation.
6. `_risk_from_scores` includes `mv` (0.35) and `vv` (0.12) terms that are 0 by default (constant offset) while `counterfactual_ablation` skips them — equation and ablation disagree.
7. Kaggle 0.959 AUC quoted in README/models as a headline → must be relabeled as clinical-variable model on one referral cohort, NOT wearable performance.
8. `data/ai_config.json` stores API keys in plaintext; LLM mode sends health-derived context externally without warning.
9. Deep/REM probabilities and AMH (own README: "cannot be estimated in real time") displayed → remove from core.
10. `BaselineManager.update_observation` EWMA math touches `cur.mad`/`cur.std` fields never populated at capture → latent scale bug in the rolling-update path (tests exercise capture, not update).

---

## PHASE 2 — THE V6 SCIENTIFIC HYPOTHESIS

**Primary hypothesis (testable):**

> **H1:** In reproductive-age individuals, longitudinal relationships among autonomic (HR/HRV), activity, thermal (skin-temperature rhythm), circadian-timing, and menstrual-cycle features — expressed as deviations from that individual's own baseline — improve PCOS-related risk estimation compared with (a) single-snapshot physiological measurements and (b) a conventional model using only clinical/cycle inputs.

**Secondary hypotheses:**

> **H2:** Cycle-relative physiological patterning (features aligned to cycle day/phase) carries more information than raw physiological values.
>
> **H3:** Signal-quality-aware feature weighting reduces the variance of risk estimates without changing their calibration (i.e., the quality engine is itself testable).
>
> **H4:** A two-stage model (physiological states → risk) generalizes across subjects better than a single-stage model that consumes raw features, at equal data size.

**Falsifiability is built in:** the ablation matrix (§18) and leakage-proof validation (§19) exist precisely to test H1–H4. If no longitudinal feature survives the ablation, the honest answer is "the wearable adds no measurable information at this sample size," and V6 says so. The hypothesis must not be assumed true.

**Pre-registration-lite:** fix the analysis plan (feature list, model, split scheme, metrics, decision rules) in a `research/protocol.md` *before* the pilot data is collected. This is the single cheapest way to make the results credible.

---

## PHASE 3 — FROZEN CORE HARDWARE

**Required (frozen):** PPG (MAX30102, IR+red) · skin temperature (MAX30205 or NTC) · IMU (MPU6050/LSM6DS3).
**Optional (gated by ablation):** GSR.
**Periodic supporting:** ECG (AD8232 checkpoint, weekly).
**Manual optional inputs:** BP, glucose, menstrual, symptoms.

**No new continuous sensors without an ablation-demonstrated benefit.** Every rejected sensor is rejected for cost/power/info-gain reasons documented in §26.

**Misleading outputs removed:** the wearable never reports testosterone, insulin, LH, FSH, AMH, or ovarian morphology — no direct measurement, no "estimated level" display in the core (§24).

---

## PHASE 4 — THE V6 WEARABLE: UPPER-ARM/FOREARM POD

### 4.1 Site evaluation

| Criterion | Upper arm (biceps) | Forearm (ventral) | Wrist | Ring (finger) | Finger clip |
|---|---|---|---|---|---|
| PPG signal | Medium (site-dependent) | Medium-Good | Medium | High | Very high |
| Motion artifact | **Low** | Low-Med | Medium | Low | High |
| Skin temp (core proximity) | **Best practical** | Good | Medium | Poor (ambient) | Poor |
| Ambient thermal coupling | **Low** | Low-Med | Medium | High | High |
| Comfort 24/7 | **High** (strap) | High | High | High | Low |
| Battery envelope | **Large** | Large | Medium | Small | n/a |
| Manufacturability | **Easiest** | Easy | Easy | Hard (sizing) | Easy (not wearable) |
| Discreteness | High | High | Medium | High | Low |

### 4.2 Recommendation

**Primary: upper-arm pod** (biceps, medial side, just above the elbow crease). Rationale: the two features that matter most for the research question — **temperature rhythm** (closest practical proxy to core, lowest ambient coupling) and **low-motion night windows for HRV** — are both best served at the upper arm; battery envelope is largest; strap-based comfort and manufacturability are best. The **forearm (ventral, ~5 cm from the elbow crease)** is the designated fallback site if biceps PPG SNR proves poor; the pod and strap are identical for both positions. **Ring = future miniaturization project only**, because finger temperature is ambient-dominated and ring manufacturing (optical window, sizing, flex PCB) is not a student-team problem.

### 4.3 Mechanical design

- **Pod (50 × 36 × 14 mm, ~30 g)**, removable from the strap via a **clip/slide-lock connector** (strap can be washed; pod charged separately).
- Base: 3D-printed PA12/ABS, two halves. A **soft silicone optical boss** (2 mm) spring-loads the MAX30102 window against the skin; 1.5 mm clear epoxy over the LED/PD aperture.
- Temperature: MAX30205 (or NTC) in a **5 mm metal coin**, pressed through a 2 mm foam aperture, thermally insulated from the PCB; a second ambient NTC (₹25) reads room temperature for ambient-coupling detection (§6).
- IMU on the rigid PCB; **battery on top, 1 mm foam spacer** so cell heat never reaches the temperature coin.
- Enclosure: seam-welded/silicone-potted top, **IP54**; strap 26 mm silicone with anti-slip inner texture, quick-release buckle.
- Charging: **pogo-pin charging cradle** (no USB port in the pod); 150–250 mAh LiPo, TP4056 + HT7333 LDO.
- Cleaning: strap washable; pod wiped with isopropyl. Sweat resistance via potting + gaskets.
- Heat budget: worst-case sensor+BLE continuous ≈ 40–60 mW → at 150 mAh/3.7 V the duty-cycled design targets **3–5 days**; no endurance number is claimed before hardware measurement.

### 4.4 Electrical block

```
ESP32-C3 (BLE + flash buffering)
 ├─ I2C: MAX30102 (0x57), MPU6050 (0x68), MAX30205 (0x48)
 ├─ ADC: battery divider (GPIO2), ambient NTC (GPIO3)
 ├─ Power: TP4056 → HT7333 3.3 V; switch
 └─ SPI/QuadSPI: 8–16 MB flash (LittleFS) for local buffering
[optional] GSR stage → ADC (GPIO4), 2 Ag/AgCl pads on strap
```

---

## PHASE 5 — END-TO-END WORKING PATH (highest priority)

The V5 story ends at firmware + protocol documentation. V6's Phase 5 is: **a demonstrably working path, tested without requiring the physical pod on day one.**

### 5.1 Target pipeline

```
POD → ESP32 (sample, SQI-lite, buffer) → BLE notify/indicate → PYTHON BLE CLIENT
   → PacketValidator (CRC16-CCITT + seq) → LocalBuffer (dedupe/reorder/stats)
   → existing feature extractor → SQLite → model → dashboard
```

### 5.2 Firmware (rewrite of `chrono_pcos_v5_ring` sketch → `arduino/chrono_pcos_v6_pod`)

- **Frames** (binary, BLE GATT notify): `[len:1][seq:4 LE][device_ms:4][rate_hz:2][payload][crc16-ccitt:2]`. `device_ms` = ESP32 uptime ms; `rate_hz` = true streaming rate (kills bug #2).
- **On-board buffering:** PPG/IMU bursts 30 s every 5 min (day), continuous 25–50 Hz at night (wear-detected via IMU + clock); every sample appended to LittleFS ring with seq; on reconnect, missed frames replayed; battery % and buffer-full flags in a status GATT characteristic.
- **Wear/off detection** → low-power bursts; **status bits** mirrored from V5 so the parser stays compatible.
- **Synchronization:** host computes `offset = host_time − device_ms_at_receive`; drift corrected by linear regression over sync packets; sync events logged for the quality engine.

### 5.3 Python BLE client (new — this is the missing piece)

- Add **`bleak`** to `requirements.txt`; new module `src/serial_io/ble_reader.py` implementing the same `sample_received / error_received / state_changed` interface as `ArduinoReader`/`NetworkReader`, so the app treats BLE, serial, and TCP identically (the V5 provider abstraction finally earns its place).
- Auto-connect to the pod's advertised service UUID, enable notify, CRC-validate, feed `LocalBuffer`, reconnect with backoff on drop.
- A **synthetic BLE server simulator** (`tests/` + demo) lets the entire path be integration-tested without hardware (§33).

### 5.4 Demo/simulation separation (hard rule)

- `python -m src.app --demo` → banner **DEMONSTRATION MODE** in the header, and every stored row is stamped `source='demo'|'synthetic'` with a **separate SQLite file** (`data/demo.db`) so simulated data can never pollute the real store or be counted in analysis. The current `generate_week` writer gains a mandatory `db_path` and the Research Lab refuses to compute anything over mixed sources (bug #5 fixed by construction).

---

## PHASE 6 — SIGNAL-QUALITY ENGINE

Keep the withhold concept ("Prediction withheld — insufficient signal quality") and the `sqi.py` decision layer; extend as follows. Every stream gets a 0–1 quality score and a human reason list.

| Stream | Checks | Gate action |
|---|---|---|
| PPG | Contact (IR DC in band, AC/DC ratio), clipping/saturation, autocorrelation regularity, IBI plausibility (35–210 bpm, <25% median deviation), trained-model blend (existing, 40% weight), **IMU cross-check** | SQI < 0.4 → HR/HRV features = missing |
| PPG↔ECG | |PPPG HR − ECG HR| > 5 bpm over a checkpoint → PPG HR/HRV down-weighted until revalidated | only when ECG present |
| IMU | Dropout, frozen axis, |a|>16 g impossible values, rate validation | gates PPG |
| Temperature | Range 25–40 °C, slew ≤ 0.5 °C/min, **ambient-coupling check** (|corr(skin, room NTC)| > 0.8 → "environmentally coupled, low information"), enclosure-heating check (temp rises with charging) | temp SQI < 0.4 → rhythm features missing |
| GSR (optional) | Contact band, <5% clipping, electrode-drying drift < 20%/h | optional |
| Wireless | Sequence gaps → coverage %, CRC failures, reorder/dedupe stats from `LocalBuffer`, timestamp drift, device-rate vs nominal | surfaced in UI; coverage feeds uncertainty (§16) |

**Decision rule (final):** no prediction when core SQI < 0.4, OR no valid HRV window, OR CI too wide, OR longitudinal coverage < 7 days. The dashboard prints the reason verbatim.

---

## PHASE 7 — REAL FEATURE ENGINE

**Kept (defensible):** HR, resting HR (night 5th percentile), RMSSD, SDNN, pNN50, motion index, activity level, sleep/wake probability, skin temp + slope + stability, GSR tonic/phasic (quality-gated), stress index, insulin-resistance proxy (manual glucose + BMI + sleep + stress), glucose risk, BP risk.

**Added in V6:**
- **Night-window aggregates** (resting HR, RMSSD, SDNN per night) — the core longitudinal features.
- **Temperature rhythm:** daily amplitude, acrophase (cosinor), nadir, and week-over-week stability of each.
- **Activity regularity:** hourly-profile CV, sedentary-bout statistics, sleep-midpoint SD.
- **Cycle features** (§9): phase, days-since-period, irregularity (SD of last 6 lengths), bleeding-day count, symptom flags.
- **Baseline-deviation features** for every core metric: robust z, abs/pct change, slope/day, persistence (consecutive out-of-band days), variability, trajectory (§8).

**Removed (not features, ever):** deep/REM probabilities, VoxVasc score, MV-AST indices, FSR correction, SpO₂-as-risk-input, AMH, and individual reproductive-hormone values.

---

## PHASE 8 — PERSONAL BASELINE (core component)

Keep the V5 median/MAD/EWMA manager (good design); fix bug #10; add:

1. **Stratified baselines**: normal ranges per time-of-day bin (2 h; night/day separate for HR/HRV) and per cycle phase when cycle data exists. Deviations are always computed against the correct stratum, so a normal luteal temperature rise is never flagged.
2. **Per-day baseline-derived metrics**: resting HR, RMSSD, SDNN, temp amplitude/acrophase/nadir, sleep midpoint/duration/regularity, activity, GSR tonic.
3. **Deviation vocabulary** (this is the model's input language): absolute value · robust z · rate of change (slope/day over 7 d) · persistence (consecutive out-of-band days) · variability (SD of daily values) · trajectory (sign + slope) · circadian characteristics (amplitude/acrophase stability).
4. **Explicit four-way distinction** (wired into the UI, never conflated):
   - **SINGLE-DAY** (1 day, z > 3) → informational only.
   - **PERSISTENT** (≥3 consecutive days, z > 2) → model feature.
   - **PROGRESSIVE** (≥7 days, significant slope) → model feature, higher weight.
   - **RECOVERY** (returning toward baseline) → model feature.
   - One abnormal reading can never redefine the baseline (|z|>3.5 rejection kept) and never produces a PCOS claim.

---

## PHASE 9 — CYCLE-AWARE MODELLING (major V6 upgrade)

**The strongest, most defensible PCOS signal the system can collect is the menstrual cycle itself.** V5 barely collects it (two spinboxes, no logging). V6 makes it first-class:

1. **1-tap cycle log (≤5 taps/day):** "period started today" · auto cycle-day · symptom checkboxes (pain / hair growth / acne / weight change / none) · optional medication flag (name optional). Written to the existing `menstrual_cycle`/`symptoms` tables.
2. **Cycle features:** current phase (only when cycle data is reliable; `unknown` otherwise), days since period start, cycle length, irregularity = SD(last 6 lengths), bleeding-day count, symptom trend. **No phase is ever assumed from unreliable information** — the estimator returns `unknown` unless enough anchoring data exists.
3. **Cycle-relative physiology:** when ≥ 1 full observed cycle exists, express temp/HRV/HR features relative to cycle day (e.g., temperature phase-position, luteal-shift detection as a *research* feature). H2 tests whether these beat raw values; until proven, raw + cycle-phase-stratified baseline are the defaults.
4. **Claim hygiene:** anything about cycle-relative patterns is labeled "experimental finding from this study" or "established clinical knowledge" — never conflated.

---

## PHASE 10 — TEMPORAL MODEL

**Decision: gradient-boosted trees (LightGBM/XGBoost) on daily longitudinal features — now; a GRU/TCN baseline only when real data justifies it; Transformer explicitly out of scope for any foreseeable dataset size.**

| Criterion | Reality | Choice |
|---|---|---|
| Dataset size | ~541 clinical rows; 0 real longitudinal wearable rows today | Trees need 10–100× less data |
| Overfitting | Small + noisy data → deep nets memorize | Regularized GBDT + early stopping |
| Interpretability | SHAP on trees is fast, standard, honest | Trees |
| Compute/deploy | Offline laptop | Trees |
| Performance at this n | Trees competitive or better on tabular data | Trees |

The model must encode the three temporal questions: **what** (current state), **how long** (persistence), **how changing** (slope) — all present as engineered features (§7–8), so the tree model genuinely "understands time" without a sequence layer. When the pilot reaches ~100 subjects × 30+ days, evaluate GRU/TCN vs GBDT head-to-head (≥0.02 AUROC gain, non-overlapping CIs) before adopting.

---

## PHASE 11 — TWO-STAGE MODEL

```
STAGE 1 (per day, quality-gated features)
  → model-derived physiological states (latent, labeled as such):
    autonomic_state · circadian_state · activity_state · thermal_state · cycle_state
  (linear projection or small PCA/encoder — interpretable, not a black box)

STAGE 2 (per subject, over the observation window)
  states + cycle/symptom + clinical/demographic + optional BP/glucose/ECG
  → calibrated PCOS-related risk estimate
```

**Naming rule (hard):** Stage-1 outputs are **"model-derived physiological states"**, never "measurements" and never "hormones". No fake biology.

---

## PHASE 12 — MULTIMODAL FUSION (missing-data-aware)

1. **Availability masks as features:** `has_ppg, has_temp, has_imu, has_gsr, has_cycle, has_symptoms, has_glucose, has_bp, has_ecg` + SQI grades. The model learns what "missing" means.
2. **Imputation order:** last valid personal value → time-of-day/cycle-phase baseline median → global median; every imputed feature carries its mask.
3. **Quality-gated inputs:** PPG SQI < 0.4 → HR/HRV missing (not garbage-filled); ambient-coupled temp → rhythm features missing.
4. **Configurations exercised in ablation:** wearable only · +cycle · +symptoms · +BP · +glucose · +ECG · full. More data is **not** assumed better — it is measured (§18).

---

## PHASE 13 — CHANGE-POINT DETECTION (research-grade)

- **Primary:** **CUSUM** (two-sided, head-start, control limits ±2σ) and **EWMA** on daily z-scores of resting HR, RMSSD, temp amplitude, and cycle length → "the person's pattern shifted on day X" with a statistical basis.
- **Semantic layer:** the existing single/persistent/progressive/recovery classifier on top of CUSUM events (wired in — today it is dead code).
- **Robustness:** require ≥3 consecutive out-of-band days and a CUSUM signal ≥5 days before "progressive change" is stated. PELT/Bayesian methods noted as future research if the pilot data warrants them; CUSUM/EWMA are chosen now for transparency and small-sample behavior.

---

## PHASE 14 — ANOMALY DETECTION (supporting only)

- Keep personal-baseline outlier detection ("unusual **for this person**") as the live layer.
- Add **robust Mahalanobis distance** (and an optional Isolation Forest) on daily feature vectors for multivariate outlier days.
- **Hard separation in UI and wording:** "deviation from your normal" vs "pattern associated with PCOS risk in this model." A single anomaly is **never** a risk event.

---

## PHASE 15 — REPLACE THE FALLBACK PCOS EQUATION

**Critical change.** The live pipeline becomes:

```
real data → quality control → features → trained model → calibration → risk → uncertainty → explanation
```

- **When a trained fusion model exists:** the live risk comes from it, with SHAP contributions and empirical calibration.
- **Until then:** the app shows **"RESEARCH PROTOTYPE — MODEL REQUIRES CLINICAL VALIDATION"** and may show the old equation **only** as an explicitly-labeled `FALLBACK (not validated)` display with a wide CI — never as a headline "PCOS risk %". This eliminates the V5 contradiction where a 0.96-AUC clinical model sat in `models/` while a hand-tuned equation drove the live number.
- The equation's domain structure is retired; the hormone twin's 0.90 endocrine weight is gone.

---

## PHASE 16 — CALIBRATION AND UNCERTAINTY

- **Calibration:** isotonic/Platt on out-of-fold predictions; report **Brier + ECE** on validation folds (reuse the existing calibration module).
- **CI:** empirical spread from out-of-fold/bootstrap predictions — not injected Gaussian noise.
- **Uncertainty dashboard block (exact fields):**

```
PCOS-related risk estimate:        XX %      (or: prediction withheld)
Confidence:                        LOW / MODERATE / HIGH
Data quality:                      XX %
Longitudinal coverage:             XX days (N nights)
Reason for uncertainty:            insufficient data | poor signal quality |
                                   out-of-distribution pattern | missing clinical inputs
```

- **Coverage gate:** <7 days / <3 nights → withheld or "preliminary, CI ±X"; >30 days + ≥5 nights/week → "longitudinal estimate."
- **OOD:** Mahalanobis distance + per-feature plausibility; flag "inputs outside the model's training range."
- **Never invent confidence.**

---

## PHASE 17 — EXPLAINABLE AI

**"WHY DID MY RISK CHANGE?"** panel:

1. **Personal baseline vs current state** table (metric · baseline · today · z · trend · persistence).
2. **Model contributors** from SHAP (trained mode) or exact per-domain contributions (fallback mode), using **"contributed to the model estimate," never "caused PCOS."**
3. **Temporal contribution:** which days/windows drove the change (ChangeDetector output).
4. Permutation importance as a global report in the Validation Lab.

Possible display (as the brief requests):

```
Cycle irregularity      ↑  contributed
HRV deviation           ↑  contributed
Activity pattern        ↓  contributed
Temperature rhythm      changed
Other features          stable
```

---

## PHASE 18 — ABLATION STUDY (mandatory, actual results only)

Fixed protocol: subject-level 5-fold CV + forward-chaining, ≥3 seeds, report **AUROC, AUPRC, sensitivity, specificity, precision, recall, F1, ECE** with CIs.

| Model | Inputs |
|---|---|
| 1 | clinical/cycle inputs only |
| 2 | PPG only |
| 3 | PPG + temperature |
| 4 | PPG + temperature + IMU |
| 5 | PPG + temperature + IMU + GSR |
| 6 | wearable + cycle |
| 7 | wearable + symptoms |
| 8 | wearable + metabolic inputs (BP/glucose) |
| 9 | wearable + periodic ECG |
| 10 | full multimodal |

Decision rule: keep a modality iff AUPRC gain ≥ 0.01 with non-overlapping CIs, else remove. A priori expectations (to be confirmed, not assumed): cycle/symptoms add the most; GSR and ECG checkpoint features are the most likely cuts; BP/glucose help only in a metabolic sub-group. **No fabricated numbers, ever.**

---

## PHASE 19 — LEAKAGE-PROOF VALIDATION

- **Subject-level GroupKFold** (default, already the pattern) and **temporal forward-chaining** (train on earlier days, test on later).
- **Documented leakage pathways** (a checklist artifact in the Validation Lab): same-subject train/test overlap; duplicate/replayed sessions; window overlap within a subject; normalization/scaling fit on train only; labels derived from features; synthetic rows in the real store; future timestamps; ID-offset cohorts across datasets (existing `dataset_manager` checks cover most).
- **Class imbalance:** report AUPRC as primary; balanced metrics.
- **External validation:** only with a second independent cohort; nothing qualifies today.
- **Status ladder shown in UI:** TRAINED → INTERNALLY VALIDATED → EXTERNALLY VALIDATED → CLINICALLY VALIDATED, with the last two honestly empty.

---

## PHASE 20 — DATASET AUDIT

| Dataset | Present | n | Use for ML | Validates the wearable? | Limitations |
|---|---|---|---|---|---|
| Kaggle PCOS clinical | ✅ | 541 (1 site, referral) | Clinical-variable feature relationships | **No** (no wearable data) | Single-site, referral bias, no longitudinal physiology |
| Wrist PPG during exercise | ✅ | 8 subj, 19 rec | PPG motion-artifact model | Sensor-level only | Different sensor/site than V6 pod |
| Synthetic week | ✅ | n/a | UI/demo | **No — never** | — |
| WESAD | ❌ | — | Stress model | Sensor-level only | Stress task protocol ≠ PCOS |
| BIDSleep / MESA | ❌ | — | Sleep/wake from HR+ACC | Sensor-level only | No PCOS |
| MMASH / mcPHASES / NHANES | ❌ | — | Hormone priors, cycle rhythms (illustrative) | No | No wearable+PCOS pairing |
| **Longitudinal wearable + PCOS outcomes** | ❌ | **0** | — | — | **Does not exist publicly** |

**Three separate buckets, never conflated:** (1) ML-development data (Kaggle, WESAD, sleep datasets), (2) wearable-validation data (wrist-PPG quality model; own pilot), (3) clinical-validation data (none). A generic PCOS dataset **never** proves the wearable works.

---

## PHASE 21 — LONGITUDINAL DATA-COLLECTION PROTOCOL

**Ethics gate (mandatory, stated plainly):** this is human-subjects health research. Before any data collection: **adult/teacher/clinician oversight, written informed consent from participants and (where applicable) guardians, privacy protection, and institutional/ethics approval** where the project is hosted. Nobody is told to diagnose classmates or collect medical information without oversight. The protocol is a *proposal*, not a mandate to enroll anyone.

**Proposed pilot (to be executed only with approval):**
- **Design:** prospective, observational, 8–12 weeks.
- **Participants:** N ≈ 20–30 reproductive-age volunteers (with guardian consent if minors); groups: (a) self-reported PCOS-likely by predefined criteria, (b) controls; plus optional clinician-confirmed subset.
- **Reference standard:** predefined criteria — self-reported cycle regularity + modified Ferriman–Gallwey score + BMI + acne (research screen), with clinician evaluation where available. Explicitly *not* a diagnosis.
- **Measurements:** continuous pod (PPG/temp/IMU; optional GSR), daily 1-tap cycle/symptom log, optional weekly BP/glucose, optional periodic ECG checkpoint, sleep/wake diary.
- **Data-quality requirements:** ≥ 5 nights/week valid, ≥ 60% daily coverage, SQI gates applied.
- **Endpoints:** (primary) AUROC/AUPRC of V6 risk estimate vs reference standard; (secondary) H1–H4 comparisons, calibration, change-point agreement.
- **Inclusion/exclusion:** e.g., age 14–45, not pregnant, no current hormonal contraception (or stratified), no known endocrine disorder other than PCOS (or documented).
- **Consent/privacy:** written consent, anonymized IDs, encrypted local storage, export/delete rights.

---

## PHASE 22 — PERIODIC ECG

- **Outside the wearable**, weekly 30–60 s checkpoint only.
- Roles: HR/HRV reference for validating PPG (§6), autonomic feature source for Stage 2, PPG-accuracy reporting.
- **No claim that ECG detects PCOS.** It is a measurement-integrity tool plus a secondary feature source.

---

## PHASE 23 — BP AND GLUCOSE

- Manual entry only; never claimed to be measured by the pod.
- Model operates without them (masks, §12); ablation decides if they earn inclusion.

---

## PHASE 24 — REMOVE MISLEADING FEATURES (enforcement list)

Removed from the core: direct hormone estimates · fake testosterone/AMH/insulin values · LH/FSH displays · ovarian morphology · deep/REM staging · VoxVasc · MV-AST · FSR correction · SpO₂-as-risk · insole-in-core · cyst anything beyond a gated status card. Anything not physically measurable or scientifically justified is either deleted or moved behind the **EXPERIMENTAL / FUTURE RESEARCH** wall with zero risk weight.

---

## PHASE 25 — SMART INSOLE

**OPTIONAL RESEARCH MODULE only.** Code retained; not built, not required, not in the BOM. Integration into the core happens only if an ablation study demonstrates meaningful improvement for the PCOS-related task. Otherwise: future research.

---

## PHASE 26 — ECONOMIC OPTIMIZATION (useful information per rupee)

**Prototype BOM (one unit, upper-arm pod):**

| Item | ₹ | Notes |
|---|---|---|
| ESP32-C3 module | 300–450 | BLE + flash buffering |
| MAX30102 breakout | 350–600 | |
| MPU6050 (or LSM6DS3) | 180–350 | |
| MAX30205 (or NTC) | 330 / 25 | |
| Ambient NTC | 25 | thermal-coupling check |
| 200 mAh LiPo + TP4056 + LDO | 180–350 | |
| PCB (2-layer) | 150–400 | |
| Pod print + silicone strap | 100–250 | |
| Switch, caps, epoxy, pogo cradle | 150 | |
| **Total prototype** | **₹1,765–2,900 (~$21–35)** | |

**Scaled product BOM (~1,000 units):**

| Item | ₹/unit |
|---|---|
| ESP32-C3 bare | 120–180 |
| MAX30102 | 200–350 |
| LSM6DS3 | 100–150 |
| NTC + circuit | 25–40 |
| 150 mAh LiPo | 80–120 |
| TP4056 + LDO + passives | 40–60 |
| PCB panelized | 60–120 |
| Molded enclosure + strap | 80–150 |
| Assembly + test | 100–200 |
| **Total scaled** | **₹805–1,370 (~$10–16)** |

**Removable without hurting the core:** GSR (−₹150–300), second temp sensor, light, BME280, FSR, mic, insole, OLED, buttons, buzzer. **Keep: PPG + IMU + skin temp + MCU + battery + buffering.**

---

## PHASE 27 — WEARABILITY ("Wear → Forget → Collect → Sync → Analyze")

- 30 g pod, upper arm; **zero-interaction operation**: auto-detect wear, auto-sync on BLE reconnect, buffered data never lost silently.
- Charging cradle, 3–5 day target (measured, not claimed); strap washable; pod IP54.
- Cleaning instructions printed on the strap tag; battery-replacement procedure documented.
- Comfort checks: strap pressure < 20 mmHg guideline (soft-textured inner), no skin irritation protocol in the pilot.
- **Ring = future miniaturization project** only.

---

## PHASE 28 — PRIVACY

- Offline-first processing; SQLite stays local. Add **encryption at rest** (SQLCipher or documented alternative), **access control** (single-user), **audit log** of exports/deletions.
- **User controls:** export CSV/JSON (exists), **delete-my-data** (add), device-unlink.
- **Anonymized research export:** strips participant ID and free text; consent checkbox at first run.
- **Demo mode:** separate DB, header banner, no identifiable data (§30).
- **LLM assistant:** default OFF; when enabled, explicit warning that health-derived context leaves the device; participant ID and free text never sent; keys never committed.

---

## PHASE 29 — DASHBOARD

**Main screen (judge-facing, ≤ 6 elements):**

```
CHRONO-PCOS  ·  [DEMONSTRATION MODE] badge when active
PCOS-related risk:        LOW / MODERATE / HIGH     (or: prediction withheld)
Confidence:               LOW / MODERATE / HIGH
Data quality:             XX %
Longitudinal coverage:    XX days (N nights)
[WHY DID THE ESTIMATE CHANGE? →]   personal baseline vs current · deviations · contributors · uncertainty
[SCIENTIFIC DETAILS →]   signal processing · features · model · validation · ablation · calibration
```

**Depth underneath (unchanged from V5's best parts):** Live Signals, History/Trends, Cycle Log (new), Baseline, Change Detection, Validation Lab, Evidence Center, Timeline, Experimental Lab (relabeled). The user is never overwhelmed on the main screen.

---

## PHASE 30 — DEMONSTRATION MODE (fully separate)

- `--demo` → separate `data/demo.db`, **DEMONSTRATION DATA — NOT A REAL MEDICAL RESULT** banner, distinct color scheme.
- **60-second script:**
  1. Put the pod on a volunteer → BLE connects (or demo BLE server).
  2. Live PPG waveform + per-sensor SQI bars.
  3. HR/HRV/activity/temperature readouts.
  4. One tap: personal baseline captured.
  5. Load the clearly-labeled 3-week simulated scenario: resting HR drifts +8 bpm, temperature amplitude shrinks, cycle becomes irregular.
  6. CUSUM + ChangeDetector show "persistent deviation (day 9–16)" and "progressive change."
  7. Model updates; risk + confidence + contributors appear.
  8. "WHY?" panel shows baseline vs current.
  9. Wave the pod / cover the sensor → quality drops → **"Prediction withheld — insufficient signal quality."**
  10. Disclaimer: research/pre-screening tool, not a diagnosis, NOT YET CLINICALLY VALIDATED.
- No fake patient diagnosis, ever.

---

## PHASE 31 — NATIONAL COMPETITION OPTIMIZATION

Optimize for novelty, social applicability, affordability, usability, comparative advantage, technical depth, scientific credibility, reproducibility, demonstrability, scalability — **not** sensor/AI counts. The 60-second story (§30) plus the honesty ladder (§19) plus the working end-to-end path (§5) are the differentiators: most competing projects stop at "Arduino reads sensors and draws a gauge"; V6's pitch is *"a quality-gated, personal-baseline longitudinal model with honest validation"* — which is both more credible and more defensible under 20 minutes of questioning.

---

## PHASE 32 — PATENT / IP PRESERVATION

**Potentially novel technical components (identified for evaluation, not claimed as patentable):**
1. **Pod architecture:** unified optical + thermal + inertial pod with ambient-thermal-coupling compensation and spring-loaded optical boss — combination may be non-obvious in the low-cost space.
2. **Quality-gated longitudinal protocol:** per-stream SQI + device-clock sync + CUSUM-driven baseline-deviation feature language.
3. **Cycle-phase-stratified personal baseline + missing-data-masked two-stage fusion** as an integrated estimation method.
4. **Low-cost BOM target (~₹1,000)** with buffered BLE and explicit dropped-data accounting.

**Required discipline:**
- Perform **prior-art searching** (wearable PPG/temp/IMU baseline; PCOS risk scoring; cycle-aware wearables; patent classes A61B5/00, G16H50/30) before any filing.
- Do **not** state "definitely patentable."
- Keep sensitive implementation details (exact fusion weights, calibration procedures) out of public judge handouts until a filing decision is made; publish only high-level methods.
- India: consider provisional application route if prior art clears; consult a patent attorney; maintain dated lab notebooks.

---

## PHASE 33 — TESTING

**Automated (extend the 84-test suite):**
- Parsing: `$CP`/`$CP2`/binary BLE frames; CRC16 + XOR CRC; malformed/corrupted frames; field-count errors.
- Transport: sequence gaps, duplicates, reordering, CRC failures, buffer-full behavior, reconnection/backoff, battery/connection interruption.
- Timestamps: monotonicity, drift correction, device-rate vs nominal.
- Signal processing: filter behavior, peak detection on synthetic waveforms, SQI thresholds.
- Features: missing-sensor masking, quality-gated missingness, baseline deviation math, cycle features.
- Model: inference, calibration, uncertainty gates, OOD flag, withheld decision.
- Baseline/change: outlier rejection, single/persistent/progressive/recovery classification, CUSUM detection on scripted series.
- DB: integrity, demo-vs-real separation, export/delete, encryption path.
- Dashboard: demo mode banner, withhold display, cycle-log persistence.

**Integration (new, the Phase-5 guarantee):**
- **Synthetic-BLE-server → `ble_reader` → extractor → SQLite → model → dashboard** end-to-end test (headless, no hardware).
- Same path over serial and TCP fixtures.
- A "hardware-in-the-loop" checklist (from `docs/V5_BUILD_GUIDE.md` §7) for the real pod: PPG pulse with finger, temp response, BLE notify, buffer sync after link drop, battery flag.

---

## PHASE 34 — FINAL V6 DEFINITION (A–Y)

### A. V5.1 weaknesses (summary)
Hand-tuned live risk equation with an over-weighted, scientifically indefensible hormone domain; flagship modules (change detector, ECG checkpoint, BLE transport, providers, insole) unwired; no real BLE path; no menstrual/symptom UI despite schema; SQI penalizes absent optional ECG; Mega 20 Hz vs 50 Hz mismatch; near-constant circadian domain with 0.60 weight; synthetic/real data share a store; Kaggle 0.959 AUC mislabeled; hormone "twin" invites the exact questions a judge should ask.

### B. V6 architecture
Pod → quality engine → features → stratified personal baseline → CUSUM/change layer → daily table (with masks) → two-stage GBDT fusion → calibration/uncertainty → SHAP explanation → dashboard; demo mode fully walled off; Evidence Center preserved.

### C. V6 hardware
ESP32-C3 + MAX30102 + IMU + MAX30205/NTC (+ ambient NTC) + LiPo/TP4056; GSR optional; AD8232 ECG periodic; manual BP/glucose.

### D. Wearable mechanical design
Upper-arm pod 50×36×14 mm, ~30 g, clip-on silicone strap, spring-loaded optical boss, insulated temp coin, IP54, pogo charging, ring = future.

### E. Firmware architecture
Burst sampling (30 s/5 min day, continuous night), LittleFS buffering with seq+CRC, BLE notify + status characteristic, wear/off duty cycling, status bits, device-clock sync.

### F. Wireless protocol
`[len][seq:4][device_ms:4][rate_hz:2][payload][crc16:2]` over BLE notify; ASCII `$CP/$CP2` retained for bench serial/TCP; seq-gap accounting everywhere.

### G. Signal-processing pipeline
Per-stream SQI (contact/clipping/regularity/ambient coupling/motion), quality-gated missingness, night-window aggregation, cosinor temperature rhythm, CUSUM on daily z-scores.

### H. Feature-engineering pipeline
Absolute + baseline-deviation + trend + persistence + variability + cycle-relative + mask features; deep/REM, hormones, VoxVasc, MV-AST excluded by construction.

### I. Personal-baseline system
Stratified (time-of-day × cycle phase) median/MAD/EWMA with outlier rejection; four-way single/persistent/progressive/recovery vocabulary; never a single-reading claim.

### J. Cycle-aware system
1-tap log → phase/length/irregularity/symptom features; phase only when reliable; cycle-relative physiology as H2 research feature.

### K. Change-point system
CUSUM + EWMA (primary), semantic single/persistent/progressive/recovery classifier (wired in), ≥3-day / ≥5-day persistence rules; PELT/Bayesian as future.

### L. Temporal model
GBDT on temporal features now; GRU/TCN only if data and head-to-head win; Transformer out of scope.

### M. Multimodal fusion
Availability masks + ordered imputation + quality gates; configurations A–D exercised; more data ≠ better (measured).

### N. PCOS risk model
Two-stage (physiological states → risk), calibrated, subject-level validated; equation demoted to labeled fallback; "RESEARCH PROTOTYPE — MODEL REQUIRES CLINICAL VALIDATION" until then.

### O. Calibration and uncertainty
Isotonic calibration, Brier/ECE, empirical CIs, coverage gate, OOD flag; never invented confidence.

### P. Explainability
SHAP/contributions with "contributed to the estimate" wording; baseline-vs-current; temporal contribution; six dashboard questions.

### Q. Dataset strategy
Three buckets (ML-dev, wearable-valid, clinical-valid); Kaggle for feature relationships only; wrist-PPG for sensor quality only; pilot for wearable validity; synthetic never validates.

### R. Leakage-proof validation
Subject-level GroupKFold + forward chaining + leakage checklist + AUPRC-primary + honest status ladder.

### S. Ablation experiments
Models 1–10 matrix with fixed protocol and removal rule; actual results only.

### T. Longitudinal research protocol
Ethics-gated pilot: N≈20–30, 8–12 weeks, consent, oversight, predefined reference standard, quality requirements, endpoints (Phase 21).

### U. Economic BOM
Prototype ₹1,765–2,900; scaled ₹805–1,370; removables listed; core = PPG+IMU+temp+MCU+battery+buffering.

### V. Dashboard design
6-element main screen; depth underneath; demo banner; withhold state; cycle log; Evidence Center.

### W. Competition demonstration
60-second script (Phase 30) + honesty ladder + working end-to-end path as differentiators.

### X. Patent/IP considerations
Candidate novelty list; prior-art search mandatory; no patentability claims; guarded disclosure; provisional-route note.

### Y. Exact implementation roadmap

| Milestone | Scope | Effort |
|---|---|---|
| M0 — Foundations | Fix bugs (§1.2 #1,#2,#4,#6,#10); wire ChangeDetector + real CircadianAnalyzer into the app; separate demo DB; relabel Kaggle AUC | 1–2 weeks |
| M1 — Scientific rework | Retire hormone twin from risk; two-stage model scaffold; SQI semantics fix; remove deep/REM/AMH/VoxVasc/MV-AST from core (Experimental Lab tab) | 2–3 weeks |
| M2 — BLE end-to-end | `bleak` client + `ble_reader`; synthetic BLE server; integration tests; protocol v6 in firmware; bench tests | 3–5 weeks |
| M3 — Pod hardware | Upper-arm pod build + firmware (buffering, night mode, sync); hardware-in-the-loop checklist | 4–8 weeks |
| M4 — Cycle-aware + longitudinal engine | Cycle log UI; stratified baselines; CUSUM; daily table; GBDT fusion + calibration + SHAP; ablation runner | 3–4 weeks |
| M5 — Pilot | Ethics/consent package; N≈20–30 × 8–12 weeks; LOSO + temporal validation; honest reporting | 8–12 weeks (parallel M2–M4) |
| M6 — Competition | Demo script, booth materials, evidence posters, prior-art search | 1 week |

---

## FINAL STATEMENT

V6 is deliberately **smaller and harder than V5**. It drops the impressive-but-weak modules (hormone twin, voice, MV-AST, deep/REM staging, insole) and invests everything in: a working BLE path, a quality engine that can say "no", a stratified personal baseline, cycle-aware modelling, a calibrated two-stage model, leakage-proof validation, and honest uncertainty. 

**The research question is not yet answered.** V6 is the instrument designed to answer it — and if the data says the wearable adds nothing, V6 reports that. That is the point.
