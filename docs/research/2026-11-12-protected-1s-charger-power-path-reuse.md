# 2026-11-12 protected 1S charging and dock power path reuse review

Scope: research only for canonical draft PR #17. No battery, charging contact, PCB, harness, or firmware charge enable is qualified. This note does not authorize energizing a lithium pack or a dock.

## Candidate comparison from primary sources

1. **TI BQ24074**: established single cell charger with dynamic power path, charge and input current limits, thermistor input, thermal regulation, timers and status pins. TI product and datasheet: https://www.ti.com/product/BQ24074/part-details/BQ24074RGTR . Adafruit's published BQ24074 Eagle schematic and PCB are an actual open hardware implementation, not just a tutorial: https://github.com/adafruit/Adafruit-BQ24074-PCB . Its published license is Creative Commons Attribution ShareAlike with attribution requirements. Do not copy the board layout into this repo without recording the exact license text, version and required attribution. The retail board's intended USB/DC/solar use does not establish safe exposed robot dock contacts, pack protection, motor peak current or mechanical isolation.
2. **TI BQ25185**: active one cell charger with regulated 4.5 V SYS power path, selectable input current limit, thermistor protection and battery/system fault handling. Datasheet and product information: https://www.ti.com/product/BQ25185 . Its maximum 1 A charge rate and stated 3.125 A system discharge capability are distinct ratings. A charger IC is not a complete dock PCB, battery protection circuit or 5 V motor supply. No reviewed, pinned and compatible open hardware carrier design has yet been selected for this alternative.
3. **Existing PR #17 owner**: retain the existing read only MCP23017 seat/PGOOD/CHG observation, WROOM fail closed motion policy and Mac docking evidence. Neither software state nor AprilTag/IR agreement may substitute for independent charger protection, contact polarity and actual current/thermal measurements.

## Decision and incompatibilities

Prefer evaluating a purchased, documented BQ24074 power path board and its published CC BY SA schematic as a **bench reference**, not transplanting it into a finalized dock. BQ25185 remains a credible IC alternative, but changing to it would require a new qualified PCB and thermal/power budget. No firmware charge control, current threshold, BOM purchase approval or pin wiring changes follow from this comparison.

Both candidates are linear chargers: verify worst case thermal dissipation at actual adapter voltage, charge current, battery voltage and robot load. Characterize motor and servo startup peaks separately from average load; do not confuse charger current with available regulator output current. Require independently protected matched 1S cell, temperature sensing, fuse/current limiting, reverse polarity and short safe keyed contacts, power path isolation, hot removal and brownout tests. Document dock input and system rail transient behavior with a current limited bench supply before attaching any lithium pack.

## Next independently verifiable engineering action

In existing `code/scripts/power_preflight.py` and its tests, inspect whether measured **peak system demand** and regulator/board continuous ratings are compared separately from charger input/charge limits. Add one deterministic failing regression only if a real missing constraint is found, without loosening existing conservative thresholds. Then record exact board revision, protection topology, battery cell datasheet, regulator load curve, contact geometry and thermal budget in the existing wiring and BOM matrix. Do not create a second charging owner or a new PR.

Verification: vendor documentation and published open hardware license reviewed on 2026-11-12. No schematic was copied, no code was changed, no electrical measurements or test executions occurred in this research pass.
