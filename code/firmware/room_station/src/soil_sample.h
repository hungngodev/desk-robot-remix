#pragma once

#include <cstdint>

// Bounded, calibration-independent acquisition for the OPTIONAL stationary
// analog soil probe. Arduino's analogRead supplies the actual sample. This
// filter does NOT infer moisture percentage or verify probe wiring/voltage.
namespace desk_robot_room {
struct SoilSample {
  bool valid = false;
  std::uint16_t raw_adc = 0;
};

template <typename Read>
SoilSample read_soil_sample(Read read) {
  const int a = read();
  const int b = read();
  const int c = read();
  // 12-bit ADC rails are suspicious disconnected/shorted or clipped outputs;
  // they cannot establish calibrated plant moisture. Reject all of a burst
  // if any sample is out of range rather than reporting a misleading median.
  if (a <= 0 || a >= 4095 || b <= 0 || b >= 4095 ||
      c <= 0 || c >= 4095) return {};
  const int smallest = a < b ? (a < c ? a : c) : (b < c ? b : c);
  const int largest = a > b ? (a > c ? a : c) : (b > c ? b : c);
  // No arbitrary wet/dry classification. Only reject a wildly unstable
  // acquisition burst. The threshold is a software sanity limit, not a
  // physical calibration or disconnection guarantee.
  if (largest - smallest > 256) return {};
  const int median = a + b + c - smallest - largest;
  // The pinned nRF52 Arduino core still compiles with C++11, where a type
  // with default member initializers cannot use this aggregate return form.
  SoilSample sample;
  sample.valid = true;
  sample.raw_adc = static_cast<std::uint16_t>(median);
  return sample;
}
}  // namespace desk_robot_room
