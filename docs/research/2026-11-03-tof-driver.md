# ToF transport-driver gap — 2026-11-03

The portable sensor policy is implemented, but the body intentionally has no
live ToF/mux reader yet. A numeric distance alone is insufficient: the adapter
must report short reads, rejected writes, timeouts, invalid range quality and
stale data to the latched guard. Default calibration/samples remain absent,
so the stepper profile refuses arming.

Context7 found Pololu/Adafruit documentation but no exact STM32duino VL53L0X
entry. Direct primary-source review of
[STM32duino VL53L0X at49f877a](https://github.com/stm32duino/VL53L0X/tree/49f877aa99664ac0c4275368235f11c4f0c3faf9)
confirmed that its [I²C platform functions](https://github.com/stm32duino/VL53L0X/blob/49f877aa99664ac0c4275368235f11c4f0c3faf9/src/vl53l0x_class.cpp)
do not propagate the Wire transaction/count checks required here. An application
must not interpret their successful return alone as proof of a valid transfer.
This is a specific integration limitation, not a claim that every use of the
library is faulty.

The next implementation should pin a licensed upstream ST-compatible driver,
retain its notices, and use a small checked platform port. Initialization may
run while all outputs are disabled. Runtime polling must select one mux channel,
check data-ready without waiting a full measurement period, read bounded results,
validate range status, clear the interrupt with a checked transaction, and give
the guard a fresh result only on success. Poll at most one channel per cycle;
measure the complete five-sensor freshness/latency under load. A bus fault/reset
invalidates old readings and never clears the motor latch.

Before integration, test NACK, short read, timeout, invalid-quality result,
not-ready/stale data, mux-selection failure and reset/recovery with a fake bus.
Check the real driver’s sensor-status mapping from its API; raw device status
bits are not interchangeable with the API’s normalized status. Then build on
ESP32 and qualify physical timing, standoff and stops. No new driver or external
library was copied into the body firmware in this milestone.
