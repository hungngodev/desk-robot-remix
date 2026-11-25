// BENCH ONLY: one-shot centering of hornless MG90S units through USB0.
// No body motion controller, network, motor driver, battery or charging path.
// Mechanically remove BOTH horns and disconnect ALL motors before flashing.
// Servo V+ comes from a separately current-limited regulated supply, with
// WROOM and servo grounds common. This is not physical travel qualification.
#include <Arduino.h>

#include "BodyPins.h"
#include "ReplyTxQueue.h"
#include "ServoCenterBenchGate.h"

namespace {
desk_robot::ServoCenterBenchGate gate;
desk_robot::ReplyTxQueue<256> replies;
bool pwm_ready = false;

unsigned center_duty() {
  const unsigned pulse_us = body_pins::kServoMinUs +
      (body_pins::kServoMaxUs - body_pins::kServoMinUs) / 2U;
  return pulse_us * 65535UL / 20000UL;  // 50 Hz, 16 bit LEDC
}

int servo_pin(desk_robot::ServoCenterBenchGate::Channel ch) {
  return ch == desk_robot::ServoCenterBenchGate::Channel::Lift ?
      body_pins::kLiftServo : body_pins::kGripServo;
}

int servo_channel(desk_robot::ServoCenterBenchGate::Channel ch) {
  return ch == desk_robot::ServoCenterBenchGate::Channel::Lift ?
      body_pins::kServoChannels[0] : body_pins::kServoChannels[1];
}

void process_byte(int byte, std::uint32_t now_ms) {
  using Result = desk_robot::ServoCenterBenchGate::InputResult;
  const auto result = gate.feed(byte, now_ms, pwm_ready);
  if (result == Result::Rejected) {
    replies.enqueue_line("ERR CENTER invalid_busy_or_already_used");
  } else if (result == Result::Started) {
    const auto channel = gate.active();
    // Program the 1500 us commanded position BEFORE attaching PWM.
    ledcWrite(servo_channel(channel), center_duty());
    ledcAttachPin(servo_pin(channel), servo_channel(channel));
    replies.enqueue_line(channel == desk_robot::ServoCenterBenchGate::Channel::Lift ?
                         "OK CENTER LIFT started_400ms" :
                         "OK CENTER GRIP started_400ms");
  }
}

void service_deadline() {
  const std::uint32_t now_ms = millis();
  if (!gate.should_detach(now_ms)) return;
  const int pin = servo_pin(gate.active());
  ledcDetachPin(pin);
  pinMode(pin, OUTPUT);
  digitalWrite(pin, LOW);
  gate.complete(now_ms);
  replies.enqueue_line("OK CENTER_DONE pwm_detached");
}
}  // namespace

void setup() {
  Serial.begin(115200);
  // Even a miswired connected DRV8833 receives BOTH inputs LOW; physical
  // motor disconnection is mandatory and is not software-verifiable.
  for (const int pin : body_pins::kMotorPins) {
    digitalWrite(pin, LOW);
    pinMode(pin, OUTPUT);
  }
  for (const int pin : body_pins::kServoPins) {
    digitalWrite(pin, LOW);
    pinMode(pin, OUTPUT);
  }
  // Servo channels own isolated 50 Hz timer 2, exactly as the full body.
  pwm_ready = ledcSetup(body_pins::kServoChannels[0],
                        body_pins::kServoFrequency,
                        body_pins::kServoResolution) != 0;
  pwm_ready = ledcSetup(body_pins::kServoChannels[1],
                        body_pins::kServoFrequency,
                        body_pins::kServoResolution) != 0 && pwm_ready;
  replies.enqueue_line("INFO BENCH ONLY: motors disconnected, both horns removed");
  replies.enqueue_line("INFO USB commands CENTER LIFT or CENTER GRIP, once each");
  if (!pwm_ready) replies.enqueue_line("ERR LEDC setup_no_servo_output");
}

void loop() {
  service_deadline();
  // A continuous 115200-baud input stream cannot keep this loop busy
  // indefinitely and postpone the next servo PWM detachment deadline.
  const int available = Serial.available();
  const std::size_t budget = gate.serial_budget(
      available > 0 ? static_cast<std::size_t>(available) : 0U);
  for (std::size_t scanned = 0; scanned < budget; ++scanned) {
    service_deadline();
    const int byte = Serial.read();
    if (byte < 0) break;
    process_byte(byte, millis());
  }
  // A saturated or disconnected USB TX must never extend an active pulse.
  // Replies may be dropped; loss of a receipt is not permission to retry.
  service_deadline();
  replies.drain(Serial);
}
