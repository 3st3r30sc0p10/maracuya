#include <Arduino.h>
#include "esp_system.h"

// Pin assignments (use Arduino aliases to avoid GPIO/strap mistakes)
const int LED_PWM_PIN = A5; // D5 maps to A5 on Feather (GPIO8)
const int PROX_PIN = A0;    // GPIO18
const int RUBBER_PIN = A1;  // GPIO17
const int FABRIC_PIN = A2;  // GPIO16
const bool ENABLE_ADC = true;
const int ULTRASONIC_TRIG_PIN = A10; // D9 maps to A10 (GPIO9)
const int ULTRASONIC_ECHO_PIN = A11; // D10 maps to A11 (GPIO10)
const bool ENABLE_ULTRASONIC = true;

// UART telemetry (Pi GPIO UART)
const bool ENABLE_SERIAL_INIT = true;
const bool TELEMETRY_USB = false;  // USB CDC disabled
const bool TELEMETRY_UART = true;  // Hardware UART routed to TX/RX pins
const bool UART_ECHO_TEST = false;
// Prefer board-defined TX/RX pins when available (matches silkscreen)
#if defined(TX) && defined(RX)
const int UART_TX_PIN = TX; // Feather TX pin (GPIO39)
const int UART_RX_PIN = RX; // Feather RX pin (GPIO38)
#else
const int UART_TX_PIN = 39;
const int UART_RX_PIN = 38;
#endif
const int UART_BAUD = 115200;
HardwareSerial TelemetrySerial(1);

// Safe-mode debug: minimal peripherals, steady heartbeat
const bool SAFE_MODE = false;
const unsigned long SAFE_INTERVAL_MS = 500;
unsigned long lastSafe = 0;
bool safeLed = false;
const unsigned long HEARTBEAT_MS = 1000;
unsigned long lastHeartbeat = 0;

// PWM configuration
const bool ENABLE_LED_PWM = true;
const int LEDC_CHANNEL = 0;
const int LEDC_FREQ_HZ = 5000;
const int LEDC_RES_BITS = 12; // 0-4095

// ADC / voltage divider configuration
const int ADC_MAX = 4095;
const float VREF = 3.3f;
const float SERIES_RESISTOR_OHMS = 10000.0f;

// Ultrasonic timing
const unsigned long ULTRASONIC_TIMEOUT_US = 25000; // ~4m max range

// Ultrasonic -> LED mapping
const float ULTRASONIC_CLOSE_CM = 30.0f;     // closer than this = full brightness
const float ULTRASONIC_FAR_CM = 180.0f;      // farther than this = dim flicker
const float ULTRASONIC_DIM_NORM = 0.02f;     // baseline dim level (very dim)
const float ULTRASONIC_FLICKER_MIN = 0.01f;  // flicker low (barely visible)
const float ULTRASONIC_FLICKER_MAX = 0.04f;  // flicker high (still dim)
const unsigned long ULTRASONIC_FLICKER_MS = 300;  // slower flicker when idle
const float ULTRASONIC_EMA_ALPHA = 0.2f;     // smoothing for LED control

// Idle timeout when close
const unsigned long CLOSE_IDLE_TIMEOUT_MS = 30000;  // 30 seconds
const float MOVEMENT_THRESHOLD_CM = 3.0f;    // movement threshold to wake up

// Proximity sensor calibration (adjust for your sensor)
const int PROX_MIN = 400;       // value when far
const int PROX_MAX = 3000;      // value when close
const bool PROX_INVERT = false; // set true if close reads lower

// Smoothing - balanced: filters noise while maintaining responsiveness
const float EMA_ALPHA = 0.45f; // lower = more smoothing, higher = more responsive

// Timing
const unsigned long UPDATE_MS = 20;  // Faster sensor reading
const unsigned long SERIAL_INTERVAL_MS = 50;  // Faster data transmission

float proxFiltered = 0.0f;
float rubberFiltered = 0.0f;
float fabricFiltered = 0.0f;
float ultrasonicFiltered = -1.0f;

// Median filter for rubber (rejects ADC spikes) - small window for fast response
const int MEDIAN_SIZE = 3;
float rubberHistory[MEDIAN_SIZE] = {0};
int rubberHistoryIdx = 0;

