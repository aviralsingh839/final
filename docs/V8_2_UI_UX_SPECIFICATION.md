# CHRONO-PCOS V8.2 — UI/UX SPECIFICATION AND V8.1 → V8.2 GAP ANALYSIS

**V8.2 is a UI/UX and usability upgrade. No engine was rebuilt, no feature was
removed, no new medical capability was added.**

> Design principle: **"SIMPLE OUTSIDE. SOPHISTICATED INSIDE."**
>
> Simple enough for a patient. Powerful enough for a clinician. Deep enough
> for a researcher.

---

## 1. V8.1 audit (what was verified before changing anything)

The complete repository was inspected before any change:

| Area | V8.1 state (verified in code, not README) |
|---|---|
| UI architecture | Single `MainWindow` with 10 top-level numbered tabs (`01 Overview` … `10 Advanced`), plus a 12-tab inner "Advanced" container — **22+ visible surfaces** |
| Theme | One hardcoded dark "midnight ocean" stylesheet (`DARK_QSS`); custom-painted widgets (gauge, radar, clock, twin, fingerprint) hardcoded dark hex colors; no light mode; no switching |
| Typography | 9–10.5pt labels widespread, ALL-CAPS group titles, low-contrast muted text on dark panels, dense multi-panel tabs |
| Patient functionality | Patient inputs (cycle/symptoms/BP/glucose/weight/manual readings), care plan + adherence + reminders — all working, but presented in engineer-facing tabs |
| Clinical functionality | ClinicalTab (What Changed since last visit, report history/compare, ultrasound entry + notes, care journey, QR, Model A–E) — working |
| Research functionality | ValidationTab (metrics, leakage checks, ablation, calibration) + 12 advanced tools — working |
| Hardware | Serial (`ArduinoReader`), Wi-Fi bridge (`NetworkReader`), demo stream, replay — working |
| Signal processing | PPG/HRV/SpO₂/temperature/GSR/IMU/ECG pipelines — working |
| Baseline/longitudinal | `BaselineModel`, `ChangeDetector` (single/persistent/progressive/recovery), `FingerprintEngine`, `MultiDayAnalyzer` — working |
| ML/CV | Risk engine (transparent fallback), `UltrasoundCV` (quality gate; features UNKNOWN by design), `FusionEngine` (provenance + missing-modality weighting) — working |
| Reports | Weekly text/PDF, one-page clinical summary, full longitudinal HTML report, report history + comparison — working |
| QR | Dependency-free QR codec + de-identified report tokens — working |
| Tests | 129 tests passing (verified as run) |

### Gap analysis (V8.1 problems → V8.2 responses)

| # | V8.1 gap | V8.2 response |
|---|---|---|
| 1 | 10 + 12 technical tabs shown simultaneously | 4 top-level areas: **Patient / Clinician / Research / Settings** |
| 2 | No patient-facing view; first screen is a risk gauge | Patient **Overview — "How am I doing?"** (pattern, quality, coverage, WHAT CHANGED?, care) |
| 3 | Baseline shown as statistics strings | **My Baseline**: usual range · current · plain-language status; stats under TECHNICAL DETAILS |
| 4 | Forced dark theme, neon accents, gradients | Token-based theme system; **light clinical theme default**, dark optional, live switching |
| 5 | Tiny labels, ALL-CAPS, dense cards | Typography scale (20pt page titles / 13pt sections / 11pt body), sentence case, card padding |
| 6 | Level-3 detail (z-scores, contributor weights) on main screens | Three information levels; [WHY?] and [TECHNICAL DETAILS] expanders |
| 7 | Connection/profile controls permanently docked above all tabs | Moved to Settings; header keeps only status badges + Exhibition/theme buttons |
| 8 | Alarming red banner styling for withheld predictions | Calm tinted banners; alarming color reserved for real alerts |
| 9 | "Judge Mode" button buried in the control bar | **Exhibition mode** header button; seeds demo record, starts stream, lands on patient overview |
| 10 | Raw metric keys (`rmssd_ms`) in patient-facing text | Friendly names ("HRV (RMSSD)", "Skin temperature") in patient surfaces |

---

## 2. V8.2 architecture

