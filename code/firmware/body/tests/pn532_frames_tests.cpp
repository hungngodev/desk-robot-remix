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

// NXP UM0701-02 normal information frame, with the I2C READY byte.
static void check_frame_boundaries() {
  const std::vector<std::uint8_t> good = {
      1, 0, 0, 0xff, 3, 0xfd, 0xd5, 0x4b, 0, 0xe0, 0
  };
  const std::uint8_t* payload = nullptr;
  std::size_t size = 0;
  const auto reject = [&](const std::uint8_t* data, std::size_t count) {
    // Failure must erase a previous successful output, not expose stale UID.
    payload = good.data();
    size = good.size();
    CHECK(!desk_robot::pn532_response(data, count, 0x4a, payload, size));
    CHECK(payload == nullptr && size == 0);
  };
  CHECK(desk_robot::pn532_response(good.data(), good.size(), 0x4a, payload, size));
  CHECK(payload == good.data() + 8 && size == 1 && payload[0] == 0);
  reject(nullptr, good.size());
  for (std::size_t n = 0; n < good.size(); ++n) {
    const std::vector<std::uint8_t> short_frame(good.begin(), good.begin() + n);
    reject(short_frame.data(), short_frame.size());
  }
  // All single-bit corruption in READY, preamble, start, LEN/LCS, TFI,
  // response code, data, DCS and postamble must be rejected independently.
  for (std::size_t i = 0; i < good.size(); ++i) {
    for (unsigned bit = 0; bit < 8; ++bit) {
      auto bad = good;
      bad[i] ^= static_cast<std::uint8_t>(1U << bit);
      reject(bad.data(), bad.size());
    }
  }
  for (const std::uint8_t length : {0, 1, 25, 255}) {
    auto bad = good;
    bad[4] = length;
    bad[5] = static_cast<std::uint8_t>(-length);
    reject(bad.data(), bad.size());
  }
  // Largest complete response that fits the actual bounded Wire read.
  const auto maximum = response(0x4a, std::vector<std::uint8_t>(21, 0xa5));
  CHECK(maximum.size() == desk_robot::kPn532MaxWire);
  CHECK(desk_robot::pn532_response(maximum.data(), maximum.size(), 0x4a, payload, size));
  CHECK(size == 21 && payload[20] == 0xa5);
  reject(maximum.data(), maximum.size() - 1);
  const auto oversized = response(0x4a, std::vector<std::uint8_t>(22, 0xa5));
  reject(oversized.data(), oversized.size());
  // A fresh complete frame must parse after truncation/corruption.
  CHECK(desk_robot::pn532_response(good.data(), good.size(), 0x4a, payload, size));
  CHECK(size == 1 && payload[0] == 0);

  const std::vector<std::uint8_t> ack = {1, 0, 0, 0xff, 0, 0xff, 0};
  CHECK(!desk_robot::pn532_ack(nullptr, ack.size()));
  for (std::size_t i = 0; i < ack.size(); ++i) {
    const std::vector<std::uint8_t> short_ack(ack.begin(), ack.begin() + i);
    CHECK(!desk_robot::pn532_ack(short_ack.data(), short_ack.size()));
    for (unsigned bit = 0; bit < 8; ++bit) {
      auto bad = ack;
      bad[i] ^= static_cast<std::uint8_t>(1U << bit);
      CHECK(!desk_robot::pn532_ack(bad.data(), bad.size()));
    }
  }
  CHECK(desk_robot::pn532_ack(ack.data(), ack.size()));
}

