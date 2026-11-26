#pragma once

#include <cstdint>

namespace desk_robot {

// Raw VL53L0X driver acceptance, not a calibrated clearance envelope.
constexpr std::uint16_t kTofMinRangeMm = 30U;
constexpr std::uint16_t kTofMaxRangeMm = 1300U;
constexpr std::uint16_t kTofMinSignal97 = 32U;
constexpr std::uint32_t kTofCriticalExpiryMs = 200U;
constexpr std::uint32_t kTofSideExpiryMs = 351U;

// Shared Wire timeout in TofBus::begin. Count every endTransmission and
// requestFrom conservatively, including deferred non-STOP writes. The pinned
// Arduino ESP32 2.0.17 actually combines each register read into one HAL call.
// One ready poll: two checked mux masks (4), status/result reads (4), clear (1).
// Recovery is a separate poll: at most two checked mux masks (4). There is no
// inline retry; the 100 ms recovery backoff is elapsed time, not a blocking wait.
constexpr std::uint16_t kTofWireTimeoutMs = 10U;
constexpr std::uint32_t kTofMaxPollWireCalls = 9U;
constexpr std::uint32_t kTofMaxRecoveryWireCalls = 4U;
// Nominal GPIO recovery delays (<1 ms clock clear plus optional 2 ms reset).
constexpr std::uint32_t kTofRecoveryDelayAllowanceMs = 3U;
constexpr std::uint32_t kTofPollWireBudgetMs =
    kTofMaxPollWireCalls * kTofWireTimeoutMs;
constexpr std::uint32_t kTofRecoveryWireBudgetMs =
    kTofMaxRecoveryWireCalls * kTofWireTimeoutMs + kTofRecoveryDelayAllowanceMs;
constexpr std::uint32_t kTofPollAndRecoveryBudgetMs =
    kTofPollWireBudgetMs + kTofRecoveryWireBudgetMs;

// Configured wait budget only: excludes mutex contention, scheduler latency,
// driver overhead, other bus clients and startup calibration. It is NOT a
// wall-clock guarantee or proof of the 45 ms MotorHeartbeat deadline.
static_assert(kTofWireTimeoutMs > 0U && kTofPollAndRecoveryBudgetMs < 250U,
              "ToF configured wait budget must fit the 250 ms drive permit");
static_assert(kTofPollAndRecoveryBudgetMs < 500U,
              "ToF configured wait budget must fit the 500 ms body watchdog");

// Includes rejection of the device's 8190 mm invalid range word.
constexpr bool tof_range_in_bounds(std::uint16_t mm) noexcept {
  return mm >= kTofMinRangeMm && mm <= kTofMaxRangeMm;
}

}  // namespace desk_robot
