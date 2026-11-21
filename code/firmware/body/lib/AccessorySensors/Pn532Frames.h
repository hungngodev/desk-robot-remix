#pragma once
#include <cstddef>
#include <cstdint>

namespace desk_robot {
// Bounded protocol adapter for Seeed Studio PN532's BSD-3-Clause I2C framing.
// Reference: https://github.com/Seeed-Studio/PN532/tree/e61296876c1c3e66ef67156562c71324b389f5fa/src
// The upstream code waits in readAckFrame()/readResponse(). This portable
// subset NEVER sleeps, polls, drives a GPIO, writes tags, or changes motors.
// In production the WROOM adapter executes one transaction on each low-
// priority mux-0x71 lane-5 slot, after all local cliff safety sampling.
constexpr std::uint8_t kPn532Address = 0x24; // 7-bit I2C, datasheet 0x48/0x49
constexpr std::size_t kPn532MaxWire = 31;     // safely below 32-byte Wire receive buffer

inline std::size_t pn532_encode(
    std::uint8_t cmd, const std::uint8_t* body, std::size_t size,
    std::uint8_t* out, std::size_t capacity) {
  if (!out || (size && !body) || size > 16 || capacity < size + 9)
    return 0;
  const std::uint8_t length = static_cast<std::uint8_t>(size + 2);
  out[0] = 0; out[1] = 0; out[2] = 0xff;
  out[3] = length;
  out[4] = static_cast<std::uint8_t>(-length);
  out[5] = 0xd4; // host to PN532
  out[6] = cmd;
  std::uint8_t sum = static_cast<std::uint8_t>(0xd4U + cmd);
  for (std::size_t i = 0; i < size; ++i) {
    out[7 + i] = body[i];
    sum = static_cast<std::uint8_t>(sum + body[i]);
  }
  out[7 + size] = static_cast<std::uint8_t>(-sum);
  out[8 + size] = 0; // postamble
  return 9 + size;
}

inline bool pn532_ack(const std::uint8_t* frame, std::size_t n) {
  static const std::uint8_t kAck[7] = {1, 0, 0, 0xff, 0, 0xff, 0};
  if (!frame || n < sizeof(kAck)) return false;
  for (std::size_t i = 0; i < sizeof(kAck); ++i)
    if (frame[i] != kAck[i]) return false;
  return true;
}

// Buffer starts with PN532 I2C's READY byte. Reads may include trailing
// zeros because Seeed's reader requests a fixed maximum buffer length.
inline bool pn532_response(
    const std::uint8_t* frame, std::size_t size, std::uint8_t command,
    const std::uint8_t*& payload, std::size_t& payload_size) {
  payload = nullptr;
  payload_size = 0;
  if (!frame || size < 10 || frame[0] != 1 ||
      frame[1] != 0 || frame[2] != 0 || frame[3] != 0xff) return false;
  const std::uint8_t length = frame[4];
  if (length < 2 || length > 24 ||
      static_cast<std::uint8_t>(length + frame[5]) != 0 ||
      static_cast<std::size_t>(length) + 8 > size ||
      frame[6] != 0xd5 ||
      frame[7] != static_cast<std::uint8_t>(command + 1) ||
      frame[7 + length] != 0) return false;
  std::uint8_t checksum = 0;
  for (std::size_t i = 0; i < length; ++i)
    checksum = static_cast<std::uint8_t>(checksum + frame[6 + i]);
  if (static_cast<std::uint8_t>(checksum + frame[6 + length]) != 0)
    return false;
  payload = frame + 8;
  payload_size = length - 2;
  return true;
}

enum class Pn532TagResult { Invalid, Absent, Present };

inline Pn532TagResult pn532_tag(
    const std::uint8_t* payload, std::size_t n,
    std::uint32_t& token, std::uint8_t& uid_length) {
  token = 0;
  uid_length = 0;
  if (!payload || n < 1) return Pn532TagResult::Invalid;
  if (payload[0] == 0) return n == 1
      ? Pn532TagResult::Absent : Pn532TagResult::Invalid;
  // InListPassiveTarget: NbTg, Tg, SENS_RES[2], SEL_RES, NFCIDLen, NFCID.
  if (payload[0] != 1 || n < 6 || payload[1] != 1 ||
      (payload[5] != 4 && payload[5] != 7 && payload[5] != 10) ||
      n < static_cast<std::size_t>(6 + payload[5]))
    return Pn532TagResult::Invalid;
  uid_length = payload[5];
  std::uint32_t hash = 2166136261U; // nonsecret game token, NOT authentication
  hash = (hash ^ uid_length) * 16777619U;
  for (unsigned i = 0; i < uid_length; ++i)
    hash = (hash ^ payload[6 + i]) * 16777619U;
  token = hash;
  return Pn532TagResult::Present;
}
} // namespace desk_robot
