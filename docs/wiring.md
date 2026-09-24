# Wiring Guide

## Arduino UNO pins

| Module | UNO pin | Note |
|---|---|---|
| MAX30102 VCC | 3.3 V preferred | Many breakout boards accept 5 V; check yours. |
| MAX30102 GND | GND | Common ground. |
| MAX30102 SDA | A4 | I2C. |
| MAX30102 SCL | A5 | I2C. |
| MPU6050 VCC | 5 V or 3.3 V | GY-521 usually accepts 5 V. |
| MPU6050 GND | GND | Common ground. |
| MPU6050 SDA | A4 | I2C. |
| MPU6050 SCL | A5 | I2C. |
| DS18B20 data | D2 | Add 4.7 kΩ pull-up to 5 V. |
| DS18B20 VCC | 5 V |  |
| DS18B20 GND | GND |  |
| GSR AO | A0 | Analog input. |
| BH1750 SDA | A4 | Optional light sensor. |
| BH1750 SCL | A5 | Optional light sensor. |
| Green LED | D8 via 220 Ω | Low risk/good signal. |
| Yellow LED | D9 via 220 Ω | Medium risk/low confidence. |
| Red LED | D10 via 220 Ω | High risk/sensor error. |
| Buzzer | D6 | Use transistor if high-current buzzer. |

## I2C address conflicts

- MAX30102 is usually `0x57`. Two MAX3010x sensors need a TCA9548A multiplexer.
- MPU6050 is `0x68` by default. If using DS3231 RTC (`0x68`), connect MPU6050 AD0 to VCC so it becomes `0x69`.

## Sensor placement

- PPG: fingertip for demonstration; avoid movement.
- MPU6050: wrist strap.
- DS18B20: inner wrist/forearm, taped and insulated from air.
- GSR: two fingers/palm electrodes.
- BH1750: exposed to ambient light.
