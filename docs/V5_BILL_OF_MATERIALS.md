# CHRONO-PCOS V5 — Bill of Materials (wearable ecosystem)

> Economic-feasibility note (V5 rule 30): every component is judged on **cost,
> power, benefit, data quality, and whether it materially improves the model**.
> Nothing here is required — the dashboard runs fully offline with the demo
> simulator, or with just the MAX30102 ring + temperature sensor. Prices are
> rough single-unit retail estimates in USD and will vary by region/vendor.

## Core continuous wearable (the ring)

| Component | Qty | Approx. cost | Purpose | Alternative | Importance |
|---|---|---|---|---|---|
| ESP32-C3 / nRF52832-class MCU | 1 | $3–6 | BLE host, local buffering, duty cycling | nRF52840 | Required |
| MAX30102 PPG (IR+red) | 1 | $4–8 | HR, HRV, SpO₂-proxy, pulse waveform | MAX30100 (cheaper), MAX30101 | Required — HR/HRV drive most domains |
| MPU6050 / LSM6DS3 IMU | 1 | $2–5 | motion index, activity, artifact gating | LIS3DH (lower power) | High — quality gate for PPG |
| DS18B20 / NTC skin temp | 1 | $1–3 | temperature rhythm, circadian | MAX30205 (medical-grade, pricier) | High — circadian + metabolic domains |
| Li-ion 120–250 mAh + charger | 1 | $2–4 | continuous wear, rechargeable | coin cell (shorter life) | Required |
| 3D-printed enclosure / band | 1 | $1–3 | comfort, long-duration wear | silicone band | Medium |

## Optional chest patch (periodic ECG checkpoint)

| Component | Qty | Approx. cost | Purpose | Alternative | Importance |
|---|---|---|---|---|---|
| AD8232 single-lead ECG front-end | 1 | $4–6 | periodic high-quality ECG checkpoint, HRV validation | MAX30001 (integrated, pricier) | High for validation, not required daily |
| ECG electrodes | 10 | $2–4 | skin contact per session | reusable gel pads | Medium |
| Same MCU family as ring | 1 | — | reuse BLE + buffering stack | — | — |

## Optional smart insole (behavioural/biomechanical signal)

| Component | Qty | Approx. cost | Purpose | Alternative | Importance |
|---|---|---|---|---|---|
| 4–8 FSR / force sensors (heel, midfoot, forefoot, toe) | 8 | $4–8 | steps, cadence, stance, L/R asymmetry, gait consistency | Velostat DIY (cheaper, noisier) | Low for risk; medium for activity/gait research |
| IMU (shared part) | 1 | $2–5 | cadence/activity validation | — | Medium |
| Thin flex PCB insole | 1 | $5–10 | mechanical integration | 3D-printed insole tray | Medium |

## Optional continuous GSR

| Component | Qty | Approx. cost | Purpose | Alternative | Importance |
|---|---|---|---|---|---|
| GSR electrodes + op-amp stage | 1 | $3–6 | sympathetic arousal, stress domain | MAX30009 (integrated) | Medium — stress is already partly covered by HRV |
| Silver/silver-chloride pads | 10 | $2–4 | contact quality | dry electrodes (research) | Medium |

## Manual / clinical inputs (no hardware)

| Component | Cost | Purpose |
|---|---|---|
| BP cuff (any validated home device) | $15–30 | manual systolic/diastolic/pulse entries |
| Glucose meter + strips | $10–20 | fasting/post-meal glucose entries |
| Scale | $10–20 | weekly weight entries |

## What actually improves the model? (honest assessment)

Based on the ablation framework in `src/validation/ablation.py` and the trained
evidence so far:

- **PPG (HR/HRV/SpO₂-proxy) + temperature + IMU** — the highest-value core.
  HR/HRV feed stress, sleep, circadian and metabolic domains; temperature feeds
  the circadian rhythm; IMU gates PPG quality (motion artifacts).
- **Periodic ECG checkpoint** — the strongest *validation* addition: it gives an
  independent HR/HRV reference and an ECG history, but it is a periodic
  measurement, not a 24/7 signal. Do not claim it is required weekly for
  clinical reasons — it is a *research monitoring checkpoint*.
- **GSR** — useful for the stress domain but partially redundant with HRV;
  the ablation table shows its marginal contribution per deployment.
- **Smart insole** — a behavioural signal (activity consistency, gait
  variability, L/R asymmetry) with **no direct PCOS claim**. Its value is for
  the longitudinal activity domain, not diagnosis; ablation should decide
  whether it earns a place in the fusion.
- **Environment sensors (light, room T/H/P)** — cheap, minor circadian assist.

No sensor is claimed to improve accuracy without experimental evidence: run the
ablation laboratory (Validation Lab → Ablation) and the cross-modal comparison
to see the measured contribution on real data.

## Power / wearability targets

- BLE (not continuous Wi-Fi) for the ring; the existing ESP8266 Wi-Fi bridge
  remains for the desktop link where already used.
- Sensor duty cycling: PPG/IMU bursts with sleep modes between windows.
- Local buffering (sequence numbers + CRC16 + duplicate detection) so the
  wearable loses no data while the laptop is away; sync on reconnect.
- Battery level and charging status are surfaced in the UI; no battery-life
  numbers are invented without hardware testing.

## Hardware connection matrix (V5 provider → device)

| Provider | Typical device | Link type |
|---|---|---|
| `RingPPGProvider` | MAX30102 + IMU + temp (ring) | BLE (or serial for bench) |
| `ChestECGProvider` | AD8232 chest module | BLE / serial |
| `SkinTempProvider` | DS18B20 / NTC | serial / BLE |
| `GSRProvider` | GSR electrodes | serial / BLE |
| `IMUProvider` | MPU6050 | serial / BLE |
| `InsoleProvider` | FSR array insole | BLE / serial |
| `BloodPressureProvider` | validated home cuff | manual entry |
| `GlucoseProvider` | glucose meter | manual entry |

See `ARDUINO_MEGA_WIRING_AND_BOM_GUIDE.md` (project root) for the existing
Mega/UNO wiring, and the `arduino/` firmware for the serial protocol. The V5
transport layer (`src/hardware/transport.py`) validates every packet with CRC16
and sequence numbers regardless of link type.
