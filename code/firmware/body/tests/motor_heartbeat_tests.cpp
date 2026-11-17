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
  std::cout << "PASS DC CPU heartbeat: motion only, fault off, wrap, rearm\n";
}
