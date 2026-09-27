/*
  CHRONO-PCOS Mega Firmware: full premium sensor edition
  ------------------------------------------------------
  Board: Arduino Mega 2560 recommended
  Serial: 115200 baud

  Sensors included:
    MAX30102/MAX3010x PPG       I2C  SDA=20 SCL=21 on Mega
    MPU6050 IMU                 I2C
    DS18B20 x1/x2 temperature   D2 OneWire, 4.7k pull-up
    GSR analog                  A0
    MAX4466 microphone          A1
    AD8232 ECG                  A2 + LO+ D11 + LO- D12
    FSR pressure sensor         A3 voltage divider
    BH1750 light sensor         I2C optional
    BME280 environment          I2C optional
    SSD1306 OLED                I2C optional
    Buttons                     D3,D4,D5 to GND, INPUT_PULLUP
    LEDs                        D8,D9,D10 through 220 ohm
    Buzzer                      D6

  Packet:
  $CP2,ms,ir,red,ax,ay,az,gx,gy,gz,temp0,temp1,gsr,micRaw,micRms,micPitch,ecg,fsr,lux,roomT,hum,press,buttons,status,crc

  Medical safety:
  Educational physiological monitoring only. Not a diagnostic medical device.
*/

#include <Wire.h>
#include "MAX30105.h"
#include <Adafruit_MPU6050.h>
#include <Adafruit_Sensor.h>
#include <OneWire.h>
#include <DallasTemperature.h>

#define USE_BH1750 1
#define USE_BME280 1
#define USE_OLED 1

#if USE_BH1750
  #include <BH1750.h>
  BH1750 lightMeter;
#endif
#if USE_BME280
  #include <Adafruit_BME280.h>
  Adafruit_BME280 bme;
#endif
#if USE_OLED
  #include <Adafruit_GFX.h>
  #include <Adafruit_SSD1306.h>
  Adafruit_SSD1306 display(128, 64, &Wire, -1);
#endif

// Current ENDO-TWIN wearable wiring profile (ESP32-S3 pod):
// I2C SDA -> GPIO8, SCL -> GPIO9, supply -> 3V3/GND
// Temperature data -> GPIO6
// Analog PPG signal -> GPIO4 (wearable harness may route sensor S/bridge from GPIO40 to GPIO4)
#define WEARABLE_SDA 8
#define WEARABLE_SCL 9
#define TEMP_DATA_PIN 6
#define PPG_SIGNAL_PIN 4

#define ONE_WIRE_BUS TEMP_DATA_PIN
#define BTN_MODE 3
#define BTN_BASE 4
#define BTN_POST 5
#define BUZZER_PIN 6
#define LED_GREEN 8
#define LED_YELLOW 9
#define LED_RED 10
#define ECG_LO_PLUS 11
#define ECG_LO_MINUS 12

#define GSR_PIN A0
#define MIC_PIN A1
#define ECG_PIN A2
#define FSR_PIN A3

#define BAUD_RATE 115200
#define PPG_PERIOD_MS 20
#define IMU_PERIOD_MS 20
#define ANALOG_PERIOD_MS 20
#define TEMP_PERIOD_MS 1000
#define ENV_PERIOD_MS 1000
#define MIC_PERIOD_MS 100
#define OLED_PERIOD_MS 500
#define PACKET_PERIOD_MS 50   // 20 Hz extended packets

// Status bits
#define ST_PPG_ABSENT   0
#define ST_PPG_SAT      1
#define ST_MPU_ERR      2
#define ST_TEMP_ERR     3
#define ST_GSR_SAT      4
#define ST_I2C_ERR      5
#define ST_LOW_QUALITY  6
#define ST_ECG_LEADS    7
#define ST_BME_ERR      8
#define ST_OLED_ERR     9
#define ST_MIC_LOW      10
#define ST_FSR_ARTIFACT 11

MAX30105 particleSensor;
Adafruit_MPU6050 mpu;
OneWire oneWire(ONE_WIRE_BUS);
DallasTemperature tempSensor(&oneWire);

bool ppgOK=false, mpuOK=false, tempOK=false, lightOK=false, bmeOK=false, oledOK=false;
uint16_t statusBase = 0;

