/*
  CHRONO-PCOS V5 — Smart Ring firmware (reference)
  ================================================
  ESP32-C3 continuous wearable: MAX30102 PPG + MPU6050 IMU + DS18B20 skin temp
  + battery monitoring.

  Emits the existing $CP2 serial protocol so the current dashboard reader
  (src/serial_io/packet_parser.py) consumes it unchanged:
    $CP2,ms,ir,red,ax,ay,az,gx,gy,gz,temp0,temp1,gsr,micRaw,micRms,micPitch,
         ecg,fsr,lux,roomT,hum,press,buttons,status,crc
  Unused channels (GSR/mic/ECG/FSR/light/room) are zeroed / -1.

  Also broadcasts the same payload as a BLE notify on a custom service so the
  V5 transport path (src/hardware/transport.py: BlePacketProtocol + LocalBuffer)
  can carry it. Battery % is appended only to the BLE payload (",batt").

  Wiring (ESP32-C3):
    MAX30102 VIN/GND/SDA/SCL -> 3V3 / GND / GPIO8 / GPIO9
    MPU6050  VCC/GND/SDA/SCL -> 3V3 / GND / GPIO8 / GPIO9 (addr 0x68)
    DS18B20  DQ                -> GPIO10 (4.7k pull-up to 3V3)
    Battery  divider (2x100k)  -> GPIO2

  Libraries: SparkFun MAX3010x, Adafruit MPU6050 + Adafruit Unified Sensor,
  OneWire, DallasTemperature. BLE is built into the ESP32 core.

  Reference sketch: compile-logic verified, not endurance-tested hardware.
  Educational monitoring only - not a medical device.
*/

#include <Wire.h>
#include "MAX30105.h"
#include "SparkFun_MAX3010x_Heart_Rate_Library.h"
#include <Adafruit_MPU6050.h>
#include <Adafruit_Sensor.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>

// ---------------------------------------------------------------- pins
#define I2C_SDA        8
#define I2C_SCL        9
#define TEMP_PIN       10
#define BATT_PIN       2
#define SAMPLE_HZ      50
#define WEAR_IR_MIN    5000        // below this for 10s -> not worn
#define LOW_POWER_MS   5000        // sleep between bursts when not worn

// ---------------------------------------------------------------- sensors
MAX30105 particleSensor;
Adafruit_MPU6050 mpu;
OneWire oneWire(TEMP_PIN);
DallasTemperature dallas(&oneWire);

// ---------------------------------------------------------------- BLE
#define BLE_SERVICE_UUID   "e0c0a001-0000-4a5e-8b6e-000000000000"
#define BLE_NOTIFY_UUID    "e0c0a002-0000-4a5e-8b6e-000000000000"
#define BLE_COMMAND_UUID   "e0c0a003-0000-4a5e-8b6e-000000000000"
BLECharacteristic *notifyChar = nullptr;
bool bleConnected = false;

class RingServerCallbacks : public BLEServerCallbacks {
  void onConnect(BLEServer *s) { bleConnected = true; }
  void onDisconnect(BLEServer *s) { bleConnected = false; BLEDevice::startAdvertising(); }
};

// ---------------------------------------------------------------- state
long notWornSince = 0;
float ax_g = 0, ay_g = 0, az_g = 1.0;
float temp0 = 0.0;
uint16_t statusBase = 0;

// ------------------------------------------------------------ helpers
uint8_t xorCRC(const char *s) {
  uint8_t c = 0;
  for (int i = 0; s[i]; i++) c ^= (uint8_t)s[i];
  return c;
}

void readIMU() {
  sensors_event_t a, g, t;
  mpu.getEvent(&a, &g, &t);
  ax_g = a.acceleration.x;
  ay_g = a.acceleration.y;
  az_g = a.acceleration.z;
}

