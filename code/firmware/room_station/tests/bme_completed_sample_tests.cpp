#include "bme_completed_sample.h"
#include <iostream>
#include <stdexcept>
#define CHECK(x) do { if (!(x)) throw std::runtime_error(#x); } while (false)
int main() {
  try {
    desk_robot_room::BmeCompletedSample sample{};
    CHECK(!sample.fresh(1000U, 3000U));
    sample.publish(24.25f, 52.5f, 101325.0f, 78291U, 1000U);
    CHECK(sample.fresh(1000U, 3000U));
    CHECK(sample.fresh(4000U, 3000U));
    CHECK(!sample.fresh(4001U, 3000U));
    CHECK(sample.temperature_c == 24.25f);
    CHECK(sample.humidity_pct == 52.5f);
    CHECK(sample.pressure_pa == 101325.0f);
    CHECK(sample.gas_ohms == 78291U);
    CHECK(sample.sample_ms == 1000U);
    sample.publish(20.0f, 40.0f, 101010.0f, 64101U, 0xfffffff0U);
    CHECK(sample.fresh(0x00000010U, 3000U)); // millis wrap
    CHECK(!sample.fresh(0x00000bb8U, 3000U));
    CHECK(sample.gas_ohms == 64101U);
    sample.invalidate(); // invalid or empty next conversion
    CHECK(!sample.fresh(0x00000010U, 3000U));
    sample.publish(23.0f, 45.0f, 100000.0f, 91231U, 30U);
    CHECK(sample.fresh(31U, 3000U) && sample.sample_ms == 30U);
    CHECK(sample.gas_ohms == 91231U);
    std::cout << "PASS BME complete snapshot and pending retention\n";
  } catch (const std::exception& e) {
    std::cerr << "FAIL " << e.what() << "\n";
    return 1;
  }
}
