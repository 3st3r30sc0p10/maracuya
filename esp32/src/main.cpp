#include <Arduino.h>

// Pin assignments (Adafruit ESP32-S3 Feather pinouts -> GPIO numbers)
// D5 = GPIO5, A0 = GPIO1, A1 = GPIO2, A2 = GPIO3
const int LED_PWM_PIN = 5; // D5
const int PROX_PIN = 1;    // A0
const int RUBBER_PIN = 2;  // A1
const int FABRIC_PIN = 3;  // A2

// PWM configuration
const int LEDC_CHANNEL = 0;
const int LEDC_FREQ_HZ = 5000;
const int LEDC_RES_BITS = 12; // 0-4095

// Proximity sensor calibration (adjust for your sensor)
const int PROX_MIN = 400;       // value when far
const int PROX_MAX = 3000;      // value when close
const bool PROX_INVERT = false; // set true if close reads lower

// Smoothing
const float EMA_ALPHA = 0.15f; // lower = more smoothing

// Timing
const unsigned long UPDATE_MS = 25;
const unsigned long SERIAL_INTERVAL_MS = 100;

float proxFiltered = 0.0f;
unsigned long lastUpdate = 0;
unsigned long lastSerial = 0;

static float clamp01(float v) {
  if (v < 0.0f)
    return 0.0f;
  if (v > 1.0f)
    return 1.0f;
  return v;
}

void setup() {
  Serial.begin(115200);
  delay(200);

  // PWM setup
  ledcSetup(LEDC_CHANNEL, LEDC_FREQ_HZ, LEDC_RES_BITS);
  ledcAttachPin(LED_PWM_PIN, LEDC_CHANNEL);

  // ADC setup
  analogReadResolution(12);
  analogSetPinAttenuation(PROX_PIN, ADC_11db);
  analogSetPinAttenuation(RUBBER_PIN, ADC_11db);
  analogSetPinAttenuation(FABRIC_PIN, ADC_11db);

  // Initialize filter with first read
  proxFiltered = analogRead(PROX_PIN);

}

void loop() {
  const unsigned long now = millis();
  if (now - lastUpdate < UPDATE_MS) {
    delay(2);
    return;
  }
  lastUpdate = now;

  const int proxRaw = analogRead(PROX_PIN);
  const int rubberRaw = analogRead(RUBBER_PIN);
  const int fabricRaw = analogRead(FABRIC_PIN);

  proxFiltered = (EMA_ALPHA * proxRaw) + ((1.0f - EMA_ALPHA) * proxFiltered);

  float proxNorm = 0.0f;
  if (PROX_MAX != PROX_MIN) {
    proxNorm = (proxFiltered - PROX_MIN) / float(PROX_MAX - PROX_MIN);
  }
  if (PROX_INVERT) {
    proxNorm = 1.0f - proxNorm;
  }
  proxNorm = clamp01(proxNorm);

  const uint32_t maxDuty = (1U << LEDC_RES_BITS) - 1;
  const uint32_t duty = uint32_t(proxNorm * maxDuty);
  ledcWrite(LEDC_CHANNEL, duty);

  if (now - lastSerial >= SERIAL_INTERVAL_MS) {
    lastSerial = now;
    const float rubberV = (rubberRaw / 4095.0f) * 3.3f;
    const float fabricV = (fabricRaw / 4095.0f) * 3.3f;

    String payload = "{";
    payload += "\"ts_ms\":" + String(now) + ",";
    payload += "\"rubber_v\":" + String(rubberV, 3) + ",";
    payload += "\"fabric_v\":" + String(fabricV, 3) + ",";
    payload += "\"prox_raw\":" + String(proxRaw) + ",";
    payload += "\"prox_norm\":" + String(proxNorm, 3);
    payload += "}";

    Serial.println(payload);
  }
}
