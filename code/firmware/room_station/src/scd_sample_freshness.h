#pragma once

namespace desk_robot_room {
// A not-ready SCD40 can retain an actual prior measurement until its age
// expires, but a failed I2C readiness poll or a failed conversion must
// invalidate the cached value immediately. Never relabel it as fresh data.
inline bool scd_sample_valid_after_poll(bool previous_valid,
                                        int readiness_status,
                                        bool ready,
                                        bool measurement_valid) {
  if (readiness_status != 0) return false;
  return ready ? measurement_valid : previous_valid;
}
}  // namespace desk_robot_room
