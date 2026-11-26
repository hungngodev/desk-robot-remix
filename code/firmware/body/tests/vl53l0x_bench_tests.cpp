#include "../src/vl53l0x_bench.cpp"
#include <cassert>

// One shared fake hardware state, without C++17 inline variables.
bool stuck_bus = false;
uint32_t clock_ms = 0;
unsigned outputs_low = 0;
std::array<unsigned, 40> low_writes{}, output_modes{}, input_reads{};
FakeSerial Serial;
FakeWire Wire;

static void reset() {
  ready = optional_mux_present = false;
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

static void next_poll() {
  clock_ms += 120;
  loop();
}

static void test_startup() {
  reset();
  Wire.fail_begin = true;
  setup();
  assert(!ready && Wire.starts == 0 && outputs_low == 10);
  assert_safe_harness();
  reset();
  Wire.short_write = true;
  setup();
  assert(!ready && Wire.starts == Wire.stops && Wire.reads == 0);
  reset();
  Wire.hold_after_stop = true;
  Wire.optional_installed = true;
  setup();
  assert(!ready && Wire.stops == 1 && Wire.reads == 0);
  reset();
  Wire.mux_readback = 3;
  setup();
  assert(!ready && sensor.starts == 0);
  reset();
  sensor.fail_start = true;
  setup();
  assert(!ready && sensor.starts == 1 && Wire.ranges == 0);
  reset();
  sensor.timed_out = true;
  setup();
  assert(!ready && Wire.ranges == 0);
  reset();
  Wire.optional_installed = true;
  Wire.extras = 1;
  Wire.optional_stuck = true;
  setup();
  assert(!ready && sensor.starts == 0 && Wire.ranges == 0);
  reset();
  Wire.optional_installed = true;
  Wire.extras = 1;
  setup();
  assert(ready && Wire.ranges == 0 && Wire.extras == 0 && Wire.timeout_ms == 10);
  assert_safe_harness();
  assert(input_reads[21] > 0 && input_reads[22] > 0);
}

static void test_optical_rejection() {
  reset();
  setup();
  assert(ready);
  loop();
  assert(Serial.samples == 1 && Serial.valid == 1 && Wire.clears == 1);
  Wire.interrupt_status = 0;
  next_poll();
  assert(Serial.samples == 1 && Wire.results == 1 && Wire.clears == 1);
  Wire.interrupt_status = 0x18;
  next_poll();
  assert(Serial.samples == 2 && Serial.valid == 0 && Wire.results == 1 && Wire.clears == 2);
  Wire.interrupt_status = 7;
  Wire.raw_status = 4;
  next_poll();
  assert(Serial.samples == 3 && Serial.valid == 0 && ready);
  Wire.raw_status = 11;
  Wire.signal = 31;
  next_poll();
  assert(Serial.samples == 4 && Serial.valid == 0 && ready);
  Wire.signal = 32;
  Wire.mm = 8190;
  next_poll();
  assert(Serial.samples == 5 && Serial.valid == 0 && ready);
  Wire.mm = 45;
  next_poll();
  assert(Serial.samples == 6 && Serial.valid == 1 && ready);
}

static void test_transport_faults() {
  for (unsigned fault_case = 0; fault_case < 4; ++fault_case) {
    reset();
    setup();
    assert(ready);
    if (fault_case == 0) Wire.short_result = true;
    if (fault_case == 1) Wire.fail_clear = true;
    if (fault_case == 2) Wire.hold_after_result = true;
    if (fault_case == 3) Wire.mux_readback = 3;
    loop();
    assert(!ready && Serial.samples == 0);
    if (fault_case == 2) assert(Wire.clears == 0);
    else assert(Wire.ranges == 0);
    const unsigned transactions = Wire.starts;
    next_poll();
    assert(Wire.starts == transactions);
  }
}

int main() {
  test_startup();
  test_optical_rejection();
  test_transport_faults();
  return 0;
}
