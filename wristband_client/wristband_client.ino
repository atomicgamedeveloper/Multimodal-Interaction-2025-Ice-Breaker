#include <WiFi.h>
#include <ArduinoJson.h>

const char* ssid = "pewpewpew";
const char* password = "13]10A2mn";

const char* mqtt_server = "192.168.137.1";
const int mqtt_port = 1883;
const char* mqtt_topic = "mafia";

const int SOLENOID_PIN = 8;

const int DEVICE_ID = 4;

WiFiClient client;
bool connected = false;

void triggerSolenoid(int times) {
  for (int i = 0; i < times; i++) {
    digitalWrite(SOLENOID_PIN, HIGH);
    delay(100);
    digitalWrite(SOLENOID_PIN, LOW);
    delay(750);
  }
}

bool connectToMQTT() {
  if (client.connect(mqtt_server, mqtt_port)) {
    connected = true;
    StaticJsonDocument<200> doc;
    doc["type"] = "subscribe";
    doc["topic"] = mqtt_topic;
    String json;
    serializeJson(doc, json);
    client.print(json);
    return true;
  } else {
    connected = false;
    return false;
  }
}

void checkForMessages() {
  if (!connected || !client.available()) {
    return;
  }
  
  String line = client.readStringUntil('\n');
  if (line.length() > 0) {
    StaticJsonDocument<512> doc;
    DeserializationError error = deserializeJson(doc, line);
    
    if (!error) {
      if (doc.containsKey("payload")) {
        const char* payloadStr = doc["payload"];
        StaticJsonDocument<256> payloadDoc;
        DeserializationError payloadError = deserializeJson(payloadDoc, payloadStr);
        
        if (!payloadError) {
          int targetId = payloadDoc["id"];
          int tapCount = payloadDoc["taps"];
          
          if (targetId == DEVICE_ID) {
            if (tapCount > 0 && tapCount <= 10) {
              triggerSolenoid(tapCount);
            }
          }
        }
      }
    }
  }
}

void setup() {
  delay(1000);
  pinMode(SOLENOID_PIN, OUTPUT);
  digitalWrite(SOLENOID_PIN, LOW);
  WiFi.begin(ssid, password);
  
  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 40) {
    delay(500);
    attempts++;
  }
  
  bool fullSuccess = false;
  
  if (WiFi.status() == WL_CONNECTED) {
    if (connectToMQTT()) {
      fullSuccess = true;
      triggerSolenoid(1);
    } else {
      triggerSolenoid(2);
    }
  } else {
    triggerSolenoid(2);
  }
}

void loop() {
  checkForMessages();
  static unsigned long lastCheck = 0;
  if (millis() - lastCheck > 5000) {
    lastCheck = millis();
    
    if (WiFi.status() != WL_CONNECTED) {
      connected = false;
      WiFi.reconnect();
    }
    
    if (connected && !client.connected()) {
      connected = false;
      delay(1000);
      connectToMQTT();
    }
  }
  
  delay(10);
}