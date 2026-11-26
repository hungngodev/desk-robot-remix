#pragma once

#include <cstdarg>
#include <cstddef>
#include <cstdio>

namespace desk_robot {
// Only complete replies may reach UART. Clear the destination on failure so
// even a fallback error that does not fit cannot masquerade as a valid frame.
inline bool format_reply(char* reply, std::size_t capacity, const char* format, ...)
#if defined(__GNUC__) || defined(__clang__)
    __attribute__((format(printf, 3, 4)))
#endif
    ;

inline bool format_reply(char* reply, std::size_t capacity, const char* format, ...) {
  if (reply == nullptr || capacity == 0) return false;
  std::va_list args;
  va_start(args, format);
  const int written = std::vsnprintf(reply, capacity, format, args);
  va_end(args);
  if (written < 0 || static_cast<std::size_t>(written) >= capacity) {
    reply[0] = '\0';
    return false;
  }
  return true;
}
}  // namespace desk_robot
