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
  return 0;
}
