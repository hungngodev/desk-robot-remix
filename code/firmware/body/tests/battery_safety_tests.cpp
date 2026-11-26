#include "BatterySafety.h"
#include <limits>

using desk_robot::fuel_above_recovery_floor;
using desk_robot::fuel_below_motor_floor;

int main() {
  if (fuel_below_motor_floor(3300U, 300U) ||
      !fuel_below_motor_floor(3299U, 300U) ||
      !fuel_below_motor_floor(3300U, 299U) ||
      !fuel_below_motor_floor(0U, 5000U) ||
      !fuel_below_motor_floor(3800U, 0U)) return 1;
  if (fuel_above_recovery_floor(3349U, 500U) ||
      fuel_above_recovery_floor(3350U, 499U) ||
      !fuel_above_recovery_floor(3350U, 500U)) return 2;
  if (fuel_below_motor_floor(4500U, 10000U) ||
      !fuel_above_recovery_floor(4500U, 10000U)) return 3;
  const auto invalid = std::numeric_limits<unsigned>::max();
  if (!fuel_below_motor_floor(4501U, 5000U) ||
      !fuel_below_motor_floor(3800U, 10001U) ||
      !fuel_below_motor_floor(invalid, invalid) ||
      fuel_above_recovery_floor(4501U, 5000U) ||
      fuel_above_recovery_floor(3800U, 10001U) ||
      fuel_above_recovery_floor(invalid, invalid)) return 4;
  // Every integer in the +/-40 mV noise band stays below recovery.
  // Healthy SOC cannot compensate for an unsafe cell voltage.
  for (unsigned mv = 3260U; mv <= 3340U; ++mv) {
    if (fuel_below_motor_floor(mv, 5000U) != (mv < 3300U) ||
        fuel_above_recovery_floor(mv, 5000U)) return 5;
  }
  return 0;
}
