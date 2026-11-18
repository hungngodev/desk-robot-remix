# Read only dock contact and charger status, one complete robot

The hardware plan allocates MCP23017 at WROOM accessory mux 0x71 lane 5, I2C address 0x20. The new firmware adapter uses *only inputs*, with on-chip 3.3V pullups:

* GPA0 and GPA1 are independent normally closed mechanical dock contact confirmation switches. Both should open to HIGH when the robot is seated. A broken wire can look like a pressed switch, so these alone never prove docking or authorize charging.
* GPA2 reads **BQ24075 PGOOD** as an open drain, LOW meaning the charger reports a valid input source. The earlier BQ24074 reference is an alternative IC and not the active paper power path. The charger status needs actual powered verification.
* GPA3 reads **BQ24075 CHG** as an open drain, LOW meaning the IC reports an active charge cycle. This is not a current measurement or proof that the battery is accepting charge.

The WROOM reports these four bools through the existing read only `aux` path. The Sense bridge and Mac validator type-check them, reject fictional `charging_verified=true`, and never enable the charger or drive actuators.

CHG active with PGOOD active but **neither independent seat switch confirming contact** is a contradiction and now reports `charge_signal_without_seat_fault`, not the routine `charger_input_without_seat` state. Three fresh matching pin readings still cannot establish actual charging current or authorize charging. The corresponding host regression was added to the existing dock test file; repository CI and physical validation are not yet proven.

Power path proposal for review, **not verified electronics**: a protected compatible 1S cell with pack protection and temperature monitoring, a current and thermally qualified boost converter for the 5V body/head motors, a separately selected single-cell power-path charger operating from a short protected dock input, and correctly fused keyed recessed contacts. A BQ24074 is a useful *reference design* with dynamic power-path management, but has max 1.5A charge current and must not be mistaken for a 5V high current boost output or protection of arbitrary bare 18650 cells. Vendor data: https://www.ti.com/product/BQ24074.

The actual battery, boost, charger board, NTC wiring, input charge contact current limit, thermal load, chassis geometry, shore power, and exposed contact safety remain unselected and cannot be called verified until built and measured. Do not energize exposed metal contacts from this file.

## November 11 replay safe physical sample path

The original three HTTP responses were **not proof of three independent physical reads**. The same cached WROOM auxiliary UART line could have been returned repeatedly and labelled `stable_three_samples=true`. The corrected source requires genuine hardware acquisition identity.

* Source register map: [Microchip MCP23017 DS20001952D](https://ww1.microchip.com/downloads/aemDocuments/documents/APID/ProductDocuments/DataSheets/MCP23017-Data-Sheet-DS20001952.pdf), BANK=0. `IODIRA=0x00`, `GPPUA=0x0C`, `GPIOA=0x12`. The actual WROOM firmware already uses these registers and no extra interrupt pin.
* `AccessorySensors::dock_status()` increments `DockPinRaw.sample_seq` **only after a successful GPIOA I2C read**. A failed read does not advance it. The WROOM `aux` UART payload now exposes `dock.seq` and `dock.age_ms`, without increasing the motor/safety authority of those pins.
* `desk_robot.aux.validate_aux()` rejects malformed/missing sequence fields, ages 500ms or older for allegedly valid samples, and any attempt to assert `charging_verified=true`.
* `desk_robot.dock_evidence.observe_dock_evidence()` requires three sequentially **increasing** nonzero acquisition IDs and unchanged physically reported seat/status signals. Replayed cached JSON, firmware restart, counter reset, or disagreeing switches return an explicit unqualified diagnostic. No motor drive, contact power enable or charging permission is introduced.
* Host tests in `code/firmware/body/tests/optional_i2c_io_tests.cpp` use the existing deterministic Wire emulator to confirm that sequence numbers only advance on successful dock GPIOA acquisitions, including failed transfer injection. `code/tests/test_dock_evidence.py` tests repeated/reordered Mac snapshots, future/stale status, contradictory seat input and false charge assertions.
* BQ24074 `CHG`/ `PGOOD` status outputs are open drain and indicate **chip state**, not bidirectional battery current. [TI BQ24074 datasheet](https://www.ti.com/lit/ds/symlink/bq24074.pdf) additionally notes timer faults and thermal suspension behavior. Three independently sampled LOW pins can still mean **no net charge flowing into the battery** under motor/head loads.

**Electrical bench acceptance remains open.** Do not command terminal approach or energize contacts until actual protected power circuit, complete rated connector/contact assembly, fuse, thermal measurements, and independent battery current sensing are validated. `charging_verified` stays `false` in every current API result.

## Actual INA226 current source and net-charge agreement, November 17

The complete power [net specification](2026-11-17-one-pet-protected-power-circuit.md)
now places a source-verified five milliohm two watt Kelvin shunt between
BQ24075 BAT pins 2/3 and the **protected external PACK+**. INA226 IN+
is at the charger side, IN- on protected pack side. Positive shunt
voltage means current **towards** the battery and negative indicates
battery supplement/discharge, in the wiring orientation described.

This is **not** a drop-in shunt on arbitrary generic INA226 modules.
Inspect the actual carrier shunt and Kelvin sense connections before
building `esp32_dc_integrated_lab`. Standard firmware sets
`DESK_ROBOT_PACK_SHUNT_MOHM=0`, so even a present INA226 never
claims physically calibrated charge amps. The opt-in integrated build
uses exactly 5 milliohm to derive `pack_ma`, `pack_valid` and
`pack_seq` only after a successful raw register read. The independent
Mac source in `dock_evidence.py` now requires three newly acquired
INA226 readings, separately from three newly acquired MCP23017 dock
status samples, before indicating **raw** charge direction. If the
charger reports CHG active but all raw current indicates sustained
battery discharge, `charger_indicator_net_discharge_conflict=true`
is reported. `charging_verified`, `charging_authorized`, and
`battery_current_measured` intentionally remain **false**; actual
shunt calibration, connector ratings, charger TS NTC fault sweep and
net battery charging must be verified with a separate instrument.