int readBatteryPct() {
  // 2x100k divider: millivolts*2 = battery mV. Approximate % for 3.4-4.2V.
  int mv = analogReadMilliVolts(BATT_PIN) * 2;
  if (mv <= 3400) return 0;
  if (mv >= 4200) return 100;
  return (mv - 3400) * 100 / 800;
}

void sendPacket(unsigned long ir, unsigned long red) {
  uint16_t st = statusBase;
  if (ir < 5000)           st |= (1 << 0);   // PPG absent
  if (ir > 250000UL)       st |= (1 << 1);   // PPG saturation
  if (!(temp0 > -20 && temp0 < 80)) st |= (1 << 2);

  char payload[200];
  snprintf(payload, sizeof(payload),
           "$CP2,%lu,%lu,%lu,%.4f,%.4f,%.4f,0,0,0,%.2f,0,0,0,0,0,-1,-1,-1,0,0,0,0,%u",
           millis(), ir, red, ax_g, ay_g, az_g, temp0, st);
  uint8_t crc = xorCRC(payload);
  Serial.print(payload);
  Serial.print(',');
  if (crc < 16) Serial.print('0');
  Serial.println(crc, HEX);

  if (bleConnected && notifyChar) {
    char bleLine[220];
    snprintf(bleLine, sizeof(bleLine), "%s,%d", payload, readBatteryPct());
    notifyChar->setValue((uint8_t *)bleLine, strlen(bleLine));
    notifyChar->notify();
  }
}

// ---------------------------------------------------------------- setup
void setup() {
  Serial.begin(115200);
  Wire.begin(I2C_SDA, I2C_SCL);

  if (!particleSensor.begin(Wire, I2C_SPEED_FAST)) {
    Serial.println("$ACK,MAX30102_ERR,00");
  } else {
    particleSensor.setup(particleSensor.LED_RATE_50, particleSensor.LED_PW_411,
                         particleSensor.ADC_RANGE_2048, particleSensor.SAMPLE_AVG_4);
    particleSensor.enableDIETEMPRDY();  // keep sensor temp readout optional
  }
  if (!mpu.begin()) Serial.println("$ACK,MPU_ERR,00");
  else {
    mpu.setAccelerometerRange(MPU6050_RANGE_4_G);
    mpu.setGyroRange(MPU6050_RANGE_500_DEG);
  }
  dallas.begin();

  BLEDevice::init("CHRONO-RING");
  BLEServer *server = BLEDevice::createServer();
  server->setCallbacks(new RingServerCallbacks());
  BLEService *svc = server->createService(BLE_SERVICE_UUID);
  notifyChar = svc->createCharacteristic(BLE_NOTIFY_UUID,
                                         BLECharacteristic::PROPERTY_NOTIFY);
  notifyChar->addDescriptor(new BLE2902());
  svc->createCharacteristic(BLE_COMMAND_UUID, BLECharacteristic::PROPERTY_WRITE);
  svc->start();
  BLEAdvertising *adv = BLEDevice::getAdvertising();
  adv->addServiceUUID(BLE_SERVICE_UUID);
  BLEDevice::startAdvertising();

  Serial.println("$ACK,RING_READY,00");
}

// ----------------------------------------------------------------- loop
void loop() {
  particleSensor.check();
  unsigned long ir = particleSensor.getIR();
  unsigned long red = particleSensor.getRed();

  // Wear detection -> low-power bursts when not worn.
  if (ir < WEAR_IR_MIN) {
    if (notWornSince == 0) notWornSince = millis();
    if (millis() - notWornSince > 10000) {
      delay(LOW_POWER_MS);   // duty-cycle sleep
      return;
    }
  } else {
    notWornSince = 0;
  }

  readIMU();
  dallas.requestTemperatures();
  temp0 = dallas.getTempCByIndex(0);
  if (temp0 < -50 || temp0 > 125) temp0 = 0.0;  // open/short read

  sendPacket(ir, red);
  delay(1000 / SAMPLE_HZ);
}
