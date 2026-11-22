// BENCH ONLY: one-shot centering of hornless MG90S units through USB0.
// No body motion controller, network, motor driver, battery or charging path.
// Mechanically remove BOTH horns and disconnect ALL motors before flashing.
// Servo V+ comes from a separately current-limited regulated supply, with
// WROOM and servo grounds common. This is not physical travel qualification.
#include <Arduino.h>

#include "BodyPins.h"
#include "ServoCenterBenchGate.h"

namespace {
desk_robot::ServoCenterBenchGate gate;
constexpr std::size_t kLineCapacity = 24;
char line[kLineCapacity]{};
std::size_t length = 0;
bool invalid_line = false;
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

void process_line(std::uint32_t now_ms) {
  line[length] = '\0';
  if (invalid_line || !pwm_ready || !gate.request(line, now_ms)) {
    Serial.println("ERR CENTER invalid_busy_or_already_used");
  } else {
    const auto channel = gate.active();
    // Program the 1500 us commanded position BEFORE attaching PWM.
    ledcWrite(servo_channel(channel), center_duty());
    ledcAttachPin(servo_pin(channel), servo_channel(channel));
    Serial.println(channel == desk_robot::ServoCenterBenchGate::Channel::Lift ?
                   "OK CENTER LIFT started_400ms" :
                   "OK CENTER GRIP started_400ms");
  }
  length = 0;
  invalid_line = false;
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
  Serial.println("INFO BENCH ONLY: motors disconnected, both horns removed");
  Serial.println("INFO USB commands CENTER LIFT or CENTER GRIP, once each");
  if (!pwm_ready) Serial.println("ERR LEDC setup_no_servo_output");
}

void loop() {
  const std::uint32_t now_ms = millis();
  if (gate.should_detach(now_ms)) {
    const int pin = servo_pin(gate.active());
    ledcDetachPin(pin);
    pinMode(pin, OUTPUT);
    digitalWrite(pin, LOW);
    gate.complete(now_ms);
    Serial.println("OK CENTER_DONE pwm_detached");
  }
  // A continuous 115200-baud input stream cannot keep this loop busy
  // indefinitely and postpone the next servo PWM detachment deadline.
  const int available = Serial.available();
  const std::size_t budget = gate.serial_budget(
      available > 0 ? static_cast<std::size_t>(available) : 0U);
  for (std::size_t scanned = 0; scanned < budget; ++scanned) {
    const int byte = Serial.read();
    if (byte < 0) break;
    if (byte == '\r') continue;  // Accept common CRLF terminal mode.
    if (byte == '\n') {
      process_line(millis());
      continue;
    }
    if (byte < 32 || byte > 126 || length >= kLineCapacity - 1) {
      invalid_line = true;
    } else if (!invalid_line) {
      line[length++] = static_cast<char>(byte);
    }
  }
}
