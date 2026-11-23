#include "MotorHeartbeat.h"
#include <stdexcept>
#define CHECK(expr) do { if (!(expr)) throw std::runtime_error(#expr); } while (false)
#include <cstdint>
#include <iostream>

using desk_robot::MotorHeartbeat;

int main() {
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
  std::cout << "PASS DC CPU heartbeat: stall latch, wrap, USB recovery\n";
}
