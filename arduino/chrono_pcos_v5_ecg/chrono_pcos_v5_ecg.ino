/*
  CHRONO-PCOS V5 — Chest ECG patch firmware (reference)
  =====================================================
  ESP32-C3 periodic ECG checkpoint at 256 Hz using an AD8232 single-lead
  front-end. Streams:

    $ECG,ms,raw,crc

  where raw is the ADC value (12-bit). The app-side ECG checkpoint session
  (src/hardware/ecg_checkpoint.py) consumes (timestamp, raw) pairs and computes
  HR / RMSSD / SDNN / quality, then compares against the checkpoint history.

  This is a periodic 30-60 s research monitoring checkpoint, NOT a 24/7 stream
  and NOT a clinical ECG. No arrhythmia claims.

  Wiring (ESP32-C3):
    AD8232 VCC  -> 3V3
    AD8232 GND  -> GND
    AD8232 OUT  -> GPIO0 (ADC1)
    AD8232 LOD+ -> GPIO3 (optional, lead-off)
    AD8232 LOD- -> GPIO4 (optional, lead-off)
    AD8232 SDN  -> 3V3 (or GPIO5 to power down between sessions)

  Reference sketch: compile-logic verified, not endurance-tested hardware.
*/

#define ECG_ADC_PIN   0
#define LOD_PLUS      3
#define LOD_MINUS     4
#define FS_HZ         256
#define ADC_MAX       4095

uint8_t xorCRC(const char *s) {
  uint8_t c = 0;
  for (int i = 0; s[i]; i++) c ^= (uint8_t)s[i];
  return c;
}

void setup() {
  Serial.begin(115200);
  analogReadResolution(12);
  pinMode(LOD_PLUS, INPUT);
  pinMode(LOD_MINUS, INPUT);
  Serial.println("$ACK,ECG_READY,00");
}

void loop() {
  // Record for RECORD_S then pause (button / serial command to extend).
  unsigned long recordStart = millis();
  unsigned long last = 0;
  while (millis() - recordStart < 30000UL) {   // 30 s session
    unsigned long now = micros();
    if (now - last >= (1000000UL / FS_HZ)) {
      last = now;
      int raw = analogRead(ECG_ADC_PIN);
      int loPlus = digitalRead(LOD_PLUS);
      int loMinus = digitalRead(LOD_MINUS);
      if (loPlus == HIGH || loMinus == HIGH) raw = -1;   // lead-off marker
      char payload[40];
      snprintf(payload, sizeof(payload), "$ECG,%lu,%d", millis(), raw);
      uint8_t crc = xorCRC(payload);
      Serial.print(payload);
      Serial.print(',');
      if (crc < 16) Serial.print('0');
      Serial.println(crc, HEX);
    }
  }
  // Sleep between sessions to save battery.
  delay(10000);
}
