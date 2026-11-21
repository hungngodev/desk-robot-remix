#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <vector>
#include "Pn532Frames.h"

#define CHECK(x) do { if (!(x)) throw std::runtime_error(#x); } while (false)

static std::vector<std::uint8_t> response(std::uint8_t cmd,
                                          const std::vector<std::uint8_t>& payload) {
  const auto length = static_cast<std::uint8_t>(payload.size() + 2);
  std::vector<std::uint8_t> wire = {1, 0, 0, 0xff, length,
      static_cast<std::uint8_t>(-length), 0xd5,
      static_cast<std::uint8_t>(cmd + 1)};
  std::uint8_t sum = static_cast<std::uint8_t>(0xd5U + cmd + 1);
  for (const auto b : payload) {
    wire.push_back(b);
    sum = static_cast<std::uint8_t>(sum + b);
  }
  wire.push_back(static_cast<std::uint8_t>(-sum));
  wire.push_back(0);
  wire.resize(desk_robot::kPn532MaxWire, 0);
  return wire;
}

int main() {
  try {
    const std::uint8_t sam[] = {1, 0x14, 1};
    std::uint8_t encoded[32]{};
    const auto n = desk_robot::pn532_encode(0x14, sam, 3, encoded, sizeof(encoded));
    CHECK(n == 12);
    CHECK(encoded[0] == 0 && encoded[1] == 0 && encoded[2] == 0xff);
    CHECK(encoded[3] == 5 && encoded[4] == 0xfb);
    CHECK(encoded[5] == 0xd4 && encoded[6] == 0x14);
    std::uint8_t checksum = 0;
    for (std::size_t i = 5; i < 10; ++i)
      checksum = static_cast<std::uint8_t>(checksum + encoded[i]);
    CHECK(static_cast<std::uint8_t>(checksum + encoded[10]) == 0);
    CHECK(encoded[11] == 0);
    CHECK(desk_robot::pn532_encode(0x14, sam, 17, encoded, sizeof(encoded)) == 0);

    const std::uint8_t ack[] = {1, 0, 0, 0xff, 0, 0xff, 0};
    const std::uint8_t fake_ack[] = {1, 0, 0, 0xff, 0, 0xfe, 0};
    CHECK(desk_robot::pn532_ack(ack, sizeof(ack)));
    CHECK(!desk_robot::pn532_ack(fake_ack, sizeof(fake_ack)));
    const std::uint8_t* payload = nullptr;
    std::size_t size = 0;
    auto empty = response(0x14, {});
    CHECK(desk_robot::pn532_response(
        empty.data(), empty.size(), 0x14, payload, size));
    CHECK(size == 0);
    CHECK(!desk_robot::pn532_response(
        empty.data(), empty.size(), 0x32, payload, size));
    auto bad = empty;
    bad[8] ^= 0xff; // wrong DCS
    CHECK(!desk_robot::pn532_response(
        bad.data(), bad.size(), 0x14, payload, size));

    auto absent = response(0x4a, {0});
    CHECK(desk_robot::pn532_response(
        absent.data(), absent.size(), 0x4a, payload, size));
    std::uint32_t token = 123;
    std::uint8_t uid_size = 9;
    CHECK(desk_robot::pn532_tag(payload, size, token, uid_size)
          == desk_robot::Pn532TagResult::Absent);
    CHECK(token == 0 && uid_size == 0);

    auto present = response(0x4a, {
        1, 1, 4, 0, 8, 4, 0x12, 0x34, 0x56, 0x78
    });
    CHECK(desk_robot::pn532_response(
        present.data(), present.size(), 0x4a, payload, size));
    CHECK(desk_robot::pn532_tag(payload, size, token, uid_size)
          == desk_robot::Pn532TagResult::Present);
    CHECK(uid_size == 4 && token != 0);
    const auto first_token = token;
    CHECK(desk_robot::pn532_tag(payload, size, token, uid_size)
          == desk_robot::Pn532TagResult::Present);
    CHECK(token == first_token);
    std::uint8_t bad_card[] = {1, 1, 0, 0, 0, 9, 1, 2, 3, 4};
    CHECK(desk_robot::pn532_tag(bad_card, sizeof(bad_card), token, uid_size)
          == desk_robot::Pn532TagResult::Invalid);
    CHECK(token == 0 && uid_size == 0);
    std::cout << "PASS bounded PN532 CRC and read only toy tag tokens\n";
  } catch (const std::exception& e) {
    std::cerr << "FAIL " << e.what() << "\n";
    return 1;
  }
  return 0;
}
