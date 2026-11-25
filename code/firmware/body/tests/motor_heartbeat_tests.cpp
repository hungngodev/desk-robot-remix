#include "MotorHeartbeat.h"
#include "TouchDebounce.h"
#include <stdexcept>
#define CHECK(expr) do { if (!(expr)) throw std::runtime_error(#expr); } while (false)
#include <cstdint>
#include <iostream>
#include <utility>

using desk_robot::MotorHeartbeat;

static_assert(noexcept(std::declval<MotorHeartbeat&>().reset()), "reset must not throw");
static_assert(noexcept(std::declval<const MotorHeartbeat&>().missed_deadline()), "deadline query must not throw");
static_assert(noexcept(std::declval<MotorHeartbeat&>().check_authority(0U, false)), "authority check must not throw");
static_assert(noexcept(std::declval<MotorHeartbeat&>().update(0U, false)), "heartbeat update must not throw");

// Model only the caller's authority input; BodyControl owns the actual leases.
// A long-running pulse train must neither hide a late CPU transition nor
// generate an extra edge when the caller revokes authority at its deadline.
void lease_boundary_handoff() {
  for (const std::uint32_t start : {100U, 0xfffffff0U}) {
    for (const std::uint32_t cutoff : {250U, 500U}) {
      for (const std::uint32_t elapsed : {cutoff - 1U, cutoff, cutoff + 1U}) {
        for (const std::uint32_t gap : {14U, 15U, 44U, 45U, 46U}) {
          for (const bool sensor_pass : {false, true}) {
            MotorHeartbeat heartbeat;
            const auto edge = elapsed - gap;
            const auto first = edge % 15U;
            bool high = true;
            for (auto t = first; t <= edge; t += 15U) {
              CHECK(heartbeat.update(start + t, true) == high);
              if (t != edge) high = !high;
            }
            const auto now = start + elapsed;
            const bool authorized = elapsed < cutoff;
            const bool missed = gap >= 45U;
            const bool expected = authorized && !missed &&
                (!sensor_pass || (gap < 15U ? high : !high));
            CHECK((sensor_pass ? heartbeat.update(now, authorized)
                               : heartbeat.check_authority(now, authorized)) == expected);
            CHECK(heartbeat.missed_deadline() == missed);
            if (!authorized || missed) {
              CHECK(!heartbeat.update(now + 1U, false));
              CHECK(heartbeat.missed_deadline() == missed);
              CHECK(heartbeat.update(now + 2U, true) == !missed);
            }
          }
        }
      }
    }
  }
}

using desk_robot::TouchDebounce;
static_assert(noexcept(std::declval<TouchDebounce&>().observe(false, 0U)),
              "raw touch observation must not throw");
static_assert(noexcept(std::declval<TouchDebounce&>().poll(false, 0U)),
              "touch polling must not throw");
static_assert(noexcept(std::declval<const TouchDebounce&>().stable()),
              "stable touch query must not throw");

// Both portable body timing policies use unsigned millisecond arithmetic.
void touch_timing_boundary() {
  for (const std::uint32_t start : {100U, 0xfffffff0U}) {
    TouchDebounce touch;
    CHECK(!touch.stable());
    touch.observe(true, start);
    CHECK(!touch.poll(true, start + 24U));
    CHECK(!touch.poll(true, start + 25U));
    CHECK(!touch.poll(true, start + 49U));
    CHECK(touch.poll(true, start + 50U));
    CHECK(touch.stable());
    touch.observe(false, start + 51U);
    touch.observe(true, start + 52U);  // raw bounce resets release candidate
    CHECK(!touch.poll(true, start + 102U));
    CHECK(touch.stable());
    touch.observe(false, start + 103U);
    CHECK(!touch.poll(false, start + 128U));
    CHECK(touch.poll(false, start + 153U));
    CHECK(!touch.stable());
  }
}

