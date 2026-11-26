#include "HapticPulse.h"
#include <stdexcept>
#include <cstdint>
#include <iostream>
#include <initializer_list>
using desk_robot::HapticPulse;

#define CHECK(condition) do { if (!(condition)) throw std::runtime_error(#condition); } while (false)

// GPB2 schedules an edge, not the physical motor's waveform or amplitude.
// The independent one-shot owns physical pulse duration.
static void check_timing_boundaries(std::uint32_t start) {
  using Action = HapticPulse::Action;
  HapticPulse h;
  h.configure(true);
  CHECK(h.request(start));
  CHECK(h.next(start + 250U, true) == Action::TurnOn);
  const std::uint32_t ack = start + 250U;
  h.completed(Action::TurnOn, true, ack);
  CHECK(h.active());
  CHECK(h.next(ack, false) == Action::TurnOff);
  h.completed(Action::TurnOff, true, ack);
  CHECK(h.next(ack + 1U, true) == Action::None);
  CHECK(!h.request(ack + 1499U));
  CHECK(h.request(ack + 1500U));
  CHECK(h.next(ack + 1751U, true) == Action::None);
  CHECK(h.next(ack + 1752U, true) == Action::None);
  CHECK(h.request(ack + 1752U));
}

static void check_failed_edge_and_reconfigure() {
  using Action = HapticPulse::Action;
  HapticPulse h;
  h.configure(true);
  CHECK(h.request(10));
  CHECK(h.next(20, true) == Action::TurnOn);
  h.completed(Action::TurnOn, false, 20);
  CHECK(!h.ready() && !h.active());
  CHECK(h.next(21, true) == Action::None);
  CHECK(!h.request(2000));
  h.configure(false);
  CHECK(!h.ready() && !h.request(2001));
  h.configure(true);
  CHECK(h.next(2002, true) == Action::None);
  CHECK(h.request(2003));
  h.configure(true);
  CHECK(h.next(2004, true) == Action::None);
  CHECK(h.request(2005));
  CHECK(h.next(2006, false) == Action::None);
  CHECK(h.next(2007, true) == Action::None);
}

// A delayed LOW is still mandatory, but must not restore edge authority.
static void check_stalled_high(std::uint32_t start) {
  using Action = HapticPulse::Action;
  for (std::uint32_t delay : {250U, 251U, 1500U, 5000U}) {
    HapticPulse h;
    h.configure(true);
    CHECK(h.request(start));
    CHECK(h.next(start, true) == Action::TurnOn);
    h.completed(Action::TurnOn, true, start);
    for (std::uint32_t elapsed = 1; elapsed <= delay; ++elapsed) {
      CHECK(!h.request(start + elapsed));
    }
    CHECK(h.next(start + delay, false) == Action::TurnOff);
    h.completed(Action::TurnOff, true, start + delay);
    CHECK(!h.active());
    CHECK(h.ready() == (delay == 250U));
    CHECK(h.request(start + 6000U) == (delay == 250U));
    if (delay > 250U) {
      CHECK(h.next(start + 6001U, true) == Action::None);
      h.configure(true);
      CHECK(h.request(start + 6002U));
    }
  }
}

// A software fault or failed LOW acknowledgment must discard the active
// scheduler state. The bus owner still owes a verified physical LOW retry.
static void check_active_fault(std::uint32_t start) {
  using Action = HapticPulse::Action;
  for (bool failed_low : {false, true}) {
    HapticPulse h;
    h.configure(true);
    CHECK(h.request(start));
    CHECK(h.next(start, true) == Action::TurnOn);
    h.completed(Action::TurnOn, true, start);
    CHECK(h.active());
    if (failed_low) {
      CHECK(h.next(start + 1U, false) == Action::TurnOff);
      h.completed(Action::TurnOff, false, start + 1U);
    } else {
      h.fault();
    }
    CHECK(!h.active() && !h.ready());
    CHECK(!h.request(start + 1500U));
    CHECK(h.next(start + 1501U, true) == Action::None);
    // A later successful LOW retry is not permission to start again.
    h.completed(Action::TurnOff, true, start + 1502U);
    CHECK(!h.active() && !h.ready());
    CHECK(!h.request(start + 3000U));
    h.configure(true);
    CHECK(h.next(start + 3001U, true) == Action::None);
    CHECK(h.request(start + 3002U));
  }
}

