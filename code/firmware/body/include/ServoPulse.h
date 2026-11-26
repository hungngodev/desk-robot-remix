#pragma once

namespace body_pins {
// Nominal command mapping only. Installed travel must be measured separately.
// Keep single return expressions for the WROOM GNU++11 toolchain.
constexpr int clamp_servo_value(int value, int minimum, int maximum) {
  return value < minimum ? minimum : value > maximum ? maximum : value;
}

constexpr bool valid_servo_pulse_span(int min_us, int max_us) {
  return min_us > 0 && min_us < max_us && max_us < 20000;
}

constexpr unsigned servo_duty_for_microseconds(int pulse_us, int min_us, int max_us) {
  // Invalid configuration must not produce a PWM pulse. Clamp while signed,
  // before conversion to the unsigned LEDC duty representation.
  return valid_servo_pulse_span(min_us, max_us)
      ? static_cast<unsigned>(clamp_servo_value(pulse_us, min_us, max_us)) *
            65535UL / 20000UL
      : 0U;  // 50 Hz, 16 bit LEDC
}

constexpr unsigned servo_duty_for_degrees(int degrees, int min_us, int max_us) {
  // Validate the span before subtracting, and clamp before multiplying.
  return valid_servo_pulse_span(min_us, max_us)
      ? servo_duty_for_microseconds(
            min_us + clamp_servo_value(degrees, 0, 180) * (max_us - min_us) / 180,
            min_us, max_us)
      : 0U;
}
}  // namespace body_pins
