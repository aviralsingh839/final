# Arduino Mega Premium Wiring: CHRONO-PCOS + VoxVasc + MV-AST

Use Arduino Mega 2560 for the full build because UNO runs out of RAM/analog pins.

## Mega I2C pins

| Mega pin | I2C function |
|---|---|
| 20 | SDA |
| 21 | SCL |

Do not use UNO A4/A5 when wiring to Mega unless your board labels SDA/SCL separately.

## Full connection table

| Sensor/module | Arduino Mega connection | Purpose |
|---|---|---|
| MAX30102 VCC | 3.3 V preferred | PPG/SpO2/pulse amplitude |
| MAX30102 GND | GND | Common ground |
| MAX30102 SDA | SDA pin 20 | I2C |
| MAX30102 SCL | SCL pin 21 | I2C |
| MPU6050 VCC | 5 V or 3.3 V depending module | Motion/activity |
| MPU6050 GND | GND |  |
| MPU6050 SDA | SDA pin 20 | I2C |
| MPU6050 SCL | SCL pin 21 | I2C |
| DS18B20 data | D2 | OneWire temp bus |
| DS18B20 VCC | 5 V |  |
| DS18B20 GND | GND |  |
| 4.7 kΩ resistor | D2 to 5 V | Required pull-up |
| GSR AO | A0 | Stress/autonomic arousal |
| MAX4466 OUT | A1 | Experimental voice/VoxVasc |
| AD8232 OUTPUT | A2 | ECG for more accurate HRV |
| AD8232 LO+ | D11 | Lead-off detection |
| AD8232 LO- | D12 | Lead-off detection |
| FSR divider output | A3 | Finger pressure correction |
| FSR leg 1 | 5 V | Voltage divider |
| FSR leg 2 | A3 and 10 kΩ to GND | Voltage divider |
| BH1750 SDA | SDA pin 20 | Circadian light |
| BH1750 SCL | SCL pin 21 | Circadian light |
| BME280 SDA | SDA pin 20 | Room temp/humidity correction |
| BME280 SCL | SCL pin 21 | Room temp/humidity correction |
| SSD1306 OLED SDA | SDA pin 20 | Hardware guide display |
| SSD1306 OLED SCL | SCL pin 21 | Hardware guide display |
| Mode button | D3 to GND | INPUT_PULLUP |
| Baseline button | D4 to GND | INPUT_PULLUP |
| Post button | D5 to GND | INPUT_PULLUP |
| Buzzer | D6 | Use transistor if high-current |
| Green LED | D8 through 220 Ω | Low risk/good signal |
| Yellow LED | D9 through 220 Ω | Medium/low confidence |
| Red LED | D10 through 220 Ω | High risk/error |

## FSR voltage divider

```text
5V ── FSR ── A3 ── 10kΩ ── GND
```

This helps detect changes in finger pressure. PPG amplitude changes can be caused by pressure, not blood-vessel physiology.

## ECG safety

- Use AD8232 only for heart beat timing, not ECG diagnosis.
- Run the laptop on battery when electrodes are connected to a person.
- Do not use ECG electrodes on anyone with implanted cardiac devices.
- Do not use on broken/irritated skin.

## I2C addresses

| Device | Common address |
|---|---|
| MAX30102 | 0x57 |
| MPU6050 | 0x68 or 0x69 |
| BH1750 | 0x23 or 0x5C |
| BME280 | 0x76 or 0x77 |
| SSD1306 | 0x3C or 0x3D |

If using two MAX30102 sensors, add a TCA9548A I2C multiplexer.
