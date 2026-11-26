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
  const auto full = desk_robot::fuel_telemetry(true, 4200U, 10000U);
  if (!full.valid || full.cell_mv != 4200U || full.soc_centi != 10000U) return 6;
  const auto failed = desk_robot::fuel_telemetry(false, full.cell_mv, full.soc_centi);
  if (failed.valid || failed.cell_mv != 0U || failed.soc_centi != 0U) return 7;
  const auto empty = desk_robot::fuel_telemetry(true, 3000U, 0U);
  if (!empty.valid || empty.cell_mv != 3000U || empty.soc_centi != 0U ||
      !fuel_below_motor_floor(empty.cell_mv, empty.soc_centi)) return 8;
  const auto bad_voltage = desk_robot::fuel_telemetry(true, 0U, 10000U);
  const auto bad_soc = desk_robot::fuel_telemetry(true, 4200U, 10001U);
  if (bad_voltage.valid || bad_voltage.cell_mv || bad_voltage.soc_centi ||
      bad_soc.valid || bad_soc.cell_mv || bad_soc.soc_centi) return 9;
  return 0;
}
