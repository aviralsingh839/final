# Enhanced Equipment + Connection Guide

This document adds a safe and realistic version of the uploaded **PCOS-VoxVasc / Metabolic-Vascular Challenge** concept to the CHRONO-PCOS project.

For the full build, use **Arduino Mega 2560**. Mega I2C pins are **SDA=20** and **SCL=21**. UNO A4/A5 notes apply only to the minimal UNO build.

## Is it possible?

Yes, the idea is possible as an **educational metabolic-vascular response module**, but it must be presented carefully:

- Do **not** call it a PCOS diagnostic test.
- Do **not** perform a 75 g oral glucose challenge on visitors without clinician/guardian approval.
- For science exhibitions, use a normal snack/meal response, pre-recorded volunteer data, or manual historical glucometer readings.
- Voice/laryngeal androgen inference is experimental and low confidence.

## Recommended extra equipment

| Equipment | Why add it? | Approx. INR | Priority |
|---|---|---:|---|
| GSR sensor | Stress/autonomic arousal | ₹300–₹700 | High |
| BH1750 light sensor | Circadian light exposure | ₹120–₹250 | High |
| SSD1306 0.96 inch OLED I2C | Premium guided hardware interface | ₹180–₹300 | Medium |
| MAX4466 microphone module | Optional voice/vibration proxy | ₹120–₹250 | Optional/experimental |
| 3 push buttons | Start/capture baseline/capture post | ₹30–₹80 | Medium |
| Second DS18B20 | One wrist temp + one fingertip perfusion temp | ₹100–₹200 | Medium |
| Digital BP monitor | Manual SYS/DIA entry for metabolic syndrome proxy. Do **not** wire the cuff to Arduino. Put the cuff on the opposite upper arm from the PPG finger. | ₹900–₹1500 | Optional |
| Measuring tape + weighing scale | BMI/waist metabolic features | ₹200–₹800 | High |
| TCA9548A I2C multiplexer | Needed only if two MAX30102 sensors | ₹150–₹300 | Optional |

You can stay within ₹4000 if you add GSR, BH1750, OLED, buttons, MAX4466, second DS18B20 and a tape.

## Connection table

| Module | Arduino UNO pin | Notes |
|---|---|---|
| MAX30102 VCC | 3.3 V preferred | Some modules accept 5 V. Check board. |
| MAX30102 GND | GND | Common ground. |
| MAX30102 SDA | A4 | I2C, address usually 0x57. |
| MAX30102 SCL | A5 | I2C. |
| MPU6050 VCC | 5 V or 3.3 V | GY-521 usually accepts 5 V. |
| MPU6050 GND | GND | Common ground. |
| MPU6050 SDA | A4 | I2C, address 0x68/0x69. |
| MPU6050 SCL | A5 | I2C. |
| DS18B20 wrist data | D2 | 4.7 kΩ pull-up to 5 V. |
| DS18B20 fingertip data | D2 same bus | Optional second sensor in parallel. |
| GSR AO | A0 | Analog input. |
| MAX4466 OUT | A1 | Optional voice/vibration proxy. |
| BH1750 SDA | A4 | I2C, usually 0x23/0x5C. |
| BH1750 SCL | A5 | I2C. |
| SSD1306 OLED SDA | A4 | I2C, usually 0x3C. |
| SSD1306 OLED SCL | A5 | I2C. |
| Baseline button | D3 to GND | Use INPUT_PULLUP. |
| Post button | D4 to GND | Use INPUT_PULLUP. |
| Mode button | D5 to GND | Use INPUT_PULLUP. |
| Buzzer | D6 | Use transistor if large buzzer. |
| Green LED | D8 via 220 Ω | Low risk/good signal. |
| Yellow LED | D9 via 220 Ω | Medium/low confidence. |
| Red LED | D10 via 220 Ω | High risk/error. |

## I2C map

| Device | Address |
|---|---|
| MAX30102 | 0x57 |
| MPU6050 | 0x68 or 0x69 |
| BH1750 | 0x23 or 0x5C |
| SSD1306 OLED | 0x3C or 0x3D |
| TCA9548A optional | 0x70 |

If using two MAX30102 boards, use TCA9548A because both usually have address 0x57.

## Safe MV-AST exhibition protocol

1. Seat volunteer quietly for 5 minutes.
2. Record 60 seconds of baseline PPG, temp, GSR, HRV, motion.
3. Enter baseline glucose only if it already exists or finger-prick is allowed by school rules.
4. Use a normal snack/meal response or pre-recorded data. Avoid unsupervised 75 g glucose loading.
5. Record post-meal physiology at 30 minutes. Optional: repeat 60 and 120 minutes.
6. Show dynamic indices:
   - ΔG = post glucose − baseline glucose
   - IMVI = post PPG amplitude / baseline PPG amplitude
   - IMTI = post fingertip/skin temperature − baseline temperature
   - ARR = post autonomic load / baseline autonomic load
7. Display: “metabolic-vascular risk contribution”, not PCOS diagnosis.

## Why ARR instead of LF/HF on Arduino PPG?

The uploaded README uses LF/HF ratio. LF/HF requires longer, clean inter-beat interval data and is sensitive to breathing and artifacts. For a Class 11 project using MAX30102, a safer term is:

**ARR — Autonomic Response Ratio**

It uses stress index, RMSSD tendency and GSR rather than claiming clinical LF/HF.
