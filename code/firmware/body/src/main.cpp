#include <Arduino.h>

#include "BodyControl.h"
#include "BodyPins.h"
#if DESK_ROBOT_STEPPER
#include "CliffGuard.h"
#include "StepperDrive.h"
#endif

namespace {
#if DESK_ROBOT_STEPPER
// No fabricated calibration or sample source. Until sensor I/O and measured
// calibration are supplied, every arm request is rejected by this guard.
desk_robot::CliffGuard cliff_guard;
desk_robot::BodyControl control(desk_robot::BodyProfile::StepperGuarded, &cliff_guard);
desk_robot::StepperDrive left_stepper;
desk_robot::StepperDrive right_stepper;
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

void process_input(Stream& stream, desk_robot::LineReceiver& receiver) {
  char reply[desk_robot::kReplyCapacity]{};
  // Bounded read prevents sustained input from starving the other port/timers.
  for (int bytes = 0; bytes < 64 && stream.available() > 0; ++bytes) {
    const bool completed = receiver.feed(static_cast<char>(stream.read()),
                                          millis(), control, reply, sizeof(reply));
    if (completed && !pwm_ready && strcmp(reply, "OK arm") == 0) {
      control.force_disarm();
      snprintf(reply, sizeof(reply), "ERR arm pwm_unavailable");
    }
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
  Serial.println(pwm_ready ?
#if DESK_ROBOT_STEPPER
      "READY desk-robot-body stepper disarmed safety_unconfigured" :
#else
      "READY desk-robot-body dc disarmed" :
#endif
      "ERR boot pwm_unavailable");
}

void loop() {
  control.tick(millis());
  apply_outputs();
  process_input(head_uart, head_receiver);
  process_input(Serial, usb_receiver);
  delay(1);
}
