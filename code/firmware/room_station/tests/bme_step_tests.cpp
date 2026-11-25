#include <cassert>
#include <cmath>
#include <cstdint>
#include "bme_completed_sample.h"

using std::isfinite;
constexpr uint32_t kReportMs = 1000, kBmeStaleMs = 3000;
uint32_t clock_ms = 0;
uint32_t millis() { return clock_ms; }

struct Adafruit_BME680 {
  static constexpr int reading_complete = 0;
  int remaining = 0;
  bool start_ok = true, end_ok = true, fields = true;
  float temperature = 0, humidity = 0, next_temp = -10, next_humidity = 55;
  uint32_t pressure = 0, gas_resistance = 0, next_pressure = 101000, next_gas = 12345;
  unsigned ends = 0;
  bool model_driver_clock = false;
  uint32_t driver_start = 0;
  unsigned starts = 0;
  uint32_t beginReading() {
    ++starts;
    if (!start_ok) return 0;
    if (!model_driver_clock) return 1;
    // Pinned 2.0.5 uses zero as both failure and a timestamp sentinel.
    if (driver_start == 0) driver_start = clock_ms;
    return driver_start + 200U;
  }
  int remainingReadingMillis() {
    if (!model_driver_clock) return remaining;
    if (driver_start == 0) return -1;
    const uint32_t elapsed = clock_ms - driver_start;
    return elapsed < 200U ? static_cast<int>(200U - elapsed) : 0;
  }
  bool endReading() {
    ++ends;
    if (model_driver_clock) {
      if (beginReading() == 0) return false;
      driver_start = 0;
    }
    if (end_ok && fields) {
      temperature = next_temp; humidity = next_humidity;
      pressure = next_pressure; gas_resistance = next_gas;
    }
    return end_ok;
  }
} bme;

bool bme_started = true, bme_pending = false;
uint32_t bme_last_start_ms = 0;
desk_robot_room::BmeCompletedSample bme_completed;

#include "bme_step_under_test.h"

void step(uint32_t now) { clock_ms = now; bme_step(now); }
void reset() {
  bme = Adafruit_BME680{};
  bme_started = true; bme_pending = false; bme_last_start_ms = 0;
  bme_completed = desk_robot_room::BmeCompletedSample{};
}

int main() {
  // A loop stall must not relabel an old conversion as freshly acquired.
  reset(); step(1000); step(4001);
  assert(!bme_completed.valid && !bme_pending && bme.ends == 1);
  reset(); step(1000); step(1200);
  assert(bme_completed.valid && bme_completed.sample_ms == 1000);
  assert(bme_completed.temperature_c == -10 && bme_completed.gas_ohms == 12345);
  // New scratch must not mix with the old tuple while the heater is active.
  step(2000); bme.remaining = 50; step(2050);
  assert(bme_pending && bme.gas_resistance == 0 && bme.ends == 1);
  assert(bme_completed.fresh(2050, kBmeStaleMs));
  assert(bme_completed.gas_ohms == 12345 && bme_completed.sample_ms == 1000);
  // Old tuple expires during a stalled conversion, even before collection.
  step(4001); assert(!bme_completed.fresh(4001, kBmeStaleMs));
  bme.remaining = 0; step(5001);
  assert(!bme_completed.valid && !bme_pending && bme.ends == 2);
  // A successful next conversion must replace every field together, not
  // just the gas value and timestamp. Use distinct scratch and new values.
  reset(); step(1000); step(1200);
  step(2000); bme.remaining = 50;
  bme.temperature = 90; bme.humidity = 99; bme.pressure = 40000;
  bme.next_temp = 21; bme.next_humidity = 42;
  bme.next_pressure = 102000; bme.next_gas = 67890;
  step(2050);
  assert(bme_completed.fresh(2050, kBmeStaleMs));
  assert(bme_completed.temperature_c == -10 && bme_completed.humidity_pct == 55);
  assert(bme_completed.pressure_pa == 101000 && bme_completed.gas_ohms == 12345);
  assert(bme_completed.sample_ms == 1000);
  bme.remaining = 0; step(2200);
  assert(bme_completed.fresh(2200, kBmeStaleMs) && bme_completed.sample_ms == 2000);
  assert(bme_completed.temperature_c == 21 && bme_completed.humidity_pct == 42);
  assert(bme_completed.pressure_pa == 102000 && bme_completed.gas_ohms == 67890);
  for (int fault = 0; fault < 9; ++fault) {
    reset(); step(1000); step(1200); assert(bme_completed.valid);
    if (fault == 0) bme.start_ok = false;
    step(2000);
    if (fault == 1) bme.end_ok = false;
    if (fault == 2) bme.fields = false;
    if (fault == 3) bme.next_gas = 0;
    if (fault == 4) bme.next_gas = 1000000001U;
    if (fault == 5) bme.next_temp = -41;
    if (fault == 6) bme.next_pressure = 29999;
    if (fault == 7) bme.next_pressure = 125001;
    if (fault == 8) bme.remaining = -1;
    step(2200); assert(!bme_completed.valid && !bme_started && !bme_pending);
  }
  // A conversion started 200 ticks before wrap would return zero and
  // leave the pinned driver permanently pending, even across begin().
  reset(); bme.model_driver_clock = true;
  step(UINT32_MAX - 199U);
  assert(bme_started && !bme_pending && bme.starts == 0);
  step(0U);
  assert(bme_started && !bme_pending && bme.starts == 0);
  step(1U); step(201U);
  assert(bme_completed.valid && bme_completed.sample_ms == 1U);
  assert(bme_started && !bme_pending && bme.driver_start == 0U);
  // A normal acquisition just before the guard remains valid, and its
  // cache expires at the usual age without a new conversion in the gap.
  reset(); bme.model_driver_clock = true;
  step(UINT32_MAX - 5200U); step(UINT32_MAX - 5000U);
  assert(bme_completed.valid && bme_completed.sample_ms == UINT32_MAX - 5200U);
  step(UINT32_MAX - 4000U);
  assert(bme_completed.fresh(UINT32_MAX - 4000U, kBmeStaleMs));
  step(UINT32_MAX - 2199U);
  assert(!bme_completed.fresh(UINT32_MAX - 2199U, kBmeStaleMs));
  step(1U); step(201U);
  assert(bme_completed.valid && bme_completed.sample_ms == 1U);
}
