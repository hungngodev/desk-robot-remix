#pragma once

namespace body_pins {
// Nominal command mapping only. Installed travel must be measured separately.
constexpr unsigned servo_duty_for_degrees(int degrees, int min_us, int max_us) {
  const unsigned pulse_us = min_us + degrees * (max_us - min_us) / 180;
  return pulse_us * 65535UL / 20000UL;  // 50 Hz, 16 bit LEDC
}
}  // namespace body_pins
