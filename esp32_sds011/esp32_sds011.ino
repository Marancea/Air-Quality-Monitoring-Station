/*
 * Air Quality Sensor Node  -  ESP32 + Nova SDS011
 * -------------------------------------------------
 * Reads PM2.5 and PM10 from an SDS011 particulate sensor over UART and
 * publishes them via MQTT to the Mosquitto broker running on the
 * Raspberry Pi weather station. The station's Screen 2 ("Local vs OpenAQ")
 * subscribes to this data.
 *
 * Wiring (SDS011 -> ESP32):
 *   5V  (red)    -> VIN
 *   GND (black)  -> GND
 *   TXD (yellow) -> GPIO16  (RX2)   <- sensor data into the ESP32
 *   RXD (blue)   -> GPIO17  (TX2)
 *
 * Publishes JSON to topic "weather/sds011" every 30 s, e.g.:
 *   {"pm25":12.3,"pm10":18.7,"sensor":"sds011","rssi":-62}
 *
 * Finding the Pi: the sketch resolves the Pi by hostname over mDNS
 * (weather.local) so you don't have to chase the hotspot IP. If mDNS
 * fails, it falls back to the fixed IP in MQTT_HOST_IP.
 *
 * Libraries required (install via Arduino Library Manager):
 *   - PubSubClient   (by Nick O'Leary)   -> MQTT
 *   - ArduinoJson    (by Benoit Blanchon) -> JSON building
 *   (ESPmDNS and WiFi come bundled with the ESP32 board package.)
 * Board package:
 *   - "esp32 by Espressif Systems"  (Boards Manager)
 *   Select board: "ESP32 Dev Module"
 */

#include <WiFi.h>
#include <WiFiMulti.h>
#include <ESPmDNS.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>

// ----------------------------------------------------------------------------
// SETTINGS  -  edit these to match your setup
// ----------------------------------------------------------------------------

// WiFi networks (the Pi must be on the same one). The board will connect
// to whichever of these is available with the strongest signal. Add as
// many as you like by copying the wifiMulti.addAP(...) lines in setup().
const char* WIFI1_SSID     = "marancea";        // <-- network 1 name
const char* WIFI1_PASSWORD = "craiova1";    // <-- network 1 password
const char* WIFI2_SSID     = "INCESA-WIFI";           // <-- network 2 name
const char* WIFI2_PASSWORD = "accesnet";       // <-- network 2 password

// MQTT broker = the Raspberry Pi.
// The sketch first tries to find the Pi by its hostname over mDNS
// (so you never have to chase the changing hotspot IP). If that fails,
// it falls back to MQTT_HOST_IP below.
const char* MQTT_HOST_NAME = "weather";           // Pi hostname -> weather.local
const char* MQTT_HOST_IP   = "192.168.1.100";     // fallback IP (set to the Pi's IP)
const int   MQTT_PORT = 1883;
const char* MQTT_TOPIC = "weather/sds011";
const char* MQTT_CLIENT_ID = "esp32-sds011";

// How often to publish (milliseconds)
const unsigned long PUBLISH_EVERY_MS = 30000;     // 30 seconds

// SDS011 UART pins (UART2)
const int SDS_RX_PIN = 16;   // ESP32 RX2  <- SDS011 TXD (yellow)
const int SDS_TX_PIN = 17;   // ESP32 TX2  -> SDS011 RXD (blue)

// ----------------------------------------------------------------------------
// Globals
// ----------------------------------------------------------------------------
WiFiClient   wifiClient;
PubSubClient mqtt(wifiClient);
HardwareSerial sds(2);                 // use UART2 for the sensor
WiFiMulti    wifiMulti;                // manages the list of WiFi networks

IPAddress brokerIP;                    // resolved broker address
bool brokerResolved = false;

float lastPm25 = -1.0;
float lastPm10 = -1.0;
unsigned long lastPublish = 0;

// ----------------------------------------------------------------------------
// SDS011 frame parser
// ----------------------------------------------------------------------------
// The SDS011 streams 10-byte frames:
//   [0]=0xAA [1]=0xC0 [2]=PM2.5 low [3]=PM2.5 high
//   [4]=PM10 low [5]=PM10 high [6,7]=device id [8]=checksum [9]=0xAB
// PM2.5 = (high<<8 | low) / 10 ;  PM10 = (high<<8 | low) / 10
bool readSDS(float &pm25, float &pm10) {
  static uint8_t buf[10];
  static int idx = 0;

  bool got = false;
  while (sds.available()) {
    uint8_t b = sds.read();

    if (idx == 0 && b != 0xAA) continue;        // wait for header
    if (idx == 1 && b != 0xC0) { idx = 0; continue; }

    buf[idx++] = b;

    if (idx == 10) {
      idx = 0;
      // verify checksum: sum of bytes [2..7] == byte[8]
      uint8_t sum = 0;
      for (int i = 2; i <= 7; i++) sum += buf[i];
      if (sum == buf[8] && buf[9] == 0xAB) {
        pm25 = (buf[2] | (buf[3] << 8)) / 10.0;
        pm10 = (buf[4] | (buf[5] << 8)) / 10.0;
        got = true;
      }
    }
  }
  return got;
}