float getMedian(float* arr, int size) {
  float sorted[MEDIAN_SIZE];
  for (int i = 0; i < size; i++) sorted[i] = arr[i];
  // Simple bubble sort for small array
  for (int i = 0; i < size - 1; i++) {
    for (int j = 0; j < size - i - 1; j++) {
      if (sorted[j] > sorted[j + 1]) {
        float tmp = sorted[j];
        sorted[j] = sorted[j + 1];
        sorted[j + 1] = tmp;
      }
    }
  }
  return sorted[size / 2];
}
float ultrasonicPrev = -1.0f;     // previous reading for movement detection
unsigned long closeStartMs = 0;   // when object first got close
bool isCloseIdle = false;         // true if close for > 30s without movement
unsigned long lastMovementMs = 0; // last time movement was detected
unsigned long lastUpdate = 0;
unsigned long lastSerial = 0;

static float clamp01(float v) {
  if (v < 0.0f)
    return 0.0f;
  if (v > 1.0f)
    return 1.0f;
  return v;
}

static float adcToVoltage(int adc) {
  return (float(adc) / float(ADC_MAX)) * VREF;
}

static float adcToResistance(int adc) {
  if (adc <= 0 || adc >= ADC_MAX) {
    return NAN;
  }
  return SERIES_RESISTOR_OHMS * (float(adc) / float(ADC_MAX - adc));
}

// Flicker with adjustable intensity (0=idle dim, 1=bright flicker)
static float flickerLevel(unsigned long nowMs, float intensity, unsigned long periodMs) {
  const float phase = (nowMs % periodMs) / float(periodMs);
  const float wave = 0.5f * (1.0f + sinf(6.283185f * phase));
  
  // Idle (intensity=0): very dim flicker between 0.01 and 0.04
  // Active (intensity=1): brighter flicker between 0.15 and 0.5
  const float minLow = ULTRASONIC_FLICKER_MIN;   // 0.01
  const float maxLow = ULTRASONIC_FLICKER_MAX;   // 0.04
  const float minHigh = 0.15f;
  const float maxHigh = 0.50f;
  
  const float flickMin = minLow + intensity * (minHigh - minLow);
  const float flickMax = maxLow + intensity * (maxHigh - maxLow);
  
  return flickMin + (flickMax - flickMin) * wave;
}

void setup() {
  if (ENABLE_SERIAL_INIT && TELEMETRY_USB) {
    Serial.begin(115200);
  }
  if (ENABLE_SERIAL_INIT && TELEMETRY_UART) {
    TelemetrySerial.begin(UART_BAUD, SERIAL_8N1, UART_RX_PIN, UART_TX_PIN);
  }
  delay(500);
  if (ENABLE_SERIAL_INIT && TELEMETRY_USB) {
    Serial.printf("{\"reset_reason\":%d}\n", (int)esp_reset_reason());
  }
  if (ENABLE_SERIAL_INIT && TELEMETRY_UART) {
    TelemetrySerial.printf("{\"reset_reason\":%d}\n", (int)esp_reset_reason());
  }

  pinMode(LED_BUILTIN, OUTPUT);

  // PWM setup
  if (ENABLE_LED_PWM) {
    ledcSetup(LEDC_CHANNEL, LEDC_FREQ_HZ, LEDC_RES_BITS);
    ledcAttachPin(LED_PWM_PIN, LEDC_CHANNEL);
  }

  // ADC setup
  if (ENABLE_ADC) {
    analogReadResolution(12);
    analogSetPinAttenuation(PROX_PIN, ADC_11db);
    analogSetPinAttenuation(RUBBER_PIN, ADC_11db);
    analogSetPinAttenuation(FABRIC_PIN, ADC_11db);
  }

  // Ultrasonic pins
  if (ENABLE_ULTRASONIC) {
    pinMode(ULTRASONIC_TRIG_PIN, OUTPUT);
    pinMode(ULTRASONIC_ECHO_PIN, INPUT);
    digitalWrite(ULTRASONIC_TRIG_PIN, LOW);
  }

  // Initialize filter with first read
  if (ENABLE_ADC) {
    proxFiltered = analogRead(PROX_PIN);
  }

}

