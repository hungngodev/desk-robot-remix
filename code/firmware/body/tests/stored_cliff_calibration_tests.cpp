#include "StoredCliffCalibration.h"

#include <cstdlib>
#include <iostream>
#include <stdexcept>

namespace {
using namespace desk_robot;

#define CHECK(expression) do { \
  if (!(expression)) throw std::runtime_error(#expression); \
} while (false)

CliffConfig measured_config() {
  CliffConfig config{};
  config.calibrated = true;
  for (std::size_t lane = 0; lane < kFloorSensorCount; ++lane) {
    config.floor[lane].min_mm = 30U + lane;
    config.floor[lane].max_mm = 60U + lane;
  }
  config.front_obstacle_mm = 100U;
  config.front_max_mm = 800U;
  config.freshness_ms = 80U;
  return config;
}

void check_hold(const StoredCliffCalibration& bytes) {
  CliffConfig decoded{};
  CliffGuard guard;
  const bool loaded = decode_stored_calibration(bytes, decoded);
  CHECK(!loaded);
  CHECK(!decoded.calibrated);
  CHECK(!guard.configured());
  for (std::uint8_t lane = 0; lane < kCliffSensorCount; ++lane)
    guard.sample(lane, lane == 4 ? 300 : 45, true, 10U);
  CHECK(!guard.evaluate(10U));
  CHECK(!guard.try_rearm(10U));
  CHECK(guard.fault() == CliffFault::Unconfigured);
}

void check_resealed_field(std::size_t offset, unsigned width, std::uint32_t value) {
  auto bytes = encode_stored_calibration(measured_config());
  write_calibration_le(bytes, offset, width, value);
  write_calibration_le(bytes, 36, 4, stored_calibration_checksum(bytes));
  check_hold(bytes);
}

void corrupt_header_and_checksum() {
  const auto good = encode_stored_calibration(measured_config());
  check_hold(StoredCliffCalibration{});
  for (std::size_t offset = 0; offset < good.size(); ++offset) {
    // v1 padding was never covered by the checksum.
    if (offset == 9 || offset == 30 || offset == 31) continue;
    for (unsigned bit = 0; bit < 8; ++bit) {
      auto corrupt = good;
      corrupt[offset] ^= static_cast<std::uint8_t>(1U << bit);
      check_hold(corrupt);
    }
  }
  for (unsigned flag = 0; flag < 256; ++flag)
    if (flag != 1) check_resealed_field(8, 1, flag);
  check_resealed_field(4, 4, 0U);
  check_resealed_field(4, 4, 2U);
  check_resealed_field(4, 4, 0xffffffffU);
}

void corrupt_thresholds_with_valid_checksum() {
  for (std::size_t offset = 10; offset <= 28; offset += 2) {
    for (const auto bad : {0U, 29U, 1301U, 65535U})
      check_resealed_field(offset, 2, bad);
  }
  for (std::size_t lane = 0; lane < kFloorSensorCount; ++lane) {
    auto bytes = encode_stored_calibration(measured_config());
    write_calibration_le(bytes, 10 + 4 * lane, 2, 60U + lane);
    write_calibration_le(bytes, 12 + 4 * lane, 2, 30U + lane);
    write_calibration_le(bytes, 36, 4, stored_calibration_checksum(bytes));
    check_hold(bytes);
  }
  check_resealed_field(26, 2, 800U);  // Equal front limits.
  check_resealed_field(26, 2, 801U);  // Inverted front limits.
  for (const auto bad : {0U, 29U, 201U, 65535U, 0xffffffffU})
    check_resealed_field(32, 4, bad);
}

void valid_legacy_record_still_requires_rearm() {
  auto config = measured_config();
  for (const auto freshness : {30U, 200U}) {
    config.freshness_ms = freshness;
    config.floor[0].max_mm = 30U;  // Equal floor limits are admissible.
    config.floor[3].max_mm = 1300U;
    config.front_max_mm = 1300U;
    const auto good = encode_stored_calibration(config);
    auto legacy = good;
    legacy[9] = legacy[30] = legacy[31] = 0xff;
    CliffConfig decoded{};
    CHECK(decode_stored_calibration(legacy, decoded));
    CHECK(encode_stored_calibration(decoded) == good);
    CliffGuard guard;
    CHECK(guard.configure(decoded));
    CHECK(!guard.try_rearm(10U));
    for (std::uint8_t lane = 0; lane < kCliffSensorCount; ++lane)
      guard.sample(lane, lane == 4 ? 300 : (lane == 0 ? 30 : 45), true, 11U);
    CHECK(!guard.evaluate(11U));
    CHECK(guard.try_rearm(11U));
    CHECK(guard.evaluate(11U));
  }
}
void bound_record_refuses_other_wroom_and_corruption() {
  constexpr CliffCalibrationOwner unit_a{0x24, 1, 2, 3, 4, 5};
  constexpr CliffCalibrationOwner unit_b{0x24, 1, 2, 3, 4, 6};
  constexpr CliffCalibrationOwner no_owner{};
  const auto good = encode_bound_calibration(measured_config(), unit_a);
  const auto check_bound_hold = [](const BoundStoredCliffCalibration& bytes,
                                   const CliffCalibrationOwner& owner) {
    CliffConfig decoded{};
    CliffGuard guard;
    CHECK(!decode_bound_calibration(bytes, owner, decoded));
    CHECK(!decoded.calibrated);
    CHECK(!guard.configured());
    for (std::uint8_t lane = 0; lane < kCliffSensorCount; ++lane)
      guard.sample(lane, lane == 4 ? 300 : 45, true, 10U);
    CHECK(!guard.evaluate(10U));
    CHECK(!guard.try_rearm(10U));
    CHECK(guard.fault() == CliffFault::Unconfigured);
  };
  check_bound_hold(good, unit_b);
  check_bound_hold(good, no_owner);
  check_bound_hold(encode_bound_calibration(measured_config(), no_owner), no_owner);
  for (std::size_t offset = 0; offset < good.size(); ++offset) {
    for (unsigned bit = 0; bit < 8; ++bit) {
      auto corrupt = good;
      corrupt[offset] ^= static_cast<std::uint8_t>(1U << bit);
      check_bound_hold(corrupt, unit_a);
    }
  }
  BoundStoredCliffCalibration unbound{};
  const auto legacy = encode_stored_calibration(measured_config());
  std::copy(legacy.begin(), legacy.end(), unbound.begin());
  check_bound_hold(unbound, unit_a);
  CliffConfig decoded{};
  CHECK(decode_bound_calibration(good, unit_a, decoded));
  CHECK(encode_bound_calibration(decoded, unit_a) == good);
  CliffGuard guard;
  CHECK(guard.configure(decoded));
  CHECK(!guard.try_rearm(10U));
  for (std::uint8_t lane = 0; lane < kCliffSensorCount; ++lane)
    guard.sample(lane, lane == 4 ? 300 : 45, true, 11U);
  CHECK(!guard.evaluate(11U));
  CHECK(guard.try_rearm(11U));
}
}  // namespace

int main() {
  try {
    corrupt_header_and_checksum();
    corrupt_thresholds_with_valid_checksum();
    valid_legacy_record_still_requires_rearm();
    bound_record_refuses_other_wroom_and_corruption();
  } catch (const std::exception& error) {
    std::cerr << "FAIL " << error.what() << '\n';
    return EXIT_FAILURE;
  }
  std::cout << "PASS stored calibration corruption and boot HOLD\n";
  return EXIT_SUCCESS;
}