// A missed CPU deadline is sticky even after long idle periods or a clock
// wrap. Neither a fresh command nor a timestamp of zero is a local USB reset.
void sticky_deadline_across_idle_and_wrap() {
  for (const std::uint32_t start : {0U, 100U, 0xfffffff0U}) {
    for (const bool sensor_pass : {false, true}) {
      MotorHeartbeat heartbeat;
      CHECK(heartbeat.update(start, true));
      const auto fault_at = start + 45U;
      CHECK(!(sensor_pass ? heartbeat.update(fault_at, true)
                          : heartbeat.check_authority(fault_at, true)));
      CHECK(heartbeat.missed_deadline());
      for (const auto now : {fault_at + 1U, fault_at + 250U,
                            fault_at + 500U, fault_at + 10000U,
                            0xffffffffU, 0U, 1U}) {
        CHECK(!heartbeat.check_authority(now, false));
        CHECK(heartbeat.missed_deadline());
        CHECK(!heartbeat.check_authority(now, true));
        CHECK(!heartbeat.update(now, true));
        CHECK(heartbeat.missed_deadline());
      }
      heartbeat.reset();
      CHECK(!heartbeat.missed_deadline());
      CHECK(!heartbeat.update(2U, false));
      CHECK(heartbeat.check_authority(3U, true));
      CHECK(heartbeat.update(100U, true));
      CHECK(heartbeat.update(114U, true));
      CHECK(!heartbeat.update(115U, true));
    }
  }
}

