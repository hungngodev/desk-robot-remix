#include "HapticPulse.h"
#include <cassert>
#include <cstdint>
#include <iostream>
using desk_robot::HapticPulse;

// GPB2 schedules an edge, not the physical motor's waveform or amplitude.
// The independent one-shot owns physical pulse duration.
static void check_timing_boundaries(std::uint32_t start) {
  using Action = HapticPulse::Action;
  HapticPulse h;
  h.configure(true);
  assert(h.request(start));
  assert(h.next(start + 250U, true) == Action::TurnOn);
  const std::uint32_t ack = start + 250U;
  h.completed(Action::TurnOn, true, ack);
  assert(h.active());
  assert(h.next(ack, false) == Action::TurnOff);
  h.completed(Action::TurnOff, true, ack);
  assert(h.next(ack + 1U, true) == Action::None);
  assert(!h.request(ack + 1499U));
  assert(h.request(ack + 1500U));
  assert(h.next(ack + 1751U, true) == Action::None);
  assert(h.next(ack + 1752U, true) == Action::None);
  assert(h.request(ack + 1752U));
}

static void check_failed_edge_and_reconfigure() {
  using Action = HapticPulse::Action;
  HapticPulse h;
  h.configure(true);
  assert(h.request(10));
  assert(h.next(20, true) == Action::TurnOn);
  h.completed(Action::TurnOn, false, 20);
  assert(!h.ready() && !h.active());
  assert(h.next(21, true) == Action::None);
  assert(!h.request(2000));
  h.configure(false);
  assert(!h.ready() && !h.request(2001));
  h.configure(true);
  assert(h.next(2002, true) == Action::None);
  assert(h.request(2003));
  h.configure(true);
  assert(h.next(2004, true) == Action::None);
  assert(h.request(2005));
  assert(h.next(2006, false) == Action::None);
  assert(h.next(2007, true) == Action::None);
}

int main(){
 check_timing_boundaries(100U);
 check_timing_boundaries(0xffffff80U);
 check_failed_edge_and_reconfigure();
 HapticPulse h;
 assert(!h.request(10));
 h.configure(true);
 assert(h.request(100));
 assert(!h.request(101));
 assert(h.next(120,false)==HapticPulse::Action::None);
 assert(!h.active());
 assert(h.request(130));
 assert(h.next(180,true)==HapticPulse::Action::TurnOn);
 h.completed(HapticPulse::Action::TurnOn,true,180);
 assert(h.active());
 assert(!h.request(181));
 assert(h.next(270,false)==HapticPulse::Action::TurnOff);
 h.completed(HapticPulse::Action::TurnOff,true,270);
 assert(!h.active());
 assert(!h.request(500));
 assert(h.request(1680));
 assert(h.next(1931,true)==HapticPulse::Action::None);
 assert(h.request(1950));
 assert(h.next(1990,true)==HapticPulse::Action::TurnOn);
 h.completed(HapticPulse::Action::TurnOn,true,1990);
 assert(h.next(2080,false)==HapticPulse::Action::TurnOff);
 h.completed(HapticPulse::Action::TurnOff,false,2080);
 assert(!h.ready());
 assert(!h.request(4000));
 h.configure(true);
 assert(h.request(0xfffffffaU));
 assert(h.next(4U,true)==HapticPulse::Action::TurnOn);
 h.completed(HapticPulse::Action::TurnOn,true,4);
 assert(h.next(100,true)==HapticPulse::Action::TurnOff);
 h.completed(HapticPulse::Action::TurnOff,true,100);
 assert(!h.request(1499));
 assert(h.request(1504));
 h.fault();
 assert(h.next(1520,true)==HapticPulse::Action::None);
 std::cout<<"PASS haptic requests, cooldown, dock gating, fault, wrap\n";
}