// A safety veto between lane-5 visits must discard queued HIGH edges but
// leave an already acknowledged HIGH eligible for the next LOW write.
static void check_safety_suppression(std::uint32_t start) {
  using Action = HapticPulse::Action;
  HapticPulse h;
  h.configure(true);
  CHECK(h.request(start));
  h.cancel_pending();
  CHECK(h.next(start + 1U, true) == Action::None);
  CHECK(h.request(start + 2U));
  CHECK(h.next(start + 3U, true) == Action::TurnOn);
  h.completed(Action::TurnOn, true, start + 3U);
  h.cancel_pending();
  CHECK(h.active());
  CHECK(h.next(start + 4U, false) == Action::TurnOff);
  h.completed(Action::TurnOff, true, start + 4U);
  CHECK(!h.active());
  CHECK(h.next(start + 5U, true) == Action::None);
  CHECK(!h.request(start + 1502U));
  CHECK(h.request(start + 1503U));
  h.cancel_pending();
  CHECK(h.next(start + 1504U, true) == Action::None);
}

// Simulate continuous local requests without host traffic. Each acknowledged
// edge consumes the full cooldown; suppressing a queued edge or disconnect
// fault must not enable an extra edge. This is not a physical duty-cycle test.
static void check_request_storm(std::uint32_t start) {
  using Action = HapticPulse::Action;
  HapticPulse h;
  h.configure(true);
  std::uint32_t edges = 0;
  for (std::uint32_t elapsed = 0; elapsed < 60000U; ++elapsed) {
    const auto now = start + elapsed;
    const bool expected_start = elapsed % 1500U == 0;
    CHECK(h.request(now) == expected_start);
    const auto action = h.next(now, true);
    if (expected_start) {
      CHECK(action == Action::TurnOn);
      h.completed(action, true, now);
      ++edges;
    } else if (elapsed % 1500U == 1U) {
      h.cancel_pending();
      CHECK(action == Action::TurnOff);
      CHECK(h.next(now, false) == Action::TurnOff);
      h.completed(action, true, now);
    } else {
      CHECK(action == Action::None);
    }
  }
  CHECK(edges == 40U && !h.active());
  CHECK(h.request(start + 60000U));
  h.fault();
  for (std::uint32_t elapsed = 60000U; elapsed < 65000U; ++elapsed) {
    const auto now = start + elapsed;
    CHECK(!h.request(now));
    CHECK(h.next(now, true) == Action::None);
  }
  // A late successful LOW retry cannot rearm a faulted scheduler.
  h.completed(Action::TurnOff, true, start + 65000U);
  CHECK(!h.ready() && !h.request(start + 65001U));
}

int main() try {
 check_request_storm(100U);
 check_request_storm(0xfffffff0U);
 check_safety_suppression(100U);
 check_safety_suppression(0xfffffffeU);
 check_active_fault(100U);
 check_active_fault(0xfffffffeU);
 check_stalled_high(100U);
 check_stalled_high(0xffffff80U);
 check_timing_boundaries(100U);
 check_timing_boundaries(0xffffff80U);
 check_failed_edge_and_reconfigure();
 HapticPulse h;
 CHECK(!h.request(10));
 h.configure(true);
 CHECK(h.request(100));
 CHECK(!h.request(101));
 CHECK(h.next(120,false)==HapticPulse::Action::None);
 CHECK(!h.active());
 CHECK(h.request(130));
 CHECK(h.next(180,true)==HapticPulse::Action::TurnOn);
 h.completed(HapticPulse::Action::TurnOn,true,180);
 CHECK(h.active());
 CHECK(!h.request(181));
 CHECK(h.next(270,false)==HapticPulse::Action::TurnOff);
 h.completed(HapticPulse::Action::TurnOff,true,270);
 CHECK(!h.active());
 CHECK(!h.request(500));
 CHECK(h.request(1680));
 CHECK(h.next(1931,true)==HapticPulse::Action::None);
 CHECK(h.request(1950));
 CHECK(h.next(1990,true)==HapticPulse::Action::TurnOn);
 h.completed(HapticPulse::Action::TurnOn,true,1990);
 CHECK(h.next(2080,false)==HapticPulse::Action::TurnOff);
 h.completed(HapticPulse::Action::TurnOff,false,2080);
 CHECK(!h.ready());
 CHECK(!h.request(4000));
 h.configure(true);
 CHECK(h.request(0xfffffffaU));
 CHECK(h.next(4U,true)==HapticPulse::Action::TurnOn);
 h.completed(HapticPulse::Action::TurnOn,true,4);
 CHECK(h.next(100,true)==HapticPulse::Action::TurnOff);
 h.completed(HapticPulse::Action::TurnOff,true,100);
 CHECK(!h.request(1499));
 CHECK(h.request(1504));
 h.fault();
 CHECK(h.next(1520,true)==HapticPulse::Action::None);
 std::cout<<"PASS haptic requests, cooldown, dock gating, fault, wrap\n";
} catch (const std::exception& error) {
  std::cerr << "FAIL " << error.what() << '\n';
  return 1;
}