int main() {
  sticky_deadline_across_idle_and_wrap();
  touch_timing_boundary();
  lease_boundary_handoff();
  MotorHeartbeat heartbeat;
  CHECK(!heartbeat.update(0, false));
  CHECK(heartbeat.update(100, true)); // first CPU motion sample starts pulses
  CHECK(heartbeat.update(114, true)); // not LEDC or timer-generated
  CHECK(!heartbeat.update(115, true));
  CHECK(!heartbeat.update(129, true));
  CHECK(heartbeat.update(130, true));
  // On a stalled CPU there are NO hardware heartbeat edges, even if the
  // last generated state remains HIGH. A physical retriggerable one-shot
  // must time out independently and hold DRV8833 nSLEEP LOW.
  CHECK(!heartbeat.update(131, false));
  CHECK(!heartbeat.update(900, false));
  CHECK(heartbeat.update(901, true));
  CHECK(!heartbeat.update(916, true));
  // Both a dock contact and local guard loss are passed as false.
  CHECK(!heartbeat.update(917, false));
  CHECK(heartbeat.update(0xfffffff5U, true));
  CHECK(!heartbeat.update(4U, true)); // millis wraps after 15 ms
  CHECK(!heartbeat.update(10U, false));
  CHECK(heartbeat.update(11U, true));
  heartbeat.reset();
  CHECK(heartbeat.update(20U, true));
  // Stall before the wheel lease expires. It cannot retrigger the one-shot.
  heartbeat.reset();
  CHECK(heartbeat.update(0U, true));
  CHECK(!heartbeat.update(15U, true));
  CHECK(!heartbeat.update(100U, true));
  CHECK(heartbeat.missed_deadline());
  CHECK(!heartbeat.update(101U, true));
  CHECK(!heartbeat.update(102U, false));
  CHECK(heartbeat.missed_deadline());
  heartbeat.reset(); // The actual WROOM calls reset only at local USB rearm.
  CHECK(!heartbeat.missed_deadline());
  CHECK(heartbeat.update(103U, true));
  heartbeat.reset();
  CHECK(heartbeat.update(0xfffffff0U, true));
  CHECK(!heartbeat.update(0xffffffffU, true));
  CHECK(!heartbeat.update(0x30U, true)); // Deadline across millis rollover.
  CHECK(heartbeat.missed_deadline());
  // A stalled loop can return after control.tick() has expired the drive.
  // Losing current permission must not discard the previous active deadline.
  heartbeat.reset();
  CHECK(heartbeat.update(200U, true));
  CHECK(!heartbeat.update(245U, false)); // exactly 45 ms, now unauthorized
  CHECK(heartbeat.missed_deadline());
  CHECK(!heartbeat.update(246U, true));
  heartbeat.reset();
  CHECK(heartbeat.update(247U, true));
  CHECK(!heartbeat.update(291U, false)); // timely stop, 44 ms
  CHECK(!heartbeat.missed_deadline());
  CHECK(!heartbeat.update(1000U, false)); // already idle, no missed deadline
  CHECK(heartbeat.update(1001U, true));
  heartbeat.reset();
  CHECK(heartbeat.update(0xfffffff0U, true));
  CHECK(!heartbeat.update(0x1dU, false)); // 45 ms across millis rollover
  CHECK(heartbeat.missed_deadline());
  CHECK(!heartbeat.update(0x1eU, true));
  // UART/output checks cannot start or refresh the pulse clock.
  heartbeat.reset();
  CHECK(heartbeat.check_authority(0U, true));
  CHECK(heartbeat.update(100U, true)); // no active heartbeat before sensor pass
  CHECK(heartbeat.check_authority(115U, true));
  CHECK(!heartbeat.update(115U, true)); // check did not toggle at 15 ms
  CHECK(heartbeat.check_authority(159U, true));
  CHECK(!heartbeat.check_authority(160U, true)); // deadline between sensor passes
  CHECK(heartbeat.missed_deadline());
  CHECK(!heartbeat.update(161U, true));
  CHECK(!heartbeat.check_authority(162U, false));
  CHECK(heartbeat.missed_deadline());
  heartbeat.reset();
  CHECK(heartbeat.update(200U, true));
  CHECK(!heartbeat.check_authority(244U, false)); // timely UART STOP
  CHECK(!heartbeat.missed_deadline());
  CHECK(heartbeat.check_authority(245U, true)); // new drive, still no edge
  CHECK(heartbeat.update(300U, true));
  heartbeat.reset();
  CHECK(heartbeat.update(0xfffffff0U, true));
  CHECK(!heartbeat.check_authority(0x1dU, false));
  CHECK(heartbeat.missed_deadline());
  // A command-path authority probe must not extend the CPU pulse deadline.
  // Cover both pin phases, both return paths and clock rollover. A resumed
  // valid command is not an explicit local safety reset.
  for (const std::uint32_t start : {100U, 0xfffffff0U}) {
    for (const bool high : {false, true}) {
      for (const bool authorized : {false, true}) {
        for (const bool sensor_pass : {false, true}) {
          for (std::uint32_t gap = 0; gap <= 60U; ++gap) {
            heartbeat.reset();
            CHECK(heartbeat.update(start, true));
            const std::uint32_t last_edge = high ? start : start + 15U;
            if (!high) CHECK(!heartbeat.update(last_edge, true));
            for (std::uint32_t t = 1; t < gap && t < 45U; ++t)
              CHECK(heartbeat.check_authority(last_edge + t, true));
            const std::uint32_t now = last_edge + gap;
            const bool result = sensor_pass ? heartbeat.update(now, authorized)
                                            : heartbeat.check_authority(now, authorized);
            const bool missed = gap >= 45U;
            CHECK(heartbeat.missed_deadline() == missed);
            const bool expected = authorized && !missed &&
                (!sensor_pass || (gap < 15U ? high : !high));
            CHECK(result == expected);
            if (missed) {
              CHECK(!heartbeat.check_authority(now + 1U, true));
              CHECK(!heartbeat.update(now + 2U, true));
              CHECK(!heartbeat.update(now + 3U, false));
              CHECK(heartbeat.missed_deadline());
              heartbeat.reset();
              CHECK(!heartbeat.missed_deadline());
              CHECK(!heartbeat.update(now + 4U, false));
              CHECK(heartbeat.update(now + 5U, true));
            }
          }
        }
      }
    }
  }
  std::cout << "PASS DC CPU heartbeat: stall latch, wrap, USB recovery\n";
}
