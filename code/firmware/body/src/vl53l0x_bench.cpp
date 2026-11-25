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

bool bus_idle() {
  return digitalRead(21) == HIGH && digitalRead(22) == HIGH;
}

bool select_sensor() {
  if (!bus_idle()) return false;
  Wire.beginTransmission(kMux);
  // Always terminate a started transmission, including short writes.
  const bool wrote = Wire.write(static_cast<uint8_t>(1U << kSensorChannel)) == 1;
  const bool acknowledged = Wire.endTransmission(true) == 0;
  if (!wrote || !acknowledged || !bus_idle()) return false;
  if (Wire.requestFrom(kMux, static_cast<size_t>(1), true) != 1 ||
      Wire.available() < 1)
    return false;
  return Wire.read() == (1U << kSensorChannel) && bus_idle();
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
  if (!Wire.begin(21, 22, 400000)) {
    Serial.println("FAIL i2c_begin");
    return;
  }
  Wire.setTimeOut(15);
  if (!select_sensor()) {
    Serial.println("FAIL mux0x70_ch0_select_or_readback");
    return;
  }
  sensor.setBus(&Wire);
  sensor.setTimeout(80); // Pololu timeout is bounded; BENCH ONLY.
  if (!sensor.init() || sensor.timeoutOccurred() || sensor.last_status != 0 || !bus_idle()) {
    Serial.println("FAIL vl53l0x_init_or_absent");
    return;
  }
  if (!sensor.setMeasurementTimingBudget(33000) || sensor.last_status != 0 || !bus_idle()) {
    Serial.println("FAIL vl53l0x_timing_budget");
    return;
  }
  sensor.startContinuous();
  if (sensor.last_status != 0 || sensor.timeoutOccurred() || !bus_idle()) {
    Serial.println("FAIL vl53l0x_start");
    return;
  }
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
  const bool bus_ok = sensor.last_status == 0 && bus_idle();
  const bool valid = !timed_out && bus_ok && mm >= 30U && mm <= 1300U;
  if (timed_out || !bus_ok) ready = false;
  Serial.printf("t_ms=%lu range_mm=%u valid=%u timeout=%u\n",
                static_cast<unsigned long>(now), static_cast<unsigned>(mm),
                valid ? 1U : 0U, timed_out ? 1U : 0U);
  if (!ready) Serial.println("FAIL ranging_io; sampling_latched_off");
  // These are raw measurements, NOT sufficient evidence of safe cliff stops.
}
