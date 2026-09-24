# CHRONO-PCOS V5 — Hardware Build Guide (wearable ecosystem)

**Project:** CHRONO-PCOS V5 — Longitudinal Multimodal Wearable Prototype (research, not clinically validated)
**Companion doc:** `docs/V5_BILL_OF_MATERIALS.md` (cost / power / benefit table)

This guide builds the modular V5 ecosystem one module at a time. Every module
is **optional** — the dashboard runs with just the ring, or even with no
hardware at all (demo simulators). Build order:

```text
Module A  Smart ring (continuous wearable)   — required for live monitoring
Module B  Chest ECG patch (periodic checkpoint) — validation / HRV reference
Module C  Smart insole (behavioural signal)  — activity / gait research
Module D  GSR electrodes (optional)          — stress domain
```

> **Medical safety:** educational physiological monitoring only — not a
> diagnostic medical device. No module "measures hormones" or "sees cysts".
> Skin-contact sensors: clean electrodes/optics between users, keep currents
> below safety limits, and never power a user-connected circuit from mains.

---

## 0. Tools, skills, safety checklist

| Item | Notes |
|---|---|
| Soldering iron + flux | All modules are through-hole / breakout boards |
| USB-C programmer for ESP32-C3 | e.g. ESP32-C3-DevKitM-1 or a bare C3 with USB |
| Multimeter | continuity + 3.3 V rail check before plugging sensors |
| Bench power (3.3 V) for first power-up | never first-power from the Li-ion directly |
| Arduino IDE 2.x + board package | `esp32` by Espressif, or PlatformIO |
| Libraries | SparkFun MAX3010x, Adafruit MPU6050 + Unified Sensor, OneWire, DallasTemperature, ESP32 BLE (built-in) |

**First-power rule:** power the board from USB (3.3 V) and confirm the serial
console prints `$CP2,` lines *before* attaching the battery. Inspect the 3.3 V
rail for shorts with the multimeter first.

---

## 1. Module A — Smart ring (continuous wearable)

### 1.1 Bill of parts

| Part | Qty | Notes |
|---|---|---|
| ESP32-C3 board | 1 | low-power BLE; nRF52832 is an alternative |
| MAX30102 breakout | 1 | PPG IR+red; address 0x57 |
| MPU6050 / LSM6DS3 breakout | 1 | motion / artifact gating |
| DS18B20 (waterproof probe or TO-92) | 1 | skin temperature |
| 120–250 mAh Li-ion + TP4056 charger | 1 | rechargeable, ~1–3 days at 50 Hz bursts |
| Slide switch + 100 nF decoupling caps | 2–4 | power isolation + I2C stability |

### 1.2 Wiring (ESP32-C3)

| Sensor pin | ESP32-C3 pin | Notes |
|---|---|---|
| MAX30102 VIN | 3V3 | 3.3 V only |
| MAX30102 GND | GND | common ground |
| MAX30102 SDA | GPIO8 (I2C SDA) | shared I2C bus |
| MAX30102 SCL | GPIO9 (I2C SCL) | shared I2C bus |
| MPU6050 VCC | 3V3 | |
| MPU6050 SDA/SCL | GPIO8 / GPIO9 | same bus, different address |
| MPU6050 AD0 | GND | address 0x68 |
| DS18B20 VDD/GND/DQ | 3V3 / GND / GPIO10 | 4.7 kΩ pull-up on DQ |
| Battery ADC (via 100 kΩ/100 kΩ divider) | GPIO2 | see 1.4 |

ESP32-C3 I2C pins are configurable in software; the sketch below uses
`I2C_SDA = 8`, `I2C_SCL = 9`, `TEMP_PIN = 10`, `BATT_PIN = 2`.

### 1.3 Firmware

Reference sketch (compile-tested logic, verify on your board):

```text
arduino/chrono_pcos_v5_ring/chrono_pcos_v5_ring.ino
```

What it does:

- reads MAX30102 (IR + red), MPU6050 (accel), DS18B20 (skin temp) at 50 Hz;
- publishes the **existing `$CP2` serial protocol** (same fields as the Mega
  build, with unused channels zeroed) so the current dashboard reader consumes
  it unchanged:
  `$CP2,ms,ir,red,ax,ay,az,gx,gy,gz,temp0,temp1,gsr,micRaw,micRms,micPitch,ecg,fsr,lux,roomT,hum,press,buttons,status,crc`;
- additionally broadcasts the payload as a **BLE notify** on a configurable
  service/characteristic (see §5) for the V5 `Transport`/`LocalBuffer` path;
- duty-cycles: bursts of 50 Hz sampling with a settable sleep window, and
  reports battery % on `BATT` via the status field.

