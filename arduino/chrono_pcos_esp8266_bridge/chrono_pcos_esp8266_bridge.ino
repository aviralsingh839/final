/*
  CHRONO-PCOS ESP8266 Wi-Fi Bridge
  ---------------------------------
  Turns the wired Arduino setup wireless. The ESP8266 sits between the Arduino
  Mega (Serial1, or Serial if wired standalone) and the Python dashboard:

      Arduino Mega (USB serial)  --or-->  ESP8266 (Serial)  <--TCP-->  dashboard

  Two wiring options:

  Option A (Mega + ESP8266, wired):
      Mega TX1 (D18)  -> ESP RX
      Mega RX1 (D19)  -> ESP TX
      Common GND, ESP powered at 3.3V.
      In this sketch set USE_SERIAL1 1 (default). The Mega's USB stays free for
      the normal wired mode and the ESP simply mirrors the same $CP2 packets.

  Option B (ESP8266 standalone firmware that reads a MAX30102 directly) is NOT
  provided - this is intentionally a transparent byte relay so the exact same
  $CP2 protocol, parsing, and sensor handling are used.

  Behaviour:
    - Connects to your Wi-Fi network (SSID/PASSWORD below) or starts its own
      soft-AP (access point "CHRONO-PCOS-BRIDGE") if it cannot join.
    - Opens a TCP server on port 7777 (see WIFI_BRIDGE_DEFAULT_PORT in
      src/config.py).
    - Every byte received on the serial line from the Arduino is forwarded to
      all connected TCP clients; every byte from a client is written to serial
      (so LED/BEEP commands still work).
    - Serial baud must match the firmware: 115200.

  Medical safety: educational physiological monitoring only, not a diagnostic
  medical device.
*/

#include <ESP8266WiFi.h>

#define WIFI_SSID     "CHRONO_PCOS_WIFI"      // << set your network name
#define WIFI_PASSWORD "changeme1234"          // << set your network password
#define TCP_PORT      7777
#define SERIAL_BAUD   115200

// Use Serial1 (pins D18/D19 on the Mega side) when the ESP is wired to a Mega.
// Use Serial when the ESP is connected to a bare UART (e.g. USB-TTL adapter).
#define USE_SERIAL1 1

#if USE_SERIAL1
  #define BRIDGE_SERIAL Serial1
#else
  #define BRIDGE_SERIAL Serial
#endif

WiFiServer server(TCP_PORT);
WiFiClient client;

void setup() {
  Serial.begin(115200);       // ESP debug console
  BRIDGE_SERIAL.begin(SERIAL_BAUD);
  delay(200);

  Serial.println();
  Serial.println("CHRONO-PCOS ESP8266 bridge");
  Serial.printf("Connecting to SSID: %s\r\n", WIFI_SSID);

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  unsigned long t0 = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - t0 < 15000) {
    delay(400);
    Serial.print(".");
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println();
    Serial.print("Connected, IP: ");
    Serial.println(WiFi.localIP());
  } else {
    // Fall back to a soft access point so the dashboard can still connect.
    Serial.println();
    Serial.println("Wi-Fi join failed; starting soft-AP 'CHRONO-PCOS-BRIDGE'");
    WiFi.mode(WIFI_AP);
    WiFi.softAP("CHRONO-PCOS-BRIDGE", "chronopcos", 6, 0, 1);
    Serial.print("AP IP: ");
    Serial.println(WiFi.softAPIP());
  }

  server.begin();
  Serial.printf("TCP bridge listening on port %d\r\n", TCP_PORT);
}

void relayBytes(uint8_t *buf, size_t n, bool toClient) {
  if (toClient) {
    if (client && client.connected()) {
      client.write(buf, n);
    }
  } else {
    if (client && client.connected()) {
      while (client.available()) {
        BRIDGE_SERIAL.write(client.read());
      }
    }
  }
}

void loop() {
  // Accept/reacquire a client.
  if (!client || !client.connected()) {
    client = server.available();
    if (client) {
      client.setNoDelay(true);
      Serial.println("Client connected");
    }
  }

  // Arduino -> TCP.
  size_t n = BRIDGE_SERIAL.available();
  if (n > 0) {
    uint8_t buf[256];
    size_t readN = BRIDGE_SERIAL.readBytes(buf, min(n, (size_t)sizeof(buf)));
    relayBytes(buf, readN, true);
  }

  // TCP -> Arduino (commands such as LED,G / BEEP).
  if (client && client.connected()) {
    while (client.available()) {
      BRIDGE_SERIAL.write(client.read());
    }
  }
}
