# CHRONO V9.0 — PCOD/PMOS detection, complication screening, smartwatch link and portable companion

V9.0 adds a **second clinical surface** to CHRONO-PCOS. V8.2 and earlier asked
one question — *"what changed since the last visit?"* — using continuous
physiology. V9.0 adds the two questions clinicians and patients actually ask
first:

| Section | Question | Engine |
|---|---|---|
| **① PCOD / PMOS detection** | *"Do I meet the diagnostic criteria?"* | `src/pcod/criteria.py` |
| **② PCOD / PMOS complication screening** | *"Which complication checks am I due for?"* | `src/pcod/complications.py` |

Everything in V8.2 is untouched. V9.0 is additive.

---

## 0. The 2026 naming change (why "PCOD" in the UI)

On **12 May 2026** an international consensus published in *The Lancet*
renamed PCOS to **PMOS — Polyendocrine Metabolic Ovarian Syndrome**
(Teede, Khomami, Morman et al., DOI `10.1016/S0140-6736(26)00717-8`). The
rename followed a multi-step process involving 56 organisations and more than
14,000 patients and health professionals.

**What changed:** the name only.
**What did not change:** the diagnostic criteria (Rotterdam 2003 as updated by
the 2023 International Evidence-based Guideline), treatments, and ICD-10
`E28.2`. A three-year transition runs to the 2028 guideline update, when
ICD-11 is expected to follow.

This app therefore labels itself `PMOS (PCOS / PCOD)`. `PCOD` is kept as a
recognised lay synonym because it is the term most people in India actually
search for, and hiding it would hurt discoverability for the exact population
this serves.

---

## 1. Section 1 — PCOD / PMOS detection

### What it implements

The **evidence-based Rotterdam criteria** as refined by the 2023 International
Guideline:

**Adults** — at least **two of three**, after other causes are excluded:

1. **Ovulatory dysfunction** — cycles `<21` or `>35` days, or `<8` cycles/year,
   or any single cycle `>90` days (from 3 years post-menarche to perimenopause).
2. **Clinical or biochemical hyperandrogenism** — hirsutism, or raised total /
   free testosterone (or calculated free androgen index).
3. **Polycystic ovarian morphology** — FNPO `≥ 20` in at least one ovary, or
   ovarian volume `≥ 10 mL` / FNPS `≥ 10` on older equipment; **or**, in adults,
   raised AMH against the laboratory's own cut-off.

**Adolescents** — **both** hyperandrogenism **and** ovulatory dysfunction are
required. Ultrasound and AMH are **not** recommended (poor specificity).
Cycle thresholds are wider: `<21` or `>45` days from 1 to `<3` years
post-menarche; irregular cycles are *normal* in the first year.

### Honesty rules (enforced, not aspirational)

| Rule | Why |
|---|---|
| Each criterion is `PRESENT` / `ABSENT` / **`UNKNOWN`** | An unmeasured test is never counted as a "no". |
| **No universal AMH threshold** | The 2023 guideline gives none; cut-offs differ substantially between the Gen II, picoAMH, Elecsys and Access platforms. The app asks for *your lab's* cut-off and stays `UNKNOWN` without it. |
| **"Meets 2 of 3" is not a diagnosis** | Other causes (TSH, prolactin, 17-OH progesterone) must be excluded first, and a clinician confirms. |
| **Ultrasound not needed** when both irregular cycles and hyperandrogenism are present | Guideline 1.4.9 — implemented as `ultrasound_needed = False`. |
| **Watch data can never establish a criterion** | It is reported only as supportive longitudinal context. |

Worked examples (all covered by `tests/test_pcod_v9.py`):

| Input | Result |
|---|---|
| Nothing recorded | `CANNOT_BE_DETERMINED`, 3 × `UNKNOWN` |
| Adult, 52-day cycles + hirsutism + FNPO 24, exclusions done | `MEETS_CRITERIA`, ultrasound not needed |
| Adult, 52-day cycles + hirsutism only | `MEETS_CRITERIA` (guideline 1.4.9) |
| 16 y/o, 2 y post-menarche, 40-day cycles + hirsutism | `DOES_NOT_MEET` (threshold is 45, not 35) |
| 16 y/o, 2 y post-menarche, 50-day cycles + hirsutism | `MEETS_CRITERIA` (adolescent rule: both required, both present) |
| <1 year post-menarche | `UNKNOWN` — irregular cycles are normal |
| AMH 8.2 with no lab cut-off | `UNKNOWN`, blocker explains why |
| AMH 8.2 **with** lab cut-off 4.7 | `PRESENT` |