Wireless fallback: the same payload can go over the ESP8266 Wi-Fi bridge
(`arduino/chrono_pcos_esp8266_bridge`) or directly over USB serial
(`python -m src.app --port /dev/ttyACM0`).

### 1.4 Battery and power

- Li-ion cell → TP4056 B+ / B−; TP4056 OUT+ → switch → 3.3 V regulator input.
- The ESP32-C3 DevKit's 3V3 pin already regulates USB 5 V; for battery use the
  **regulated 3.3 V out** (e.g. TP4056 + HT7333 LDO), never raw 4.2 V into a
  sensor.
- Battery ADC: divide battery voltage by 2 (two 100 kΩ resistors) into GPIO2;
  read with `analogReadMilliVolts()*2`. Calibrate the two endpoints against a
  multimeter — the app displays the raw percentage from the firmware, and it
  never claims an accuracy it doesn't have.
- Keep the firmware in modem-sleep between bursts when not worn (see sketch).

### 1.5 Enclosure

- 3D-print a ring/tracker body that holds the battery + PCB, with the MAX30102
  window facing the skin and a small strap.
- Keep the DS18B20 probe pressed against skin (thin thermal pad, not against
  the PCB heat).
- Seal seams with epoxy for sweat resistance; make the battery removable for
  charging.

---

## 2. Module B — Chest ECG patch (periodic checkpoint)

ECG is a **periodic high-quality measurement** (default suggested cadence:
every 7 days — a *research monitoring checkpoint*, never a clinically required
schedule). 30–60 s per session at 256 Hz.

### 2.1 Parts

| Part | Qty | Notes |
|---|---|---|
| AD8232 single-lead heart-rate monitor breakout | 1 | SparkFun-style |
| ESP32-C3 (or reuse ring MCU) | 1 | second device or shared |
| ECG electrodes (3 per session) | 3 | RA / LA / RL |
| 3.3 V Li-ion + charger | 1 | |

### 2.2 Wiring

| AD8232 pin | ESP32-C3 pin | Notes |
|---|---|---|
| VCC | 3V3 | |
| GND | GND | |
| OUTPUT | GPIO0 (ADC1) | analog ECG out |
| LOD+ / LOD− | GPIO3 / GPIO4 (optional) | lead-off detection |
| SDN | 3V3 (or GPIO5 to sleep) | |

Electrode placement (standard limb lead I): RA (right wrist/chest), LA (left
chest), RL (right lower chest, reference). Follow the AD8232 datasheet for the
right-leg-drive wiring.

### 2.3 Firmware

```text
arduino/chrono_pcos_v5_ecg/chrono_pcos_v5_ecg.ino
```

- samples ADC at 256 Hz and streams `$ECG,ms,raw,crc`;
- the app-side ECG checkpoint session (`src/hardware/ecg_checkpoint.py`) takes
  `(timestamp, raw)` samples and computes HR / RMSSD / SDNN / quality, and the
  checkpoint history compares against previous sessions;
- a "record for 30–60 s then stop" workflow keeps power low — the patch is not
  a 24/7 stream.

---

## 3. Module C — Smart insole (behavioural signal)

An **optional** behavioural/biomechanical longitudinal signal. It does not
"detect PCOS" — it feeds the activity/gait domain.

### 3.1 Parts

| Part | Qty | Notes |
|---|---|---|
| ESP32-C3 | 1 | |
| FSR-402 (or Velostat DIY) pressure sensors | 8 | heel ×2, midfoot ×2, forefoot ×2, toe ×2 |
| CD74HC4067 16-ch analog mux | 1 | ESP32-C3 has few ADC pins |
| MPU6050 | 1 | cadence / impact validation |
| Thin flex PCB or 3D-printed tray | 1 | |

### 3.2 Wiring

| Part | ESP32-C3 | Notes |
|---|---|---|
| 4067 S0–S3 | GPIO1,2,3,4 | mux select |
| 4067 SIG | GPIO0 (ADC1) | muxed analog |
| 4067 EN | GND (enabled) | |
| FSR array | 4067 CH0–CH7 | each FSR: 3V3 → FSR → 10 kΩ → GND, junction → mux channel |
| MPU6050 | I2C GPIO8/9 | |

Zone map (see `src/hardware/insole.py` `ZONE_NAMES`):
`CH0 left_heel, CH1 left_midfoot, CH2 left_forefoot, CH3 left_toe,
 CH4 right_heel, CH5 right_midfoot, CH6 right_forefoot, CH7 right_toe`.

### 3.3 Firmware

```text
arduino/chrono_pcos_v5_insole/chrono_pcos_v5_insole.ino
```

- scans the 8 FSR channels + accel at 50 Hz, emits `$INS,ms,z1..z8,ax,ay,az,crc`;
- the app-side `InsoleAnalyzer` (`src/hardware/insole.py`) computes step count,
  cadence, stance time, left/right asymmetry and gait consistency from these
  frames.

