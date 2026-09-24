/*
  CHRONO-PCOS V5 — Smart insole firmware (reference)
  ==================================================
  ESP32-C3 insole: 8 FSR pressure zones (heel/midfoot/forefoot/toe, L+R) via a
  CD74HC4067 analog mux + MPU6050 IMU. Streams at 50 Hz:

    $INS,ms,z1,z2,z3,z4,z5,z6,z7,z8,ax,ay,az,crc

  Zone map (matches src/hardware/insole.py ZONE_NAMES):
    z1 left_heel   z2 left_midfoot  z3 left_forefoot  z4 left_toe
    z5 right_heel  z6 right_midfoot z7 right_forefoot z8 right_toe

  The app-side InsoleAnalyzer computes steps, cadence, stance time, left/right
  asymmetry and gait consistency from these frames.

  Wiring (ESP32-C3):
    4067 S0..S3        -> GPIO1, GPIO2, GPIO3, GPIO4
    4067 SIG           -> GPIO0 (ADC1)
    4067 EN            -> GND
    FSR array          -> 4067 CH0..CH7 (3V3 -> FSR -> 10k to GND, junction to channel)
    MPU6050 SDA/SCL    -> GPIO8 / GPIO9

  Reference sketch: compile-logic verified, not endurance-tested hardware.
  Behavioural/biomechanical signal only - does not detect PCOS.
*/

#include <Wire.h>
#include <Adafruit_MPU6050.h>
#include <Adafruit_Sensor.h>

#define MUX_S0  1
#define MUX_S1  2
#define MUX_S2  3
#define MUX_S3  4
#define MUX_SIG 0
#define FS_HZ   50

Adafruit_MPU6050 mpu;
float ax = 0, ay = 0, az = 1.0;

uint8_t xorCRC(const char *s) {
  uint8_t c = 0;
  for (int i = 0; s[i]; i++) c ^= (uint8_t)s[i];
  return c;
}

void selectChannel(int ch) {
  digitalWrite(MUX_S0, ch & 1);
  digitalWrite(MUX_S1, (ch >> 1) & 1);
  digitalWrite(MUX_S2, (ch >> 2) & 1);
  digitalWrite(MUX_S3, (ch >> 3) & 1);
  delayMicroseconds(20);
}

int readZone(int ch) {
  selectChannel(ch);
  return analogRead(MUX_SIG);
}

void setup() {
  Serial.begin(115200);
  analogReadResolution(12);
  Wire.begin(8, 9);
  for (int p = MUX_S0; p <= MUX_S3; p++) pinMode(p, OUTPUT);
  if (!mpu.begin()) Serial.println("$ACK,INS_MPU_ERR,00");
  else mpu.setAccelerometerRange(MPU6050_RANGE_4_G);
  Serial.println("$ACK,INS_READY,00");
}

void loop() {
  int z[8];
  for (int i = 0; i < 8; i++) z[i] = readZone(i);

  sensors_event_t a, g, t;
  mpu.getEvent(&a, &g, &t);
  ax = a.acceleration.x;
  ay = a.acceleration.y;
  az = a.acceleration.z;

  char payload[120];
  snprintf(payload, sizeof(payload),
           "$INS,%lu,%d,%d,%d,%d,%d,%d,%d,%d,%.4f,%.4f,%.4f",
           millis(), z[0], z[1], z[2], z[3], z[4], z[5], z[6], z[7], ax, ay, az);
  uint8_t crc = xorCRC(payload);
  Serial.print(payload);
  Serial.print(',');
  if (crc < 16) Serial.print('0');
  Serial.println(crc, HEX);

  delay(1000 / FS_HZ);
}
