#include "../src/vl53l0x_bench.cpp"
#include <cassert>

static void reset() {
  ready = false;
  last_report_ms = 0;
  stuck_bus = false;
  clock_ms = 120;
  outputs_low = 0;
  low_writes.fill(0);
  output_modes.fill(0);
  input_reads.fill(0);
  Wire = FakeWire{};
  sensor = VL53L0X{};
  Serial = FakeSerial{};
}

static void assert_safe_harness() {
  // Independent fixed harness oracle; do not derive the expectation from
  // the production array, which could contain the same erroneous pin.
  const int expected[] = {13, 14, 18, 19, 23, 25, 26, 27, 32, 33};
  for (int pin = 0; pin < 40; ++pin) {
    unsigned writes = 0;
    for (int safe : expected) if (pin == safe) ++writes;
    assert(low_writes[pin] == writes && output_modes[pin] == writes);
  }
}

int main() {
  reset();
  Wire.fail_begin = true;
  setup();
  assert(!ready && Wire.starts == 0 && outputs_low == 10);
  assert_safe_harness();
  reset();
  Wire.short_write = true;
  setup();
  assert(!ready && Wire.starts == 1 && Wire.stops == 1 && Wire.reads == 0);
  reset();
  Wire.hold_after_stop = true;
  setup();
  assert(!ready && Wire.stops == 1 && Wire.reads == 0);
  reset();
  Wire.mux_readback = 3;
  setup();
  assert(!ready && sensor.starts == 0);
  reset();
  sensor.fail_start = true;
  setup();
  assert(!ready && sensor.starts == 1);
  reset();
  setup();
  assert(ready);
  assert_safe_harness();
  assert(input_reads[21] > 0 && input_reads[22] > 0);
  loop();
  assert(Serial.samples == 1 && Serial.valid == 1);
  clock_ms += 120;
  sensor.mm = 8190;
  loop();
  assert(Serial.samples == 2 && Serial.valid == 0 && ready);
  clock_ms += 120;
  sensor.mm = 45;
  sensor.fail_sample = true;
  loop();
  assert(Serial.samples == 3 && Serial.valid == 0 && !ready);
  clock_ms += 120;
  loop();
  assert(sensor.reads == 3);
  reset();
  setup();
  sensor.timed_out = true;
  loop();
  assert(!ready && Serial.valid == 0);
  return 0;
}
