#include "RangeScanOrder.h"

#include <iostream>
#include <stdexcept>

#define CHECK(expr) do { if (!(expr)) throw std::runtime_error(#expr); } while (false)

// Count poll opportunities, not milliseconds or completed conversions. A
// not-ready sensor still consumes its scheduled opportunity in TofBus::poll.
static void check_windows(bool full_eight) {
  const int channels = full_eight ? 8 : 5;
  const int period = full_eight ? 18 : 5;
  const int critical_gap = full_eight ? 6 : 5;
  for (int phase = 0; phase < period; ++phase) {
    desk_robot::RangeScanOrder scan(full_eight);
    for (int i = 0; i < phase; ++i) scan.next();
    unsigned int critical_seen = 0;
    unsigned int all_seen = 0;
    for (int i = 0; i < period; ++i) {
      const auto channel = scan.next();
      CHECK(channel < channels);
      all_seen |= 1U << channel;
      if (i < critical_gap && channel < 5) critical_seen |= 1U << channel;
    }
    CHECK(critical_seen == 0x1FU);
    CHECK(all_seen == (1U << channels) - 1U);

    // Restart from every possible phase, including after an optional lane.
    scan.reset();
    for (int i = 0; i < period; ++i) {
      const int expected = full_eight && i % 6 == 5 ? 5 + i / 6 :
                           full_eight ? i % 6 : i % 5;
      CHECK(scan.next() == expected);
    }
  }
}

int main() {
  try {
    desk_robot::RangeScanOrder five(false);
    for (int i = 0; i < 100; ++i)
      CHECK(five.next() == i % 5);
    desk_robot::RangeScanOrder eight(true);
    for (int cycle = 0; cycle < 100; ++cycle) {
      for (int c = 0; c < 5; ++c) CHECK(eight.next() == c);
      CHECK(eight.next() == 5 + cycle % 3);
    }
    eight.reset();
    for (int i = 0; i < 5; ++i) CHECK(eight.next() == i);
    CHECK(eight.next() == 5);
    check_windows(false);
    check_windows(true);
    std::cout << "PASS all 5 critical ToF channels sampled before one optional direction\n";
    return 0;
  } catch (const std::exception& e) {
    std::cerr << "FAIL " << e.what() << '\n';
    return 1;
  }
}
