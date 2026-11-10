#include <Arduino.h>

#include "BodyControl.h"
#include "BodyPins.h"
#if DESK_ROBOT_STEPPER
#include "CliffGuard.h"
#include "BerryImu.h"
#include "StepperDrive.h"
#include "TofBus.h"
#include <Preferences.h>
#endif

namespace {
#if DESK_ROBOT_STEPPER
// No fabricated calibration or sample source. Until sensor I/O and measured
// calibration are supplied, every arm request is rejected by this guard.
desk_robot::CliffGuard cliff_guard;
desk_robot::BodyControl control(desk_robot::BodyProfile::StepperGuarded, &cliff_guard);
desk_robot::StepperDrive left_stepper;
desk_robot::StepperDrive right_stepper;
desk_robot::TofBus tof;
desk_robot::BerryImu berry_imu;  // Shares upstream Wire and existing identity probe
// AT42QT1010 owns the input threshold. Sample without internal pullups
// (GPIO34 is input-only), debounce three equal 25ms samples, and retain
// an edge counter so the Mac can detect short taps between status polls.
bool touch_stable = false;
bool touch_candidate = false;
std::uint8_t touch_candidate_samples = 0;
std::uint32_t touch_last_sample_ms = 0;

void poll_touch(std::uint32_t now_ms) {
  if (now_ms - touch_last_sample_ms < 25) return;
  touch_last_sample_ms = now_ms;
  const bool active = digitalRead(body_pins::kTouchOutput) == HIGH;
  // One raw active sample stops the body in this same WROOM loop. Gesture
  // counters still require three matching samples, so contact noise may
  // conservatively stop the robot but cannot fake a counted tap/hold.
  control.sample_touch_input(active);
  if (active != touch_candidate) {
    touch_candidate = active;
    touch_candidate_samples = 1;
  } else if (touch_candidate_samples < 3) {
    ++touch_candidate_samples;
  }
  if (touch_candidate_samples >= 3 && touch_candidate != touch_stable) {
    touch_stable = touch_candidate;
    control.set_touch(touch_stable, now_ms);
  }
}

// Nonvolatile calibration is written only by a completed local USB commit.
// The hardware never resumes movement after reboot, even with valid stored
// thresholds: CliffGuard starts MissingSample and requires local USB rearm.
struct StoredCalibration {
  std::uint32_t magic;
  std::uint32_t version;
  desk_robot::CliffConfig config;
  std::uint32_t checksum;
};
constexpr std::uint32_t kCalibrationMagic = 0x434C4635U; // "CLF5"
constexpr std::uint32_t kCalibrationVersion = 1U;

std::uint32_t calibration_checksum(const desk_robot::CliffConfig& c) {
  std::uint32_t value = 2166136261U;
  auto byte = [&value](std::uint8_t n) { value = (value ^ n) * 16777619U; };
  auto halfword = [&byte](std::uint16_t n) {
    byte(static_cast<std::uint8_t>(n));
    byte(static_cast<std::uint8_t>(n >> 8));
  };
  byte(c.calibrated ? 1U : 0U);
  for (const auto& interval : c.floor) {
    halfword(interval.min_mm);
    halfword(interval.max_mm);
  }
  halfword(c.front_obstacle_mm);
  halfword(c.front_max_mm);
  for (unsigned bits = 0; bits < 32; bits += 8) {
    byte(static_cast<std::uint8_t>(c.freshness_ms >> bits));
  }
  return value;
}

bool load_calibration() {
  Preferences preferences;
  if (!preferences.begin("cliffsafety", true)) return false;
  const bool right_length =
      preferences.getBytesLength("calibration") == sizeof(StoredCalibration);
  StoredCalibration saved{};
  const size_t read = right_length
      ? preferences.getBytes("calibration", &saved, sizeof(saved)) : 0;
  preferences.end();
  if (read != sizeof(saved) ||
      saved.magic != kCalibrationMagic ||
      saved.version != kCalibrationVersion ||
      saved.checksum != calibration_checksum(saved.config)) return false;
  return cliff_guard.configure(saved.config);
}

bool save_calibration() {
  if (!cliff_guard.configured()) return false;
  StoredCalibration saved{};
  saved.magic = kCalibrationMagic;
  saved.version = kCalibrationVersion;
  saved.config = cliff_guard.configuration();
  saved.checksum = calibration_checksum(saved.config);
  Preferences preferences;
  if (!preferences.begin("cliffsafety", false)) return false;
  const size_t written =
      preferences.putBytes("calibration", &saved, sizeof(saved));
  preferences.end();
  return written == sizeof(saved);
}
#else
desk_robot::BodyControl control;
#endif
// Recovery is deliberately unavailable on the head UART or network bridge.
desk_robot::LineReceiver usb_receiver(true);
desk_robot::LineReceiver head_receiver;
HardwareSerial head_uart(2);
bool pwm_ready = false;
bool servo_attached = false;
#if !DESK_ROBOT_STEPPER
int applied_left = 0;
int applied_right = 0;
#endif
int applied_lift = -1;
int applied_grip = -1;

void all_motor_inputs_low() {
  for (int pin : body_pins::kMotorPins) {
    pinMode(pin, OUTPUT);
    digitalWrite(pin, LOW);
  }
}

void zero_motor_pwm() {
#if DESK_ROBOT_STEPPER
  // Clear all phase inputs; coast is an unqualified conservative power default.
  for (int pin : body_pins::kMotorPins) digitalWrite(pin, LOW);
#else
  for (int channel : body_pins::kMotorChannels) ledcWrite(channel, 0);
#endif
}

#if !DESK_ROBOT_STEPPER
void write_motor_pair(int forward_channel, int reverse_channel, int percent) {
  // Zero inactive side first; neither direction is driven during a reversal.
  const unsigned duty = static_cast<unsigned>(abs(percent) * 255 / 100);
  if (percent > 0) {
    ledcWrite(reverse_channel, 0);
    ledcWrite(forward_channel, duty);
  } else {
    ledcWrite(forward_channel, 0);
    ledcWrite(reverse_channel, percent < 0 ? duty : 0);
  }
}
#else
void write_stepper(const int (&pins)[4], std::uint8_t mask) {
  // Remove inactive coils before enabling the next phase. No blocking step call.
  for (int phase = 0; phase < 4; ++phase)
    if ((mask & (1U << phase)) == 0) digitalWrite(pins[phase], LOW);
  for (int phase = 0; phase < 4; ++phase)
    if ((mask & (1U << phase)) != 0) digitalWrite(pins[phase], HIGH);
}
#endif

unsigned servo_duty(int degrees) {
  const unsigned pulse_us = body_pins::kServoMinUs +
      degrees * (body_pins::kServoMaxUs - body_pins::kServoMinUs) / 180;
  return pulse_us * 65535UL / 20000UL;
}

void apply_outputs() {
  // All output paths, including commands received on either UART, recheck the
  // local interlock/timers immediately before writing the physical pins.
  control.tick(millis());
  if (!pwm_ready) {
    control.force_disarm();
    zero_motor_pwm();
    return;
  }
  const auto& state = control.state();
#if DESK_ROBOT_STEPPER
  const std::uint32_t now_us = micros();
  write_stepper(body_pins::kLeftStepperPins,
                left_stepper.update(now_us, state.left, state.armed));
  write_stepper(body_pins::kRightStepperPins,
                right_stepper.update(now_us, state.right, state.armed));
#else
  if ((applied_left > 0 && state.left < 0) ||
      (applied_left < 0 && state.left > 0) ||
      (applied_right > 0 && state.right < 0) ||
      (applied_right < 0 && state.right > 0)) {
    zero_motor_pwm();
    delayMicroseconds(100);  // short dead-time before reversing polarity
  }
  write_motor_pair(0, 1, state.left);
  write_motor_pair(2, 3, state.right);
  applied_left = state.left;
  applied_right = state.right;
#endif
  if (state.servos_attached && !servo_attached) {
    // Program duty before attaching: never emit a default zero-width command.
    ledcWrite(4, servo_duty(state.lift));
    ledcWrite(5, servo_duty(state.grip));
    ledcAttachPin(body_pins::kLiftServo, 4);
    ledcAttachPin(body_pins::kGripServo, 5);
    servo_attached = true;
    applied_lift = state.lift;
    applied_grip = state.grip;
  } else if (!state.servos_attached && servo_attached) {
    for (int pin : body_pins::kServoPins) {
      ledcDetachPin(pin);
      pinMode(pin, OUTPUT);
      digitalWrite(pin, LOW);
    }
    servo_attached = false;
    applied_lift = -1;
    applied_grip = -1;
  }
  if (servo_attached && state.lift != applied_lift) {
    ledcWrite(4, servo_duty(state.lift));
    applied_lift = state.lift;
  }
  if (servo_attached && state.grip != applied_grip) {
    ledcWrite(5, servo_duty(state.grip));
    applied_grip = state.grip;
  }
}

void process_input(Stream& stream, desk_robot::LineReceiver& receiver, bool local_usb) {
  char reply[desk_robot::kReplyCapacity]{};
  // Bounded read prevents sustained input from starving the other port/timers.
  for (int bytes = 0; bytes < 64 && stream.available() > 0; ++bytes) {
    const bool completed = receiver.feed(static_cast<char>(stream.read()),
                                          millis(), control, reply, sizeof(reply));
    if (completed && !pwm_ready && strcmp(reply, "OK arm") == 0) {
      control.force_disarm();
      snprintf(reply, sizeof(reply), "ERR arm pwm_unavailable");
    }
#if DESK_ROBOT_STEPPER
    if (completed && local_usb && strcmp(reply, "OK calcommit") == 0 &&
        !save_calibration()) {
      // A partially written or unavailable NVS record cannot silently allow
      // operation on a calibration that would disappear next boot.
      cliff_guard.configure(desk_robot::CliffConfig{});
      control.force_disarm();
      snprintf(reply, sizeof(reply), "ERR calcommit nvs_write_failed");
    }
#else
    (void)local_usb;
#endif
    apply_outputs();  // apply accepted command/expired timer before acknowledging
    if (completed) {
      stream.print(reply);
      stream.print("\r\n");
    }
  }
}
}  // namespace

