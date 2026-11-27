#pragma once

#include <cstdarg>
#include <cstddef>
#include <cstdio>

namespace desk_robot {
// Only complete, nonempty single-line replies may reach UART. Clear on failure so
// even a fallback error that does not fit cannot masquerade as a valid frame.
inline bool format_reply(char* reply, std::size_t capacity, const char* format, ...)
#if defined(__GNUC__) || defined(__clang__)
    __attribute__((format(printf, 3, 4)))
#endif
    ;

inline bool format_reply(char* reply, std::size_t capacity, const char* format, ...) {
  if (reply == nullptr || capacity == 0) return false;
  if (format == nullptr) {
    reply[0] = '\0';
    return false;
  }
  std::va_list args;
  va_start(args, format);
  const int written = std::vsnprintf(reply, capacity, format, args);
  va_end(args);
  if (written <= 0 || static_cast<std::size_t>(written) >= capacity) {
    reply[0] = '\0';
    return false;
  }
  // vsnprintf counts embedded NUL bytes, but the UART queue reads a C string.
  // Reject every frame delimiter within the reported payload, not just the
  // prefix visible to strlen. Never let a partial OK masquerade as a receipt.
  for (int i = 0; i < written; ++i) {
    if (reply[i] == '\0' || reply[i] == '\r' || reply[i] == '\n') {
      reply[0] = '\0';
      return false;
    }
  }
  return true;
}
}  // namespace desk_robot
