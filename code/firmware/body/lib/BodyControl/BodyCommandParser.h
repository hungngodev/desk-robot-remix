#pragma once

#include <cstddef>

namespace desk_robot {
namespace body_command {

// Split a bounded printable ASCII frame in caller-owned storage. Return a
// fixed wire error on failure with count zero; tokens are usable only on success.
template <std::size_t N, std::size_t T>
const char* tokenize(const char* line, std::size_t length, char (&buffer)[N],
                     char* (&tokens)[T], std::size_t& count) noexcept {
  static_assert(N > 0 && T > 0, "command storage must not be empty");
  count = 0;
  if (length >= N) return "ERR input line_too_long";
  if (line == nullptr && length != 0) return "ERR input invalid_buffer";
  for (std::size_t i = 0; i < length; ++i) {
    const unsigned char byte = static_cast<unsigned char>(line[i]);
    if (byte < 32 || byte > 126) return "ERR input invalid_ascii";
    buffer[i] = line[i];
  }
  buffer[length] = '\0';
  char* position = buffer;
  while (*position != '\0') {
    while (*position == ' ') ++position;
    if (*position == '\0') break;
    if (count == T) {
      count = 0;
      return "ERR input trailing_tokens";
    }
    tokens[count++] = position;
    while (*position != '\0' && *position != ' ') ++position;
    if (*position != '\0') *position++ = '\0';
  }
  return count == 0 ? "ERR input empty" : nullptr;
}

}  // namespace body_command
}  // namespace desk_robot
