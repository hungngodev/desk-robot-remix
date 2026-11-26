#include "BatterySafety.h"
#include <limits>

using desk_robot::fuel_above_recovery_floor;
using desk_robot::fuel_below_motor_floor;

// Keep the safety predicates and telemetry normalization usable in C++11
// constant expressions (the firmware stepper profile uses that standard).
static_assert(!fuel_below_motor_floor(3300U, 300U), "inclusive motor floor");
static_assert(fuel_below_motor_floor(3299U, 10000U), "voltage veto");
static_assert(!fuel_above_recovery_floor(3349U, 10000U), "recovery hysteresis");
static_assert(fuel_above_recovery_floor(3350U, 500U), "inclusive recovery floor");
static_assert(fuel_below_motor_floor(std::numeric_limits<unsigned>::max(), 500U),
              "out-of-range voltage must inhibit motion");
constexpr auto depleted = desk_robot::fuel_telemetry(true, 3000U, 0U);
static_assert(depleted.valid && depleted.cell_mv == 3000U && depleted.soc_centi == 0U,
              "zero SOC is valid depleted telemetry");
constexpr auto stale = desk_robot::fuel_telemetry(false, 4200U, 10000U);
static_assert(!stale.valid && stale.cell_mv == 0U && stale.soc_centi == 0U,
              "stale telemetry must clear both numeric fields");
constexpr auto malformed = desk_robot::fuel_telemetry(
    true, 4200U, std::numeric_limits<unsigned>::max());
static_assert(!malformed.valid && malformed.cell_mv == 0U && malformed.soc_centi == 0U,
              "out-of-range SOC must clear both numeric fields");

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
  // Cross independent voltage and SOC boundaries, including valid but
  // depleted telemetry, the hysteresis band and malformed readings.
  struct Boundary {
    unsigned value;
    bool telemetry_valid, motor_safe, recovery_safe;
  };
  const Boundary voltages[] = {
      {0U, false, false, false}, {2499U, false, false, false},
      {2500U, true, false, false}, {3299U, true, false, false},
      {3300U, true, true, false}, {3349U, true, true, false},
      {3350U, true, true, true}, {4500U, true, true, true},
      {4501U, false, false, false}, {invalid, false, false, false}};
  const Boundary charges[] = {
      {0U, true, false, false}, {299U, true, false, false},
      {300U, true, true, false}, {499U, true, true, false},
      {500U, true, true, true}, {10000U, true, true, true},
      {10001U, false, false, false}, {invalid, false, false, false}};
  for (const auto& voltage : voltages) {
    for (const auto& charge : charges) {
      if (fuel_below_motor_floor(voltage.value, charge.value) !=
          !(voltage.motor_safe && charge.motor_safe)) return 10;
      if (fuel_above_recovery_floor(voltage.value, charge.value) !=
          (voltage.recovery_safe && charge.recovery_safe)) return 11;
      const bool valid = voltage.telemetry_valid && charge.telemetry_valid;
      const auto sample = desk_robot::fuel_telemetry(true, voltage.value, charge.value);
      if (sample.valid != valid || sample.cell_mv != (valid ? voltage.value : 0U) ||
          sample.soc_centi != (valid ? charge.value : 0U)) return 12;
      const auto stale = desk_robot::fuel_telemetry(false, voltage.value, charge.value);
      if (stale.valid || stale.cell_mv != 0U || stale.soc_centi != 0U) return 13;
    }
  }
  return 0;
}
