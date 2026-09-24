/*
  CHRONO-PCOS Arduino UNO firmware
  --------------------------------
  Educational biomedical data acquisition firmware for:
    - MAX30102/MAX3010x PPG red + IR
    - MPU6050 acceleration + gyro
    - DS18B20 skin temperature
    - GSR analog sensor
    - optional BH1750 light sensor
    - LED/buzzer feedback from Python

  Serial output at 115200 baud:
    $CP,ms,ir,red,ax,ay,az,gx,gy,gz,tempC,gsr,lux,status,crc

  Install Arduino libraries:
    SparkFun MAX3010x Pulse and Proximity Sensor Library
    Adafruit MPU6050
    Adafruit Unified Sensor
    OneWire
    DallasTemperature
    Optional: BH1750 by Christopher Laws
*/

#include <Wire.h>
#include "MAX30105.h"
#include <Adafruit_MPU6050.h>
#include <Adafruit_Sensor.h>
#include <OneWire.h>
#include <DallasTemperature.h>

#define USE_BH1750 0
#if USE_BH1750
  #include <BH1750.h>
  BH1750 lightMeter;
#endif

#define ONE_WIRE_BUS 2
#define GSR_PIN A0
#define LED_GREEN 8
#define LED_YELLOW 9
#define LED_RED 10
#define BUZZER_PIN 6

#define BAUD_RATE 115200
#define PPG_PERIOD_MS 20      // 50 Hz
#define IMU_PERIOD_MS 20      // 50 Hz
#define GSR_PERIOD_MS 100     // 10 Hz
#define TEMP_PERIOD_MS 1000   // 1 Hz
#define PACKET_PERIOD_MS 20   // 50 Hz

// Status bits
#define ST_PPG_ABSENT   0
#define ST_PPG_SAT      1
#define ST_MPU_ERR      2
#define ST_TEMP_ERR     3
#define ST_GSR_SAT      4
#define ST_I2C_ERR      5
#define ST_LOW_QUALITY  6

MAX30105 particleSensor;
Adafruit_MPU6050 mpu;
OneWire oneWire(ONE_WIRE_BUS);
DallasTemperature tempSensor(&oneWire);

bool ppgOK = false;
bool mpuOK = false;
bool tempOK = false;
bool lightOK = false;

uint32_t irValue = 0;
uint32_t redValue = 0;
float ax_g = 0, ay_g = 0, az_g = 1;
float gx_dps = 0, gy_dps = 0, gz_dps = 0;
float ax_bias = 0, ay_bias = 0, az_bias = 0;
float gx_bias = 0, gy_bias = 0, gz_bias = 0;
float tempC = NAN;
int gsrRaw = 0;
float luxValue = -1;
uint8_t baseStatus = 0;

unsigned long lastPPG = 0;
unsigned long lastIMU = 0;
unsigned long lastGSR = 0;
unsigned long lastTemp = 0;
unsigned long lastPacket = 0;

char cmdBuf[40];
uint8_t cmdIdx = 0;

uint8_t xorCRC(const char *s) {
  uint8_t c = 0;
  while (*s) {
    c ^= (uint8_t)(*s++);
  }
  return c;
}

void setLedState(char state) {
  digitalWrite(LED_GREEN, state == 'G');
  digitalWrite(LED_YELLOW, state == 'Y');
  digitalWrite(LED_RED, state == 'R');
}

void beepShort() {
  tone(BUZZER_PIN, 2200, 120);
}

void setupPPG() {
  if (!particleSensor.begin(Wire, I2C_SPEED_FAST)) {
    ppgOK = false;
    baseStatus |= (1 << ST_I2C_ERR);
    return;
  }
  ppgOK = true;
  // Conservative MAX30102 configuration for finger PPG.
  byte ledBrightness = 0x24;  // 0x00-0xFF
  byte sampleAverage = 4;
  byte ledMode = 2;           // red + IR
  int sampleRate = 100;
  int pulseWidth = 411;
  int adcRange = 4096;
  particleSensor.setup(ledBrightness, sampleAverage, ledMode, sampleRate, pulseWidth, adcRange);
  particleSensor.setPulseAmplitudeRed(0x24);
  particleSensor.setPulseAmplitudeIR(0x24);
  particleSensor.setPulseAmplitudeGreen(0);
}

void setupMPU() {
  if (!mpu.begin()) {
    mpuOK = false;
    baseStatus |= (1 << ST_MPU_ERR);
    return;
  }
  mpuOK = true;
  mpu.setAccelerometerRange(MPU6050_RANGE_4_G);
  mpu.setGyroRange(MPU6050_RANGE_500_DEG);
  mpu.setFilterBandwidth(MPU6050_BAND_21_HZ);
}

void setupTemperature() {
  tempSensor.begin();
  tempOK = (tempSensor.getDeviceCount() > 0);
  if (!tempOK) baseStatus |= (1 << ST_TEMP_ERR);
}

void setupLight() {
#if USE_BH1750
  lightOK = lightMeter.begin(BH1750::CONTINUOUS_LOW_RES_MODE);
  if (!lightOK) baseStatus |= (1 << ST_I2C_ERR);
#else
  lightOK = false;
#endif
}