uint32_t irValue=0, redValue=0;
float ax_g=0, ay_g=0, az_g=1, gx_dps=0, gy_dps=0, gz_dps=0;
float ax_bias=0, ay_bias=0, az_bias=0, gx_bias=0, gy_bias=0, gz_bias=0;
float temp0=NAN, temp1=NAN;
int gsrRaw=0, ecgRaw=0, fsrRaw=0, micRaw=0;
float micRms=0, micPitchHz=0;
float luxValue=-1, roomT=NAN, humidity=NAN, pressure=NAN;
uint8_t buttonMask=0;
char ledState='Y';

unsigned long lastPPG=0,lastIMU=0,lastAnalog=0,lastTemp=0,lastEnv=0,lastMic=0,lastOLED=0,lastPacket=0;

char cmdBuf[48];
uint8_t cmdIdx=0;

uint8_t xorCRC(const char *s) {
  uint8_t c=0;
  while(*s) c ^= (uint8_t)(*s++);
  return c;
}

void setLedState(char s){
  ledState=s;
  digitalWrite(LED_GREEN, s=='G');
  digitalWrite(LED_YELLOW, s=='Y');
  digitalWrite(LED_RED, s=='R');
}
void beepShort(){ tone(BUZZER_PIN,2200,120); }

void setupPins(){
  pinMode(LED_GREEN,OUTPUT); pinMode(LED_YELLOW,OUTPUT); pinMode(LED_RED,OUTPUT);
  pinMode(BUZZER_PIN,OUTPUT);
  pinMode(BTN_MODE,INPUT_PULLUP); pinMode(BTN_BASE,INPUT_PULLUP); pinMode(BTN_POST,INPUT_PULLUP);
  pinMode(ECG_LO_PLUS,INPUT); pinMode(ECG_LO_MINUS,INPUT);
  setLedState('Y');
}

void setupPPG(){
  if(!particleSensor.begin(Wire, I2C_SPEED_FAST)){ ppgOK=false; statusBase|=(1<<ST_I2C_ERR); return; }
  ppgOK=true;
  particleSensor.setup(0x28, 4, 2, 100, 411, 4096); // brightness, avg, red+IR, sampleRate, pulseWidth, adcRange
  particleSensor.setPulseAmplitudeRed(0x28);
  particleSensor.setPulseAmplitudeIR(0x28);
  particleSensor.setPulseAmplitudeGreen(0);
}

void setupMPU(){
  if(!mpu.begin()){ mpuOK=false; statusBase|=(1<<ST_MPU_ERR); return; }
  mpuOK=true;
  mpu.setAccelerometerRange(MPU6050_RANGE_4_G);
  mpu.setGyroRange(MPU6050_RANGE_500_DEG);
  mpu.setFilterBandwidth(MPU6050_BAND_21_HZ);
}

void setupTemp(){
  tempSensor.begin();
  tempOK = tempSensor.getDeviceCount() > 0;
  if(!tempOK) statusBase|=(1<<ST_TEMP_ERR);
}

void setupLight(){
#if USE_BH1750
  lightOK = lightMeter.begin(BH1750::CONTINUOUS_LOW_RES_MODE);
  if(!lightOK) statusBase|=(1<<ST_I2C_ERR);
#endif
}

void setupBME(){
#if USE_BME280
  bmeOK = bme.begin(0x76) || bme.begin(0x77);
  if(!bmeOK) statusBase|=(1<<ST_BME_ERR);
#endif
}

void setupOLED(){
#if USE_OLED
  oledOK = display.begin(SSD1306_SWITCHCAPVCC, 0x3C);
  if(!oledOK){ statusBase|=(1<<ST_OLED_ERR); return; }
  display.clearDisplay();
  display.setTextColor(SSD1306_WHITE);
  display.setTextSize(1);
  display.setCursor(0,0);
  display.println("CHRONO-PCOS MEGA");
  display.println("Educational monitor");
  display.display();
#endif
}

void calibrateIMU(){
  if(!mpuOK) return;
  const int N=160; float sax=0,say=0,saz=0,sgx=0,sgy=0,sgz=0;
  for(int i=0;i<N;i++){
    sensors_event_t a,g,t;
    mpu.getEvent(&a,&g,&t);
    sax += a.acceleration.x/9.80665; say += a.acceleration.y/9.80665; saz += a.acceleration.z/9.80665;
    sgx += g.gyro.x*57.29578; sgy += g.gyro.y*57.29578; sgz += g.gyro.z*57.29578;
    delay(8);
  }
  ax_bias=sax/N; ay_bias=say/N; az_bias=(saz/N)-1.0;
  gx_bias=sgx/N; gy_bias=sgy/N; gz_bias=sgz/N;
}

