#include "thermal_pixels.h"
#include <array>
#include <cassert>
#include <cstddef>
#include <cstdint>
#include <iostream>

struct FakeWire {
  std::uint8_t selected = 0;
  std::uint8_t reg = 0;
  std::array<std::uint8_t, 128> data{};
  int available_delta = 0;
  int cursor = 0;
  int requests = 0;
  bool write_failure = false;
  bool nack = false;
  bool short_read = false;
  bool invalid_byte = false;
  bool oversized_byte = false;
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
  int available() { return 16 - cursor + available_delta; }
  int read() {
    if (invalid_byte && cursor == 7) return -1;
    if (oversized_byte && cursor == 15) return 256;
    return data[static_cast<std::size_t>(reg - 0x80 + cursor++)];
  }
};

int main() {
  using desk_robot_room::decode_thermal_pixel;
  using desk_robot_room::read_thermal_chunk;
  using desk_robot_room::thermal_pixel_quarters;
  // Exhaust the register domain independently of the high-gain validity gate.
  for (int quarters = -2048; quarters <= 2047; ++quarters) {
    const unsigned raw = static_cast<unsigned>(quarters) & 0xfffU;
    const auto low = static_cast<std::uint8_t>(raw);
    const auto high = static_cast<std::uint8_t>(raw >> 8);
    for (unsigned reserved = 0; reserved < 16; ++reserved) {
      const auto decorated = static_cast<std::uint8_t>(high | (reserved << 4));
      assert(thermal_pixel_quarters(low, decorated) == quarters);
    }
    float decoded = 900.0f;
    const bool in_range = quarters >= 0 && quarters <= 320;
    assert(decode_thermal_pixel(low, high, decoded) == in_range);
    assert(decoded == (in_range ? static_cast<float>(quarters) * 0.25f : 900.0f));
  }
  assert(thermal_pixel_quarters(0xd8, 0x0f) == -40);  // -10 C pixel
  assert(thermal_pixel_quarters(0xa0, 0x08) == -1888);  // -10 C thermistor encoding
  float c = 900.0f;
  assert(decode_thermal_pixel(0x00, 0x00, c) && c == 0.0f);
  assert(decode_thermal_pixel(0x64, 0x00, c) && c == 25.0f);
  assert(decode_thermal_pixel(0x40, 0x01, c) && c == 80.0f);
  assert(!decode_thermal_pixel(0xd8, 0x0f, c) && c == 80.0f);
  assert(!decode_thermal_pixel(0xa0, 0x08, c) && c == 80.0f);
  assert(!decode_thermal_pixel(0x41, 0x01, c) && c == 80.0f);
  assert(!decode_thermal_pixel(0xff, 0x0f, c) && c == 80.0f);
  assert(!decode_thermal_pixel(0x60, 0x0f, c) && c == 80.0f);
  assert(!decode_thermal_pixel(0xf4, 0x01, c) && c == 80.0f);
  assert(!decode_thermal_pixel(0x00, 0x08, c) && c == 80.0f);
  assert(!decode_thermal_pixel(0xff, 0x07, c) && c == 80.0f);

  FakeWire bus;
  for (std::size_t i = 0; i < 64; ++i) {
    bus.data[2 * i] = 0x64;  // each pixel 25 C
    bus.data[2 * i + 1] = 0;
  }
  std::array<float, 64> frame{};
  for (std::uint8_t chunk = 0; chunk < 8; ++chunk) {
    assert(read_thermal_chunk(bus, 0x69, chunk, frame.data() + chunk * 8, 8));
    assert(bus.reg == 0x80 + chunk * 16);
    assert(bus.selected == 0x69);
  }
  assert(bus.requests == 8);
  for (float pixel : frame) assert(pixel == 25.0f);
  assert(!read_thermal_chunk(bus, 0x69, 8, frame.data(), frame.size()));
  assert(!read_thermal_chunk(bus, 0x69, 0, nullptr, 8));
  std::array<float, 7> undersized{};
  assert(!read_thermal_chunk(bus, 0x69, 0, undersized.data(), undersized.size()));
  for (float pixel : undersized) assert(pixel == 0.0f);
  assert(bus.requests == 8);

  bus.nack = true;
  assert(!read_thermal_chunk(bus, 0x69, 0, frame.data(), frame.size()));
  bus.nack = false;
  bus.write_failure = true;
  assert(!read_thermal_chunk(bus, 0x69, 0, frame.data(), frame.size()));
  assert(bus.stopped_on_failed_write);
  bus.write_failure = false;
  bus.short_read = true;
  assert(!read_thermal_chunk(bus, 0x69, 0, frame.data(), frame.size()));
  bus.short_read = false;
  for (int delta : {-1, 1}) {
    bus.available_delta = delta;
    assert(!read_thermal_chunk(bus, 0x69, 0, frame.data(), frame.size()));
    for (float pixel : frame) assert(pixel == 25.0f);
  }
  bus.available_delta = 0;
  bus.invalid_byte = true;
  assert(!read_thermal_chunk(bus, 0x69, 0, frame.data(), frame.size()));
  bus.invalid_byte = false;
  bus.oversized_byte = true;
  assert(!read_thermal_chunk(bus, 0x69, 7, frame.data() + 56, 8));
  bus.oversized_byte = false;
  // Last pixel invalid: the chunk must not partially overwrite old data.
  // Make every preceding pixel distinct from the cached 25 C frame.
  // Otherwise direct writes before a late failure are unobservable.
  for (std::size_t i = 0; i < 7; ++i) bus.data[2 * i] = 0x50;  // 20 C
  bus.data[14] = 0x41;
  bus.data[15] = 0x01;  // 80.25 C is outside AMG8833 high-gain spec.
  assert(!read_thermal_chunk(bus, 0x69, 0, frame.data(), frame.size()));
  for (float pixel : frame) assert(pixel == 25.0f);
  bus.data[14] = 0x40;
  bus.data[15] = 0x01;
  assert(read_thermal_chunk(bus, 0x69, 0, frame.data(), frame.size()));
  for (std::size_t i = 0; i < 7; ++i) assert(frame[i] == 20.0f);
  assert(frame[7] == 80.0f);
  for (std::size_t i = 8; i < 64; ++i) assert(frame[i] == 25.0f);
  // Distinct register values expose repeated, reordered or byte-swapped pixels.
  for (std::size_t i = 0; i < frame.size(); ++i) {
    const unsigned raw = 256U + static_cast<unsigned>(i);
    bus.data[2 * i] = static_cast<std::uint8_t>(raw);
    bus.data[2 * i + 1] = static_cast<std::uint8_t>(raw >> 8);
  }
  for (std::uint8_t chunk = 0; chunk < 8; ++chunk) {
    assert(read_thermal_chunk(bus, 0x69, chunk, frame.data() + chunk * 8, 8));
  }
  for (std::size_t i = 0; i < frame.size(); ++i)
    assert(frame[i] == 64.0f + 0.25f * static_cast<float>(i));
  const auto previous = frame;
  bus.data[112] = 0x64;
  bus.data[113] = 0;  // first pixel of last chunk now 25 C
  bus.data[126] = 0xff;
  bus.data[127] = 0x0f;  // final pixel -0.25 C: reject entire chunk
  assert(!read_thermal_chunk(bus, 0x69, 7, frame.data() + 56, 8));
  assert(frame == previous);
  std::cout << "PASS room thermal 8x16 I2C chunks, bounded AMG8833 pixels, atomic chunk and faults\n";
}
