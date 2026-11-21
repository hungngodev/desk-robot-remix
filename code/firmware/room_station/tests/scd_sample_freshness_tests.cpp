#include <cassert>
#include <iostream>
#include "scd_sample_freshness.h"

int main() {
  using desk_robot_room::scd_sample_valid_after_poll;
  // No observation exists until the first successful SCD40 measurement.
  assert(!scd_sample_valid_after_poll(false, 0, false, false));
  assert(scd_sample_valid_after_poll(false, 0, true, true));
  // Polling between periodic measurements preserves the previous sample.
  assert(scd_sample_valid_after_poll(true, 0, false, false));
  // Physical readiness transport failure must revoke the cached value,
  // even though its station timestamp is still within the freshness age.
  assert(!scd_sample_valid_after_poll(true, 4, false, false));
  assert(!scd_sample_valid_after_poll(true, 4, true, true));
  // A ready sensor with an invalid reading must not preserve prior CO2.
  assert(!scd_sample_valid_after_poll(true, 0, true, false));
  assert(!scd_sample_valid_after_poll(false, 0, true, false));
  assert(scd_sample_valid_after_poll(true, 0, true, true));
  std::cout << "PASS SCD40 cached-sample invalidation and not-ready retention\n";
}
