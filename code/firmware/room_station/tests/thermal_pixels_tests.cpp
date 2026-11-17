#include "thermal_pixels.h"
#include <cassert>
#include <iostream>

int main() {
  using desk_robot_room::decode_thermal_pixel;
  float c = 900.0f;
  assert(decode_thermal_pixel(0x64, 0x00, c) && c == 25.0f);
  assert(decode_thermal_pixel(0xff, 0x0f, c) && c == -0.25f);
  assert(decode_thermal_pixel(0x60, 0x0f, c) && c == -40.0f);
  assert(decode_thermal_pixel(0xf4, 0x01, c) && c == 125.0f);
  assert(!decode_thermal_pixel(0x00, 0x08, c) && c == -512.0f);
  assert(!decode_thermal_pixel(0xff, 0x07, c) && c == 511.75f);
  std::cout << "PASS room thermal signed conversion and fail-closed bounds\n";
}
