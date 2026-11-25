#pragma once

#include "BodyControl.h"
#include "TofBus.h"

namespace desk_robot {

// Publish one poll's evidence to the body status cache. An interrupt error
// is a revocation, not a new measurement. A shared bus fault revokes all lanes.
inline void publish_range_telemetry(const TofBus& bus, BodyControl& control,
                                    std::uint32_t scan_ms, bool bus_fault) {
  if (bus_fault) {
    control.invalidate_side_ranges();
    control.invalidate_range_optics();
  }
  const auto rejected = bus.rejected_channel();
  if (rejected < 8) control.invalidate_range_lane(rejected);
  const auto optical_channel = bus.new_optical_channel();
  if (optical_channel < 8) {
    const auto raw = bus.optical_diagnostic(optical_channel, scan_ms);
    if (raw.present) {
      control.sample_range_optics(
          optical_channel, raw.ambient_97, raw.signal_97, raw.valid, scan_ms);
    }
  }
  const auto extra = bus.new_extra_channel();
  if (extra < 3) {
    const auto sample = bus.extra_diagnostic(extra, scan_ms);
    control.sample_side_range(extra, sample.distance_mm, sample.valid, scan_ms);
  }
}

}  // namespace desk_robot