void calibrateIMU() {
  if (!mpuOK) return;
  const int N = 120;
  float sax = 0, say = 0, saz = 0, sgx = 0, sgy = 0, sgz = 0;
  for (int i = 0; i < N; i++) {
    sensors_event_t a, g, temp;
    mpu.getEvent(&a, &g, &temp);
    sax += a.acceleration.x / 9.80665;
    say += a.acceleration.y / 9.80665;
    saz += a.acceleration.z / 9.80665;
    sgx += g.gyro.x * 57.29578;
    sgy += g.gyro.y * 57.29578;
    sgz += g.gyro.z * 57.29578;
    delay(10);
  }
  ax_bias = sax / N;
  ay_bias = say / N;
  az_bias = (saz / N) - 1.0; // leave gravity as +1 g on z when flat
  gx_bias = sgx / N;
  gy_bias = sgy / N;
  gz_bias = sgz / N;
}

void readPPG() {
  if (!ppgOK) return;
  redValue = particleSensor.getRed();
  irValue = particleSensor.getIR();
}

void readIMU() {
  if (!mpuOK) return;
  sensors_event_t a, g, temp;
  mpu.getEvent(&a, &g, &temp);
  ax_g = a.acceleration.x / 9.80665 - ax_bias;
  ay_g = a.acceleration.y / 9.80665 - ay_bias;
  az_g = a.acceleration.z / 9.80665 - az_bias;
  gx_dps = g.gyro.x * 57.29578 - gx_bias;
  gy_dps = g.gyro.y * 57.29578 - gy_bias;
  gz_dps = g.gyro.z * 57.29578 - gz_bias;
}

void readGSR() {
  gsrRaw = analogRead(GSR_PIN);
}

void readTemperature() {
  if (!tempOK) return;
  tempSensor.requestTemperatures();
  float t = tempSensor.getTempCByIndex(0);
  if (t > -20 && t < 80) {
    tempC = t;
  }
}

void readLight() {
#if USE_BH1750
  if (lightOK) luxValue = lightMeter.readLightLevel();
#else
  luxValue = -1;
#endif
}

uint8_t makeStatus() {
  uint8_t st = baseStatus;
  if (ppgOK) {
    if (irValue < 5000) st |= (1 << ST_PPG_ABSENT);
    if (irValue > 250000UL || redValue > 250000UL) st |= (1 << ST_PPG_SAT);
  }
  if (tempOK && !(tempC > 0 && tempC < 50)) st |= (1 << ST_TEMP_ERR);
  if (gsrRaw < 5 || gsrRaw > 1018) st |= (1 << ST_GSR_SAT);
  return st;
}

void sendPacket() {
  char fax[12], fay[12], faz[12], fgx[12], fgy[12], fgz[12], ft[12], flux[12];
  dtostrf(ax_g, 1, 4, fax);
  dtostrf(ay_g, 1, 4, fay);
  dtostrf(az_g, 1, 4, faz);
  dtostrf(gx_dps, 1, 3, fgx);
  dtostrf(gy_dps, 1, 3, fgy);
  dtostrf(gz_dps, 1, 3, fgz);
  dtostrf(tempC, 1, 2, ft);
  dtostrf(luxValue, 1, 1, flux);

  char payload[190];
  uint8_t st = makeStatus();
  snprintf(payload, sizeof(payload), "$CP,%lu,%lu,%lu,%s,%s,%s,%s,%s,%s,%s,%d,%s,%u",
           millis(), (unsigned long)irValue, (unsigned long)redValue,
           fax, fay, faz, fgx, fgy, fgz, ft, gsrRaw, flux, st);
  uint8_t crc = xorCRC(payload);
  Serial.print(payload);
  Serial.print(',');
  if (crc < 16) Serial.print('0');
  Serial.println(crc, HEX);
}

void handleCommand(const char *cmd) {
  if (strncmp(cmd, "LED,G", 5) == 0) setLedState('G');
  else if (strncmp(cmd, "LED,Y", 5) == 0) setLedState('Y');
  else if (strncmp(cmd, "LED,R", 5) == 0) setLedState('R');
  else if (strncmp(cmd, "BEEP", 4) == 0) beepShort();
  else if (strncmp(cmd, "PING", 4) == 0) Serial.println("$ACK,PONG,00");
}

void readSerialCommands() {
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\n' || c == '\r') {
      if (cmdIdx > 0) {
        cmdBuf[cmdIdx] = 0;
        handleCommand(cmdBuf);
        cmdIdx = 0;
      }
    } else if (cmdIdx < sizeof(cmdBuf) - 1) {
      cmdBuf[cmdIdx++] = c;
    }
  }
}

void setup() {
  pinMode(LED_GREEN, OUTPUT);
  pinMode(LED_YELLOW, OUTPUT);
  pinMode(LED_RED, OUTPUT);
  pinMode(BUZZER_PIN, OUTPUT);
  setLedState('Y');

  Serial.begin(BAUD_RATE);
  Wire.begin();
  delay(250);

  setupPPG();
  setupMPU();
  setupTemperature();
  setupLight();
  calibrateIMU();
  readTemperature();
  readLight();

  setLedState('G');
  beepShort();
}

void loop() {
  unsigned long now = millis();
  if (now - lastPPG >= PPG_PERIOD_MS) {
    lastPPG = now;
    readPPG();
  }
  if (now - lastIMU >= IMU_PERIOD_MS) {
    lastIMU = now;
    readIMU();
  }
  if (now - lastGSR >= GSR_PERIOD_MS) {
    lastGSR = now;
    readGSR();
  }
  if (now - lastTemp >= TEMP_PERIOD_MS) {
    lastTemp = now;
    readTemperature();
    readLight();
  }
  if (now - lastPacket >= PACKET_PERIOD_MS) {
    lastPacket = now;
    sendPacket();
  }
  readSerialCommands();
}
