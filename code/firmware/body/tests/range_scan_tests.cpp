#include "RangeScanOrder.h"
#include "TofResult.h"

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
      // Optional lanes are not scheduled during recovery.
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
        if (full_eight && sweep == 1) CHECK(scan.next() == 5);
      }
      scan.transport_fault();
      CHECK(scan.degraded());
      scan.reset();
      CHECK(!scan.degraded());
    }
  }
}

// Accessory mux addresses and all other noncritical identifiers must never
// be interpreted as floor/front recovery evidence, even between valid lanes.
static void check_noncritical_recovery_isolation() {
  for (bool full_eight : {false, true}) {
    desk_robot::RangeScanOrder scan(full_eight);
    scan.transport_fault();
    for (unsigned sweep = 0; sweep < 2; ++sweep) {
      for (std::uint8_t lane = 0; lane < 5; ++lane) {
        for (unsigned id = 5; id <= 255; ++id) {
          scan.transport_succeeded(static_cast<std::uint8_t>(id));
          CHECK(scan.degraded());
        }
        CHECK(scan.next() == lane);
        scan.transport_succeeded(lane);
        CHECK(scan.degraded() == (sweep == 0 || lane < 4));
      }
    }
    for (unsigned id = 5; id <= 255; ++id) {
      scan.transport_succeeded(static_cast<std::uint8_t>(id));
      CHECK(!scan.degraded());
    }
    CHECK(scan.next() == (full_eight ? 5 : 0));
  }
}

// Exercise every optional rotation and every fault phase, including a slow
// second recovery sweep at the exact half-window boundary across rollover.
static void check_recovery_budget_and_rotation() {
  for (std::uint32_t base : {0U, 0xfffffff0U}) {
    for (unsigned phase = 0; phase < 18; ++phase) {
      for (bool slow : {false, true}) {
        desk_robot::RangeScanOrder scan(true);
        for (unsigned i = 0; i < phase; ++i) scan.next(base);
        scan.transport_fault();
        for (unsigned sweep = 0; sweep < 2; ++sweep) {
          for (unsigned lane = 0; lane < 5; ++lane) {
            const auto now = base + sweep * 100U + lane * (slow ? 20U : 1U);
            CHECK(scan.next(now, 200U) == lane);
            scan.transport_succeeded(lane);
            CHECK(scan.degraded() == (sweep == 0 || lane < 4));
          }
        }
        const auto boundary = base + (slow ? 200U : 105U);
        if (slow) {
          for (unsigned lane = 0; lane < 5; ++lane)
            CHECK(scan.next(boundary + lane, 200U) == lane);
        }
        const auto optional_at = boundary + (slow ? 5U : 0U);
        CHECK(scan.next(optional_at, 200U) == 5U + (phase / 6U) % 3U);
      }
    }
  }
}

// The device reports raw millimeters. No software offset is authorized here.
// Test every wire word, including 0..15 and their hypothetical wrapped
// values after subtracting 20 mm. Neither may become valid clearance.
static void check_raw_range_word_domain() {
  for (std::uint32_t mm = 0; mm <= 65535U; ++mm) {
    std::uint8_t raw[12]{};
    raw[0] = 11U << 3;
    raw[7] = 32;
    raw[10] = static_cast<std::uint8_t>(mm >> 8);
    raw[11] = static_cast<std::uint8_t>(mm);
    const auto result = desk_robot::decode_tof_result(raw);
    CHECK(result.distance_mm == mm);
    CHECK(result.accepted == (mm >= 30U && mm <= 1300U));
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
    check_noncritical_recovery_isolation();
    check_recovery_budget_and_rotation();
    check_raw_range_word_domain();
    std::cout << "PASS all 5 critical ToF channels sampled before one optional direction\n";
    return 0;
  } catch (const std::exception& e) {
    std::cerr << "FAIL " << e.what() << '\n';
    return 1;
  }
}
