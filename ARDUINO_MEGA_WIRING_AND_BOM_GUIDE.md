# CHRONO-PCOS Arduino Mega Wiring Guide + Bill of Materials

**Project:** CHRONO-PCOS — Multi-Modal Chrono-Metabolic Digital Twin for Educational PCOD/PCOS Risk Estimation  
**Controller:** Arduino Mega 2560  
**Important:** This is an educational biomedical engineering prototype. It estimates PCOS risk tendency; it does **not** diagnose PCOS. Hormones shown in the dashboard are estimated tendencies, not measured laboratory hormones.

---

## 1. Why Arduino Mega?

The final/premium version uses Arduino Mega because it has:

- 54 digital I/O pins
- 16 analog inputs
- more memory than Arduino UNO
- enough pins for ECG, GSR, microphone, FSR, buttons, LEDs, OLED, and I2C sensors

Use this firmware:

```text
arduino/chrono_pcos_mega_firmware/chrono_pcos_mega_firmware.ino
```

Do **not** use the UNO firmware for the full build.

---

## 2. Very Important Arduino Mega Pin Rule

On Arduino Mega:

```text
SDA = pin 20
SCL = pin 21
```

So all I2C sensors go to pins **20 and 21**, not A4/A5.

---

## 3. Full Wiring Summary Table

| Module | Module pin | Arduino Mega pin | Notes |
|---|---:|---:|---|
| MAX30102 PPG | VCC | 3.3V preferred | Some breakout boards accept 5V; check module. |
| MAX30102 PPG | GND | GND | Common ground. |
| MAX30102 PPG | SDA | 20 SDA | I2C, address usually 0x57. |
| MAX30102 PPG | SCL | 21 SCL | I2C. |
| MPU6050 | VCC | 5V or 3.3V | GY-521 boards usually accept 5V. |
| MPU6050 | GND | GND | Common ground. |
| MPU6050 | SDA | 20 SDA | I2C. |
| MPU6050 | SCL | 21 SCL | I2C. |
| BH1750 light | VCC | 3.3V/5V depending module | Circadian light sensor. |
| BH1750 light | GND | GND | Common ground. |
| BH1750 light | SDA | 20 SDA | I2C. |
| BH1750 light | SCL | 21 SCL | I2C. |
| BME280 | VCC | 3.3V/5V depending module | Room temp/humidity/pressure. |
| BME280 | GND | GND | Common ground. |
| BME280 | SDA | 20 SDA | I2C. |
| BME280 | SCL | 21 SCL | I2C. |
| SSD1306 OLED | VCC | 5V or 3.3V | Most 0.96 inch modules accept 3.3–5V. |
| SSD1306 OLED | GND | GND | Common ground. |
| SSD1306 OLED | SDA | 20 SDA | I2C, usually 0x3C. |
| SSD1306 OLED | SCL | 21 SCL | I2C. |
| DS18B20 wrist | VCC | 5V | Temperature sensor. |
| DS18B20 wrist | GND | GND | Common ground. |
| DS18B20 wrist | DATA | D2 | OneWire bus. |
| DS18B20 fingertip | VCC | 5V | Optional second sensor. |
| DS18B20 fingertip | GND | GND | Common ground. |
| DS18B20 fingertip | DATA | D2 | Same OneWire bus. |
| Pull-up resistor | 4.7kΩ | D2 to 5V | Required for DS18B20 OneWire bus. |
| GSR sensor | VCC | 5V | Stress/autonomic module. |
| GSR sensor | GND | GND | Common ground. |
| GSR sensor | AO | A0 | Analog input. |
| MAX4466 mic | VCC | 5V | VoxVasc experimental voice proxy. |
| MAX4466 mic | GND | GND | Common ground. |
| MAX4466 mic | OUT | A1 | Analog input. |
| AD8232 ECG | 3.3V | 3.3V | Use 3.3V, not 5V. |
| AD8232 ECG | GND | GND | Common ground. |
| AD8232 ECG | OUTPUT | A2 | ECG analog output. |
| AD8232 ECG | LO+ | D11 | Lead-off detection. |
| AD8232 ECG | LO- | D12 | Lead-off detection. |
| AD8232 ECG | SDN | Not connected | Optional shutdown pin. |
| FSR pressure | leg 1 | 5V | Finger pressure voltage divider. |
| FSR pressure | leg 2 | A3 + 10kΩ to GND | See divider below. |
| 10kΩ resistor | one side | A3 | FSR divider. |
| 10kΩ resistor | other side | GND | FSR divider. |
| Mode button | one side | D3 | Use INPUT_PULLUP. |
| Mode button | other side | GND | Pressed = LOW. |
| Baseline button | one side | D4 | Use INPUT_PULLUP. |
| Baseline button | other side | GND | Pressed = LOW. |
| Post button | one side | D5 | Use INPUT_PULLUP. |
| Post button | other side | GND | Pressed = LOW. |
| Buzzer | + | D6 | Active buzzer module preferred. |
| Buzzer | - | GND | Use transistor if high-current. |
| Green LED | anode | D8 through 220Ω | Status LED. |
| Yellow LED | anode | D9 through 220Ω | Medium/low confidence. |
| Red LED | anode | D10 through 220Ω | High risk/error. |
| LED cathodes | cathode | GND | Common ground. |