// ----------------------------------------------------------------------------
// WiFi + MQTT connection helpers
// ----------------------------------------------------------------------------
void ensureWifi() {
  if (WiFi.status() == WL_CONNECTED) return;
  Serial.print("WiFi connecting (trying known networks)");
  WiFi.mode(WIFI_STA);
  // wifiMulti.run() scans and connects to the best available known network.
  unsigned long start = millis();
  while (wifiMulti.run() != WL_CONNECTED && millis() - start < 20000) {
    delay(500);
    Serial.print(".");
  }
  if (WiFi.status() == WL_CONNECTED) {
    Serial.print(" connected to ");
    Serial.print(WiFi.SSID());
    Serial.print(", IP=");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println(" FAILED (will retry)");
  }
}

// Resolve the broker address: try mDNS hostname first, fall back to IP.
void resolveBroker() {
  brokerResolved = false;

  // Try mDNS: "weather" -> resolves to the Pi's current IP.
  IPAddress ip = MDNS.queryHost(MQTT_HOST_NAME);
  if (ip != IPAddress(0, 0, 0, 0)) {
    brokerIP = ip;
    brokerResolved = true;
    Serial.print("mDNS resolved ");
    Serial.print(MQTT_HOST_NAME);
    Serial.print(".local -> ");
    Serial.println(brokerIP);
    return;
  }

  // Fallback: use the fixed IP from settings.
  if (brokerIP.fromString(MQTT_HOST_IP)) {
    brokerResolved = true;
    Serial.print("mDNS failed; using fallback IP ");
    Serial.println(brokerIP);
  } else {
    Serial.println("Could not resolve broker by name or IP!");
  }
}

void ensureMqtt() {
  if (mqtt.connected()) return;
  if (WiFi.status() != WL_CONNECTED) return;

  // (Re)resolve the broker address if we don't have one yet.
  if (!brokerResolved) {
    resolveBroker();
    if (!brokerResolved) return;
    mqtt.setServer(brokerIP, MQTT_PORT);
  }

  Serial.print("MQTT connecting to ");
  Serial.print(brokerIP);
  Serial.print("...");
  if (mqtt.connect(MQTT_CLIENT_ID)) {        // anonymous connection
    Serial.println(" connected");
  } else {
    Serial.print(" failed rc=");
    Serial.println(mqtt.state());
    // If it keeps failing, drop the cached address so we re-resolve
    // (the Pi may have got a new IP on the hotspot).
    static int fails = 0;
    if (++fails >= 3) {
      fails = 0;
      brokerResolved = false;
      Serial.println("Re-resolving broker address next attempt...");
    }
  }
}

// ----------------------------------------------------------------------------
// Publish the latest reading as JSON
// ----------------------------------------------------------------------------
void publishReading() {
  if (!mqtt.connected()) return;
  if (lastPm25 < 0 || lastPm10 < 0) {
    Serial.println("No valid sensor reading yet; skipping publish");
    return;
  }
  StaticJsonDocument<160> doc;
  doc["pm25"]   = lastPm25;
  doc["pm10"]   = lastPm10;
  doc["sensor"] = "sds011";
  doc["rssi"]   = WiFi.RSSI();

  char payload[160];
  size_t n = serializeJson(doc, payload);
  bool ok = mqtt.publish(MQTT_TOPIC, payload, n);
  Serial.print("Publish ");
  Serial.print(ok ? "OK: " : "FAILED: ");
  Serial.println(payload);
}

// ----------------------------------------------------------------------------
// Setup / loop
// ----------------------------------------------------------------------------
void setup() {
  Serial.begin(115200);
  delay(200);
  Serial.println("\nESP32 SDS011 air quality node starting...");

  // SDS011 talks at 9600 baud, 8N1.
  sds.begin(9600, SERIAL_8N1, SDS_RX_PIN, SDS_TX_PIN);

  // Register the known WiFi networks. Add more by copying this line.
  wifiMulti.addAP(WIFI1_SSID, WIFI1_PASSWORD);
  wifiMulti.addAP(WIFI2_SSID, WIFI2_PASSWORD);

  ensureWifi();

  // Start mDNS so we can resolve the Pi by hostname (weather.local).
  if (MDNS.begin("esp32-sds011")) {
    Serial.println("mDNS started on ESP32");
  } else {
    Serial.println("mDNS start failed (will use fallback IP)");
  }

  ensureMqtt();   // resolves broker (mDNS or fallback IP) then connects
}

void loop() {
  // Keep connections alive.
  ensureWifi();
  ensureMqtt();
  mqtt.loop();

  // Continuously read the sensor; keep the latest valid values.
  float pm25, pm10;
  if (readSDS(pm25, pm10)) {
    lastPm25 = pm25;
    lastPm10 = pm10;
  }

  // Publish on a timer.
  unsigned long now = millis();
  if (now - lastPublish >= PUBLISH_EVERY_MS) {
    lastPublish = now;
    Serial.print("Latest  PM2.5=");
    Serial.print(lastPm25);
    Serial.print("  PM10=");
    Serial.println(lastPm10);
    publishReading();
  }

  delay(10);
}