void setup() {
  // The first hardware action disables every motor/phase input, before UART.
  all_motor_inputs_low();
#if DESK_ROBOT_STEPPER
  // The touch breakout OUT is actively driven and powered at 3.3V.
  // GPIO34 has no internal pullup; do not leave it floating when fitted.
  pinMode(body_pins::kTouchOutput, INPUT);
#endif
  for (int pin : body_pins::kServoPins) {
    pinMode(pin, OUTPUT);
    digitalWrite(pin, LOW);
  }
  pwm_ready = true;
#if !DESK_ROBOT_STEPPER
  for (int i = 0; i < 4; ++i) {
    if (ledcSetup(body_pins::kMotorChannels[i], body_pins::kMotorFrequency,
                  body_pins::kMotorResolution) == 0) pwm_ready = false;
    ledcWrite(body_pins::kMotorChannels[i], 0);
    ledcAttachPin(body_pins::kMotorPins[i], body_pins::kMotorChannels[i]);
  }
#endif
  for (int channel : body_pins::kServoChannels) {
    if (ledcSetup(channel, body_pins::kServoFrequency,
                  body_pins::kServoResolution) == 0) pwm_ready = false;
    ledcWrite(channel, 0);
  }
  zero_motor_pwm();
  Serial.begin(115200);
  head_uart.begin(115200, SERIAL_8N1, body_pins::kUartRx, body_pins::kUartTx);
#if DESK_ROBOT_STEPPER
  // Keep motors and servos de-energized through all five device inits.
  // No accepted calibration is embedded in this image. A local calibration
  // commit and a fresh manual USB rearm are required before any arm can pass.
  if (!tof.begin(body_pins::kSensorSda, body_pins::kSensorScl,
                 body_pins::kMuxReset)) {
    cliff_guard.bus_fault();
    Serial.println("ERR sensor_init check_mux_0x70_and_five_vl53l4cd_channels");
  } else {
    Serial.println("OK sensor_init five_vl53l4cd_channels");
  }
  // The same upstream Wire bus can read WHO_AM_I from the owned BerryIMU
  // before motion is ever enabled. No IMU driver, sensor fusion, second
  // controller or unqualified safety thresholds are silently installed.
  const auto imu = tof.ready() ? tof.probe_imu() : desk_robot::ImuIdentity{};
  control.set_imu_identity(imu.family, imu.gyro_id, imu.aux_id);
  if (tof.ready() && imu.family != 0 &&
      !berry_imu.begin(Wire, desk_robot::BerryImu::identify(imu.gyro_id, imu.aux_id),
                      imu.gyro_address, imu.aux_address)) {
    Serial.println("WARN berryimu_raw_sample_init_failed");
  }
  Serial.printf("INFO imu_probe family=%u gyro_id=0x%02x aux_id=0x%02x unqualified",
                static_cast<unsigned>(imu.family),
                static_cast<unsigned>(imu.gyro_id),
                static_cast<unsigned>(imu.aux_id));
  Serial.println();
  if (load_calibration()) {
    Serial.println("OK calibration_loaded samples_and_local_rearm_required");
  } else {
    Serial.println("ERR calibration_missing_or_invalid use_local_usb_calfloor_calfront_calfresh_calcommit");
  }
#endif
  Serial.println(pwm_ready ?
#if DESK_ROBOT_STEPPER
      "READY desk-robot-body stepper disarmed local_rearm_required" :
#else
      "READY desk-robot-body dc disarmed" :
#endif
      "ERR boot pwm_unavailable");
}

void loop() {
#if DESK_ROBOT_STEPPER
  // Real I2C sampling precedes every physical motor update. The pure
  // CliffGuard remains the only local motion/safety authority.
  if (tof.ready()) {
    tof.poll(cliff_guard, millis());
    berry_imu.poll(millis());
    control.set_imu(berry_imu.reading());
  }
  poll_touch(millis());
#endif
  control.tick(millis());
  apply_outputs();
  process_input(head_uart, head_receiver, false);
  process_input(Serial, usb_receiver, true);
  delay(1);
}
