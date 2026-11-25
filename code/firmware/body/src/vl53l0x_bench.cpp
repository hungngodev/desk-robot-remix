// One generic VL53L0X carrier bench probe on the EXISTING 0x70 TCA9548A.
// Not the cliff safety firmware. MOTOR POWER MUST BE PHYSICALLY DISCONNECTED.
// Only a correctly verified 3.3V SDA/SCL carrier and one sensor on mux CH0.
// Reuse: https://github.com/pololu/vl53l0x-arduino (ST API adaptation).
#include <Arduino.h>
#include <Wire.h>
#include <VL53L0X.h>
#include "BodyPins.h"

#if !DESK_ROBOT_STEPPER
#error Ranging bench must neutralize the entire eight-phase actuator harness
#endif

namespace {
constexpr uint8_t kMux = 0x70;
constexpr uint8_t kSensorChannel = 0;
constexpr uint32_t kReportEveryMs = 120;
// The stepper harness is the superset of both drive alternatives. If the
// DC mapping ever changes, refuse to compile an incomplete bench shutdown.
constexpr bool covers_motor_pin(int pin, unsigned i = 0) {
  return i < body_pins::count(body_pins::kMotorPins) &&
      (body_pins::kMotorPins[i] == pin || covers_motor_pin(pin, i + 1));
}
static_assert(covers_motor_pin(body_pins::kLeftIn1) &&
              covers_motor_pin(body_pins::kLeftIn2) &&
              covers_motor_pin(body_pins::kRightIn1) &&
              covers_motor_pin(body_pins::kRightIn2),
              "Ranging bench must hold both motor harness alternatives low");
VL53L0X sensor;
bool ready = false;
uint32_t last_report_ms = 0;

bool bus_idle() {
  return digitalRead(body_pins::kSensorSda) == HIGH &&
      digitalRead(body_pins::kSensorScl) == HIGH;
}

void hold_low(int pin) {
  digitalWrite(pin, LOW);
  pinMode(pin, OUTPUT);
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
  for (int pin : body_pins::kMotorPins) hold_low(pin);
  for (int pin : body_pins::kServoPins) hold_low(pin);
  Serial.begin(115200);
  Serial.println("BENCH_ONLY VL53L0X; motors physically disconnected; no cliff permission");
  if (!Wire.begin(body_pins::kSensorSda, body_pins::kSensorScl, 400000)) {
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
