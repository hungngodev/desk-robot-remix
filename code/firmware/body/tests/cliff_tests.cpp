#include "CliffGuard.h"

#include <cstdlib>
#include <cstring>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

using desk_robot::CliffConfig;
using desk_robot::CliffFault;
using desk_robot::CliffGuard;

namespace {
#define CHECK(expression)                                                        \
  do {                                                                          \
    if (!(expression))                                                          \
      throw std::runtime_error(std::string(__FILE__) + ":" +                      \
                               std::to_string(__LINE__) + ": " #expression);    \
  } while (false)

CliffConfig config() {
  CliffConfig value;
  value.calibrated = true;
  for (auto& floor : value.floor) {
    floor.min_mm = 30;
    floor.max_mm = 60;
  }
  value.front_obstacle_mm = 100;
  value.front_max_mm = 800;
  value.freshness_ms = 80;
  return value;
}

void healthy_samples(CliffGuard& guard, std::uint32_t now_ms) {
  for (std::uint8_t sensor = 0; sensor < desk_robot::kFloorSensorCount; ++sensor)
    guard.sample(sensor, 45, true, now_ms);
  guard.sample(4, 300, true, now_ms);
}

void ready(CliffGuard& guard, std::uint32_t now_ms) {
  CHECK(guard.configure(config()));
  healthy_samples(guard, now_ms);
  CHECK(guard.try_rearm(now_ms));
  CHECK(guard.evaluate(now_ms));
}

void boot_and_configuration() {
  CliffGuard guard;
  CHECK(!guard.configured());
  CHECK(!guard.evaluate(0));
  CHECK(guard.fault() == CliffFault::Unconfigured);
  CHECK(guard.fault_sensor() == desk_robot::kNoFaultSensor);
  CHECK(!guard.try_rearm(0));
  CHECK(!guard.configure(CliffConfig{}));
  CHECK(guard.configure(config()));
  CHECK(guard.configured());
  CHECK(!guard.try_rearm(0));
  healthy_samples(guard, 10);
  CHECK(!guard.evaluate(10));  // samples alone never arm/clear the latch
  CHECK(guard.try_rearm(10));
  CHECK(guard.fault() == CliffFault::None);
  CHECK(guard.fault_sensor() == desk_robot::kNoFaultSensor);
  CHECK(guard.evaluate(10));
}

void invalid_configuration() {
  CliffGuard guard;
  auto value = config();
  value.calibrated = false;
  CHECK(!guard.configure(value));
  value = config(); value.floor[2].max_mm = 29;
  CHECK(!guard.configure(value));
  value = config(); value.floor[0].min_mm = 0;
  CHECK(!guard.configure(value));
  value = config(); value.floor[0].min_mm = 29;
  CHECK(!guard.configure(value)); // active VL53L0X never accepts <30mm
  value = config(); value.floor[0].max_mm = 1301;
  CHECK(!guard.configure(value)); // active VL53L0X rejects >1300mm
  value = config(); value.front_obstacle_mm = 29;
  CHECK(!guard.configure(value));
  value = config(); value.front_max_mm = 1301;
  CHECK(!guard.configure(value));
  value = config(); value.front_max_mm = value.front_obstacle_mm;
  CHECK(!guard.configure(value));
  value = config(); value.front_obstacle_mm = 0;
  CHECK(!guard.configure(value));
  value = config(); value.freshness_ms = 0;
  CHECK(!guard.configure(value));
  value = config(); value.freshness_ms = 29;
  CHECK(!guard.configure(value)); // Reject NVS below local cal command minimum
  value = config(); value.freshness_ms = 30;
  CHECK(guard.configure(value));
  value = config(); value.freshness_ms = 200;
  CHECK(guard.configure(value));
  value = config(); value.freshness_ms = 201;
  CHECK(!guard.configure(value)); // Reject NVS with overly permissive stale window
  value = config(); value.freshness_ms = 1000;
  CHECK(!guard.configure(value)); // Old guard wrongly accepted this on restore
  value = config(); value.freshness_ms = 1001;
  CHECK(!guard.configure(value));
  value = config(); value.freshness_ms = 0x80000000U;
  CHECK(!guard.configure(value));
  healthy_samples(guard, 10);
  CHECK(!guard.try_rearm(10));
}

void each_floor_sensor_latches() {
  for (std::uint8_t sensor = 0; sensor < desk_robot::kFloorSensorCount; ++sensor) {
    for (std::uint16_t distance : {29, 61}) {
      CliffGuard guard;
      ready(guard, 0);
      guard.sample(sensor, distance, true, 10);
      CHECK(guard.fault() == CliffFault::FloorOutOfRange);
      CHECK(guard.fault_sensor() == sensor);
      CHECK(!guard.evaluate(10));
      CHECK(!guard.try_rearm(10));
      healthy_samples(guard, 11);
      CHECK(!guard.evaluate(11));
      CHECK(guard.try_rearm(11));
    }
  }
  CliffGuard guard;
  ready(guard, 0);
  guard.sample(0, 30, true, 10);
  guard.sample(1, 60, true, 10);
  CHECK(guard.evaluate(10));
}

void invalid_then_good_is_sticky() {
  CliffGuard guard;
  ready(guard, 0);
  guard.sample(2, 45, false, 10);
  CHECK(guard.fault() == CliffFault::InvalidSample);
  guard.sample(2, 45, true, 11); // distinct conversion, not a replay
  CHECK(!guard.evaluate(11));
  CHECK(guard.fault_sensor() == 2);
  CHECK(guard.try_rearm(11));
  guard.sample(1, 0, true, 11);
  CHECK(guard.fault() == CliffFault::InvalidSample);
  CHECK(!guard.evaluate(11));
}

void front_sensor_rules() {
  CliffGuard guard;
  ready(guard, 0);
  guard.sample(4, 101, true, 1);
  CHECK(guard.evaluate(1));
  guard.sample(4, 100, true, 2);
  CHECK(!guard.evaluate(2));
  CHECK(guard.fault() == CliffFault::FrontObstacle);
  CHECK(guard.fault_sensor() == 4);
  guard.sample(4, 800, true, 3);
  CHECK(guard.try_rearm(3));
  guard.sample(4, 801, true, 4);
  CHECK(guard.fault() == CliffFault::FrontOutOfRange);
  CHECK(!guard.evaluate(4));
  guard.sample(4, 300, true, 5);
  CHECK(guard.try_rearm(5));
  // An empty/open scene yielding no valid return is not verified clear space.
  guard.sample(4, 8190, false, 6);
  CHECK(guard.fault() == CliffFault::InvalidSample);
  CHECK(!guard.evaluate(6));
  CHECK(!guard.try_rearm(6));
}

void stale_and_missing_samples() {
  CliffGuard guard;
  CHECK(guard.configure(config()));
  for (std::uint8_t sensor = 0; sensor < 4; ++sensor)
    guard.sample(sensor, 45, true, 0);
  CHECK(!guard.try_rearm(0));
  guard.sample(4, 300, true, 0);
  CHECK(guard.try_rearm(0));
  CHECK(guard.evaluate(79));
  CHECK(!guard.evaluate(80));
  CHECK(guard.fault() == CliffFault::StaleSample);
  CHECK(guard.fault_sensor() == 0);
  healthy_samples(guard, 80);
  CHECK(!guard.evaluate(80));
  CHECK(guard.try_rearm(80));
  guard.sample(0, 45, true, 159);
  CHECK(!guard.evaluate(160));
  CHECK(guard.fault() == CliffFault::StaleSample);
  CHECK(guard.fault_sensor() == 1);
}

void bus_fault_requires_new_samples() {
  CliffGuard guard;
  ready(guard, 0);
  guard.bus_fault();
  CHECK(guard.fault() == CliffFault::BusFailure);
  CHECK(guard.fault_sensor() == desk_robot::kNoFaultSensor);
  CHECK(!guard.try_rearm(1));
  for (std::uint8_t sensor = 0; sensor < 4; ++sensor)
    guard.sample(sensor, 45, true, 1);
  CHECK(!guard.try_rearm(1));
  guard.sample(4, 300, true, 1);
  CHECK(!guard.evaluate(1));
  CHECK(guard.try_rearm(1));
  CHECK(guard.evaluate(1));
}

void configuration_replacement_invalidates_samples() {
  CliffGuard guard;
  ready(guard, 0);
  CHECK(guard.configure(config()));
  CHECK(!guard.evaluate(0));
  CHECK(!guard.try_rearm(0));
  healthy_samples(guard, 1);
  CHECK(!guard.evaluate(1));
  CHECK(guard.try_rearm(1));
  auto value = config();
  value.floor[0].min_mm = 55;
  CHECK(guard.configure(value));
  healthy_samples(guard, 2);
  CHECK(!guard.try_rearm(2));
}

void first_fault_and_invalid_channel() {
  CliffGuard guard;
  ready(guard, 0);
  guard.sample(3, 90, true, 1);
  guard.sample(1, 0, false, 1);
  guard.bus_fault();
  CHECK(guard.fault() == CliffFault::FloorOutOfRange);
  CHECK(guard.fault_sensor() == 3);
  healthy_samples(guard, 2);
  CHECK(guard.try_rearm(2));
  guard.sample(5, 45, true, 2);
  CHECK(guard.fault() == CliffFault::InvalidChannel);
  CHECK(!guard.evaluate(2));
}

void duplicate_conversion_timestamp_requires_new_sensor_evidence() {
  CliffGuard guard;
  ready(guard, 100);
  guard.sample(2, 46, true, 110);
  CHECK(guard.evaluate(110));
  guard.sample(2, 44, true, 110); // replayed same conversion timestamp
  CHECK(guard.fault() == CliffFault::InvalidSample);
  CHECK(guard.fault_sensor() == 2);
  const auto preserved = guard.diagnostic(2, 111);
  CHECK(preserved.distance_mm == 46); // stale replay did not overwrite raw
  CHECK(preserved.present && !preserved.valid);
  CHECK(!guard.try_rearm(111));
  guard.sample(2, 45, true, 112); // genuine later conversion restores freshness
  CHECK(guard.try_rearm(112));
  CHECK(guard.evaluate(112));
}

void invalid_channel_requires_five_new_measurements() {
  CliffGuard guard;
  ready(guard, 100);
  guard.sample(5, 45, true, 101);
  CHECK(guard.fault() == CliffFault::InvalidChannel);
  for (std::uint8_t sensor = 0; sensor < desk_robot::kCliffSensorCount; ++sensor) {
    const auto old = guard.diagnostic(sensor, 101);
    CHECK(old.present && !old.valid); // preserve raw mm but deny clearance
  }
  CHECK(!guard.try_rearm(101));
  for (std::uint8_t sensor = 0; sensor < desk_robot::kFloorSensorCount; ++sensor)
    guard.sample(sensor, 45, true, 102);
  CHECK(!guard.try_rearm(102)); // front channel still not refreshed
  guard.sample(4, 300, true, 102);
  CHECK(guard.try_rearm(102));
  CHECK(guard.evaluate(102));
}

void unsigned_clock_rollover() {
  CliffGuard guard;
  const std::uint32_t start = std::numeric_limits<std::uint32_t>::max() - 30U;
  ready(guard, start);
  CHECK(guard.evaluate(start + 79U));
  CHECK(!guard.evaluate(start + 80U));
  CHECK(guard.fault() == CliffFault::StaleSample);
  healthy_samples(guard, start + 81U);
  CHECK(guard.try_rearm(start + 81U));
  CHECK(guard.evaluate(start + 82U));
}

void diagnostics_read_only_and_bounded() {
  CliffGuard guard;
  auto missing = guard.diagnostic(0, 0);
  CHECK(!missing.present && !missing.valid && missing.distance_mm == 0);
  CHECK(guard.configure(config()));
  healthy_samples(guard, 10);
  CHECK(guard.fault() == CliffFault::MissingSample);
  auto observed = guard.diagnostic(2, 25);
  CHECK(observed.present && observed.valid);
  CHECK(observed.distance_mm == 45 && observed.age_ms == 15);
  CHECK(!guard.diagnostic(255, 25).present);
  // Reading does not automatically rearm or clear the sticky fault.
  CHECK(guard.fault() == CliffFault::MissingSample);
  CHECK(guard.try_rearm(25));
  guard.sample(3, 800, false, 30);
  const auto bad = guard.diagnostic(3, 31);
  CHECK(bad.present && !bad.valid);
  CHECK(bad.distance_mm == 800 && bad.age_ms == 1);
  CHECK(guard.fault() == CliffFault::InvalidSample);
  guard.bus_fault();
  CHECK(!guard.diagnostic(3, 32).present);
  CHECK(guard.fault() == CliffFault::InvalidSample);
  // Millis wrap measures elapsed age using unsigned arithmetic.
  CliffGuard another;
  CHECK(another.configure(config()));
  another.sample(0, 50, true, 0xfffffff0U);
  CHECK(another.diagnostic(0, 0x10U).age_ms == 32U);
}

void diagnostics_reject_fresh_unsafe_distances_without_erasing_raw() {
  // A functioning ToF chip is not proof that its measured desk clearance
  // satisfies the local calibrated envelope. Status must agree with it.
  for (const std::uint16_t distance : {std::uint16_t(29), std::uint16_t(61)}) {
    CliffGuard guard;
    ready(guard, 100);
    guard.sample(0, distance, true, 101);
    const auto unsafe = guard.diagnostic(0, 102);
    CHECK(unsafe.present && !unsafe.valid);
    CHECK(unsafe.distance_mm == distance && unsafe.age_ms == 1);
    CHECK(guard.fault() == CliffFault::FloorOutOfRange);
    guard.sample(0, 45, true, 103);
    CHECK(guard.diagnostic(0, 104).valid);
    CHECK(!guard.evaluate(104)); // a healthy sample cannot clear the latch
    CHECK(guard.try_rearm(104));  // local authorized recovery is separate
  }

  for (const std::uint16_t distance : {std::uint16_t(100), std::uint16_t(801)}) {
    CliffGuard guard;
    ready(guard, 100);
    guard.sample(4, distance, true, 101);
    const auto unsafe = guard.diagnostic(4, 102);
    CHECK(unsafe.present && !unsafe.valid);
    CHECK(unsafe.distance_mm == distance && unsafe.age_ms == 1);
    CHECK(guard.fault() ==
          (distance == 100 ? CliffFault::FrontObstacle
                           : CliffFault::FrontOutOfRange));
    guard.sample(4, 300, true, 103);
    CHECK(guard.diagnostic(4, 104).valid);
    CHECK(!guard.evaluate(104));
    CHECK(guard.try_rearm(104));
  }
}

void diagnostics_expire_validity_without_clearing_raw_or_latched_fault() {
  CliffGuard guard;
  CHECK(guard.configure(config()));
  healthy_samples(guard, 10);
  CHECK(guard.try_rearm(10));
  auto fresh = guard.diagnostic(2, 89);  // 79 ms, valid under 80 ms TTL
  CHECK(fresh.present && fresh.valid && fresh.distance_mm == 45);
  CHECK(fresh.age_ms == 79);
  const auto expired = guard.diagnostic(2, 90);  // exact TTL is stale
  CHECK(expired.present && !expired.valid && expired.distance_mm == 45);
  CHECK(expired.age_ms == 80);
  CHECK(guard.fault() == CliffFault::None);  // read-only; no auto-stop/rearm
  CHECK(!guard.evaluate(90));
  CHECK(guard.fault() == CliffFault::StaleSample);
  CHECK(!guard.diagnostic(2, 90).valid);
  // 32-bit monotonic rollover must still expire at the same TTL.
  CliffGuard wrapped;
  CHECK(wrapped.configure(config()));
  wrapped.sample(0, 45, true, 0xfffffff0U);
  CHECK(wrapped.diagnostic(0, 0x3fU).valid);  // 79 ms elapsed
  CHECK(!wrapped.diagnostic(0, 0x40U).valid); // 80 ms elapsed
}

void delayed_range_sample_never_replaces_newer_evidence() {
  CliffGuard guard;
  ready(guard, 100);
  guard.sample(0, 46, true, 110);
  CHECK(guard.diagnostic(0, 111).distance_mm == 46);
  // A late completion from the previous scan must not replace the 110 ms
  // sample or make an old obstacle result appear newly measured.
  guard.sample(0, 45, true, 105);
  CHECK(!guard.evaluate(111));
  CHECK(guard.fault() == CliffFault::InvalidSample);
  CHECK(guard.fault_sensor() == 0);
  // The stale packet must not make a prior good result reusable as motor
  // clearance, even when the operator explicitly attempts local rearm.
  CHECK(!guard.try_rearm(111));
  const auto preserved = guard.diagnostic(0, 111);
  CHECK(preserved.present && !preserved.valid);
  CHECK(preserved.distance_mm == 46);
  CHECK(preserved.age_ms == 1);
  guard.sample(0, 46, true, 112);  // new actual conversion required
  CHECK(guard.try_rearm(112));
  CHECK(guard.evaluate(112));

  // New timestamps across uint32 wrap are forward, whereas an older
  // pre-wrap completion must never overwrite the post-wrap sample.
  CliffGuard wrapped;
  const auto start = std::numeric_limits<std::uint32_t>::max() - 10U;
  ready(wrapped, start);
  wrapped.sample(0, 47, true, 5U);
  CHECK(wrapped.evaluate(5U));
  wrapped.sample(0, 48, true,
                 std::numeric_limits<std::uint32_t>::max() - 5U);
  CHECK(!wrapped.evaluate(6U));
  CHECK(wrapped.fault() == CliffFault::InvalidSample);
  CHECK(wrapped.fault_sensor() == 0);
  CHECK(wrapped.diagnostic(0, 6U).distance_mm == 47);
  CHECK(!wrapped.diagnostic(0, 6U).valid);
  CHECK(!wrapped.try_rearm(6U));  // never reuse pre-wrap evidence
  wrapped.sample(0, 47, true, 7U);
  CHECK(wrapped.try_rearm(7U));
  CHECK(wrapped.evaluate(7U));
}

void fault_names() {
  CHECK(std::strcmp(CliffGuard::fault_name(CliffFault::None), "none") == 0);
  CHECK(std::strcmp(CliffGuard::fault_name(CliffFault::Unconfigured), "unconfigured") == 0);
  CHECK(std::strcmp(CliffGuard::fault_name(CliffFault::MissingSample), "missing_sample") == 0);
  CHECK(std::strcmp(CliffGuard::fault_name(CliffFault::InvalidSample), "invalid_sample") == 0);
  CHECK(std::strcmp(CliffGuard::fault_name(CliffFault::StaleSample), "stale_sample") == 0);
  CHECK(std::strcmp(CliffGuard::fault_name(CliffFault::FloorOutOfRange), "floor_out_of_range") == 0);
  CHECK(std::strcmp(CliffGuard::fault_name(CliffFault::FrontObstacle), "front_obstacle") == 0);
  CHECK(std::strcmp(CliffGuard::fault_name(CliffFault::FrontOutOfRange), "front_out_of_range") == 0);
  CHECK(std::strcmp(CliffGuard::fault_name(CliffFault::BusFailure), "bus_failure") == 0);
  CHECK(std::strcmp(CliffGuard::fault_name(CliffFault::InvalidChannel), "invalid_channel") == 0);
  CHECK(std::strcmp(CliffGuard::fault_name(static_cast<CliffFault>(255)), "unknown") == 0);
}
}  // namespace

int main(int argc, char** argv) {
  using Test = std::pair<const char*, void (*)()>;
  const std::vector<Test> tests = {
      {"boot_and_configuration", boot_and_configuration},
      {"invalid_configuration", invalid_configuration},
      {"each_floor_sensor_latches", each_floor_sensor_latches},
      {"invalid_then_good_is_sticky", invalid_then_good_is_sticky},
      {"front_sensor_rules", front_sensor_rules},
      {"stale_and_missing_samples", stale_and_missing_samples},
      {"bus_fault_requires_new_samples", bus_fault_requires_new_samples},
      {"configuration_replacement_invalidates_samples", configuration_replacement_invalidates_samples},
      {"first_fault_and_invalid_channel", first_fault_and_invalid_channel},
      {"duplicate_conversion_timestamp_requires_new_sensor_evidence",
       duplicate_conversion_timestamp_requires_new_sensor_evidence},
      {"invalid_channel_requires_five_new_measurements",
       invalid_channel_requires_five_new_measurements},
      {"unsigned_clock_rollover", unsigned_clock_rollover},
      {"delayed_range_sample_never_replaces_newer_evidence",
       delayed_range_sample_never_replaces_newer_evidence},
      {"fault_names", fault_names},
      {"diagnostics_read_only_and_bounded", diagnostics_read_only_and_bounded},
      {"diagnostics_expire_validity_without_clearing_raw_or_latched_fault",
       diagnostics_expire_validity_without_clearing_raw_or_latched_fault},
      {"diagnostics_reject_fresh_unsafe_distances_without_erasing_raw",
       diagnostics_reject_fresh_unsafe_distances_without_erasing_raw}};
  int ran = 0;
  for (const auto& test : tests) {
    if (argc > 1 && std::strcmp(argv[1], test.first) != 0) continue;
    try {
      test.second();
      ++ran;
      std::cout << "PASS " << test.first << '\n';
    } catch (const std::exception& error) {
      std::cerr << "FAIL " << test.first << ": " << error.what() << '\n';
      return EXIT_FAILURE;
    }
  }
  if (ran == 0) return EXIT_FAILURE;
  return EXIT_SUCCESS;
}