---

## 4. Module D — GSR (optional)

Two silver/silver-chloride electrodes on the palm/wrist, an op-amp stage
(simple voltage divider + buffer, see the Mega wiring doc) into an ADC pin.
50–100 nA drive currents; never exceed skin-safety limits. Feed the value into
the `$CP2` `gsr` field of Module A's firmware or stream it on the same serial
line. The dashboard's GSR provider and SQI already expect this channel.

---

## 5. Wireless protocol (V5 transport)

The app's `src/hardware/transport.py` defines the framing used by any link:

```text
frame = [len:1][seq:4 little-endian][payload][crc16-ccitt:2]
```

- **Serial:** the classic ASCII `$CP2,...` / `$ECG,...` / `$INS,...` lines
  (XOR CRC in the last field) are consumed by `PacketParser`;
- **BLE:** the ring advertises a service, one characteristic carries the
  payload bytes, and the client reconstructs frames from `len + seq + crc16`;
  `LocalBuffer` deduplicates and reports any dropped/reordered frames so the
  app always knows how much data it actually has;
- **Wi-Fi:** existing `chrono_pcos_esp8266_bridge` relays the same serial bytes
  over TCP port 7777 (`python -m src.app --net 192.168.4.1:7777`).

The `BlePacketProtocol`/`LocalBuffer` unit tests (`tests/test_v5_master.py`)
are the reference behaviour: a corrupted packet must be rejected, a duplicate
must be counted, and pull-order must be sorted.

---

## 6. Connecting to the app

| Source | Command / path |
|---|---|
| Ring over USB serial | `python -m src.app --port /dev/ttyACM0` (or COM5) |
| Ring/Mega over Wi-Fi bridge | `python -m src.app --net 192.168.4.1:7777` |
| No hardware (demo) | `python -m src.app --demo` (simulated ring/insole/ECG) |
| ECG checkpoint sessions | `src/hardware/ecg_checkpoint.ECGCheckpointSession` (feed samples) |
| Insole frames | `src/hardware.insole.InsoleAnalyzer.analyze(list_of_frames)` |

New hardware plugs into a `SensorProvider` (`src/hardware/providers.py`) so
the rest of the app never changes when a sensor is swapped.

---

## 7. Bench-test & verification checklist

1. **Power:** 3.3 V rail steady, no warm components, USB console boots.
2. **Ring serial:** see `$CP2` lines at 50 Hz; `ir`/`red` pulse when a finger
   covers the window; `crc` field always passes the app's parser (run
   `python -m pytest tests/test_packet_parser.py`).
3. **Ring BLE:** connect with a BLE client, enable notify, frames decode with
   matching CRC16 (reference: `BlePacketProtocol` tests).
4. **ECG patch:** run a 30 s session; the checkpoint reports HR within ±3 bpm
   of a finger-counted pulse on a clean recording, quality > 0.5 (reference:
   `test_ecg_checkpoint_session`).
5. **Insole:** walk 10 s; `InsoleAnalyzer` reports steps ≈ cadence×time,
   L/R asymmetry small when balanced (reference: `test_insole_analysis`).
6. **Data completeness:** kill the BLE link for 30 s, reconnect — `LocalBuffer`
   stats show exactly how many frames were dropped; the app shows a quality
   warning rather than pretending the gap doesn't exist.
7. **Baseline:** run the 5-min calm calibration; confirm the personal baseline
   updates only gradually (an outlier run must not shift it — reference:
   `test_baseline_gradual_updates`).

---

## 8. Power / wearability quick settings

| Setting | Default | Where |
|---|---|---|
| PPG/IMU sampling | 50 Hz bursts | ring firmware `SAMPLE_HZ` |
| ECG checkpoint cadence | every 7 days (configurable) | ECG checkpoint workflow |
| Insole sampling | 50 Hz while active, sleep when idle | insole firmware |
| BLE advertise/notify | notify on connect, sleep in between | ring firmware |
| Battery warning | < 20% → low-battery flag in status | ring firmware `BATT_PIN` |

The dashboard shows battery % and "estimated monitoring availability" only from
the firmware-reported value; no battery-life numbers are claimed without
hardware testing.

---

## 9. Known limitations (read before demo)

- Reference sketches are compile-logic verified, not endurance-tested on
  hardware; verify sampling rates and battery life on your exact board.
- BLE support in the app is protocol-level (framing/validation/buffering) —
  real commercial rings are NOT claimed to be supported.
- The insole/ECG analytics are validated on synthetic signals; their clinical
  value must be demonstrated through the ablation and prospective-validation
  paths.
- This is a research/education prototype. It does not diagnose PCOS, does not
  measure hormones, and cannot predict cyst rupture.