---

## 4. System Wiring Block Diagram

```text
                    ARDUINO MEGA 2560
        ┌─────────────────────────────────────────┐
        │                                         │
I2C     │  SDA 20 ── MAX30102                     │
BUS     │          ├─ MPU6050                     │
        │          ├─ BH1750 / VEML7700           │
        │          ├─ BME280                      │
        │          └─ SSD1306 OLED                │
        │  SCL 21 ─────────────────────────────── │
        │                                         │
TEMP    │  D2 ── DS18B20 wrist + DS18B20 finger   │
        │        4.7kΩ pull-up from D2 to 5V       │
        │                                         │
ANALOG  │  A0 ── GSR sensor                       │
        │  A1 ── MAX4466 microphone               │
        │  A2 ── AD8232 ECG output                │
        │  A3 ── FSR pressure divider             │
        │                                         │
DIGITAL │  D3 ── Mode button to GND               │
        │  D4 ── Baseline button to GND           │
        │  D5 ── Post button to GND               │
        │  D6 ── Buzzer                           │
        │  D8 ── Green LED                        │
        │  D9 ── Yellow LED                       │
        │  D10 ─ Red LED                          │
        │  D11 ─ AD8232 LO+                       │
        │  D12 ─ AD8232 LO-                       │
        │                                         │
USB     │  USB-B cable ── Python dashboard        │
        └─────────────────────────────────────────┘
```

---

## 5. I2C Bus Wiring

All I2C sensors share the same SDA/SCL lines:

```text
Mega pin 20 SDA ── MAX30102 SDA ── MPU6050 SDA ── BH1750 SDA ── BME280 SDA ── OLED SDA
Mega pin 21 SCL ── MAX30102 SCL ── MPU6050 SCL ── BH1750 SCL ── BME280 SCL ── OLED SCL
GND shared by all modules
```

### Common I2C addresses

| Module | Common I2C address |
|---|---:|
| MAX30102 | 0x57 |
| MPU6050 | 0x68 or 0x69 |
| BH1750 | 0x23 or 0x5C |
| BME280 | 0x76 or 0x77 |
| SSD1306 OLED | 0x3C or 0x3D |

### Important I2C warning

Arduino Mega uses 5V logic. Some sensor breakout boards are 3.3V-only. If your breakout board does not include level shifting, use a **bidirectional I2C logic level converter** between Mega and 3.3V sensors.

For most common hobby modules with regulators/level shifting, direct wiring works, but always check the product page.

---

## 6. DS18B20 Temperature Wiring

Use two DS18B20 sensors on the same D2 pin.

```text
DS18B20 red wire    → 5V
DS18B20 black wire  → GND
DS18B20 yellow/data → D2
4.7kΩ resistor      → between D2 and 5V
```

ASCII diagram:

```text
5V ───────────────┬──────── DS18B20 VCC red
                  │
                 4.7kΩ
                  │
D2 ───────────────┴──────── DS18B20 DATA yellow

GND ─────────────────────── DS18B20 GND black
```

If using two sensors, connect both data wires to D2, both red wires to 5V, and both black wires to GND. Only one 4.7kΩ pull-up is required.

Placement:

| Sensor | Placement | Purpose |
|---|---|---|
| DS18B20 #1 | Inner wrist/forearm | Skin temperature rhythm |
| DS18B20 #2 | Fingertip near PPG | Fingertip perfusion / IMTI |

---

## 7. FSR Finger Pressure Wiring

The FSR is used to detect whether the finger is pressing too hard or too lightly on the PPG sensor.

```text
5V ── FSR ── A3 ── 10kΩ ── GND
```

Explanation:

- When pressure increases, FSR resistance changes.
- The voltage at A3 changes.
- The dashboard can warn if PPG amplitude may be caused by finger pressure instead of vascular change.

---

## 8. AD8232 ECG Wiring and Safety

### Wiring

| AD8232 pin | Arduino Mega |
|---|---:|
| 3.3V | 3.3V |
| GND | GND |
| OUTPUT | A2 |
| LO+ | D11 |
| LO- | D12 |
| SDN | Not connected |

### Electrode placement

| Electrode | Placement |
|---|---|
| RA | Right upper chest / below right clavicle |
| LA | Left upper chest / below left clavicle |
| RL | Lower right abdomen / lower rib area |

### Safety rules

1. Use ECG only for heart-beat timing/HRV, not ECG diagnosis.
2. Run laptop on battery when ECG electrodes are connected.
3. Do not use on people with pacemakers/implanted cardiac devices.
4. Do not use on broken or irritated skin.
5. Do not connect ECG electrodes to anyone without consent.

---

## 9. Buttons

Each button connects from Arduino pin to GND.

```text
D3 ── button ── GND    Mode button
D4 ── button ── GND    Capture baseline
D5 ── button ── GND    Capture post-meal/post-challenge
```

Arduino firmware uses:

```cpp
pinMode(3, INPUT_PULLUP);
pinMode(4, INPUT_PULLUP);
pinMode(5, INPUT_PULLUP);
```

So:

```text
Not pressed = HIGH
Pressed     = LOW
```

---

## 10. LEDs and Buzzer

### LEDs

```text
D8  ── 220Ω ── Green LED anode, cathode to GND
D9  ── 220Ω ── Yellow LED anode, cathode to GND
D10 ── 220Ω ── Red LED anode, cathode to GND
```

Meaning:

| LED | Meaning |
|---|---|
| Green | Good signal / low estimated risk |
| Yellow | Medium risk / low confidence / waiting |
| Red | High estimated risk / sensor error |

### Buzzer

```text
D6 ── buzzer +
GND ─ buzzer -
```

If the buzzer module draws high current, use a transistor driver.

---

## 11. Sensor Placement on Body

| Sensor | Placement | Reason |
|---|---|---|
| MAX30102 + FSR | Fingertip | PPG, pulse amplitude, SpO2 estimate, finger pressure |
| DS18B20 fingertip | Near PPG finger | Fingertip perfusion temperature |
| DS18B20 wrist | Inner wrist/forearm | Skin temperature rhythm |
| GSR electrodes | Index + middle finger or palm | Sympathetic arousal/stress |
| MPU6050 | Wrist strap or device band | Activity, sleep restlessness, motion artifact |
| BH1750 | Device top exposed to light | Circadian light exposure |
| AD8232 electrodes | Chest triangle | Beat timing / HRV |
| MAX4466 | Near mouth or neck collar area | Experimental VoxVasc voice proxy |

---

## 12. Recommended Power Wiring Strategy

Use Arduino Mega powered by USB from the laptop.

Recommended breadboard rails:

```text
Mega 5V  → breadboard + rail
Mega GND → breadboard - rail
Mega 3.3V → separate 3.3V rail for 3.3V-only sensors
```

Important:

- Do not power high-current devices from the 3.3V pin.
- Keep all grounds common.
- Avoid messy long wires for ECG and microphone.
- For final exhibition, use labelled connectors and zip ties.

---

## 13. Testing Order

Do not connect everything at once. Test in this order:

1. Upload Mega firmware with only Mega connected.
2. Test serial output in Arduino Serial Monitor.
3. Connect MAX30102 and check IR/red values.
4. Connect MPU6050 and check motion values.
5. Connect DS18B20 and check temperature.
6. Connect GSR to A0.
7. Connect OLED and confirm display.
8. Connect BH1750 and BME280.
9. Connect FSR and check A3 changes with pressure.
10. Connect AD8232 last, after reading ECG safety rules.
11. Connect microphone last.
12. Run Python dashboard.

