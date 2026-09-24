# CHRONO-PCOS V6 — Implementation Status

*This file records what was actually changed in the codebase to turn the V5.1 audit/spec into the running V6 app. It is the honest companion to `V6_BUILD_SPECIFICATION.md` (design) and `V5_1_BUILD_SPECIFICATION.md` (prior audit).*

**Date of change round:** V6 UI/scientific-consistency pass.
**Test result after changes:** `97 passed` (84 pre-existing + 13 new V6 tests), run with `python -m pytest tests/ -q`.

---

## 1. Scientific core — risk engine (Phase 2 of the V6 requirements)

### `src/models/risk_engine.py` — REWRITTEN

The headline PCOS risk estimate is now computed **exclusively from defensible domains**:

| Domain | Source | Weight |
|---|---|---|
| Cycle irregularity | self-reported cycle length / irregularity / gap | 1.20 |
| Metabolic tendency | insulin-resistance proxy (BMI, glucose, sleep, stress) | 0.90 |
| Stress / autonomic load | HR / HRV / GSR | 0.60 |
| Sleep disruption | sleep/wake estimate | 0.50 |
| Circadian disruption | real CircadianAnalyzer cosinor metrics | 0.50 |
| Temperature rhythm | skin-temp rhythm disruption | 0.35 |
| Manual glucose risk | optional manual entry | 0.35 |
| Low activity | IMU-derived | 0.30 |
| Manual BP risk | optional manual entry | 0.20 |

**Removed from the score:** testosterone, AMH, LH, FSH, insulin, estrogen, progesterone, cortisol. `estimate(fv, hormones=..., phase=...)` still *accepts* hormone estimates for the research-illustration tab and the assistant, but they **never influence the risk percentage** — verified by test `test_v6_risk_engine_hormones_do_not_change_score`.

The engine remains explicitly labelled a **FALLBACK** (research-prototype weights); a trained, calibrated model must replace it before the system may be called validated.

### `src/validation/ablation.py` — UPDATED

Ablation now operates on the V6 domain set only (`cycle, metabolic, glucose, bp, stress_autonomic, sleep, circadian, temperature_rhythm, low_activity`). Endocrine / VoxVasc / metabolic-vascular domains removed. This is a **mechanism ablation of the explainable fallback engine**, not a trained-model ablation — documented as such.

## 2. Cycle awareness & patient inputs (Phases 7, 9, UI 5)

### `src/config.py` — UserProfile extended
Added `days_since_last_period` and `cycle_irregular` fields; version bumped to `6.0.0` with the honest label `"V6 — Personalized Longitudinal PCOS Risk Research Prototype (not clinically validated)"`.

### `src/ui/patient_inputs_tab.py` — NEW (V6)
Low-burden inputs: cycle day / usual length / "period started today" / irregularity checkbox / symptom checkboxes (Pain, Hair growth, Acne, Weight change, Fatigue, Other) / medication note / BP (SYS, DIA, pulse, source) / glucose (value, context) / weight. Every entry is timestamped into the local SQLite store (`menstrual_cycle`, `symptoms`, `bp_readings`, `glucose_readings`, `weight_readings`). A recent-entries table shows history. The tab never invents cycle phase — only what the user enters is used.

### `src/utils/history_store.py` — EXTENDED
`log_cycle_entry`, `log_symptom`, `log_bp`, `log_glucose`, `log_weight` and readers already existed; wiring verified by `test_v6_patient_inputs_store_round_trip`. `features_as_frame` / `export_features_csv` / `coverage_days` gained `include_demo` filtering so synthetic sessions can be excluded from real analysis.

### `src/models/multi_day.py` — UPDATED
`build_profile(..., include_demo=...)` passes the demo filter through; trajectories exclude synthetic rows unless the caller explicitly asks for them.

### `src/utils/synthetic.py` — UPDATED
Synthetic patient profiles now carry `cycle_length`, `cycle_irregular`, `days_since_last_period`, and generated rows are marked synthetic so they are excluded from real analysis.

## 3. Signal quality & live data honesty (Phases 5, 6)

