#include <Arduino.h>
#include <esp_system.h>
#include <esp_timer.h>

#include "BodyControl.h"
#include "BodyReplyFormat.h"
#include "ReplyTxQueue.h"
#include "BodyPins.h"
#include "ServoPulse.h"
#ifndef DESK_ROBOT_FULL_SENSORS
#define DESK_ROBOT_FULL_SENSORS DESK_ROBOT_STEPPER
#endif
#if DESK_ROBOT_STEPPER && !DESK_ROBOT_FULL_SENSORS
#error Stepper backend requires the full sensor guard
#endif
// Existing 28BYJ48/ULN2003 has NO hardware nSLEEP. Its unqualified
// stepper motor rail must remain OFF even if USB issues a local arm.
// Only a reviewed, physically measured independent power-cutoff circuit may
// enable stepper motion in an explicit qualified firmware build.
#ifndef DESK_ROBOT_STEPPER_HARDWARE_CUTOFF_QUALIFIED
#define DESK_ROBOT_STEPPER_HARDWARE_CUTOFF_QUALIFIED 0
#endif
// The external DC CD74HC123 to DRV8833 nSLEEP wiring is not qualified by
// compiling a heartbeat. Do not drive wheels without measured fail-low cutoff.
#ifndef DESK_ROBOT_DC_HARDWARE_CUTOFF_QUALIFIED
#define DESK_ROBOT_DC_HARDWARE_CUTOFF_QUALIFIED 0
#endif
#if (DESK_ROBOT_STEPPER_HARDWARE_CUTOFF_QUALIFIED != 0 && \
     DESK_ROBOT_STEPPER_HARDWARE_CUTOFF_QUALIFIED != 1) || \
    (DESK_ROBOT_DC_HARDWARE_CUTOFF_QUALIFIED != 0 && \
     DESK_ROBOT_DC_HARDWARE_CUTOFF_QUALIFIED != 1)
#error Motor cutoff qualification flags must be 0 or 1
#endif
// A guarded DC image must not silently omit its CPU-stall motor cutoff.
// The historical unguarded DC bench remains separate from full-sensor motion.
#if !DESK_ROBOT_STEPPER && DESK_ROBOT_FULL_SENSORS && \
    (!defined(DESK_ROBOT_ENABLE_DC_WATCHDOG) || DESK_ROBOT_ENABLE_DC_WATCHDOG != 1)
#error Full-sensor DC motion requires the independent motor watchdog heartbeat
#endif
// nFAULT is a separate local interlock, not a substitute for the one-shot.
// A custom full DC build must not silently compile it out.
#if !DESK_ROBOT_STEPPER && DESK_ROBOT_FULL_SENSORS && \
    (!defined(DESK_ROBOT_REQUIRE_DC_NFAULT) || DESK_ROBOT_REQUIRE_DC_NFAULT != 1)
#error Full-sensor DC motion requires the driver nFAULT monitor
#endif
#if defined(DESK_ROBOT_ENABLE_DC_WATCHDOG) && DESK_ROBOT_ENABLE_DC_WATCHDOG
#if DESK_ROBOT_STEPPER || !DESK_ROBOT_FULL_SENSORS
#error Motor watchdog lab requires full sensors with DC drive pins
#endif
#include "MotorHeartbeat.h"
#endif
#if DESK_ROBOT_FULL_SENSORS
#include "CliffGuard.h"
#include "BerryImu.h"
#include "StepperDrive.h"
#include "TofBus.h"
#include "RangeTelemetry.h"
#include "ExpansionTouch.h"
#include "TouchDebounce.h"
#include "PulsePad.h"
#include "AccessorySensors.h"
#include "McpContactEvidence.h"
#include "TerminalIr.h"
#include <Preferences.h>
#endif