---

## 14. Bill of Materials From Robu.in and Robocraze

**Important price note:** Prices and stock change frequently. The prices below are approximate observed prices from Robu.in/Robocraze search results and should be verified in the cart before purchase. Shipping is not included. If you already own MAX30102, MPU6050, DS18B20, Arduino, breadboard, etc., subtract those items.

### Core electronics BOM

| Item | Qty | Robu.in observed price | Robocraze observed price | Recommended choice | Notes |
|---|---:|---:|---:|---|---|
| Arduino Mega 2560 compatible | 1 | ₹1059–₹1128 compatible Mega variants ([3](https://robu.in/product/atmel-mcu-atmega16u2-mega-2560-r3-improved-version-ch340g-board/), [1](https://robu.in/product/atmel-mcu-atmega16u2-mega-2560-r3-improved-version-ch340g-cable-arduino-mega-2560-transparent-acrylic-case-arduino-mega-2560/)) | ₹1329 compatible Mega; original Mega ₹3879 ([1](https://robocraze.com/collections/boards), [2](https://robocraze.com/products/arduino-mega-original)) | Robu compatible if budget; Robocraze original if authenticity matters | Use Mega, not UNO. |
| MAX30102 PPG/SpO2 module | 1 | DFRobot Fermion/Gravity versions ₹1449–₹2252 ([3](https://stg.robu.in/product/dfrobot-fermion-max30102-heart-rate-and-oximeter-sensor-breakout/?add-to-cart=31464), [1](https://robu.in/product/dfrobot-gravity-max30102-heart-rate-and-oximeter-sensor/)) | Generic MAX30102 around ₹189 ([2](https://robocraze.com/products/max30102-pulse-oximeter-heart-rate-sensor-module)) | Robocraze generic for low cost; DFRobot for premium build | You already have this, so may skip. |
| MPU6050 accelerometer/gyro | 1 | ₹165 ([1](https://robu.in/product-tag/gyro/)) | ₹154 ([3](https://robocraze.com/products/mpu-6050-triple-axis-accelerometer-gyroscope-module)) | Either | Motion, sleep restlessness, artifact rejection. |
| AD8232 ECG module kit | 1 | Robu AD8232 listings vary: ₹499 out-of-stock kit or ₹1299 in-stock variant ([2](https://robu.in/product/ecg-module-ad8232-ecg-measurement-pulse-heart-ecg-monitoring-sensor-module-kit/), [3](https://robu.in/product/ecg-module-ad8232-heart-ecg-monitoring-sensor/)) | ₹1119 in-stock kit ([1](https://robocraze.com/products/ad8232-ecg-module)) | Robocraze if in stock | For HRV timing only, not ECG diagnosis. |
| DS18B20 waterproof temperature probe | 2 | ₹89 each ([2](https://robu.in/product/ds18b20-water-proof-temperature-probe-black-1m/)) | ₹63 each generic probe ([3](https://robocraze.com/products/ds18b20-waterproof-digital-thermometer-sensor-probe)) | Robocraze low cost | Use two: wrist + fingertip. |
| GSR sensor | 1 | Grove GSR around ₹1057 shown in Robu category ([1](https://robu.in/product-category/sensor-modules/biometric-ecg-emg-sensor/)) | GSR Skin Current V2 around ₹1144; Grove GSR ₹1057 out-of-stock listing ([1](https://robocraze.com/collections/biomedical-sensors/new-arrivals), [2](https://robocraze.com/products/seeedstudio-v1-1-5v-3-3v-grove-gsr-sensor-module)) | Whichever is in stock | Stress/autonomic arousal. |
| BH1750 light sensor | 1 | GY-302/GY-30 around ₹99–₹114 ([1](https://robu.in/product-category/sensor/light-color-sensor/), [2](https://robu.in/product/gy-302-bh1750-light-intensity-module/)) | ₹129 ([2](https://robocraze.com/products/gy-302-bh1750-light-intensity-module)) | Robu/Robocraze both fine | Circadian light exposure. |
| BME280 environment sensor | 1 | BME280 cabled module ₹1389; cheaper SmartElex board ₹530 listed out-of-stock ([1](https://robu.in/product/bme280-black-shell-built-in-cotton-core/), [2](https://robu.in/product/smartelex-bme280-atmospheric-sensor-breakout-board/)) | BME280 probe ₹770 in stock; breakout ₹584 out-of-stock ([2](https://robocraze.com/products/bme280-humidity-temperature-sensor-probe-7semi), [1](https://robocraze.com/products/7semi-bme280-temperature-humidity-pressure-sensor-breakout-module-i2c-spi)) | Robocraze BME280 probe if in stock | Environmental correction. |
| MAX4466 microphone | 1 | Generic MAX4466 ₹99; Adafruit MAX4466 ₹1077 ([1](https://robu.in/product-tag/microphone-amplifier/), [2](https://robu.in/product/adafruit-electret-microphone-amplifier-max4466-with-adjustable-gain/)) | M5 mic unit around ₹417 out-of-stock ([2](https://robocraze.com/products/m5-stick-microphone-unit-lm393)) | Robu generic ₹99 | VoxVasc experimental module. |
| Force Sensitive Resistor / FSR | 1 | SOUSHINE FSR406 ₹360 in stock; other FSRs ₹131 out-of-stock or ₹5499 premium ([3](https://robu.in/product/soushine-fsr406-short-tail-39-7-mm-39-7-mm-force-sensing-shunt-resistor-20g10kg/), [2](https://robu.in/product/force-sensitive-resistor-rp-c7-6-st30g-1-5kg/)) | Square FSR around ₹379 out-of-stock; collection lists other FSR around ₹344 ([1](https://robocraze.com/products/square-force-sensitive-resistor), [3](https://robocraze.com/collections/force-flex-load-sensors)) | Robu FSR406 ₹360 | Corrects PPG pressure artifact. |
| SSD1306 0.96 inch OLED | 1 | ₹199–₹282 variants ([3](https://robu.in/product/2-23-inch-monochrome-oled-display-module-white/), [2](https://robu.in/product/oled-display-white-color-screen/)) | ₹162–₹209 variants ([2](https://robocraze.com/), [3](https://robocraze.com/blogs/post/oled-demo-and-working-part-ii)) | Either | I2C OLED for protocol display. |
| MB102 / 830-point breadboard | 1 | ₹438 out-of-stock; kit ₹660 ([1](https://robu.in/product/zy-201-830-points-solderless-breadboard/), [2](https://robu.in/product/beginner-electronics-component-package-kit/)) | ₹64 in stock ([2](https://robocraze.com/products/mb102-830-points-solderless-breadboard)) | Robocraze ₹64 | Buy 2 if many modules. |
| Jumper wire set | 1 | M-F pack ₹43; combo around ₹123 ([3](https://robu.in/product/10cm-male-female-breadboard-jumper-dupont-2-54mm-1p-1p-cable-40-pcs), [2](https://robu.in/product-category/batteries/wires-and-cables/multi-color-project-cables/dupont-cable/)) | M2M/M2F/F2F set ₹132 ([1](https://robocraze.com/collections/jumper-wires/wires-connectors)) | Robocraze full set | Need male-female and male-male. |
| Resistor box / resistor packs | 1 | Individual SMD/through-hole options; 4.7k network ₹9 ([3](https://robu.in/product/4-7k-ohm-through-hole-resistor-network-pack-of-5/)) | Resistor box ₹45; 220Ω, 4.7kΩ, 10kΩ packs listed ([2](https://robocraze.com/products/resistor-box), [1](https://robocraze.com/collections/resistors)) | Robocraze resistor box | Need 220Ω, 4.7kΩ, 10kΩ. |
| LEDs | 3 minimum | Large LED kit ₹583 ([1](https://robu.in/product/pro-range-5mm-led-assortment-kit-500pcs-with-bonus-pcb-and-220-0-resistors100pcs/)) | Packs of 10 LEDs around ₹9–₹15; LED kit ₹334 ([2](https://robocraze.com/collections/leds/leds?page=2), [1](https://robocraze.com/products/500pcs-5-mm-led-kit-5-colors-with-durable-storage-box)) | Robocraze small packs | Green/yellow/red status LEDs. |
| Active buzzer module | 1 | ₹46 module out-of-stock; pack options exist ([1](https://robu.in/product/5v-active-alarm-buzzer-module-arduino/)) | ₹27 active buzzer module ([2](https://robocraze.com/products/active-buzzer-module)) | Robocraze ₹27 | Alerts. |
| Push buttons | 3 | Button module ₹32 each; large kit available ([1](https://robu.in/product/tactile-push-button-switch-assorted-kit-25-pcs/)) | 10 tactile buttons ₹15–₹25; pack options listed ([1](https://robocraze.com/collections/push-buttons)) | Robocraze pack | Mode/baseline/post buttons. |
| USB A-B cable for Mega | 1 | ₹65/₹76 listings, often stock-dependent ([1](https://robu.in/product/cable-for-arduino-uno-mega-usb-a-to-b-1m/), [2](https://robu.in/product/cable-for-arduino-nano-usb-a-to-mini-b-4-5-feet-gold-plated-high-quality/)) | ₹25 short cable or ₹49–₹69 longer variants ([3](https://robocraze.com/products/usb-a-b-cable-3-0-cm), [2](https://robocraze.com/collections/usb-cable/usb-cable)) | Robocraze if needed | Some Mega boards include cable. |

---

## 15. Approximate Cost Estimate

### Economy recommended build

Using mostly lower-cost Robocraze/Robu options, approximate total is:

```text
Arduino Mega compatible           ~ ₹1059–1329
MAX30102                          ~ ₹189   (skip if already owned)
MPU6050                           ~ ₹154–165
AD8232 ECG kit                    ~ ₹1119  (or cheaper if available)
DS18B20 x2                        ~ ₹126–178
GSR sensor                        ~ ₹1057–1144
BH1750                            ~ ₹99–129
BME280                            ~ ₹770
MAX4466                           ~ ₹99
FSR                               ~ ₹360
OLED                              ~ ₹162–282
Breadboard                        ~ ₹64
Jumper set                        ~ ₹132
Resistor box                      ~ ₹45
LEDs                              ~ ₹30–50 basic packs
Buzzer                            ~ ₹27
Buttons                           ~ ₹15–36
USB cable                         ~ ₹25–69
```

Approximate total if buying almost everything:

```text
₹5,500 to ₹7,000 + shipping
```

If you already own Arduino, MAX30102, MPU6050, DS18B20, breadboard, LEDs, and jumper wires, your additional cost will be much lower.

### Premium build

If you use original Arduino Mega, DFRobot MAX30102, premium GSR, premium BME280 housing, and branded modules, the total can exceed:

```text
₹10,000 to ₹15,000+
```

For a science exhibition, the economy build is sufficient.

---

## 16. What to Buy First

If you do not want to buy everything at once, buy in this order:

1. Arduino Mega 2560
2. MAX30102
3. MPU6050
4. DS18B20 x2
5. GSR sensor
6. AD8232 ECG
7. FSR pressure sensor
8. BH1750
9. OLED display
10. BME280
11. MAX4466 microphone
12. Buttons, buzzer, LEDs, resistors, wires

---

## 17. Minimum Working Build vs Full Premium Build

### Minimum working build

```text
Arduino Mega
MAX30102
MPU6050
DS18B20
GSR
Breadboard + wires
Python dashboard
```

This gives:

- heart rate
- SpO2 estimate
- HRV from PPG
- motion/activity
- skin temperature
- stress index
- risk dashboard

### Full premium build

```text
Arduino Mega
MAX30102
AD8232 ECG
MPU6050
DS18B20 x2
GSR
BH1750
BME280
FSR
MAX4466
SSD1306 OLED
buttons
LEDs
buzzer
manual glucometer
```

This gives:

- better HRV
- metabolic-vascular challenge
- finger-pressure correction
- environmental correction
- circadian light sensing
- VoxVasc experimental module
- premium hardware interface

---

## 18. Final Safety Note

Do not present the system as a PCOS detector.

Correct statement:

```text
CHRONO-PCOS estimates PCOS risk tendency using multi-modal physiological signals.
It is an educational biomedical engineering prototype and not a diagnostic medical device.
```

For ECG:

```text
Use laptop on battery.
Do not use ECG electrodes on visitors without consent.
Do not use on people with implanted cardiac devices.
```

For glucose:

```text
Do not perform finger-prick tests unless school rules, hygiene, and consent allow it.
Do not perform a 75g glucose challenge on visitors.
Use normal snack/meal data or pre-recorded volunteer data.
```
