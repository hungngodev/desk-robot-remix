#include "BodyReplyFormat.h"

#include <climits>
#include <clocale>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cwchar>
#include <limits>

namespace {
#define CHECK(condition) do { \
  if (!(condition)) { \
    std::fprintf(stderr, "line %d: %s\n", __LINE__, #condition); \
    std::abort(); \
  } \
} while (false)

// Exercise every capacity through exact fit, with a poisoned destination and
// canaries on both sides. No test-side dynamic storage is needed.
template <typename... Args>
void check_boundaries(const char* expected, const char* format, Args... args) {
  const std::size_t length = std::strlen(expected);
  char storage[1803];
  CHECK(length + 2 < sizeof(storage));
  for (std::size_t capacity = 0; capacity <= length + 2; ++capacity) {
    std::memset(storage, 'X', sizeof(storage));
    char* reply = storage + 1;
    const bool complete = desk_robot::format_reply(reply, capacity, format, args...);
    CHECK(complete == (capacity > length));
    CHECK(storage[0] == 'X');
    for (std::size_t i = capacity + 1; i < sizeof(storage); ++i)
      CHECK(storage[i] == 'X');
    if (complete) CHECK(std::strcmp(reply, expected) == 0);
    else if (capacity != 0) CHECK(reply[0] == '\0');
  }
}

void numeric_boundaries() {
  char expected[1800];
  const char* format = "ERR drive %d %d %u %lu %llu motor_watchdog_latched";
  const int length = std::snprintf(expected, sizeof(expected), format,
      INT_MIN, INT_MAX, UINT_MAX, static_cast<unsigned long>(0xffffffffU), ULLONG_MAX);
  CHECK(length > 0 && static_cast<std::size_t>(length) < sizeof(expected));
  CHECK(std::strstr(expected, "motor_watchdog_latched") != nullptr);
  check_boundaries(expected, format, INT_MIN, INT_MAX, UINT_MAX,
                   static_cast<unsigned long>(0xffffffffU), ULLONG_MAX);

  const double max_float = std::numeric_limits<float>::max();
  const double max_double = std::numeric_limits<double>::max();
  const char* float_format = "%.2f %.2f %.2f %.2f safety_interlock";
  const int float_length = std::snprintf(expected, sizeof(expected), float_format,
                                        -max_float, max_float, -max_double, max_double);
  CHECK(float_length > 0 && static_cast<std::size_t>(float_length) < sizeof(expected));
  CHECK(std::strstr(expected, "safety_interlock") != nullptr);
  check_boundaries(expected, float_format, -max_float, max_float, -max_double, max_double);
  check_boundaries("-0.00 0.00 safety_interlock", "%.2f %.2f safety_interlock",
                   -0.0, std::numeric_limits<double>::denorm_min());
}

void invalid_arguments() {
  char reply[32] = "OK arm";
  CHECK(!desk_robot::format_reply(nullptr, sizeof(reply), "OK arm"));
  CHECK(!desk_robot::format_reply(reply, 0, "OK stop"));
  CHECK(std::strcmp(reply, "OK arm") == 0);
  const char* null_format = nullptr;
  CHECK(!desk_robot::format_reply(reply, sizeof(reply), null_format, 0));
  CHECK(reply[0] == '\0');
  // A surrogate cannot be encoded as a wide character in the C locale.
  std::strcpy(reply, "OK arm");
  CHECK(!desk_robot::format_reply(reply, sizeof(reply), "OK %lc",
                                  static_cast<std::wint_t>(0xd800)));
  CHECK(reply[0] == '\0');
  CHECK(desk_robot::format_reply(reply, sizeof(reply), "OK halt"));
  CHECK(std::strcmp(reply, "OK halt") == 0);
}

void full_buffer_boundary() {
  char payload[1800];
  std::memset(payload, 'x', sizeof(payload));
  std::memcpy(payload + sizeof(payload) - sizeof(" safety_interlock"),
              " safety_interlock", sizeof(" safety_interlock"));
  CHECK(std::strlen(payload) == sizeof(payload) - 1);
  check_boundaries(payload, "%s", payload);
}
}  // namespace

int main() {
  CHECK(std::setlocale(LC_ALL, "C") != nullptr);
  check_boundaries("OK stop", "%s", "OK stop");
  check_boundaries("ERR drive motor_watchdog_latched", "%s",
                   "ERR drive motor_watchdog_latched");
  numeric_boundaries();
  full_buffer_boundary();
  invalid_arguments();
}
