#pragma once

#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <limits>

namespace desk_robot {

enum class UartFrameStatus : std::uint8_t {
  Ok,
  Unframed,
  BadChecksum,
};

inline std::uint8_t uart_crc8(const char* data, std::size_t length) {
  std::uint8_t crc = 0x00U;
  for (std::size_t i = 0; i < length; ++i) {
    crc ^= static_cast<std::uint8_t>(data[i]);
    for (int bit = 0; bit < 8; ++bit) {
      crc = (crc & 0x80U) != 0U
          ? static_cast<std::uint8_t>((crc << 1) ^ 0x07U)
          : static_cast<std::uint8_t>(crc << 1);
    }
  }
  return crc;
}

inline int parse_hex_nibble(char c) {
  if (c >= '0' && c <= '9') return c - '0';
  if (c >= 'A' && c <= 'F') return 10 + (c - 'A');
  if (c >= 'a' && c <= 'f') return 10 + (c - 'a');
  return -1;
}

inline UartFrameStatus parse_uart_integrity_frame(
    const char* line, std::size_t length, std::uint32_t& tx_id,
    std::size_t& payload_offset, std::size_t& payload_length) {
  tx_id = 0;
  payload_offset = 0;
  payload_length = 0;
  if (!line || length < 7U || line[0] != '@') return UartFrameStatus::Unframed;

  std::size_t pos = 1;
  if (pos >= length || line[pos] < '1' || line[pos] > '9') {
    return UartFrameStatus::Unframed;
  }
  std::uint64_t parsed_id = 0;
  while (pos < length && line[pos] >= '0' && line[pos] <= '9') {
    parsed_id = parsed_id * 10U + static_cast<std::uint64_t>(line[pos] - '0');
    if (parsed_id > std::numeric_limits<std::uint32_t>::max()) {
      return UartFrameStatus::Unframed;
    }
    ++pos;
  }
  if (pos >= length || line[pos] != ':') return UartFrameStatus::Unframed;
  const std::size_t start = pos + 1U;
  if (start + 3U >= length) return UartFrameStatus::Unframed;
  const std::size_t star = length - 3U;
  if (line[star] != '*') return UartFrameStatus::Unframed;
  const int hi = parse_hex_nibble(line[star + 1U]);
  const int lo = parse_hex_nibble(line[star + 2U]);
  if (hi < 0 || lo < 0) return UartFrameStatus::Unframed;
  if (star <= start) return UartFrameStatus::Unframed;

  const std::uint8_t expected = uart_crc8(line, star);
  const std::uint8_t received = static_cast<std::uint8_t>((hi << 4) | lo);
  if (expected != received) return UartFrameStatus::BadChecksum;

  tx_id = static_cast<std::uint32_t>(parsed_id);
  payload_offset = start;
  payload_length = star - start;
  return UartFrameStatus::Ok;
}

inline bool wrap_uart_integrity_reply(char* reply, std::size_t capacity,
                                      std::uint32_t tx_id) {
  if (!reply || capacity == 0U || tx_id == 0U) return false;
  const std::size_t inner_len = std::strlen(reply);
  char header[16]{};
  const int header_len =
      std::snprintf(header, sizeof(header), "@%lu:",
                    static_cast<unsigned long>(tx_id));
  if (header_len <= 0 ||
      static_cast<std::size_t>(header_len) >= sizeof(header)) {
    return false;
  }
  const std::size_t total =
      static_cast<std::size_t>(header_len) + inner_len + 3U;
  if (total + 1U > capacity) return false;

  // Compute CRC across "@<txid>:<reply>" before modifying reply in-place.
  std::uint8_t crc = uart_crc8(header, static_cast<std::size_t>(header_len));
  for (std::size_t i = 0; i < inner_len; ++i) {
    crc ^= static_cast<std::uint8_t>(reply[i]);
    for (int bit = 0; bit < 8; ++bit) {
      crc = (crc & 0x80U) != 0U
          ? static_cast<std::uint8_t>((crc << 1) ^ 0x07U)
          : static_cast<std::uint8_t>(crc << 1);
    }
  }
  std::memmove(reply + header_len, reply, inner_len);
  std::memcpy(reply, header, static_cast<std::size_t>(header_len));
  std::snprintf(reply + static_cast<std::size_t>(header_len) + inner_len, 4U,
                "*%02X", static_cast<unsigned>(crc));
  return true;
}

}  // namespace desk_robot
