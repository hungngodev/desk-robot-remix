#pragma once

namespace desk_robot {
// Candidate software floors; actual pack and loaded rail limits need bench evidence.
constexpr bool fuel_below_motor_floor(unsigned cell_mv, unsigned soc_centi) {
  return cell_mv < 3300U || soc_centi < 300U;
}

constexpr bool fuel_above_recovery_floor(unsigned cell_mv, unsigned soc_centi) {
  return cell_mv >= 3350U && soc_centi >= 500U;
}
}  // namespace desk_robot