```
MainWindow (engines unchanged: extractor, risk, change, fusion, US-CV, stores)
│
├── Header: title · LIVE/DEMO badge · battery · status · Exhibition mode · theme toggle
│
├── 👤 PATIENT (patient_tabs)
│   ├── Overview            src/ui/patient_pages.py: PatientOverviewPage
│   ├── My Baseline         src/ui/patient_pages.py: MyBaselinePage (+ fingerprint in details)
│   ├── My Timeline         change analysis card + HistoryTrendsTab
│   ├── Symptoms & Cycle    PatientInputsTab (unchanged)
│   ├── Care & Reminders    CarePlanTab (unchanged)
│   └── Reports             PatientReportsPage (text/PDF/JSON)
│
├── 🩺 CLINICIAN (clinician_tabs)
│   ├── Clinical Dashboard  ClinicalTab (What Changed, reports+compare, US+notes, QR, Model A–E)
│   ├── Analysis            risk gauge + CI + withheld banner, live vitals, contributors, trend
│   ├── Model Inputs        information-used grid + provenance/transparency + radar
│   ├── Live Signals        connection, sensor cards, PPG waveform
│   └── Ultrasound & Imaging UltrasoundFusionTab (unchanged)
│
├── 🔬 RESEARCH (research_tabs)
│   ├── Validation & Model Performance   ValidationTab (unchanged)
│   └── Advanced Tools      12 experimental modules (unchanged)
│
└── ⚙ SETTINGS
    ├── Device connection (serial / Wi-Fi bridge / demo)
    ├── Participant profile (optional)
    ├── Appearance (LIGHT default / DARK optional)
    └── About (version, scope, safety statement)
```

New shared modules:

* `src/ui/theme.py` — token-based theme system (LIGHT/DARK dictionaries,
  `build_qss()`, `apply_theme()`, `color()/qcolor()` for painted widgets,
  `tint()` for translucent chips, live pyqtgraph restyling registry).
* `src/ui/components.py` — `SectionCard`, `StatTile`, `StatusRow`
  (STABLE/IMPROVED/CHANGED/REVIEW), `CollapsibleSection`, `page_title`,
  `source_tag` (MEASURED / PATIENT REPORTED / CLINICALLY ENTERED /
  IMAGE-DERIVED / MODEL-INFERRED / DEMO DATA), `empty_state`, `status_banner`.
* `src/ui/patient_pages.py` — the three new patient pages.

---

## 3. Three information levels

| Level | Question | Where |
|---|---|---|
| 1 | What is happening? | Cards/tiles on every main view (plain statements) |
| 2 | Why is the system showing this? | **[WHY?]** expanders |
| 3 | What data/model/statistics support this? | **[TECHNICAL DETAILS]** expanders, Model Inputs, Research area |

---

## 4. Theme system

* Light is the default (`theme.apply_theme("light")` at window construction).
* Every surface color is a token; both themes define the identical token set
  (enforced by a test).
* Semantic status colors (green/amber/orange/red/accent) are theme-neutral
  mid-tones chosen to be readable on white **and** dark panels.
* Custom-painted widgets query tokens at paint time (`theme.qcolor(...)`),
  so a theme switch restyles gauges/radar/clock/fingerprint without restart.
* Translucent chips/banners use `theme.tint()` (rgba), never 8-digit hex —
  Qt parses `#RRGGBBAA`-style values as `#AARRGGBB` and silently produces
  wrong colors.

---

## 5. Exhibition mode (2–3 minute judge flow)

Header button → seeds a clearly-labelled synthetic record (DEMO DATA), starts
the demo stream, and lands on the patient overview.

1. Patient → Overview — "How am I doing?" (DEMO DATA labelled)
2. Patient → My Baseline — personal usual ranges
3. Patient → My Timeline — trends + change analysis
4. Clinician → Clinical Dashboard → What Changed since last visit
5. Clinician → Ultrasound & Imaging — upload → quality gate → features (UNKNOWN honesty) → fusion context
6. Clinician → Clinical Dashboard → generate report → QR / print

All synthetic data remains excluded from real analysis (`include_demo=False`
everywhere it mattered in V8.1 — unchanged).

---

## 6. Medical safety (unchanged, restated)

The application does **not** diagnose PCOS, replace ultrasound or a doctor,
predict cyst rupture, prescribe medication, or claim clinical validation.
Language used: *PCOS-related risk estimation · longitudinal monitoring ·
clinical decision support · research prototype*. Withheld-prediction rules,
UNKNOWN-by-design image features and DEMO exclusion are untouched.

---

## 7. Testing

* All 129 pre-V8.2 tests pass unmodified except for two intentional updates:
  * the window-structure test now asserts the 4-area navigation;
  * the version test asserts `8.2`.
* 10 new V8.2 tests (`tests/test_v8_2.py`) cover: light-default + dark
  switching, token completeness, navigation structure, V8.1-widget survival,
  patient-overview honesty (no fabricated values), calm status states,
  plain-language baseline ranges, exhibition-mode demo labelling, and
  provenance-label coverage.
* Verified at 1366×768 and 1920×1080 in both themes (offscreen render
  screenshots; no clipped text, no overlapping cards, no horizontal scroll).

## 8. Known limitations

* Semantic status colors are single mid-tones shared by both themes — ideal
  contrast is tuned for the light (default) theme.
* A handful of legacy research widgets (Advanced Tools) keep their original
  denser layouts; they are intentionally out of the main flow.
* No mobile build exists in this repository; the PC app is the
  clinical/research workstation. The patient section is designed so a future
  mobile companion can reuse its information architecture.