void readPPG(){ if(ppgOK){ redValue=particleSensor.getRed(); irValue=particleSensor.getIR(); } }

void readIMU(){
  if(!mpuOK) return;
  sensors_event_t a,g,t;
  mpu.getEvent(&a,&g,&t);
  ax_g=a.acceleration.x/9.80665-ax_bias;
  ay_g=a.acceleration.y/9.80665-ay_bias;
  az_g=a.acceleration.z/9.80665-az_bias;
  gx_dps=g.gyro.x*57.29578-gx_bias;
  gy_dps=g.gyro.y*57.29578-gy_bias;
  gz_dps=g.gyro.z*57.29578-gz_bias;
}

void readAnalogSensors(){
  gsrRaw=analogRead(GSR_PIN);
  ecgRaw=analogRead(ECG_PIN);
  fsrRaw=analogRead(FSR_PIN);
  buttonMask=0;
  if(digitalRead(BTN_MODE)==LOW) buttonMask |= 1;
  if(digitalRead(BTN_BASE)==LOW) buttonMask |= 2;
  if(digitalRead(BTN_POST)==LOW) buttonMask |= 4;
}

void readTemperatures(){
  if(!tempOK) return;
  tempSensor.requestTemperatures();
  temp0=tempSensor.getTempCByIndex(0);
  temp1=tempSensor.getDeviceCount()>1 ? tempSensor.getTempCByIndex(1) : NAN;
}

void readEnvironment(){
#if USE_BH1750
  if(lightOK) luxValue=lightMeter.readLightLevel();
#endif
#if USE_BME280
  if(bmeOK){ roomT=bme.readTemperature(); humidity=bme.readHumidity(); pressure=bme.readPressure()/100.0F; }
#endif
}

void readMicFeatures(){
  // 256 samples, rough 4 kHz. Estimates RMS and zero-crossing pitch for sustained vowel only.
  const int N=256;
  const int delayUs=250;
  long sum=0;
  int samples[N];
  for(int i=0;i<N;i++){
    int v=analogRead(MIC_PIN);
    samples[i]=v;
    sum += v;
    delayMicroseconds(delayUs);
  }
  float mean=sum/(float)N;
  float ss=0;
  int crossings=0;
  int lastSign=0;
  for(int i=0;i<N;i++){
    float d=samples[i]-mean;
    ss += d*d;
    int sign = d>=0 ? 1 : -1;
    if(i>0 && sign!=lastSign) crossings++;
    lastSign=sign;
  }
  micRaw=samples[N-1];
  micRms=sqrt(ss/N);
  float fs=1000000.0/delayUs;
  micPitchHz=(crossings/2.0)*(fs/N);
  if(micPitchHz<60 || micPitchHz>400) micPitchHz=0;
}

uint16_t makeStatus(){
  uint16_t st=statusBase;
  if(ppgOK){ if(irValue<5000) st|=(1<<ST_PPG_ABSENT); if(irValue>250000UL || redValue>250000UL) st|=(1<<ST_PPG_SAT); }
  if(tempOK && !(temp0>-20 && temp0<80)) st|=(1<<ST_TEMP_ERR);
  if(gsrRaw<5 || gsrRaw>1018) st|=(1<<ST_GSR_SAT);
  if(digitalRead(ECG_LO_PLUS)==HIGH || digitalRead(ECG_LO_MINUS)==HIGH) st|=(1<<ST_ECG_LEADS);
  if(micRms<2) st|=(1<<ST_MIC_LOW);
  if(fsrRaw<20 || fsrRaw>1000) st|=(1<<ST_FSR_ARTIFACT);
  return st;
}

