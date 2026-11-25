#include "../src/vl53l0x_bench.cpp"
#include <cassert>

static void reset() {
  ready = false;
  last_report_ms = 0;
  stuck_bus = false;
  clock_ms = 120;
  outputs_low = 0;
  Wire = FakeWire{};
  sensor = VL53L0X{};
  Serial = FakeSerial{};
}

int main() {
  reset();
  Wire.fail_begin = true;
  setup();
  assert(!ready && Wire.starts == 0 && outputs_low == 10);
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
