#include "StepperDrive.h"

#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

using desk_robot::StepperDrive;

namespace {
#define CHECK(expression)                                                        \
  do {                                                                          \
    if (!(expression))                                                          \
      throw std::runtime_error(std::string(__FILE__) + ":" +                      \
                               std::to_string(__LINE__) + ": " #expression);    \
  } while (false)

constexpr std::uint8_t kPhases[] = {1, 3, 2, 6, 4, 12, 8, 9};

void run_until(StepperDrive& drive, std::uint32_t start,
               std::uint32_t duration, int percent) {
  for (std::uint32_t elapsed = 1000; elapsed <= duration; elapsed += 1000)
    drive.update(start + elapsed, percent, true);
}

void boot_and_start_delay() {
  StepperDrive drive;
  CHECK(drive.mask() == 0 && drive.rate_milli_steps_per_second() == 0);
  CHECK(drive.update(0, 40, false) == 0);
  CHECK(drive.update(10, 0, true) == 0);
  CHECK(drive.update(100, 40, true) == 1);
  CHECK(drive.rate_milli_steps_per_second() == 0);
  run_until(drive, 100, 30000, 40);
  CHECK(drive.mask() == 1);  // No instantaneous step on startup.
  CHECK(drive.rate_milli_steps_per_second() > 0);
}

void sequence(int direction) {
  StepperDrive drive;
  CHECK(drive.update(0, direction * 40, true) == kPhases[0]);
  int index = 0;
  int changes = 0;
  std::uint8_t previous = drive.mask();
  for (std::uint32_t now = 1000; now <= 1000000; now += 1000) {
    const auto mask = drive.update(now, direction * 40, true);
    if (mask != previous) {
      index = (index + direction + 8) % 8;
      CHECK(mask == kPhases[index]);
      ++changes;
      previous = mask;
    }
  }
  CHECK(changes >= 16);
  CHECK(drive.rate_milli_steps_per_second() == direction * 160000);
}

void positive_sequence() { sequence(1); }
void negative_sequence() { sequence(-1); }

void zero_and_disable_coast_preserve_phase() {
  StepperDrive drive;
  drive.update(0, 40, true);
  run_until(drive, 0, 200000, 40);
  const auto retained = drive.mask();
  CHECK(retained != 0);
  CHECK(drive.update(200001, 0, true) == 0);
  CHECK(drive.rate_milli_steps_per_second() == 0);
  CHECK(drive.update(200002, 40, true) == retained);
  CHECK(drive.rate_milli_steps_per_second() == 0);
  CHECK(drive.update(200003, 40, false) == 0);
  CHECK(drive.rate_milli_steps_per_second() == 0);
  CHECK(drive.update(900000, -40, false) == 0);
  CHECK(drive.update(900001, -40, true) == retained);
  CHECK(drive.update(900001, -40, true) == retained);
}

// STOP (zero demand) and HALT/fault (disabled) must coast every phase,
// even at the same timestamp as an energized output. No idle holding current.
void every_phase_releases_immediately() {
  for (const std::uint32_t origin : {0U, 0xffff0000U}) {
    for (const int direction : {-1, 1}) {
      for (const bool enabled : {false, true}) {
        for (const auto phase : kPhases) {
          StepperDrive drive;
          const int requested = direction * 40;
          drive.update(origin, requested, true);
          run_until(drive, origin, 600000U, requested);
          auto now = origin + 600000U;
          for (int step = 0; step < 8 && drive.mask() != phase; ++step) {
            now += 6250U;
            drive.update(now, requested, true);
          }
          CHECK(drive.mask() == phase);
          CHECK(drive.rate_milli_steps_per_second() == direction * 160000);
          const int stopped_request = enabled ? 0 : -requested;
          CHECK(drive.update(now, stopped_request, enabled) == 0);
          CHECK(drive.mask() == 0);
          CHECK(drive.rate_milli_steps_per_second() == 0);
          for (const std::uint32_t delay : {0U, 1U, 250000U, 500000U, 60000000U}) {
            CHECK(drive.update(now + delay, stopped_request, enabled) == 0);
            CHECK(drive.mask() == 0);
            CHECK(drive.rate_milli_steps_per_second() == 0);
          }
          // A fresh authorized command must start from rest, not repay old steps.
          now += 60000000U;
          CHECK(drive.update(now, -requested, true) == phase);
          CHECK(drive.rate_milli_steps_per_second() == 0);
          CHECK(drive.update(now, -requested, true) == phase);
          CHECK(drive.rate_milli_steps_per_second() == 0);
        }
      }
    }
  }
}

void speed_limit_and_integer_extremes() {
  StepperDrive positive;
  StepperDrive negative;
  positive.update(0, std::numeric_limits<int>::max(), true);
  negative.update(0, std::numeric_limits<int>::min(), true);
  for (std::uint32_t now = 1000; now <= 1000000; now += 1000) {
    positive.update(now, std::numeric_limits<int>::max(), true);
    negative.update(now, std::numeric_limits<int>::min(), true);
    CHECK(positive.rate_milli_steps_per_second() >= 0);
    CHECK(positive.rate_milli_steps_per_second() <= 160000);
    CHECK(negative.rate_milli_steps_per_second() <= 0);
    CHECK(negative.rate_milli_steps_per_second() >= -160000);
  }
  CHECK(positive.rate_milli_steps_per_second() == 160000);
  CHECK(negative.rate_milli_steps_per_second() == -160000);
}

void acceleration_and_reversal_through_zero() {
  StepperDrive drive;
  drive.update(0, 40, true);
  int previous_rate = 0;
  for (std::uint32_t now = 1000; now <= 600000; now += 1000) {
    drive.update(now, 40, true);
    const int rate = drive.rate_milli_steps_per_second();
    CHECK(rate >= previous_rate && rate - previous_rate <= 320);
    previous_rate = rate;
  }
  CHECK(previous_rate == 160000);
  bool observed_zero = false;
  for (std::uint32_t now = 601000; now <= 1800000; now += 1000) {
    drive.update(now, -40, true);
    const int rate = drive.rate_milli_steps_per_second();
    CHECK(rate <= previous_rate && previous_rate - rate <= 320);
    if (rate == 0) observed_zero = true;
    if (rate < 0) CHECK(observed_zero);
    CHECK(drive.mask() != 0);  // No phase-index reset/coast during a reversal.
    previous_rate = rate;
  }
  CHECK(observed_zero && previous_rate == -160000);
}

void small_commands_and_no_zero_time_ramp() {
  StepperDrive drive;
  drive.update(100, 1, true);
  CHECK(drive.update(100, 1, true) == 1);
  CHECK(drive.rate_milli_steps_per_second() == 0);
  run_until(drive, 100, 300000, 1);
  CHECK(drive.rate_milli_steps_per_second() == 4000);
  CHECK(drive.mask() == 3);
}

void long_stall_does_not_catch_up() {
  StepperDrive drive;
  drive.update(0, 40, true);
  run_until(drive, 0, 1000000, 40);
  const auto before_stall = drive.mask();
  int index = 0;
  while (kPhases[index] != before_stall) ++index;
  const auto after_stall = drive.update(5000000, 40, true);
  CHECK(after_stall == kPhases[(index + 1) % 8]);
  for (int calls = 0; calls < 100; ++calls)
    CHECK(drive.update(5000000, 40, true) == after_stall);
  CHECK(drive.update(5006249, 40, true) == after_stall);
  CHECK(drive.update(5006250, 40, true) == kPhases[(index + 2) % 8]);

  StepperDrive slow;
  slow.update(0, 40, true);
  slow.update(10000000, 40, true);
  CHECK(slow.rate_milli_steps_per_second() == 6400);  // Ramp advances at most20ms.
}

void irregular_cadence_reversal_preserves_phase_order() {
  StepperDrive drive;
  std::uint32_t now = std::numeric_limits<std::uint32_t>::max() - 30000U;
  auto previous = drive.update(now, 40, true);
  int phase = 0;
  int previous_rate = 0;
  int forward_steps = 0;
  int reverse_steps = 0;
  constexpr std::uint32_t gaps[] = {250, 1000, 6250, 9000, 20000, 37000};
  for (int i = 0; i < 600; ++i) {
    const int requested = (i / 100) % 2 == 0 ? 40 : -40;
    const auto gap = gaps[i % 6];
    now += gap;
    const auto mask = drive.update(now, requested, true);
    const int rate = drive.rate_milli_steps_per_second();
    const auto capped = gap < 20000U ? gap : 20000U;
    const int max_delta = static_cast<int>((capped * 320U + 999U) / 1000U);
    CHECK(std::abs(rate - previous_rate) <= max_delta);
    CHECK(!(previous_rate > 0 && rate < 0));
    CHECK(!(previous_rate < 0 && rate > 0));
    if (mask != previous) {
      CHECK(rate != 0);
      phase = (phase + (rate > 0 ? 1 : 7)) % 8;
      CHECK(mask == kPhases[phase]);
      if (rate > 0) ++forward_steps;
      else ++reverse_steps;
    }
    CHECK(drive.update(now, requested, true) == mask);
    CHECK(drive.rate_milli_steps_per_second() == rate);
    previous = mask;
    previous_rate = rate;
  }
  CHECK(forward_steps > 0 && reverse_steps > 0);
  CHECK(drive.update(now, 40, false) == 0);
  CHECK(drive.rate_milli_steps_per_second() == 0);
  CHECK(drive.update(now, -40, true) == previous);
  CHECK(drive.rate_milli_steps_per_second() == 0);
}

// These are logical coil-mask deadlines, not measured shaft motion or ISR time.
void steady_rate_phase_spacing() {
  constexpr std::uint32_t period_us = 6250;  // 160 half-steps/s.
  for (int direction : {1, -1}) {
    StepperDrive drive;
    const auto origin = std::numeric_limits<std::uint32_t>::max() - 650000U;
    const int requested = direction * 40;
    drive.update(origin, requested, true);
    run_until(drive, origin, 600000, requested);
    CHECK(drive.rate_milli_steps_per_second() == direction * 160000);
    auto previous = drive.mask();
    int phase = 0;
    while (phase < 8 && kPhases[phase] != previous) ++phase;
    CHECK(phase < 8);

    // Synchronize to an observed transition after a delayed poll. A delayed
    // call may advance one phase, never repay a backlog of missed steps.
    std::uint32_t now = origin + 640000U;
    phase = (phase + direction + 8) % 8;
    previous = drive.update(now, requested, true);
    CHECK(previous == kPhases[phase]);
    const auto start = now;
    for (int step = 0; step < 160; ++step) {
      CHECK(drive.update(now + period_us - 1, requested, true) == previous);
      now += period_us;
      phase = (phase + direction + 8) % 8;
      previous = drive.update(now, requested, true);
      CHECK(previous == kPhases[phase]);
      CHECK(drive.update(now, requested, true) == previous);
    }
    CHECK(now - start == 1000000U);  // Also crosses micros() rollover.

    // Irregular calls, including long pauses and identical timestamps, must
    // still enforce the minimum interval between actual mask transitions.
    constexpr std::uint32_t gaps[] = {0, 1, 6248, 1, 1, 37000, 6249, 1};
    auto last_edge = now;
    for (int repeat = 0; repeat < 20; ++repeat) {
      for (const auto gap : gaps) {
        now += gap;
        const bool due = now - last_edge >= period_us;
        if (due) {
          phase = (phase + direction + 8) % 8;
          last_edge = now;
        }
        CHECK(drive.update(now, requested, true) == kPhases[phase]);
        CHECK(drive.rate_milli_steps_per_second() == direction * 160000);
      }
    }
  }
}

void fractional_period_rounds_up() {
  // Every nonzero command below the ceiling must use the ceiling of the
  // fractional microsecond period, not a truncated (too-fast) interval.
  for (int percent = 1; percent < 40; ++percent) {
    const auto rate = static_cast<std::uint32_t>(percent * 4);
    const auto period_us = (1000000U + rate - 1U) / rate;
    for (int direction : {1, -1}) {
      StepperDrive drive;
      const int requested = direction * percent;
      drive.update(0, requested, true);
      run_until(drive, 0, 600000, requested);
      CHECK(drive.rate_milli_steps_per_second() == direction * percent * 4000);
      int phase = 0;
      const auto before = drive.mask();
      while (phase < 8 && kPhases[phase] != before) ++phase;
      CHECK(phase < 8);
      constexpr std::uint32_t edge = 1000000U;
      phase = (phase + direction + 8) % 8;
      CHECK(drive.update(edge, requested, true) == kPhases[phase]);
      CHECK(drive.update(edge + period_us - 1U, requested, true) == kPhases[phase]);
      phase = (phase + direction + 8) % 8;
      CHECK(drive.update(edge + period_us, requested, true) == kPhases[phase]);
    }
  }
}

void rate_ceiling_during_ramp_and_reversal() {
  for (int sign : {1, -1}) {
    StepperDrive drive;
    std::uint32_t now = std::numeric_limits<std::uint32_t>::max() - 500000U;
    auto previous = drive.update(now, sign * 40, true);
    auto last_edge = now;
    int changes = 0;
    for (int i = 0; i < 10000; ++i) {
      now += i % 97 == 0 ? 37000U : 137U;
      const int direction = (i / 2000) % 2 ? -sign : sign;
      const int requested = direction > 0 ? std::numeric_limits<int>::max()
                                          : std::numeric_limits<int>::min();
      const auto mask = drive.update(now, requested, true);
      const auto rate = drive.rate_milli_steps_per_second();
      CHECK(rate >= -160000 && rate <= 160000);
      if (mask != previous) {
        CHECK(now - last_edge >= 6250U);
        last_edge = now;
        previous = mask;
        ++changes;
      }
    }
    CHECK(changes > 100);
  }
}

// Fast polls must accumulate fractional milli-step rates without losing
// elapsed microseconds, including reversal and micros() rollover.
void microsecond_ramp_accumulates_without_rounding() {
  for (const std::uint32_t start : {100U, 0xfffffff0U}) {
    for (const int sign : {-1, 1}) {
      StepperDrive drive;
      CHECK(drive.update(start, sign * 40, true) == kPhases[0]);
      for (std::uint32_t elapsed = 1; elapsed <= 1000U; ++elapsed) {
        const int expected = sign * static_cast<int>(elapsed * 320U / 1000U);
        CHECK(drive.update(start + elapsed, sign * 40, true) == kPhases[0]);
        CHECK(drive.rate_milli_steps_per_second() == expected);
        CHECK(drive.update(start + elapsed, sign * 40, true) == kPhases[0]);
        CHECK(drive.rate_milli_steps_per_second() == expected);
      }
      for (std::uint32_t elapsed = 1; elapsed <= 1000U; ++elapsed) {
        const int expected = sign * static_cast<int>((1000U - elapsed) * 320U / 1000U);
        CHECK(drive.update(start + 1000U + elapsed, -sign * 40, true) == kPhases[0]);
        CHECK(drive.rate_milli_steps_per_second() == expected);
      }
      for (std::uint32_t elapsed = 1; elapsed <= 1000U; ++elapsed) {
        const int expected = -sign * static_cast<int>(elapsed * 320U / 1000U);
        CHECK(drive.update(start + 2000U + elapsed, -sign * 40, true) == kPhases[0]);
        CHECK(drive.rate_milli_steps_per_second() == expected);
      }
      CHECK(drive.update(start + 3000U, -sign * 40, false) == 0);
      CHECK(drive.rate_milli_steps_per_second() == 0);
    }
  }
}

// Polling diagnostics must not alter the subsequent motor phase/ramp trace.
void telemetry_getters_preserve_drive_trace() {
  StepperDrive polled;
  StepperDrive reference;
  const StepperDrive& telemetry = polled;
  const std::uint32_t origin = 0xffff0000U;
  for (std::uint32_t i = 0; i < 2400; ++i) {
    const auto now = origin + i * 1000U;
    const int requested = i < 800 ? 40 : -40;
    const bool enabled = i < 1600 || i >= 1800;
    const auto expected = reference.update(now, requested, enabled);
    CHECK(polled.update(now, requested, enabled) == expected);
    const int rate = reference.rate_milli_steps_per_second();
    for (int read = 0; read < 32; ++read) {
      CHECK(telemetry.mask() == expected);
      CHECK(telemetry.rate_milli_steps_per_second() == rate);
    }
  }
}

void clock_rollover_matches_normal_clock() {
  StepperDrive normal;
  StepperDrive wrapped;
  const auto origin = std::numeric_limits<std::uint32_t>::max() - 50000U;
  normal.update(0, 40, true);
  wrapped.update(origin, 40, true);
  for (std::uint32_t elapsed = 1000; elapsed <= 1500000; elapsed += 1000) {
    CHECK(normal.update(elapsed, 40, true) == wrapped.update(origin + elapsed, 40, true));
    CHECK(normal.rate_milli_steps_per_second() == wrapped.rate_milli_steps_per_second());
  }
}
}  // namespace

int main(int argc, char** argv) {
  using Test = std::pair<const char*, void (*)()>;
  const std::vector<Test> tests = {
      {"boot_and_start_delay", boot_and_start_delay},
      {"positive_sequence", positive_sequence},
      {"negative_sequence", negative_sequence},
      {"zero_and_disable_coast_preserve_phase", zero_and_disable_coast_preserve_phase},
      {"every_phase_releases_immediately", every_phase_releases_immediately},
      {"speed_limit_and_integer_extremes", speed_limit_and_integer_extremes},
      {"acceleration_and_reversal_through_zero", acceleration_and_reversal_through_zero},
      {"small_commands_and_no_zero_time_ramp", small_commands_and_no_zero_time_ramp},
      {"long_stall_does_not_catch_up", long_stall_does_not_catch_up},
      {"irregular_cadence_reversal_preserves_phase_order",
       irregular_cadence_reversal_preserves_phase_order},
      {"steady_rate_phase_spacing", steady_rate_phase_spacing},
      {"fractional_period_rounds_up", fractional_period_rounds_up},
      {"rate_ceiling_during_ramp_and_reversal", rate_ceiling_during_ramp_and_reversal},
      {"microsecond_ramp_accumulates_without_rounding",
       microsecond_ramp_accumulates_without_rounding},
      {"telemetry_getters_preserve_drive_trace", telemetry_getters_preserve_drive_trace},
      {"clock_rollover_matches_normal_clock", clock_rollover_matches_normal_clock}};
  int ran = 0;
  for (const auto& test : tests) {
    if (argc > 1 && std::strcmp(argv[1], test.first) != 0) continue;
    try {
      test.second();
      ++ran;
      std::cout << "PASS " << test.first << '\n';
    } catch (const std::exception& error) {
      std::cerr << "FAIL " << test.first << ": " << error.what() << '\n';
      return EXIT_FAILURE;
    }
  }
  return ran == 0 ? EXIT_FAILURE : EXIT_SUCCESS;
}
