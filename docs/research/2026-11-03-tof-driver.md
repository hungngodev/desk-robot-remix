# ToF transport-driver gap — 2026-11-03

## Current source status (2026-11-27, DRX-1733)

The November 3 missing-driver description below is historical. The default
`esp32_full` and guarded `esp32_dc_full` profiles in
[platformio.ini](../../code/firmware/body/platformio.ini) pin Pololu
VL53L0X (MIT) at `9f3773cb48d4e4e844d689cfc529a06f96d1d264`.
The historical `esp32_stepper` profile retains five range channels; both
full profiles enable eight.

[TofBus](../../code/firmware/body/lib/TofBus/TofBus.cpp) reuses the pinned
driver for startup and performs checked, bounded runtime I2C on TCA9548A
0x70, with VL53L0X address 0x29 and fitted accessory mux 0x71 quiesced.
Lanes 0–4 are four floor and one forward critical measurements; lanes 5–7
are side/rear diagnostics, not movement authority. Polling reads readiness
at 0x13, the 12-byte result at 0x14 and checks interrupt clear at 0x0B.
Not-ready transport success does not renew optical freshness.
[TofResult](../../code/firmware/body/lib/TofBus/TofResult.h) accepts raw
device status 11, a minimum signal threshold and an in-bounds range; this
raw status is not the normalized ST API status. Recovery does not publish
a new range or clear the CliffGuard latch.

The [host mux regression](../../code/firmware/body/tests/tof_mux_tests.cpp)
and [cliff guard tests](../../code/firmware/body/tests/cliff_tests.cpp) are
existing source evidence, not test execution evidence for this review.
The exact carrier, optical geometry, calibration, scan latency under load
and physical stopping envelope remain unqualified. No motion release
follows from this documentation update.

## Historical November 3 research

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
