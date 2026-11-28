// One generic VL53L0X carrier bench probe on the EXISTING 0x70 TCA9548A.
// Not the cliff safety firmware. MOTOR POWER MUST BE PHYSICALLY DISCONNECTED.
// Only a correctly verified 3.3V SDA/SCL carrier and one sensor on mux CH0.
// Reuse: https://github.com/pololu/vl53l0x-arduino (ST API adaptation).
#include <Arduino.h>
#include <Wire.h>
#include <VL53L0X.h>
#include "BodyPins.h"
#include "TofTransactions.h"
#include "../lib/TofBus/TofResult.h"

#if !DESK_ROBOT_STEPPER
#error Ranging bench must neutralize the entire eight-phase actuator harness
#endif

namespace {
constexpr uint8_t kMux = 0x70;
constexpr uint8_t kOptionalMux = 0x71;
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
bool optional_mux_present = false;
uint32_t last_report_ms = 0;

bool bus_idle() {
  return digitalRead(body_pins::kSensorSda) == HIGH &&
      digitalRead(body_pins::kSensorScl) == HIGH;
}

void hold_low(int pin) {
  digitalWrite(pin, LOW);
  pinMode(pin, OUTPUT);
}

bool quiesce_optional_mux() {
  return bus_idle() && (!optional_mux_present ||
      desk_robot::checked_mux_mask(Wire, kOptionalMux, 0, bus_idle));
}

bool select_sensor() {
  return quiesce_optional_mux() && desk_robot::checked_mux_mask(
      Wire, kMux, 1U << kSensorChannel, bus_idle);
}

void fault(const char* message) {
  ready = false;
  Serial.println(message);
  // No RESET GPIO exists on this harness. Isolate reachable lanes, but
  // never transact on held lines or resume sampling after a transport fault.
  if (bus_idle()) (void)quiesce_optional_mux();
  if (bus_idle()) (void)desk_robot::checked_mux_mask(Wire, kMux, 0, bus_idle);
}

void report(uint32_t now, uint16_t mm, bool valid) {
  Serial.printf("t_ms=%lu range_mm=%u valid=%u timeout=%u\n",
                static_cast<unsigned long>(now), static_cast<unsigned>(mm),
                valid ? 1U : 0U, 0U);
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
  Wire.setTimeOut(10);
  if (!bus_idle()) {
    fault("FAIL i2c_held_lines");
    return;
  }
  Wire.beginTransmission(kOptionalMux);
  optional_mux_present = Wire.endTransmission(true) == 0;
  if (!select_sensor()) {
    fault("FAIL mux0x70_ch0_select_or_readback");
    return;
  }
  sensor.setBus(&Wire);
  sensor.setTimeout(80);
  if (!sensor.init() || sensor.timeoutOccurred() || sensor.last_status != 0 || !bus_idle()) {
    fault("FAIL vl53l0x_init_or_absent");
    return;
  }
  if (!sensor.setMeasurementTimingBudget(33000) || sensor.last_status != 0 || !bus_idle()) {
    fault("FAIL vl53l0x_timing_budget");
    return;
  }
  sensor.startContinuous();
  if (sensor.last_status != 0 || sensor.timeoutOccurred() || !bus_idle() ||
      !quiesce_optional_mux() || !desk_robot::checked_mux_mask(Wire, kMux, 0, bus_idle)) {
    fault("FAIL vl53l0x_start_or_isolation");
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
    fault("FAIL mux_select_or_readback; sampling_latched_off");
    return;
  }
  uint8_t status = 0;
  if (!desk_robot::read_tof_register(Wire, 0x13, &status, 1) || !bus_idle()) {
    fault("FAIL ranging_io; sampling_latched_off");
    return;
  }
  if ((status & 0x18U) != 0) {
    report(now, 0, false);
    if (!desk_robot::write_tof_byte(Wire, 0x0B, 0x01) || !bus_idle())
      fault("FAIL ranging_io; sampling_latched_off");
    return;
  }
  // Not ready is not a new reading; never renew cached sample evidence.
  if ((status & 0x07U) == 0) return;
  uint8_t raw[12]{};
  if (!desk_robot::read_tof_register(Wire, 0x14, raw, sizeof(raw)) || !bus_idle() ||
      !desk_robot::write_tof_byte(Wire, 0x0B, 0x01) || !bus_idle()) {
    fault("FAIL ranging_io; sampling_latched_off");
    return;
  }
  const auto result = desk_robot::decode_tof_result(raw);
  report(now, result.distance_mm, result.accepted);
  // These are raw measurements, NOT sufficient evidence of safe cliff stops.
}
