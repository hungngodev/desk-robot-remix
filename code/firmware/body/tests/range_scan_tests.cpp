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

static void check_slow_sweeps() {
  // Includes millis rollover, exact boundary, and recovery of optional cadence.
  for (std::uint32_t start : {0U, 0xfffffff0U}) {
    desk_robot::RangeScanOrder scan(true);
    for (int c = 0; c < 5; ++c) CHECK(scan.next(start + c * 20U, 200) == c);
    CHECK(scan.next(start + 100U, 200) == 0);
    for (int c = 1; c < 5; ++c) CHECK(scan.next(start + 100U + c * 5U, 200) == c);
    CHECK(scan.next(start + 125U, 200) == 5);
    for (int c = 0; c < 5; ++c) CHECK(scan.next(start + 130U + c * 2U, 30) == c);
    CHECK(scan.next(start + 144U, 30) == 6);
  }
}

static void check_fault_restart() {
  for (int phase = 0; phase < 18; ++phase) {
    desk_robot::RangeScanOrder scan(true);
    for (int i = 0; i < phase; ++i) scan.next();
    scan.restart_critical();
    for (int c = 0; c < 5; ++c) CHECK(scan.next() == c);
    CHECK(scan.next() == 5 + (phase / 6) % 3);
  }
}

static void check_transport_recovery() {
  for (bool full_eight : {false, true}) {
    for (unsigned failure_lane = 0; failure_lane < 5; ++failure_lane) {
      desk_robot::RangeScanOrder scan(full_eight);
      CHECK(!scan.degraded());
      scan.transport_fault();
      for (unsigned lane = 0; lane < 5; ++lane) {
        CHECK(scan.next() == lane);
        scan.transport_succeeded(lane);
        CHECK(scan.degraded());
      }
      if (full_eight) scan.transport_succeeded(scan.next());
      for (unsigned lane = 0; lane < failure_lane; ++lane) {
        CHECK(scan.next() == lane);
        scan.transport_succeeded(lane);
      }
      scan.transport_fault();
      for (unsigned i = 0; i < 20; ++i) {
        scan.transport_succeeded(0);
        scan.transport_succeeded(5);
        CHECK(scan.degraded());
      }
      // A persistent NACK cannot be masked by a healthy partial sweep.
      for (unsigned i = 0; i < 20; ++i) {
        for (unsigned lane = 0; lane < failure_lane; ++lane) {
          CHECK(scan.next() == lane);
          scan.transport_succeeded(lane);
        }
        scan.transport_fault();
        CHECK(scan.degraded());
      }
      for (unsigned sweep = 0; sweep < 2; ++sweep) {
        for (unsigned lane = 0; lane < 5; ++lane) {
          CHECK(scan.next() == lane);
          scan.transport_succeeded(lane);
          CHECK(scan.degraded() == (sweep == 0 || lane < 4));
        }
        if (full_eight) scan.transport_succeeded(scan.next());
      }
      scan.transport_fault();
      CHECK(scan.degraded());
      scan.reset();
      CHECK(!scan.degraded());
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
    check_slow_sweeps();
    check_fault_restart();
    check_transport_recovery();
    std::cout << "PASS all 5 critical ToF channels sampled before one optional direction\n";
    return 0;
  } catch (const std::exception& e) {
    std::cerr << "FAIL " << e.what() << '\n';
    return 1;
  }
}