void sendPacket(){
  char fax[12],fay[12],faz[12],fgx[12],fgy[12],fgz[12],ft0[12],ft1[12],flux[12],frt[12],fhum[12],fpress[12],fmr[12],fmp[12];
  dtostrf(ax_g,1,4,fax); dtostrf(ay_g,1,4,fay); dtostrf(az_g,1,4,faz);
  dtostrf(gx_dps,1,3,fgx); dtostrf(gy_dps,1,3,fgy); dtostrf(gz_dps,1,3,fgz);
  dtostrf(temp0,1,2,ft0); dtostrf(temp1,1,2,ft1); dtostrf(luxValue,1,1,flux);
  dtostrf(roomT,1,2,frt); dtostrf(humidity,1,1,fhum); dtostrf(pressure,1,1,fpress);
  dtostrf(micRms,1,2,fmr); dtostrf(micPitchHz,1,1,fmp);
  char payload[260];
  uint16_t st=makeStatus();
  snprintf(payload,sizeof(payload),"$CP2,%lu,%lu,%lu,%s,%s,%s,%s,%s,%s,%s,%s,%d,%d,%s,%s,%d,%d,%s,%s,%s,%s,%u,%u",
    millis(),(unsigned long)irValue,(unsigned long)redValue,
    fax,fay,faz,fgx,fgy,fgz,ft0,ft1,gsrRaw,micRaw,fmr,fmp,ecgRaw,fsrRaw,flux,frt,fhum,fpress,buttonMask,st);
  uint8_t crc=xorCRC(payload);
  Serial.print(payload); Serial.print(','); if(crc<16) Serial.print('0'); Serial.println(crc,HEX);
}

void updateOLED(){
#if USE_OLED
  if(!oledOK) return;
  display.clearDisplay();
  display.setTextSize(1); display.setCursor(0,0);
  display.println("CHRONO-PCOS MEGA");
  display.print("IR:"); display.print(irValue); display.print(" ECG:"); display.println(ecgRaw);
  display.print("T0:"); display.print(temp0,1); display.print(" T1:"); display.println(temp1,1);
  display.print("GSR:"); display.print(gsrRaw); display.print(" FSR:"); display.println(fsrRaw);
  display.print("Lux:"); display.print(luxValue,0); display.print(" MicHz:"); display.println(micPitchHz,0);
  display.print("BTN:"); display.print(buttonMask); display.print(" LED:"); display.println(ledState);
  display.println("Not medical diagnosis");
  display.display();
#endif
}

void handleCommand(const char *cmd){
  if(strncmp(cmd,"LED,G",5)==0) setLedState('G');
  else if(strncmp(cmd,"LED,Y",5)==0) setLedState('Y');
  else if(strncmp(cmd,"LED,R",5)==0) setLedState('R');
  else if(strncmp(cmd,"BEEP",4)==0) beepShort();
  else if(strncmp(cmd,"PING",4)==0) Serial.println("$ACK,PONG,00");
}

void readSerialCommands(){
  while(Serial.available()){
    char c=(char)Serial.read();
    if(c=='\n' || c=='\r'){
      if(cmdIdx>0){ cmdBuf[cmdIdx]=0; handleCommand(cmdBuf); cmdIdx=0; }
    } else if(cmdIdx<sizeof(cmdBuf)-1) cmdBuf[cmdIdx++]=c;
  }
}

void setup(){
  setupPins();
  Serial.begin(BAUD_RATE);
  // Use the current wearable's I2C pins.
  Wire.begin(WEARABLE_SDA, WEARABLE_SCL);
  delay(300);
  setupOLED();
  setupPPG(); setupMPU(); setupTemp(); setupLight(); setupBME();
  calibrateIMU(); readTemperatures(); readEnvironment(); readMicFeatures();
  setLedState('G'); beepShort();
}

void loop(){
  unsigned long now=millis();
  if(now-lastPPG>=PPG_PERIOD_MS){ lastPPG=now; readPPG(); }
  if(now-lastIMU>=IMU_PERIOD_MS){ lastIMU=now; readIMU(); }
  if(now-lastAnalog>=ANALOG_PERIOD_MS){ lastAnalog=now; readAnalogSensors(); }
  if(now-lastTemp>=TEMP_PERIOD_MS){ lastTemp=now; readTemperatures(); }
  if(now-lastEnv>=ENV_PERIOD_MS){ lastEnv=now; readEnvironment(); }
  if(now-lastMic>=MIC_PERIOD_MS){ lastMic=now; readMicFeatures(); }
  if(now-lastOLED>=OLED_PERIOD_MS){ lastOLED=now; updateOLED(); }
  if(now-lastPacket>=PACKET_PERIOD_MS){ lastPacket=now; sendPacket(); }
  readSerialCommands();
}
