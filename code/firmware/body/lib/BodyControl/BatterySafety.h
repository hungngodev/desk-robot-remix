#pragma once

namespace desk_robot {
// Candidate software floors; actual pack and loaded rail limits need bench evidence.
constexpr bool fuel_below_motor_floor(unsigned cell_mv, unsigned soc_centi) {
  return cell_mv < 3300U || cell_mv > 4500U ||
         soc_centi < 300U || soc_centi > 10000U;
}

constexpr bool fuel_above_recovery_floor(unsigned cell_mv, unsigned soc_centi) {
  return cell_mv >= 3350U && cell_mv <= 4500U &&
         soc_centi >= 500U && soc_centi <= 10000U;
}

struct FuelTelemetry {
  unsigned cell_mv, soc_centi;
  bool valid;
};

// Keep numeric wire fields for old clients, but never publish stale or
// malformed values as a charge estimate. Zero with valid=false is unknown;
// zero SOC with valid=true is a real depleted measurement.
constexpr FuelTelemetry fuel_telemetry(bool fresh, unsigned cell_mv,
                                       unsigned soc_centi) {
  return (!fresh || cell_mv < 2500U || cell_mv > 4500U || soc_centi > 10000U)
             ? FuelTelemetry{0U, 0U, false}
             : FuelTelemetry{cell_mv, soc_centi, true};
}
}  // namespace desk_robot