static void check_tag_boundaries() {
  using desk_robot::Pn532TagResult;
  std::uint32_t token = 0;
  std::uint8_t uid_size = 0;
  const auto reject = [&](const std::uint8_t* data, std::size_t count) {
    token = 123;
    uid_size = 10;
    CHECK(desk_robot::pn532_tag(data, count, token, uid_size) == Pn532TagResult::Invalid);
    CHECK(token == 0 && uid_size == 0);
  };
  reject(nullptr, 10);
  const std::uint8_t false_absence[] = {0, 1};
  reject(false_absence, sizeof(false_absence));
  for (const std::uint8_t length : {4, 7, 10}) {
    std::vector<std::uint8_t> tag = {1, 1, 4, 0, 8, length};
    for (std::uint8_t i = 0; i < length; ++i) tag.push_back(i + 1);
    for (std::size_t n = 0; n < tag.size(); ++n) {
      const std::vector<std::uint8_t> short_tag(tag.begin(), tag.begin() + n);
      reject(short_tag.data(), short_tag.size());
    }
    auto bad = tag;
    bad[0] = 2;
    reject(bad.data(), bad.size());
    bad = tag;
    bad[1] = 0;
    reject(bad.data(), bad.size());
    CHECK(desk_robot::pn532_tag(tag.data(), tag.size(), token, uid_size) == Pn532TagResult::Present);
    CHECK(uid_size == length && token != 0);
    const auto previous = token;
    tag.back() ^= 1;
    CHECK(desk_robot::pn532_tag(tag.data(), tag.size(), token, uid_size) == Pn532TagResult::Present);
    CHECK(uid_size == length && token != previous);
  }
}

static void check_ats_and_wire_limit() {
  using desk_robot::Pn532TagResult;
  std::uint32_t token = 0;
  std::uint8_t uid_size = 0;
  const std::uint8_t* payload = nullptr;
  std::size_t size = 0;
  // A checksum-valid frame may still contain structurally invalid ATS data.
  for (unsigned declared = 0; declared <= 255; ++declared) {
    for (unsigned actual = 1; actual <= 11; ++actual) {
      std::vector<std::uint8_t> tag = {1, 1, 4, 0, 0x20, 4, 1, 2, 3, 4};
      tag.resize(10 + actual, 0x75);
      tag[10] = static_cast<std::uint8_t>(declared);
      const auto wire = response(0x4a, tag);
      CHECK(desk_robot::pn532_response(wire.data(), wire.size(), 0x4a, payload, size));
      token = 123;
      uid_size = 10;
      const auto result = desk_robot::pn532_tag(payload, size, token, uid_size);
      if (declared == actual) {
        CHECK(result == Pn532TagResult::Present && uid_size == 4 && token != 0);
      } else {
        CHECK(result == Pn532TagResult::Invalid && uid_size == 0 && token == 0);
      }
    }
  }
  // Restore the final postamble truncated by response()'s fixed Wire buffer.
  auto oversized = response(0x4a, std::vector<std::uint8_t>(22, 0xa5));
  oversized.push_back(0);
  CHECK(oversized.size() == desk_robot::kPn532MaxWire + 1);
  CHECK(!desk_robot::pn532_response(
      oversized.data(), oversized.size(), 0x4a, payload, size));
  CHECK(payload == nullptr && size == 0);
}

static void check_encoder_boundaries() {
  const std::vector<std::uint8_t> body(17, 0xa5);
  const std::vector<std::uint8_t> untouched(26, 0x55);
  auto out = untouched;
  CHECK(desk_robot::pn532_encode(0x4a, body.data(), 17, out.data(), out.size()) == 0);
  CHECK(out == untouched);
  CHECK(desk_robot::pn532_encode(0x4a, body.data(), 16, out.data(), 24) == 0);
  CHECK(out == untouched);
  CHECK(desk_robot::pn532_encode(0x4a, nullptr, 1, out.data(), out.size()) == 0);
  CHECK(out == untouched);
  CHECK(desk_robot::pn532_encode(0x4a, body.data(), 16, nullptr, 25) == 0);
  CHECK(desk_robot::pn532_encode(0x4a, body.data(), 16, out.data(), 25) == 25);
  CHECK(out[3] == 18 && out[4] == 0xee && out[23] == 0x92);
  CHECK(out[24] == 0 && out[25] == 0x55);
  for (std::size_t i = 7; i < 23; ++i) CHECK(out[i] == 0xa5);
  out = untouched;
  CHECK(desk_robot::pn532_encode(0x02, nullptr, 0, out.data(), 9) == 9);
  const std::vector<std::uint8_t> expected = {0, 0, 0xff, 2, 0xfe, 0xd4, 2, 0x2a, 0};
  CHECK(std::vector<std::uint8_t>(out.begin(), out.begin() + 9) == expected);
  CHECK(out[9] == 0x55);
}

int main() {
  try {
    check_frame_boundaries();
    check_tag_boundaries();
    check_encoder_boundaries();
    check_ats_and_wire_limit();
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