void loop() {
  const unsigned long now = millis();
  if (UART_ECHO_TEST) {
    if (TelemetrySerial.available() > 0) {
      while (TelemetrySerial.available() > 0) {
        int ch = TelemetrySerial.read();
        TelemetrySerial.write(ch);
      }
      safeLed = !safeLed;
      digitalWrite(LED_BUILTIN, safeLed ? HIGH : LOW);
    }
    if (now - lastHeartbeat >= HEARTBEAT_MS) {
      lastHeartbeat = now;
      TelemetrySerial.println("{\"uart\":\"alive\"}");
    }
    return;
  }
  if (SAFE_MODE) {
    if (now - lastSafe >= SAFE_INTERVAL_MS) {
      lastSafe = now;
      safeLed = !safeLed;
      digitalWrite(LED_BUILTIN, safeLed ? HIGH : LOW);

      String payload = "{";
      payload += "\"ts_ms\":" + String(now) + ",";
      payload += "\"mode\":\"safe\"";
      payload += "}";

      if (ENABLE_SERIAL_INIT && TELEMETRY_USB) {
        Serial.println(payload);
      }
      if (ENABLE_SERIAL_INIT && TELEMETRY_UART) {
        TelemetrySerial.println(payload);
      }
    }
    return;
  }
  if (now - lastUpdate < UPDATE_MS) {
    delay(2);
    return;
  }
  lastUpdate = now;

  int proxRaw = 0;
  int rubberRaw = 0;
  int fabricRaw = 0;
  if (ENABLE_ADC) {
    proxRaw = analogRead(PROX_PIN);
    rubberRaw = analogRead(RUBBER_PIN);
    fabricRaw = analogRead(FABRIC_PIN);
  }

  // Ultrasonic read (HC-SR04 style)
  unsigned long echoUs = 0;
  if (ENABLE_ULTRASONIC) {
    digitalWrite(ULTRASONIC_TRIG_PIN, LOW);
    delayMicroseconds(2);
    digitalWrite(ULTRASONIC_TRIG_PIN, HIGH);
    delayMicroseconds(10);
    digitalWrite(ULTRASONIC_TRIG_PIN, LOW);

    echoUs = pulseIn(ULTRASONIC_ECHO_PIN, HIGH, ULTRASONIC_TIMEOUT_US);
  }
  float ultrasonicCm = -1.0f;
  if (echoUs > 0) {
    ultrasonicCm = echoUs / 58.0f; // round-trip time to cm
  }

  if (ENABLE_ADC) {
    proxFiltered = (EMA_ALPHA * proxRaw) + ((1.0f - EMA_ALPHA) * proxFiltered);
    
    // Apply median + EMA filter to rubber sensor (reject ADC spikes)
    rubberHistory[rubberHistoryIdx] = (float)rubberRaw;
    rubberHistoryIdx = (rubberHistoryIdx + 1) % MEDIAN_SIZE;
    float rubberMedian = getMedian(rubberHistory, MEDIAN_SIZE);
    rubberFiltered = (EMA_ALPHA * rubberMedian) + ((1.0f - EMA_ALPHA) * rubberFiltered);
    
    // Apply EMA to fabric sensor
    fabricFiltered = (EMA_ALPHA * fabricRaw) + ((1.0f - EMA_ALPHA) * fabricFiltered);
  }

  float proxNorm = 0.0f;
  if (ENABLE_ADC && PROX_MAX != PROX_MIN) {
    proxNorm = (proxFiltered - PROX_MIN) / float(PROX_MAX - PROX_MIN);
  }
  if (ENABLE_ADC && PROX_INVERT) {
    proxNorm = 1.0f - proxNorm;
  }
  if (ENABLE_ADC) {
    proxNorm = clamp01(proxNorm);
  }

  if (ENABLE_ULTRASONIC && ultrasonicCm > 0.0f) {
    if (ultrasonicFiltered < 0.0f) {
      ultrasonicFiltered = ultrasonicCm;
    } else {
      ultrasonicFiltered =
          (ULTRASONIC_EMA_ALPHA * ultrasonicCm) +
          ((1.0f - ULTRASONIC_EMA_ALPHA) * ultrasonicFiltered);
    }
  }

  float ledNorm = 0.0f;
  const char *ledMode = "off";
  // Detect movement (significant change in distance)
  bool isMoving = false;
  if (ultrasonicPrev > 0.0f && ultrasonicFiltered > 0.0f) {
    float delta = fabsf(ultrasonicFiltered - ultrasonicPrev);
    if (delta > MOVEMENT_THRESHOLD_CM) {
      isMoving = true;
      lastMovementMs = now;
    }
  }
  ultrasonicPrev = ultrasonicFiltered;
  
  // Track close/idle state
  bool isClose = (ultrasonicFiltered > 0.0f && ultrasonicFiltered <= ULTRASONIC_CLOSE_CM);
  
  if (isClose) {
    if (closeStartMs == 0) {
      // Just got close
      closeStartMs = now;
      isCloseIdle = false;
    } else if (!isCloseIdle && (now - closeStartMs > CLOSE_IDLE_TIMEOUT_MS)) {
      // Been close for > 30 seconds without significant movement
      if (now - lastMovementMs > CLOSE_IDLE_TIMEOUT_MS) {
        isCloseIdle = true;
      }
    }
    // Wake up if movement detected while idle
    if (isCloseIdle && isMoving) {
      isCloseIdle = false;
      closeStartMs = now;
    }
  } else {
    // Not close - reset idle tracking
    closeStartMs = 0;
    isCloseIdle = false;
  }
  
  // LED behavior based on distance and idle state
  if (ENABLE_ULTRASONIC && ultrasonicFiltered > 0.0f) {
    if (isCloseIdle) {
      // Close but idle for 30+ seconds: LED OFF completely
      ledNorm = 0.0f;
      ledMode = "idle_off";
    } else if (ultrasonicFiltered <= ULTRASONIC_CLOSE_CM) {
      // Close and active: full brightness, no flicker
      ledNorm = 1.0f;
      ledMode = "bright";
    } else {
      // In between: brightness and flicker intensity scale with distance
      const float span = ULTRASONIC_FAR_CM - ULTRASONIC_CLOSE_CM;
      float t = (ultrasonicFiltered - ULTRASONIC_CLOSE_CM) / span;
      t = clamp01(t);
      
      // t=0 means close (bright, fast flicker), t=1 means far (dim, slow flicker)
      // Flicker period: faster when closer (100ms), slower when far (400ms)
      unsigned long flickerPeriod = (unsigned long)(100 + t * 300);
      
      // Intensity: 1.0 when close, 0.0 when far
      float intensity = 1.0f - t;
      
      // Base brightness also scales: 1.0 when close, 0.02 when far
      float baseBrightness = (1.0f - t) * 1.0f + t * ULTRASONIC_DIM_NORM;
      
      // Blend between base brightness and flicker based on distance
      // Close: mostly base brightness, Far: mostly flicker
      float flicker = flickerLevel(now, intensity, flickerPeriod);
      ledNorm = (1.0f - t) * baseBrightness + t * flicker;
      
      ledMode = "approach";
    }
  } else {
    // No valid reading: very dim flicker
    ledNorm = flickerLevel(now, 0.0f, 300);
    ledMode = "no_signal";
  }

  const uint32_t maxDuty = (1U << LEDC_RES_BITS) - 1;
  const uint32_t duty = uint32_t(ledNorm * maxDuty);
  if (ENABLE_LED_PWM) {
    ledcWrite(LEDC_CHANNEL, duty);
  }

  if (now - lastSerial >= SERIAL_INTERVAL_MS) {
    lastSerial = now;
    // Use filtered values for voltage (reduces ADC noise spikes)
    const float rubberV = adcToVoltage((int)rubberFiltered);
    const float fabricV = adcToVoltage((int)fabricFiltered);
    const float rubberOhms = adcToResistance((int)rubberFiltered);
    const float fabricOhms = adcToResistance((int)fabricFiltered);

    String payload = "{";
    payload += "\"ts_ms\":" + String(now) + ",";
    payload += "\"rubber_adc\":" + String(rubberRaw) + ",";
    payload += "\"rubber_v\":" + String(rubberV, 3) + ",";
    payload += "\"rubber_ohms\":" + String(rubberOhms, 1) + ",";
    payload += "\"fabric_adc\":" + String(fabricRaw) + ",";
    payload += "\"fabric_v\":" + String(fabricV, 3) + ",";
    payload += "\"fabric_ohms\":" + String(fabricOhms, 1) + ",";
    payload += "\"ultrasonic_us\":" + String(echoUs) + ",";
    payload += "\"ultrasonic_cm\":" + String(ultrasonicCm, 1) + ",";
    payload += "\"led_duty\":" + String(duty) + ",";
    payload += "\"led_pwm_norm\":" + String(ledNorm, 3) + ",";
    payload += "\"led_mode\":\"" + String(ledMode) + "\",";
    payload += "\"prox_raw\":" + String(proxRaw) + ",";
    payload += "\"prox_norm\":" + String(proxNorm, 3);
    payload += "}";

    if (ENABLE_SERIAL_INIT && TELEMETRY_USB) {
      Serial.println(payload);
    }
    if (ENABLE_SERIAL_INIT && TELEMETRY_UART) {
      TelemetrySerial.println(payload);
    }
  }

  if (!ENABLE_SERIAL_INIT && now - lastHeartbeat >= HEARTBEAT_MS) {
    lastHeartbeat = now;
    safeLed = !safeLed;
    digitalWrite(LED_BUILTIN, safeLed ? HIGH : LOW);
  }
}