### `src/features/realtime_features.py` — FIXED
- **Overall SQI is now the mean over *present* sensors only.** Optional channels (ECG, GSR) can no longer drag the score down when absent.
- **Circadian metrics now come from the real `CircadianAnalyzer`** (set by the main window's 60 s timer) instead of the near-constant placeholder.
- Feature-completeness and baseline-aware adjustment retained.

### `src/signal_processing/ppg.py` + `src/signal_processing/ecg.py` — BUG FIXED
The DC-blocker's zero initial condition created a huge warm-up transient that made peak detection blind for the first ~20 s of every session (HR/HRV = None even with a clean signal). Both processors now prime the blocker from the first sample, and the PPG peak detector skips the first 2 s of the analysis window as a safety net. Verified: clean synthetic PPG now yields HR within ~5–8 s; regression test `test_v6_synthetic_sample_flow`.

### `src/models/change_detector.py` — BUG FIXED
`pers_hours` indexed `ts[-(persistence+1)]`; when *every* point is out of band (persistence == n) this raised `IndexError` and crashed the UI update path. Index is now clamped (`min(persistence, len(ts)-1)`). Regression test `test_v6_change_detector_all_points_out_of_band_no_crash`.

## 4. UI restructure (Phases 13, UI 1–6, Judge Mode)

### `src/ui/main_window.py` — REWRITTEN
Exactly **7 top-level tabs**: `01 Overview`, `02 Live Wearable`, `03 Longitudinal`, `04 PCOS Analysis`, `05 Patient Inputs`, `06 Validation / Research`, `07 Advanced / Research Tools` (a nested tab container for hormone illustration, metabolic challenge, VoxVasc, what-if, research lab, AI assistant, evidence center, diagnostics, timeline, equipment/protocol, recommendations + alerts log).

Key behaviours added/kept:
- **Mode badge** in the header: `LIVE MODE` / `DEMO MODE (SYNTHETIC)` / `REPLAYING RECORDED DATA` / `NO STREAM`.
- **Withheld banner** on Overview and Live Wearable: `PREDICTION WITHHELD — <reason>` whenever the SQI/confidence decision layer says no; the gauge and the PCOS Analysis headline show `WITHHELD` instead of a number.
- **Change detector wired** into the Longitudinal tab (`ChangeDetector.evaluate` on live feature history every 15 s, per-metric phrases, quality gate, baseline reference).
- **Longitudinal coverage** counts real (non-demo) days only; demo/replay explicitly annotated.
- **Risk trend plot** on Overview from live-only history (demo data excluded).
- **Patient Inputs tab** wired to the live `UserProfile` (cycle fields propagate to the risk engine on save).
- **Judge Mode** (`_judge_demo`): synthetic calm baseline + clearly-marked synthetic week, opens Overview, sets DEMO badge.
- Legacy hormone tab demoted to a research illustration under Advanced with a prominent "NOT MEASURED — never enters the risk score" warning.

### Supporting widgets updated for the new domains
`src/ui/digital_twin.py` (cycle/metabolic/stress nodes), `src/ui/radar_chart.py` (V6 axis labels), `src/models/whatif.py` (V6 domain keys), `src/models/recommendations.py` (V6 domains).

## 5. Tests

### `tests/test_v6.py` — NEW (13 tests)
1. `test_v6_risk_engine_hormones_do_not_change_score`
2. `test_v6_risk_engine_cycle_domain`
3. `test_v6_risk_engine_domains_have_no_hormone_keys`
4. `test_v6_risk_engine_confidence_drops_without_cycle`
5. `test_v6_withhold_without_heart_data`
6. `test_v6_withhold_on_poor_quality`
7. `test_v6_allow_when_quality_good`
8. `test_v6_change_detector_all_points_out_of_band_no_crash` (regression)
9. `test_v6_change_detector_single_point_is_not_persistent`
10. `test_v6_patient_inputs_store_round_trip`
11. `test_v6_window_structure_and_mode_badge`
12. `test_v6_window_risk_flow_and_withheld_banner`
13. `test_v6_synthetic_sample_flow`

### Updated
- `tests/test_v5_master.py::test_versioning` (expects `6.` prefix; label assertion kept).
- `tests/test_validation.py::test_ablation_configs_and_rows` (V6 domain dict; 17 rows preserved; asserts no VoxVasc/endocrine names).

### Smoke checks performed
- `QT_QPA_PLATFORM=offscreen` construction of `MainWindow`, all 7 tabs built.
- Full demo stream run: HR ≈ 77 bpm, RMSSD ≈ 28 ms, SQI ≈ 0.97, risk ≈ 23 %, confidence ≈ 92 %, banner hidden, change state `NORMAL` after ~12 s.
- `python -m src.app --demo` runs without errors.

## 6. Files changed / created in this round

| File | Change |
|---|---|
| `src/config.py` | V6 version/label, UserProfile cycle fields |
| `src/models/risk_engine.py` | Rewritten (defensible domains, cycle domain, hormone-free score) |
| `src/validation/ablation.py` | V6 domain set |
| `src/models/whatif.py` | V6 domain keys |
| `src/models/recommendations.py` | V6 domains |
| `src/ui/radar_chart.py` | V6 axis labels |
| `src/ui/digital_twin.py` | V6 nodes |
| `src/features/realtime_features.py` | SQI over present sensors, real circadian wiring |
| `src/signal_processing/ppg.py` | DC-blocker priming + warm-up skip (bug fix) |
| `src/signal_processing/ecg.py` | DC-blocker priming (bug fix) |
| `src/models/change_detector.py` | Persistence index clamp (bug fix) |
| `src/utils/history_store.py` | include_demo filtering passthrough |
| `src/models/multi_day.py` | include_demo passthrough |
| `src/utils/synthetic.py` | cycle-aware profiles |
| `src/ui/patient_inputs_tab.py` | **NEW** — Patient Inputs tab |
| `src/ui/main_window.py` | Rewritten — 6+1 tabs, mode badge, withheld banners, change wiring, judge mode |
| `tests/test_v6.py` | **NEW** — 13 V6 tests |
| `tests/test_v5_master.py` | version assertion |
| `tests/test_validation.py` | ablation domain dict |
| `README.md` | Rewritten for V6 |
| `docs/V6_IMPLEMENTATION_STATUS.md` | This file |

## 7. Exact remaining limitations (unchanged from the audit)

1. **No BLE client in Python yet.** The V6 wearable pod (ESP32 + BLE) is design + firmware; the app currently consumes USB serial or the ESP8266 TCP bridge. The BLE path is milestone M3 of `V6_BUILD_SPECIFICATION.md`.
2. **Live risk engine is still a transparent fallback equation.** Weights are research prototypes; a trained + calibrated fusion model is milestone M4 and requires labelled longitudinal data (which does not exist publicly).
3. **Firmware sample-rate mismatch:** the Mega streams at 20 Hz while several signal-processing constants assume 50 Hz. The PPG pipeline now tolerates the actual delivered rate, but a formal 50 Hz (or rate-adaptive) firmware update is a listed M0 fix.
4. **The Kaggle 0.959 AUC is a clinical-variable model on one single-site referral cohort.** It is a model-development result and is never presented as wearable accuracy.
5. **No human-data collection has been performed.** Any pilot study requires ethics/institutional approval, informed consent, and adult/teacher/clinician oversight.
6. SpO₂ educational only; sleep staging approximate; skin temp ≠ core temp; no hormone is directly measured by any sensor.

## 8. How to run

```bash
# Full test suite (97 tests)
python -m pytest tests/ -q

# Demo mode (synthetic, clearly labelled)
python -m src.app --demo
# or
python run_demo.py

# LIVE mode (USB serial)
python -m src.app --port COM5        # Windows
python -m src.app --port /dev/ttyACM0  # Linux/macOS

# LIVE mode (ESP8266 Wi-Fi bridge)
python -m src.app --net 192.168.4.1:7777
```

Judge Mode: press **"Judge Mode (60 s demo)"** in the connection bar, or follow the Overview → Longitudinal → PCOS Analysis → Validation flow.

**State of wearable integration:** serial + Wi-Fi bridge paths are implemented and tested end-to-end with the demo stream; real-device validation requires the hardware. **State of PCOS model integration:** the fallback engine is wired into the live path with honest labelling; a trained model is the next research milestone.