---

## 2. Section 2 — complication screening

### What it is

A **screening-status engine**, deliberately *not* a risk predictor. For each of
ten domains it answers: *is an assessment due, overdue, up to date, or not
indicated — and what resolves it?*

**No "your risk is 42%" number is produced anywhere.** Fabricating one from
wearable data plus a few manual entries would be unsupportable, so the app
refuses to.

### Status vocabulary

| Status | Meaning |
|---|---|
| `ACTION_NEEDED` | A signal is present that warrants clinical assessment now |
| `OVERDUE` | Well past the guideline interval |
| `DUE` | The guideline interval has elapsed |
| `UP_TO_DATE` | Assessed within the interval |
| `UNKNOWN` | Never assessed — no value recorded, **never assumed normal** |
| `NOT_INDICATED` | The guideline explicitly advises *against* routine screening |

### The ten domains and their intervals

| Domain | Interval | Source |
|---|---|---|
| Impaired glucose tolerance / T2DM | At diagnosis in **all**, then 1–3 years (1 year if risk factors) | rec 1.9.1–1.9.4 |
| Dyslipidaemia | At diagnosis in **all**, then ≈2 years | rec 1.8.3 |
| Hypertension | At diagnosis and each visit, min 6–12 months | rec 1.8.2 |
| Overweight / central adiposity | Each visit, min 6–12 months | rec 1.8.4 |
| Cardiovascular risk | Risk factors at diagnosis | rec 1.8.1 |
| Obstructive sleep apnoea | **Symptom screen only** — no routine screening | RCOG GTG 33 |
| Depression and anxiety | **All** patients, regionally validated tool | rec 1.10 |
| NAFLD | Awareness only — **routine screening not recommended** | Allen 2022 |
| Endometrial hyperplasia / cancer | **No routine screening**; act on bleeding or amenorrhoea >90 days | StatPearls / AAFP |
| Fertility and pregnancy | At diagnosis and each life-stage change; GDM screen 24–28 weeks | rec 1.11 |

### Two details that matter clinically

1. **The Asian BMI cut-off is 23, not 25.** For the Indian population this app
   serves, the action threshold for adiposity-related screening is `BMI ≥ 23`.
   This is a user-selectable input (`asian_ethnicity`), not an assumption.
2. **`NOT_INDICATED` is a real recommendation, not a gap.** NAFLD and
   asymptomatic endometrial screening stay `NOT_INDICATED` *even when risk
   factors are present*, because current guidance advises against routine
   screening. The UI says so explicitly so it is never read as an oversight.

---

## 3. Smartwatch link

Three ingest paths, identical treatment once data arrives:

### 3.1 Web Bluetooth (BLE)

The browser connects directly to the watch's standard **Heart Rate service**
(`0x180D`) and **Battery service** (`0x180F`). No native Bluetooth driver is
needed — which is precisely why this works on an Android phone under Termux,
where a Python BLE stack is unavailable.

Frames are parsed per the GATT `0x2A37` Heart Rate Measurement spec, including
the RR-interval block (uint16, 1/1024 s resolution → ms), from which RMSSD is
computed.

*Requires Chrome or Edge* (Web Bluetooth is not in Safari or Firefox), and on
Android requires Location + Nearby devices permissions.

### 3.2 HTTP ingest

Any watch, phone bridge, Wear OS app, Tasker profile or Gadgetbridge export can
POST JSON:

```bash
curl -X POST http://<device-ip>:8000/api/watch/ingest \
  -H "Content-Type: application/json" \
  -d '{"hr_bpm":72,"steps":4300,"spo2_pct":97,"sleep_hours":7.2,"device":"My Watch"}'
```

