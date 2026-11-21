#include "MotorHeartbeat.h"
#include <cassert>
#include <cstdint>
#include <iostream>

using desk_robot::MotorHeartbeat;

int main() {
  MotorHeartbeat heartbeat;
  assert(!heartbeat.update(0, false));
  assert(heartbeat.update(100, true)); // first CPU motion sample starts pulses
  assert(heartbeat.update(114, true)); // not LEDC or timer-generated
  assert(!heartbeat.update(115, true));
  assert(!heartbeat.update(129, true));
  assert(heartbeat.update(130, true));
  // On a stalled CPU there are NO hardware heartbeat edges, even if the
  // last generated state remains HIGH. A physical retriggerable one-shot
  // must time out independently and hold DRV8833 nSLEEP LOW.
  assert(!heartbeat.update(131, false));
  assert(!heartbeat.update(900, false));
  assert(heartbeat.update(901, true));
  assert(!heartbeat.update(916, true));
  // Both a dock contact and local guard loss are passed as false.
  assert(!heartbeat.update(917, false));
  assert(heartbeat.update(0xfffffff5U, true));
  assert(!heartbeat.update(4U, true)); // millis wraps after 15 ms
  assert(!heartbeat.update(10U, false));
  assert(heartbeat.update(11U, true));
  heartbeat.reset();
  assert(heartbeat.update(20U, true));
  // Stall before the wheel lease expires. It cannot retrigger the one-shot.
  heartbeat.reset();
  assert(heartbeat.update(0U, true));
  assert(!heartbeat.update(15U, true));
  assert(!heartbeat.update(100U, true));
  assert(heartbeat.missed_deadline());
  assert(!heartbeat.update(101U, true));
  assert(!heartbeat.update(102U, false));
  assert(heartbeat.missed_deadline());
  heartbeat.reset(); // The actual WROOM calls reset only at local USB rearm.
  assert(!heartbeat.missed_deadline());
  assert(heartbeat.update(103U, true));
  heartbeat.reset();
  assert(heartbeat.update(0xfffffff0U, true));
  assert(!heartbeat.update(0xffffffffU, true));
  assert(!heartbeat.update(0x30U, true)); // Deadline across millis rollover.
  assert(heartbeat.missed_deadline());
  std::cout << "PASS DC CPU heartbeat: stall latch, wrap, USB recovery\n";
}
