#include "thermal_pixels.h"
#include <array>
#include <cassert>
#include <cstddef>
#include <cstdint>
#include <iostream>

struct FakeWire {
  std::uint8_t selected = 0;
  std::uint8_t reg = 0;
  std::array<std::uint8_t, 16> data{};
  int cursor = 0;
  int requests = 0;
  bool write_failure = false;
  bool nack = false;
  bool short_read = false;
  bool invalid_byte = false;
  bool stopped_on_failed_write = false;

  void beginTransmission(std::uint8_t address) { selected = address; }
  std::size_t write(std::uint8_t value) {
    reg = value;
    return write_failure ? 0 : 1;
  }
  int endTransmission(bool stop) {
    if (write_failure && stop) stopped_on_failed_write = true;
    return nack ? 4 : 0;
  }
  int requestFrom(std::uint8_t address, std::uint8_t len, bool stop) {
    assert(address == selected && len == 16 && stop);
    ++requests;
    cursor = 0;
    return short_read ? 15 : 16;
  }
  int available() { return 16 - cursor; }
  int read() {
    if (invalid_byte && cursor == 7) return -1;
    return data[cursor++];
  }
};

int main() {
  using desk_robot_room::decode_thermal_pixel;
  using desk_robot_room::read_thermal_chunk;
  float c = 900.0f;
  assert(decode_thermal_pixel(0x00, 0x00, c) && c == 0.0f);
  assert(decode_thermal_pixel(0x64, 0x00, c) && c == 25.0f);
  assert(decode_thermal_pixel(0x40, 0x01, c) && c == 80.0f);
  assert(!decode_thermal_pixel(0x41, 0x01, c) && c == 80.0f);
  assert(!decode_thermal_pixel(0xff, 0x0f, c) && c == 80.0f);
  assert(!decode_thermal_pixel(0x60, 0x0f, c) && c == 80.0f);
  assert(!decode_thermal_pixel(0xf4, 0x01, c) && c == 80.0f);
  assert(!decode_thermal_pixel(0x00, 0x08, c) && c == 80.0f);
  assert(!decode_thermal_pixel(0xff, 0x07, c) && c == 80.0f);

  FakeWire bus;
  for (int i = 0; i < 8; ++i) {
    bus.data[2 * i] = 0x64;  // each pixel 25 C
    bus.data[2 * i + 1] = 0;
  }
  std::array<float, 64> frame{};
  for (int chunk = 0; chunk < 8; ++chunk) {
    assert(read_thermal_chunk(bus, 0x69, chunk, frame.data() + chunk * 8));
    assert(bus.reg == 0x80 + chunk * 16);
    assert(bus.selected == 0x69);
  }
  assert(bus.requests == 8);
  for (float pixel : frame) assert(pixel == 25.0f);
  assert(!read_thermal_chunk(bus, 0x69, 8, frame.data()));
  assert(!read_thermal_chunk(bus, 0x69, 0, nullptr));
  assert(bus.requests == 8);

  bus.nack = true;
  assert(!read_thermal_chunk(bus, 0x69, 0, frame.data()));
  bus.nack = false;
  bus.write_failure = true;
  assert(!read_thermal_chunk(bus, 0x69, 0, frame.data()));
  assert(bus.stopped_on_failed_write);
  bus.write_failure = false;
  bus.short_read = true;
  assert(!read_thermal_chunk(bus, 0x69, 0, frame.data()));
  bus.short_read = false;
  bus.invalid_byte = true;
  assert(!read_thermal_chunk(bus, 0x69, 0, frame.data()));
  bus.invalid_byte = false;
  // Last pixel invalid: the chunk must not partially overwrite old data.
  // Make every preceding pixel distinct from the cached 25 C frame.
  // Otherwise direct writes before a late failure are unobservable.
  for (int i = 0; i < 7; ++i) bus.data[2 * i] = 0x50;  // 20 C
  bus.data[14] = 0x41;
  bus.data[15] = 0x01;  // 80.25 C is outside AMG8833 high-gain spec.
  assert(!read_thermal_chunk(bus, 0x69, 0, frame.data()));
  for (float pixel : frame) assert(pixel == 25.0f);
  bus.data[14] = 0x40;
  bus.data[15] = 0x01;
  assert(read_thermal_chunk(bus, 0x69, 0, frame.data()));
  for (int i = 0; i < 7; ++i) assert(frame[i] == 20.0f);
  assert(frame[7] == 80.0f);
  for (int i = 8; i < 64; ++i) assert(frame[i] == 25.0f);
  std::cout << "PASS room thermal 8x16 I2C chunks, bounded AMG8833 pixels, atomic chunk and faults\n";
}