Field aliases are accepted (`hr` / `heart_rate`, `spo2`, `step_count`, `rri`, …).

### 3.3 Simulated watch

A clearly-labelled synthetic generator (`source="simulated"`) so the whole app
is demonstrable with no hardware. Simulated rows are tagged and can be cleared
independently of real data.

### Validation

Out-of-range values are **rejected, never clamped into plausibility**
(HR 25–220, SpO₂ 70–100, wrist temp 20–45 °C, RR 200–2500 ms). Consumer SpO₂
is stored and displayed as a *wellness estimate* and never feeds a sleep-apnoea
conclusion.

---

## 4. Portability

### 4.1 Server (primary — this is the phone-first path)

`web/server.py` uses **only the Python standard library**: no Flask, no Qt, no
numpy. It runs on CPython 3.9+ on a laptop, a Raspberry Pi, or Android/Termux.

```bash
python web/server.py --demo          # or: python run_companion.py
bash termux_setup.sh                 # one-time on Android, then: chrono
```

Served as a **PWA** (manifest + service worker), so it installs to the home
screen and opens offline.

### 4.2 Single-file edition

```bash
python tools/build_portable.py       # → dist/CHRONO_PMOS_Portable.html (~142 KB)
```

One self-contained HTML document — CSS, client script, engines and the full
evidence registry inlined. Double-click to run; no server, no Python, no
internet. Suitable for a USB stick or an email attachment.

**Known, deliberate limitation:** Web Bluetooth requires a secure context,
which `file://` is not. The single-file edition therefore disables pairing and
says so. Use the server build on the phone for Bluetooth.

### 4.3 Keeping the two engines in sync

The single-file build re-implements both engines in JavaScript
(`web/static/engine.js`) because no Python runtime is available under
`file://`. To stop the two drifting, `tests/test_portable_parity.py` runs
**14 fixtures through both implementations** and fails on any difference in
life stage, verdict, per-criterion status, per-domain status or status counts.

Static prose is not retyped either: `build_portable.py` **extracts** `why`,
`action` and `watch_support` text from the running Python engines, so wording
cannot diverge either.

---

## 5. Architecture

```
src/pcod/                  ← Qt-free, the single source of truth
    evidence.py            ← cited 2026-era registry (37 items, 13 topics)
    criteria.py            ← Section 1
    complications.py       ← Section 2
    watch.py               ← ingest, validation, storage, simulation
    assessment.py          ← combined report + plain-text export

web/                       ← portable companion
    server.py              ← stdlib-only HTTP server + REST API
    static/                ← PWA shell, styles, client, engine.js mirror

tools/build_portable.py    ← single-file build
termux_setup.sh            ← Android installer

src/ui/pcod_pages.py       ← Qt mirror (same engines, no duplicated logic)
```

Both surfaces call **the same** `src/pcod` code paths, so the phone and the
desktop cannot disagree.

---

## 6. Medical safety

* Not a diagnostic device. Section 1 produces a **screening result**; a
  clinician confirms and excludes other causes.
* Section 2 produces a **checklist**, not a risk percentage.
* A smartwatch cannot measure testosterone, AMH, glucose, HbA1c, lipids,
  insulin or ovarian morphology. The app states this on every relevant screen.
* Nothing starts, stops, prescribes or changes treatment.
* Every clinical statement carries a citation into `src/pcod/evidence.py`.

---

## 7. Testing

`tests/test_pcod_v9.py` — 50 tests covering:

* Evidence integrity (unique ids, real URLs, no invented AMH threshold, the
  2026 rename recorded)
* Section 1: all eight worked examples above, plus exclusions gating and the
  guarantee that a fully-populated watch never flips a criterion
* Section 2: interval maths, escalation on abnormal labs, the Asian BMI
  threshold, `NOT_INDICATED` invariance, symptom-only OSA screening, and that
  every domain is cited
* Watch: range rejection, RMSSD minimum beats, field aliases, round-trip
  persistence, simulated-data separation
* **JS ↔ Python parity across 14 fixtures**
* The portable build contains no external references and carries the prose

Plus two new Qt tests asserting the five-area navigation and that both
sections are present and render honestly with empty input.