namespace {
#if DESK_ROBOT_FULL_SENSORS
// A common full motion safety guard survives motor backend substitution.
desk_robot::CliffGuard cliff_guard;
desk_robot::BodyControl control(
    DESK_ROBOT_STEPPER ? desk_robot::BodyProfile::StepperGuarded :
                         desk_robot::BodyProfile::DcGuarded, &cliff_guard);
#if defined(DESK_ROBOT_ENABLE_DC_WATCHDOG) && DESK_ROBOT_ENABLE_DC_WATCHDOG
desk_robot::MotorHeartbeat motor_heartbeat;
#endif
#if DESK_ROBOT_STEPPER && DESK_ROBOT_STEPPER_HARDWARE_CUTOFF_QUALIFIED
desk_robot::StepperDrive left_stepper;
desk_robot::StepperDrive right_stepper;
#endif
desk_robot::TofBus tof;
desk_robot::ExpansionTouch cap1188;
desk_robot::PulsePad paw_pulse;
desk_robot::AccessorySensors accessories;
desk_robot::TerminalIr terminal_ir; // 2 independent direct RMT inputs, read-only
desk_robot::BerryImu berry_imu;  // One six-axis adapter, MPU6050 or BerryIMU; shares Wire
// AT42QT1010 owns the input threshold. Sample without internal pullups
// (GPIO34 is input-only), debounce three equal 25ms samples, and retain
// an edge counter so the Mac can detect short taps between status polls.
desk_robot::TouchDebounce touch_debounce;

std::uint32_t last_extra_sample_ms = 0;
desk_robot::McpContactEvidence contact_evidence;
bool sample_raw_bumper() {
#if defined(DESK_ROBOT_ENABLE_BUMPER) && DESK_ROBOT_ENABLE_BUMPER
  // NC series to GND; open or unplugged -> HIGH trip. Direct GPIO
  // acquisition does not wait for I2C, UART or the event debounce.
  control.sample_bumper_input(digitalRead(body_pins::kBumperInput) == HIGH);
  return control.state().bumper_raw;
#else
  return false;
#endif
}

void poll_optional(std::uint32_t now_ms) {
  sample_raw_bumper();
  if (now_ms - last_extra_sample_ms < 25) return;
  last_extra_sample_ms = now_ms;
  std::uint8_t mask = 0;
  bool bumper = false, reed = false, pir = false;
#if defined(DESK_ROBOT_ENABLE_BUMPER) && DESK_ROBOT_ENABLE_BUMPER
  mask |= 1U;
  bumper = control.state().bumper_raw; // same direct acquisition as the safety trip
#endif
  // Slow magnetic/PIR inputs arrive from MCP23017 GPIOB on the existing
  // accessory mux. The required dock seat/PGOOD remains independent GPIOA.
  // Never interpret an old optional bus value as a new local event.
#if (defined(DESK_ROBOT_ENABLE_REED) && DESK_ROBOT_ENABLE_REED) || \
    (defined(DESK_ROBOT_ENABLE_PIR) && DESK_ROBOT_ENABLE_PIR)
  const auto& extension = accessories.readings().optional_inputs;
  const bool extension_fresh = contact_evidence.observe(extension, now_ms);
#endif
#if defined(DESK_ROBOT_ENABLE_REED) && DESK_ROBOT_ENABLE_REED
  if (extension_fresh) {
    mask |= 2U;
    reed = contact_evidence.reed_closed();
  }
#endif
#if defined(DESK_ROBOT_ENABLE_PIR) && DESK_ROBOT_ENABLE_PIR
  if (extension_fresh) {
    mask |= 4U;
    pir = contact_evidence.pir_active();
  }
#endif
  // McpContactEvidence already debounces distinct GPIOB acquisitions.
  // Do not re-count cached 25ms reads as new physical reed/PIR samples.
  control.sample_optional_inputs(mask, bumper, reed, pir, true);
}

void apply_outputs();

bool sample_raw_touch(std::uint32_t now_ms) {
  const bool active = digitalRead(body_pins::kTouchOutput) == HIGH;
  control.sample_touch_input(active, now_ms, touch_debounce.baseline_ready());
  touch_debounce.observe(active, now_ms);
  return active;
}

void poll_touch(std::uint32_t now_ms) {
  // Independent wheel inhibition must not wait for the 25 ms gesture timer.
  const bool was_armed = control.state().armed;
  const bool active = sample_raw_touch(now_ms);
  if (was_armed && !control.state().armed) {
    apply_outputs();
    // apply_outputs resamples GPIO; do not feed its predecessor back into
    // the gesture classifier with an older timestamp.
    return;
  }
  if (touch_debounce.poll(active, now_ms)) {
    control.set_touch(touch_debounce.stable(), now_ms);
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
      !desk_robot::valid_stored_calibrated_flag(saved.config) ||
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
// UART output is never sent synchronously inside the sensor/heartbeat loop.
// Two full worst-case replies fit per port; saturation drops an ACK rather
// than holding the local STOP and watchdog behind UART backpressure.
using ReplyQueue = desk_robot::ReplyTxQueue<2 * (desk_robot::kReplyCapacity + 2)>;
ReplyQueue head_replies;
ReplyQueue usb_replies;
bool pwm_ready = false;
#if DESK_ROBOT_FULL_SENSORS
bool servo_attached = false;
int applied_lift = -1;
int applied_grip = -1;
#endif
#if !DESK_ROBOT_STEPPER && DESK_ROBOT_FULL_SENSORS && DESK_ROBOT_DC_HARDWARE_CUTOFF_QUALIFIED
int applied_left = 0;
int applied_right = 0;
#endif

void all_motor_inputs_low() {
  for (int pin : body_pins::kMotorPins) {
    // Preload the GPIO latch before enabling the output (Arduino ESP32 2.0.17).
    digitalWrite(pin, LOW);
    pinMode(pin, OUTPUT);
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

#if !DESK_ROBOT_STEPPER && DESK_ROBOT_FULL_SENSORS && DESK_ROBOT_DC_HARDWARE_CUTOFF_QUALIFIED
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
#elif DESK_ROBOT_STEPPER
void write_stepper(const int (&pins)[4], std::uint8_t mask) {
  // Reject every pattern outside the eight half-steps and explicit coast.
  switch (mask) {
    case 0: case 1: case 3: case 2: case 6: case 4: case 12: case 8: case 9:
      break;
    default:
      mask = 0;
  }
  // Remove inactive coils before enabling the next phase. No blocking step call.
  for (int phase = 0; phase < 4; ++phase)
    if ((mask & (1U << phase)) == 0) digitalWrite(pins[phase], LOW);
  for (int phase = 0; phase < 4; ++phase)
    if ((mask & (1U << phase)) != 0) digitalWrite(pins[phase], HIGH);
}
#endif

#if DESK_ROBOT_FULL_SENSORS
unsigned servo_duty(int degrees) {
  return body_pins::servo_duty_for_degrees(
      degrees, body_pins::kServoMinUs, body_pins::kServoMaxUs);
}
#endif

#if defined(DESK_ROBOT_ENABLE_DC_WATCHDOG) && DESK_ROBOT_ENABLE_DC_WATCHDOG
void enforce_motor_heartbeat(bool advance) {
  const auto& drive = control.state();
  const bool allow_heartbeat = DESK_ROBOT_DC_HARDWARE_CUTOFF_QUALIFIED &&
      pwm_ready && drive.armed &&
      (drive.left != 0 || drive.right != 0);
  if (advance) {
    // Only the full sensor loop can generate CPU heartbeat edges.
    const bool pulse = motor_heartbeat.update(millis(), allow_heartbeat);
    digitalWrite(body_pins::kDcHeartbeatPin, pulse ? HIGH : LOW);
  } else if (!motor_heartbeat.check_authority(millis(), allow_heartbeat)) {
    // UART/outputs must enforce a missed deadline or STOP without extending
    // the independent one-shot or clearing the existing fault latch.
    digitalWrite(body_pins::kDcHeartbeatPin, LOW);
  }
  if (motor_heartbeat.missed_deadline()) {
    // Stop both wheels before writing PWM; preserve a held payload.
    control.motor_watchdog_trip();
  }
}
#endif

void apply_outputs() {
  // All output paths, including commands received on either UART, recheck the
  // local interlock/timers immediately before writing the physical pins.
#if DESK_ROBOT_FULL_SENSORS
  sample_raw_bumper();
  sample_raw_touch(millis());
#endif
  control.tick(millis());
#if defined(DESK_ROBOT_ENABLE_DC_WATCHDOG) && DESK_ROBOT_ENABLE_DC_WATCHDOG
  enforce_motor_heartbeat(false);
#endif
#if !DESK_ROBOT_FULL_SENSORS
  // Historical unguarded DC profiles are diagnostic-only. Even a valid
  // remote/local ARM must never drive the H-bridge or attach a servo here.
  // A physical actuator can be enabled only through a qualified full guard.
  control.force_disarm();
  zero_motor_pwm();
#else
  if (!pwm_ready) {
    control.force_disarm();
    zero_motor_pwm();
    return;
  }
  const auto& state = control.state();
#if DESK_ROBOT_STEPPER
#if !DESK_ROBOT_STEPPER_HARDWARE_CUTOFF_QUALIFIED
  // This is the default release-safe state: no coil may be energized when
  // there is no independently timed and physically qualified motor cutoff.
  // A software watchdog is not a substitute if the WROOM CPU stalls.
  control.force_disarm();
  write_stepper(body_pins::kLeftStepperPins, 0);
  write_stepper(body_pins::kRightStepperPins, 0);
#else
  const std::uint32_t now_us = micros();
  write_stepper(body_pins::kLeftStepperPins,
                left_stepper.update(now_us, state.left, state.armed));
  write_stepper(body_pins::kRightStepperPins,
                right_stepper.update(now_us, state.right, state.armed));
#endif
#else
#if DESK_ROBOT_FULL_SENSORS && !DESK_ROBOT_DC_HARDWARE_CUTOFF_QUALIFIED
  // A CPU heartbeat alone does NOT certify its external one-shot and nSLEEP.
  // Keep every DRV8833 bridge input LOW until the physical cutoff is proven.
  zero_motor_pwm();
#else
  if ((applied_left > 0 && state.left < 0) ||
      (applied_left < 0 && state.left > 0) ||
      (applied_right > 0 && state.right < 0) ||
      (applied_right < 0 && state.right > 0)) {
    zero_motor_pwm();
    delayMicroseconds(100);  // short dead-time before reversing polarity
  }
  write_motor_pair(body_pins::kMotorChannels[0], body_pins::kMotorChannels[1], state.left);
  write_motor_pair(body_pins::kMotorChannels[2], body_pins::kMotorChannels[3], state.right);
  applied_left = state.left;
  applied_right = state.right;
#endif
#endif
  if (state.servos_attached && !servo_attached) {
    // Program duty before attaching: never emit a default zero-width command.
    ledcWrite(body_pins::kServoChannels[0], servo_duty(state.lift));
    ledcWrite(body_pins::kServoChannels[1], servo_duty(state.grip));
    ledcAttachPin(body_pins::kLiftServo, body_pins::kServoChannels[0]);
    ledcAttachPin(body_pins::kGripServo, body_pins::kServoChannels[1]);
    servo_attached = true;
    applied_lift = state.lift;
    applied_grip = state.grip;
  } else if (!state.servos_attached && servo_attached) {
    for (int pin : body_pins::kServoPins) {
      digitalWrite(pin, LOW);  // preload before switching away from LEDC
      ledcDetachPin(pin);
      pinMode(pin, OUTPUT);
    }
    servo_attached = false;
    applied_lift = -1;
    applied_grip = -1;
  }
  if (servo_attached && state.lift != applied_lift) {
    ledcWrite(body_pins::kServoChannels[0], servo_duty(state.lift));
    applied_lift = state.lift;
  }
  if (servo_attached && state.grip != applied_grip) {
    ledcWrite(body_pins::kServoChannels[1], servo_duty(state.grip));
    applied_grip = state.grip;
  }
#endif  // DESK_ROBOT_FULL_SENSORS
}

void process_input(HardwareSerial& stream, desk_robot::LineReceiver& receiver,
                   ReplyQueue& replies, bool local_usb) {
  char reply[desk_robot::kReplyCapacity]{};
  // Bounded read prevents sustained input from starving the other port/timers.
  for (int bytes = 0; bytes < 64 && stream.available() > 0; ++bytes) {
    const char received = static_cast<char>(stream.read());
    // A completed pose reply uses the WROOM's 64-bit monotonic microsecond
    // clock. Non-pose commands ignore the timestamp; UART reads stay bounded.
    const std::uint64_t sample_us = received == '\n' ?
        static_cast<std::uint64_t>(esp_timer_get_time()) : 0ULL;
#if DESK_ROBOT_FULL_SENSORS
    // A pending UART command must see both current local interlocks.
    if (sample_raw_bumper()) apply_outputs();
    if (sample_raw_touch(millis())) apply_outputs();
#endif
#if defined(DESK_ROBOT_ENABLE_DC_WATCHDOG) && DESK_ROBOT_ENABLE_DC_WATCHDOG
    // Latch a CPU pause before a pending command can reuse an old drive.
    enforce_motor_heartbeat(false);
#endif
    const bool completed = receiver.feed(received, millis(), control, reply,
                                          sizeof(reply), sample_us);
    if (completed && !pwm_ready && strcmp(reply, "OK arm") == 0) {
      control.force_disarm();
      desk_robot::format_reply(reply, sizeof(reply), "ERR arm pwm_unavailable");
    }
#if DESK_ROBOT_STEPPER && !DESK_ROBOT_STEPPER_HARDWARE_CUTOFF_QUALIFIED
    if (completed && strcmp(reply, "OK arm") == 0) {
      control.force_disarm();
      desk_robot::format_reply(reply, sizeof(reply), "ERR arm stepper_cutoff_unqualified");
    }
#endif
#if defined(DESK_ROBOT_ENABLE_DC_WATCHDOG) && DESK_ROBOT_ENABLE_DC_WATCHDOG
    // Successful local USB rearm alone clears the missed CPU heartbeat.
    if (completed && local_usb && strcmp(reply, "OK rearm") == 0)
      motor_heartbeat.reset();
#endif
#if DESK_ROBOT_FULL_SENSORS
    if (completed && local_usb && strcmp(reply, "OK calcommit") == 0 &&
        !save_calibration()) {
      // A partially written or unavailable NVS record cannot silently allow
      // operation on a calibration that would disappear next boot.
      cliff_guard.configure(desk_robot::CliffConfig{});
      control.force_disarm();
      desk_robot::format_reply(reply, sizeof(reply), "ERR calcommit nvs_write_failed");
    }
#else
    (void)local_usb;
#endif
    apply_outputs();  // apply accepted command/expired timer before acknowledging
#if DESK_ROBOT_FULL_SENSORS
    // The contact can open between command validation and output application.
    // Do not acknowledge a motion/recovery decision that this new sample vetoed.
    if (completed && control.state().bumper_raw)
      desk_robot::veto_motion_ack(reply, sizeof(reply), desk_robot::MotionAckVeto::BumperActive);
    if (completed && control.state().touch_blocked())
      desk_robot::veto_motion_ack(reply, sizeof(reply), desk_robot::MotionAckVeto::TouchActive);
#endif
#if defined(DESK_ROBOT_ENABLE_DC_WATCHDOG) && DESK_ROBOT_ENABLE_DC_WATCHDOG
    // A deadline can also expire while processing the command itself.
    if (completed && motor_heartbeat.missed_deadline())
      desk_robot::veto_motion_ack(reply, sizeof(reply),
                                 desk_robot::MotionAckVeto::MotorWatchdogLatched);
#endif
    if (completed) {
      control.veto_unapplied_motion_ack(reply, sizeof(reply));
      // STOP/HALT already took effect before acknowledgement. Keep the
      // small final reply out of the normal status backlog without splicing
      // it into any JSON line that has begun transmitting.
      if (strcmp(reply, "OK halt") == 0 || strcmp(reply, "OK stop") == 0)
        replies.enqueue_priority_line(reply);
      else
        replies.enqueue_line(reply);
    }
  }
}
}  // namespace

void setup() {
  // The first hardware action disables every motor/phase input, before UART.
  all_motor_inputs_low();
#if defined(DESK_ROBOT_ENABLE_DC_WATCHDOG) && DESK_ROBOT_ENABLE_DC_WATCHDOG
  // Pin must stay LOW until the first complete local safety and dock pass.
  // The external CD74HC123 Q, not this GPIO, may drive DRV8833 nSLEEP.
  digitalWrite(body_pins::kDcHeartbeatPin, LOW);
  pinMode(body_pins::kDcHeartbeatPin, OUTPUT);
  motor_heartbeat.reset();
#endif
  // This is observation identity only, not cryptographic authentication.
  // New WROOM boots must not reuse the last IMU observation session.
  control.set_boot_epoch(esp_random() | 1U);
#if !DESK_ROBOT_FULL_SENSORS || \
    (DESK_ROBOT_STEPPER && !DESK_ROBOT_STEPPER_HARDWARE_CUTOFF_QUALIFIED) || \
    (!DESK_ROBOT_STEPPER && DESK_ROBOT_FULL_SENSORS && \
     !DESK_ROBOT_DC_HARDWARE_CUTOFF_QUALIFIED)
  // Neither a legacy DC bench, a software heartbeat nor simulated guard
  // readings qualify motor power. Unguarded images are actuator-inert;
  // guarded images require an independently measured external cutoff.
  control.inhibit_unqualified_motor_cutoff();
#endif
#if DESK_ROBOT_FULL_SENSORS
  // The touch breakout OUT is actively driven and powered at 3.3V.
  // GPIO34 has no internal pullup; do not leave it floating when fitted.
  pinMode(body_pins::kTouchOutput, INPUT);
#if defined(DESK_ROBOT_ENABLE_BUMPER) && DESK_ROBOT_ENABLE_BUMPER
  pinMode(body_pins::kBumperInput, INPUT); // external pullup mandatory
#endif
// GPIO36/39 are reserved for independent read-only dock NEC RMT inputs.
// Reed and PIR use optional MCP23017 GPIOB, not MCU pinMode.
// The existing decoder is compiled only with DESK_ROBOT_ENABLE_TERMINAL_IR;
// no IR evidence authorizes motor movement or charger contacts.
#endif
  for (int pin : body_pins::kServoPins) {
    digitalWrite(pin, LOW);
    pinMode(pin, OUTPUT);
  }
  pwm_ready = true;
#if !DESK_ROBOT_STEPPER
  for (int i = 0; i < 4; ++i) {
    if (ledcSetup(body_pins::kMotorChannels[i], body_pins::kMotorFrequency,
                  body_pins::kMotorResolution) == 0) pwm_ready = false;
    ledcWrite(body_pins::kMotorChannels[i], 0);
  }
#endif
  for (int channel : body_pins::kServoChannels) {
    if (ledcSetup(channel, body_pins::kServoFrequency,
                  body_pins::kServoResolution) == 0) pwm_ready = false;
    ledcWrite(channel, 0);
  }
#if !DESK_ROBOT_STEPPER
  // Keep GPIO LOW ownership until every PWM timer has initialized safely.
  if (pwm_ready) {
    for (int i = 0; i < 4; ++i)
      ledcAttachPin(body_pins::kMotorPins[i], body_pins::kMotorChannels[i]);
  }
#endif
  zero_motor_pwm();
  Serial.begin(115200);
  head_uart.begin(115200, SERIAL_8N1, body_pins::kUartRx, body_pins::kUartTx);
#if DESK_ROBOT_FULL_SENSORS
  // Keep motors and servos de-energized through all five device inits.
  // No accepted calibration is embedded in this image. A local calibration
  // commit and a fresh manual USB rearm are required before any arm can pass.
#if DESK_ROBOT_EXTRA_RANGERS
  // The complete eight-ranger product includes the 0x71 accessory mux.
  // A startup NACK is not proof of isolation on this required topology.
  tof.note_optional_mux_present();
#endif
  if (!tof.begin(body_pins::kSensorSda, body_pins::kSensorScl,
                 body_pins::kMuxReset)) {
    cliff_guard.bus_fault();
    Serial.println("ERR sensor_init check_mux_0x70_and_five_critical_vl53l0x_channels");
  } else {
    Serial.println("OK sensor_init five_critical_vl53l0x_channels_three_diagnostic");
  }
  // This is a required sensor for the selected physical robot core. No
  // optional board or stale sample is allowed to bypass the local arm gate.
  // A fresh IMU is not sufficient to declare upright/held safety.
  control.require_imu_for_motion(true);
  control.require_imu_attitude_guard(true);
#if defined(DESK_ROBOT_ATTITUDE_LIMITS_QUALIFIED) && DESK_ROBOT_ATTITUDE_LIMITS_QUALIFIED
#if !defined(DESK_ROBOT_UPRIGHT_ACCEL_X) || !defined(DESK_ROBOT_UPRIGHT_ACCEL_Y) || \
    !defined(DESK_ROBOT_UPRIGHT_ACCEL_Z) || !defined(DESK_ROBOT_UPRIGHT_PROJECTION_PERMILLE) || \
    !defined(DESK_ROBOT_ACCEL_MIN_NORM_RAW) || !defined(DESK_ROBOT_ACCEL_MAX_NORM_RAW)
#error Measured installed MPU6050 upright axes and tolerance bounds are required
#endif
  const desk_robot::ImuAttitudeLimits attitude_limits{
      {DESK_ROBOT_UPRIGHT_ACCEL_X, DESK_ROBOT_UPRIGHT_ACCEL_Y,
       DESK_ROBOT_UPRIGHT_ACCEL_Z},
      DESK_ROBOT_UPRIGHT_PROJECTION_PERMILLE,
      DESK_ROBOT_ACCEL_MIN_NORM_RAW, DESK_ROBOT_ACCEL_MAX_NORM_RAW};
  if (!control.configure_imu_attitude_limits(attitude_limits)) {
    control.force_disarm();
    Serial.println("ERR imu_attitude_limits_invalid wheels_locked");
  }
#else
  Serial.println("WARN imu_attitude_unqualified wheels_locked");
#endif
  // ARM energizes BOTH positional MG90S channels. A generic 60..120 degree
  // parser range does not qualify the actual lift horn, linkage or chassis.
  // The default firmware leaves the lift and jaw unpowered at boot.
  control.require_lift_travel_limits(true);
#if defined(DESK_ROBOT_LIFT_LIMITS_QUALIFIED) && DESK_ROBOT_LIFT_LIMITS_QUALIFIED
#if !defined(DESK_ROBOT_LIFT_MIN_DEG) || !defined(DESK_ROBOT_LIFT_MAX_DEG)
#error Qualified lift travel requires measured minimum and maximum degrees
#endif
  const desk_robot::LiftTravelLimits lift_limits{
      DESK_ROBOT_LIFT_MIN_DEG, DESK_ROBOT_LIFT_MAX_DEG};
  if (!control.configure_lift_travel_limits(lift_limits)) {
    control.force_disarm();
    Serial.println("ERR lift_travel_limits_invalid servos_locked");
  }
#else
  Serial.println("WARN lift_travel_unqualified servos_locked");
#endif
  // A full physical jaw cannot execute a queued close while its own
  // ADS1115 feedback has gone stale. Bench-only fixtures remain opt-in.
  control.require_grip_feedback(true);
#if defined(DESK_ROBOT_JAW_FORCE_LIMITS_QUALIFIED) && DESK_ROBOT_JAW_FORCE_LIMITS_QUALIFIED
  // Explicit measured values for the installed assembly ONLY. Stock images
  // have none and cannot close the jaw; a compile flag is not physical proof.
#if !defined(DESK_ROBOT_JAW_OPEN_DEG) || !defined(DESK_ROBOT_JAW_CLOSED_DEG) || \
    !defined(DESK_ROBOT_JAW_EMPTY_ADC) || !defined(DESK_ROBOT_JAW_FORCE_SIGN) || \
    !defined(DESK_ROBOT_JAW_MAX_DELTA_ADC)
#error Qualified jaw calibration requires all five physical measurements
#endif
  const desk_robot::JawForceLimits jaw_limits{
      DESK_ROBOT_JAW_OPEN_DEG, DESK_ROBOT_JAW_CLOSED_DEG,
      DESK_ROBOT_JAW_EMPTY_ADC, DESK_ROBOT_JAW_FORCE_SIGN,
      DESK_ROBOT_JAW_MAX_DELTA_ADC};
  if (!control.configure_jaw_force_limits(jaw_limits)) {
    control.force_disarm();
    Serial.println("ERR jaw_force_limits_invalid jaw_locked");
  }
#else
  Serial.println("WARN jaw_force_limits_unqualified jaw_locked");
#endif
  // The same upstream Wire bus can read WHO_AM_I from the owned BerryIMU
  // before motion is ever enabled. No IMU driver, sensor fusion, second
  // controller or unqualified safety thresholds are silently installed.
  // MPU6050 uses WHO_AM_I at 0x75 on 0x68/0x69; BerryIMU has paired
  // WHO_AM_I at 0x0f. No second bus, no speculative pin swap.
  // Sensor bringup is independently diagnosable on USB. Even if one ToF
  // channel fails to initialize, Wire was opened with a bounded timeout by
  // TofBus.begin. We can identify the owned upstream IMU without granting
  // movement: the ToF guard remains fault-latched.
  const auto imu = tof.probe_imu();
  control.set_imu_identity(imu.family, imu.gyro_id, imu.aux_id);
  if (imu.family != 0 &&
      !berry_imu.begin(Wire, desk_robot::BerryImu::identify(imu.gyro_id, imu.aux_id),
                      imu.gyro_address, imu.aux_address)) {
    Serial.println("WARN six_axis_sample_init_failed");
  }
  Serial.printf("INFO imu_probe family=%u gyro_id=0x%02x aux_id=0x%02x unqualified",
                static_cast<unsigned>(imu.family),
                static_cast<unsigned>(imu.gyro_id),
                static_cast<unsigned>(imu.aux_id));
  Serial.println();
  // Optional CAP1188 on mux 0x71 channel 0: prefer 0x29, accept 0x28
  // only after manufacturer and product ID checks on the isolated bus.
  // The dedicated AT42QT1010 GPIO34 remains the actual touch stop.
  const bool petting_present = tof.bus_accessible() && cap1188.begin(Wire);
  Serial.println(petting_present ? "INFO cap1188_read_only_available" :
                   "INFO cap1188_missing_or_wrong_id");
  const bool paw_present = tof.bus_accessible() && paw_pulse.begin(Wire);
  Serial.println(paw_present ? "INFO max30102_raw_optical_available" :
                               "INFO max30102_optional_unavailable");
#if defined(DESK_ROBOT_MAX30102_FIFO_IR_FIRST) && DESK_ROBOT_MAX30102_FIFO_IR_FIRST
  Serial.println("INFO max30102_fifo_ir_first_compiled_unqualified");
#else
  Serial.println("INFO max30102_fifo_red_first_compiled_unqualified");
#endif
  const bool accessory_mux = tof.bus_accessible() && accessories.begin(
      Wire, [] { return tof.bus_accessible(); });
#if defined(DESK_ROBOT_REQUIRE_FUEL_MONITOR) && DESK_ROBOT_REQUIRE_FUEL_MONITOR
  // Full battery robot cannot move when its fuel gauge is missing/stale.
  // A valid digital voltage read does not certify the pack or charger.
  control.require_fuel_monitor(true);
  Serial.println(accessories.readings().gauge.fuel_present ?
      "INFO required_max17048_found_unqualified_until_first_read" :
      "ERR required_max17048_missing_motor_locked");
#endif
  // A mux ACK proves presence even if downstream configuration/readback
  // fails. Do not use sensor begin() success as the isolation contract.
  // This also protects the five-ranger bench if a later 0x71 probe succeeds.
  if (cap1188.present() || paw_pulse.mux_present() || accessories.mux_present())
    tof.note_optional_mux_present();
  Serial.println(accessory_mux ? "INFO optional_accessory_bus_probed" :
                                 "INFO optional_accessory_bus_unavailable");
#if DESK_ROBOT_ENABLE_HAPTIC
  Serial.println(accessories.haptic_ready() ?
      "INFO haptic_edge_source_ready_external_one_shot_required" :
      "WARN haptic_edge_source_disabled_or_unverified");
#endif
  // Both demodulated IR receiver inputs are optional observed evidence.
  // The main WROOM motor guard never consumes this signal to arm itself.
#if defined(DESK_ROBOT_ENABLE_TERMINAL_IR) && DESK_ROBOT_ENABLE_TERMINAL_IR
  const bool ir_ready = terminal_ir.begin(
      body_pins::kTerminalIrLeftInput, body_pins::kTerminalIrRightInput);
  Serial.println(ir_ready ? "INFO dual_nec_rmt_rx_ready_read_only" :
                            "WARN dual_nec_rmt_rx_unavailable_motion_unchanged");
#endif
#if defined(DESK_ROBOT_REQUIRE_DC_NFAULT) && DESK_ROBOT_REQUIRE_DC_NFAULT
  // Full guarded DC build demands fresh LOW-active DRV8833 nFAULT evidence
  // on MCP23017 GPB3, not merely a toggling CPU heartbeat. Absence holds
  // motor outputs off until real GPIOB evidence and local USB rearm.
  control.require_dc_driver_fault_monitor(true);
  Serial.println("INFO dc_driver_nfault_gpb3_required_unqualified_hardware");
#endif
#if defined(DESK_ROBOT_REQUIRE_DOCK_MONITOR) && DESK_ROBOT_REQUIRE_DOCK_MONITOR
  control.require_dock_monitor(true);
  Serial.println(accessories.readings().dock.present ?
      "INFO required_dock_gpio_found_unverified_until_first_read" :
      "ERR required_dock_gpio_missing_motor_locked");
#endif
  if (load_calibration()) {
    Serial.println("OK calibration_loaded samples_and_local_rearm_required");
  } else {
    Serial.println("ERR calibration_missing_or_invalid use_local_usb_calfloor_calfront_calfresh_calcommit");
  }
#endif
  Serial.println(pwm_ready ?
#if DESK_ROBOT_STEPPER
#if !DESK_ROBOT_STEPPER_HARDWARE_CUTOFF_QUALIFIED
      "READY desk-robot-body stepper motor_disabled_cutoff_unqualified" :
#else
      "READY desk-robot-body stepper disarmed local_rearm_required" :
#endif
#elif DESK_ROBOT_FULL_SENSORS
#if !DESK_ROBOT_DC_HARDWARE_CUTOFF_QUALIFIED
      "READY desk-robot-body dc_guarded motor_disabled_cutoff_unqualified" :
#else
      "READY desk-robot-body dc_guarded disarmed local_rearm_required" :
#endif
#else
      "READY desk-robot-body dc_bench_only disarmed" :
#endif
      "ERR boot pwm_unavailable");
}

#if DESK_ROBOT_FULL_SENSORS
void invalidate_shared_bus_if_faulted() {
  if (tof.bus_accessible()) return;
  // A client after the range scan can hold SDA/SCL. No more I2C work,
  // no cached evidence and no wait for the next scan before stopping.
  tof.observe_shared_bus_fault(cliff_guard);
  control.invalidate_side_ranges();
  control.invalidate_range_optics();
  berry_imu.invalidate_bus();
  control.set_imu(berry_imu.reading());
  cap1188.invalidate_bus();
  control.set_cap(false, 0);
  paw_pulse.invalidate_bus();
  control.set_paw_pulse(paw_pulse.sample());
  accessories.invalidate_bus();
  control.set_accessories(accessories.readings(), millis());
}

void service_safety_checkpoint() {
  // No new motor permission or heartbeat edge: enforce existing authority
  // and deadlines before the next synchronous client gets the shared bus.
  invalidate_shared_bus_if_faulted();
  poll_touch(millis());
  apply_outputs();
}
#endif

void loop() {
#if DESK_ROBOT_FULL_SENSORS
  // Apply an open NC contact before the first potentially blocking bus read.
  if (sample_raw_bumper()) apply_outputs();
  // Sample raw touch before any potentially blocking shared bus transfer.
  // Poll again after IMU work below; the gesture clock is independent.
  poll_touch(millis());
  // Expire an old drive before starting another synchronous sensor call.
  // New UART commands still wait for the complete critical sensor pass.
  service_safety_checkpoint();
  if (tof.ready()) {
    const auto scan_ms = millis();
    const auto errors_before = tof.errors();
    tof.poll(cliff_guard, scan_ms);
    desk_robot::publish_range_telemetry(
        tof, control, scan_ms, tof.errors() != errors_before);
  }
  // A fault must reach the physical outputs before another shared I2C
  // transaction can block. Preserve holding PWM through apply_outputs().
  if (!cliff_guard.evaluate(millis())) apply_outputs();
  service_safety_checkpoint();
  if (tof.bus_accessible()) berry_imu.poll(millis());
  if (!tof.bus_accessible()) {
    berry_imu.invalidate_bus();
    accessories.invalidate_bus();
  }
  const bool was_armed_before_imu = control.state().armed;
  control.set_imu(berry_imu.reading());
  // Apply a newly detected IMU veto before optional I2C can delay STOP.
  // A stale/invalid frame is handled by tick inside apply_outputs().
  if (was_armed_before_imu &&
      (!control.state().armed || !control.imu_fresh(millis()))) {
    apply_outputs();
  }
  poll_touch(millis());
  poll_optional(millis());
  if (control.state().bumper_raw) apply_outputs();
  service_safety_checkpoint();
  if (tof.bus_accessible()) accessories.poll(millis());
  invalidate_shared_bus_if_faulted();
  control.set_accessories(accessories.readings(), millis());
  service_safety_checkpoint();
#if defined(DESK_ROBOT_ENABLE_TERMINAL_IR) && DESK_ROBOT_ENABLE_TERMINAL_IR
  terminal_ir.poll(millis());  // bounded, nonblocking, after cliff/dock reads
  const auto ir_assessed_at_ms = millis();
  control.set_terminal_ir(terminal_ir.evidence(ir_assessed_at_ms), ir_assessed_at_ms);
#endif
  service_safety_checkpoint();
#endif
  apply_outputs();
  process_input(head_uart, head_receiver, head_replies, false);
  process_input(Serial, usb_receiver, usb_replies, true);
  // Never wait for the complete JSON/status wire time. Each port transfers
  // at most 32 already-bufferable bytes after safety and input handling.
  head_replies.drain(head_uart);
  usb_replies.drain(Serial);
#if DESK_ROBOT_FULL_SENSORS
  // One non-authoritative context client per loop, after both UART RX slices.
  // This bounds the optional work ahead of the next safety/STOP service.
  static bool cap_next = true;
  if (cap_next) {
    std::uint8_t cap_zones = 0;
    if (tof.bus_accessible() && cap1188.present()) {
      if (cap1188.poll(millis(), cap_zones)) control.set_cap(true, cap_zones);
      else if (!cap1188.verified()) control.set_cap(false, 0);
    } else {
      cap1188.invalidate_bus();
      control.set_cap(false, 0);
    }
  } else {
    if (tof.bus_accessible()) paw_pulse.poll(millis());
    if (!tof.bus_accessible()) paw_pulse.invalidate_bus();
    control.set_paw_pulse(paw_pulse.sample());
  }
  cap_next = !cap_next;
  service_safety_checkpoint();
#if DESK_ROBOT_ENABLE_HAPTIC
  // React only to a genuine fresh CAP1188 rising touch zone, not a boot
  // baseline, microphone/LLM request, or arbitrary remote motor command.
  static std::uint32_t last_haptic_cap_events = 0;
  const std::uint32_t cap_events = control.state().cap_events;
  if (cap_events != last_haptic_cap_events) {
    last_haptic_cap_events = cap_events;
    if (control.state().cap_valid && control.state().cap_mask != 0U &&
        !control.state().touch_blocked())
      accessories.request_haptic(millis());
  }
#endif
  // Never advance a CPU heartbeat using pre-I2C contact observations.
  sample_raw_bumper();
  sample_raw_touch(millis());
#endif
  control.tick(millis());
#if defined(DESK_ROBOT_ENABLE_DC_WATCHDOG) && DESK_ROBOT_ENABLE_DC_WATCHDOG
  enforce_motor_heartbeat(true);
#endif
  apply_outputs();
  delay(1);
}
