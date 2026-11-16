// One generic VL53L0X carrier bench probe on the EXISTING 0x70 TCA9548A.
// Not the cliff safety firmware. MOTOR POWER MUST BE PHYSICALLY DISCONNECTED.
// Only a correctly verified 3.3V SDA/SCL carrier and one sensor on mux CH0.
// Reuse: https://github.com/pololu/vl53l0x-arduino (ST API adaptation).
#include <Arduino.h>
#include <Wire.h>
#include <VL53L0X.h>

namespace {
constexpr uint8_t kMux = 0x70;
constexpr uint8_t kSensorChannel = 0;
constexpr uint32_t kReportEveryMs = 120;
constexpr int kActuatorPins[] = {
    13, 14, 25, 26, 27, 32, 33, 23, 18, 19};
VL53L0X sensor;
bool ready = false;
uint32_t last_report_ms = 0;

bool select_sensor() {
  Wire.beginTransmission(kMux);
  if (Wire.write(static_cast<uint8_t>(1U << kSensorChannel)) != 1 ||
      Wire.endTransmission(true) != 0)
    return false;
  if (Wire.requestFrom(kMux, static_cast<size_t>(1), true) != 1 ||
      Wire.available() < 1)
    return false;
  return Wire.read() == (1U << kSensorChannel);
}
}

void setup() {
  // No commands in this sketch can authorize or drive the body. On a shared
  // assembly, disconnect stepper/servo power BEFORE flashing this bench target.
  for (int pin : kActuatorPins) {
    digitalWrite(pin, LOW);
    pinMode(pin, OUTPUT);
  }
  Serial.begin(115200);
  Serial.println("BENCH_ONLY VL53L0X; motors physically disconnected; no cliff permission");
  Wire.begin(21, 22, 400000);
  Wire.setTimeOut(15);
  if (!select_sensor()) {
    Serial.println("FAIL mux0x70_ch0_select_or_readback");
    return;
  }
  sensor.setBus(&Wire);
  sensor.setTimeout(80); // Pololu timeout is bounded; BENCH ONLY.
  if (!sensor.init()) {
    Serial.println("FAIL vl53l0x_init_or_absent");
    return;
  }
  if (!sensor.setMeasurementTimingBudget(33000)) {
    Serial.println("FAIL vl53l0x_timing_budget");
    return;
  }
  sensor.startContinuous();
  ready = true;
  Serial.println("READY log real desk readings at 30, 40, 50, 60 mm");
}

void loop() {
  if (!ready) {
    delay(200);
    return;
  }
  const uint32_t now = millis();
  if (now - last_report_ms < kReportEveryMs) return;
  last_report_ms = now;
  if (!select_sensor()) {
    ready = false; // Do not treat a previous sample as newly valid.
    Serial.println("FAIL mux_select_or_readback; sampling_latched_off");
    return;
  }
  const uint16_t mm = sensor.readRangeContinuousMillimeters();
  const bool timed_out = sensor.timeoutOccurred();
  const bool valid = !timed_out && mm != 65535U && mm != 0U;
  Serial.printf("t_ms=%lu range_mm=%u valid=%u timeout=%u\n",
                static_cast<unsigned long>(now), static_cast<unsigned>(mm),
                valid ? 1U : 0U, timed_out ? 1U : 0U);
  // These are raw measurements, NOT sufficient evidence of safe cliff stops.
}
