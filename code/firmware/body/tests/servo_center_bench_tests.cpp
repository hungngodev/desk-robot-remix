#include "ServoCenterBenchGate.h"

#include <cassert>
#include <cstdint>

using Gate = desk_robot::ServoCenterBenchGate;

int main() {
  // Even a continuously refilled USB RX queue leaves each loop iteration
  // bounded so deadline polling cannot be starved by parser throughput.
  assert(Gate::serial_budget(0) == 0U);
  assert(Gate::serial_budget(1) == 1U);
  assert(Gate::serial_budget(31) == 31U);
  assert(Gate::serial_budget(32) == 32U);
  assert(Gate::serial_budget(33) == 32U);
  assert(Gate::serial_budget(1000000) == 32U);

  Gate gate;
  assert(gate.active() == Gate::Channel::None);
  assert(!gate.request(nullptr, 0));
  assert(!gate.request("", 0));
  assert(!gate.request("CENTER", 0));
  assert(!gate.request("CENTER BOTH", 0));
  assert(!gate.request("CENTER LIFT 95", 0));
  assert(!gate.request("center lift", 0));
  assert(!gate.request("CENTER LIFT\n", 0));
  assert(!gate.already_used(Gate::Channel::Lift));
  assert(!gate.already_used(Gate::Channel::None));

  assert(gate.request("CENTER LIFT", 100));
  assert(gate.active() == Gate::Channel::Lift);
  assert(gate.already_used(Gate::Channel::Lift));
  assert(!gate.request("CENTER GRIP", 101)); // never simultaneous
  assert(!gate.should_detach(499));
  assert(!gate.complete(499));
  assert(gate.should_detach(500));
  assert(gate.complete(500));
  assert(gate.active() == Gate::Channel::None);
  assert(!gate.complete(501));
  assert(!gate.request("CENTER LIFT", 502)); // one lift pulse per boot
  assert(gate.request("CENTER GRIP", 502));
  assert(gate.active() == Gate::Channel::Grip);
  assert(gate.already_used(Gate::Channel::Grip));
  assert(!gate.request("CENTER GRIP", 503));
  assert(gate.complete(902));
  assert(!gate.request("CENTER GRIP", 903));

  // Millis rollover is safe; a delayed loop expires, never extends power.
  Gate wrapped;
  assert(wrapped.request("CENTER LIFT", 0xfffffff0U));
  assert(!wrapped.should_detach(0x0000017fU));
  assert(wrapped.should_detach(0x00000180U));
  assert(wrapped.complete(0x00000180U));
  assert(wrapped.request("CENTER GRIP", 0x00000181U));
  assert(!wrapped.should_detach(0x00000182U));
  assert(wrapped.should_detach(0x00000311U));
  assert(wrapped.complete(0x00000311U));

  // Nothing automatically starts after idle or expiry.
  assert(wrapped.active() == Gate::Channel::None);
  assert(!wrapped.should_detach(0x00000400U));
  return 0;
}
