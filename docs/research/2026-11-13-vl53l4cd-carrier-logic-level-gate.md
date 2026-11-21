# Historical VL53L4CD carrier voltage warning (superseded 2026-11-13 research)

**SUPERSEDED HARDWARE SELECTION: DO NOT USE THIS DOCUMENT AS CURRENT GY-530 WIRING OR PURCHASING INSTRUCTIONS.** Pololu #3692 VL53L4CD was a previous proposal only. The current WROOM `esp32_full` uses eight **VL53L0X GY-530 candidate** carriers at I2C 0x29, one per TCA9548A 0x70 lane, through pinned Pololu `vl53l0x-arduino` 1.3.1. None of the eight current carrier revisions has qualified 3.3 V I2C pullups, regulator, lens mounting or optical performance. The following Pololu #3692 electrical observations are retained only as evidence of why IC supply ratings cannot justify a generic breakout hookup. They do not describe the GY-530. Do not replace `TofBus`, mux fault latches or local cliff guard.

## Specific risk missed by an IC-only voltage check

The selected [Pololu #3692 VL53L4CD carrier](https://www.pololu.com/product/3692?coupon=BF24P3692) includes a 2.8 V regulator and SDA/SCL level shifters. Its **external SDA and SCL logic high is pulled toward the carrier VIN**, not automatically toward the sensor's 2.8 V internal rail. Feeding the carrier VIN from 5 V while wiring its external I2C lines to a 3.3 V WROOM/mux bus is therefore **not a validated safe hookup**. Do not equate the carrier's advertised 2.8–5.5 V input capability with WROOM-safe signal levels. Confirm the exact purchased carrier revision and the complete upstream mux-side pull-up voltage before energizing.

Pololu also states that XSHUT and GPIO1 are **not level shifted**, are pulled toward internal VDD, and are not 5 V tolerant. Do not drive XSHUT push-pull high at 5 V. The current plan does not allocate eight independent XSHUT outputs; do not add unreviewed pins or bypass the mux fault guard to work around that.

## Reuse and scope

* [Pololu #3692 product documentation](https://www.pololu.com/product/3692?coupon=BF24P3692): hardware reference, not a code license. Its published carrier circuit and pin semantics take precedence over assumptions from generic breakout descriptions.
* [ST VL53L4CD datasheet](https://www.pololu.com/file/0J2060/vl53l4cd.pdf): native I2C pull-up and XSHUT electrical recommendations; bare IC recommendations must not be substituted for the breakout's external level-shifter behavior.
* [Adafruit multi-mux tutorial](https://learn.adafruit.com/working-with-multiple-i2c-devices/multiple-muxers): demonstrates independent 0x70 and 0x71 mux addresses, selecting one downstream branch at a time and deselecting all others. This is an educational topology reference, not imported source or evidence of the actual bus. Current repository already implements and tests mux select/readback/fault logic, so do not create another bus abstraction.
* [ST VL53L4CD ULD license example](https://github.com/bslisowski/VL53L4CD-ULD-esp-idf/blob/main/platform.h): shows the ST ULD dual proprietary/BSD 3-Clause notice. This third-party port is not imported or pinned for this product; preserve the existing pinned Pololu/ST attribution and verify exact copied file notices before any source replacement.

## Historical experiment to adapt only after identifying the actual VL53L0X carrier

The named Pololu VIN, VDD, XSHUT and GPIO1 silk labels below describe **VL53L4CD #3692** and must not be assumed on the selected generic VL53L0X GY-530. Before adapting these steps, record the actual GY-530 board schematic, markings, breakout 3.3 V limits, lens pin/position and connector orientation. The current eight-channel WROOM harness must remain unpowered until each actual carrier's logic levels are measured against the mux and host.

## Historical unpowered acceptance experiment

1. Inventory the **exact eight carrier part numbers and PCB markings**; photograph their VIN, VDD, SDA, SCL, XSHUT and GPIO1 labels. Compare each actual carrier schematic with the documented selected source. Do not assume all eight boards have the same circuitry.
2. Trace WROOM 3.3 V logic through both muxes and every external SDA/SCL pull-up, including onboard resistors. Document the intended logic domain at each mux upstream/downstream pin. **Do not energize until any 5 V pull-up exposure to WROOM is eliminated.**
3. With motors and charger physically disconnected, current-limit the sensor-only supply and measure idle SDA/SCL high voltage at the WROOM and at each selected mux branch, including after brownout/reset. Verify no simultaneous same-address lanes remain connected and no bus recovery clears the local stop latch.
4. Measure bus rise time and branch loading with the full harness; verify each of eight lane IDs, boot/readback, repeated sample freshness and induced stuck/ACK faults. A passing portable test is not an electrical measurement.
5. Record actual results in docs/records/verification.md with carrier revision, supply voltage, probe point, instruments, scope trace, source commit and outcome. Until then mark the **entire ToF electrical harness unqualified**, including optional side/rear ranges.

**Next source-level action:** review the current wiring manifest and its test to see whether an explicit per-carrier VIN/I2C-domain constraint can be enforced without inventing a regulator selection or changing motor safety. Do not alter WROOM safety policy from this research note.
