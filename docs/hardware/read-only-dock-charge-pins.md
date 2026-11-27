# Read only dock contact and charger status, one complete robot

The hardware plan allocates MCP23017 at WROOM accessory mux 0x71 lane 5, I2C address 0x20. The dock status adapter configures GPIOA as inputs (`IODIRA=0xFF`) with on-chip 3.3V pullups on GPA0–3 (`GPPUA=0x0F`):

* GPA0 and GPA1 are independent normally closed mechanical dock contact confirmation switches. Both should open to HIGH when the robot is seated. A broken wire can look like a pressed switch, so these alone never prove docking or authorize charging.
* GPA2 reads **BQ24075 PGOOD** as an open drain, LOW meaning the charger reports a valid input source. The earlier BQ24074 reference is an alternative IC and not the active paper power path. The charger status needs actual powered verification.
* GPA3 reads **BQ24075 CHG** as an open drain, LOW meaning the IC reports an active charge cycle. This is not a current measurement or proof that the battery is accepting charge.

These four dock pins are read only; the entire expander is not necessarily input only. GPIOB has separate accessory inputs, and the opt-in haptic profile configures GPB2 as an output to an external current-limited hardware one-shot, not a charger enable. The WROOM reports the four normalized dock booleans through `aux`: `left_seated`, `right_seated`, `input_good`, and `charge_indicated`. The Mac validator rejects `charging_verified=true`. The WROOM local dock interlock may inhibit motion; these observations never authorize movement or charging. The GPIO levels do not identify the installed charger IC.

`classify_dock()` first reports `charge_signal_without_input_fault` for CHG asserted without PGOOD, even if the seat switches disagree. Otherwise asymmetric normalized seating is `asymmetric_seat_or_fault`. With PGOOD and CHG asserted but neither seat switch confirming contact, the result is `charge_signal_without_seat_fault`, not `charger_input_without_seat`. Three fresh matching pin readings still cannot establish actual charging current or authorize charging. `code/tests/test_dock_evidence.py` covers all 16 combinations; see exact-revision CI for software test results, not physical validation.

Power path proposal for review, **not verified electronics**: a protected compatible 1S cell with pack protection and temperature monitoring, a current and thermally qualified buck/boost regulator for the 5V system rail from the charger OUT domain, a separately selected single-cell power-path charger operating from a short protected dock input, and correctly fused keyed recessed contacts. BQ24075 is the active paper candidate with dynamic power-path management and a 1.5A maximum input limit; BQ24074 is an alternative reference only. Neither is a regulated 5V boost output or protection for arbitrary bare 18650 cells. See the [selected paper net specification](2026-11-17-one-pet-protected-power-circuit.md) and [TI BQ24075](https://www.ti.com/product/BQ24075).

The actual battery, buck/boost regulator, charger board, NTC wiring, input charge contact current limit, thermal load, chassis geometry, shore power, and exposed contact safety remain unselected and cannot be called verified until built and measured. Do not energize exposed metal contacts from this file.

## Independent cold-contact acceptance boundary

The two normally closed GPA0/GPA1 switches are **robot-side read-only
evidence**, not the dock-side charge enable interlock. In the following
matrix, seated means the normalized logical observation (HIGH on GPA0 or
GPA1), not a physically closed electrical switch. An open wire can
produce the same observation as a pressed switch. Even both HIGH cannot
prove correct mating, polarity, or electrical independence.

| Physical test condition | Required dock contact power state |
| --- | --- |
| Empty dock, including startup/reset or loss of controller power | Off |
| Partial bump, left switch alone, or right switch alone | Off |
| One switch stuck, open wire, shorted wire, or contradictory seat evidence | Off; do not bypass a failed seat channel |
| Both switches apparently seated, but polarity, contact coverage or protection not established | Off |
| Full correctly polarized seating and independently validated hardware interlock | Eligible for separate current-limited electrical acceptance only; still off in the current unqualified build |
| Removal, intermittent seating, or dock supply loss/recovery | Off; no software-only reenable |

The independent dock supply and switching schematic must establish its
default-off state and fault behavior without Mac, WROOM, Nano beacon,
I2C, or any software permission. Before approval, record measured contact
voltage in the above conditions, removal cutoff and residual stored
energy, connector polarity, reverse/backfeed isolation (including robot
battery and USB sources), and current-limit/short protection. Begin with
unpowered continuity and mechanical tests; any powered fault test requires
a separately reviewed current-limited bench fixture without a live pack.
Use the existing protected power design and DRR-145 acceptance boundary;
no new component or charge-enable implementation is selected here.
PGOOD, CHG, an AprilTag, NEC reception, and even signed pack current are
not substitutes for independently safe contact energization.

## November 11 replay safe physical sample path

The original three HTTP responses were **not proof of three independent physical reads**. The same cached WROOM auxiliary UART line could have been returned repeatedly and labelled `stable_three_samples=true`. The corrected source requires genuine hardware acquisition identity.

* Source register map: [Microchip MCP23017 DS20001952D](https://ww1.microchip.com/downloads/aemDocuments/documents/APID/ProductDocuments/DataSheets/MCP23017-Data-Sheet-DS20001952.pdf), BANK=0. `IODIRA=0x00`, `GPPUA=0x0C`, `GPIOA=0x12`. The actual WROOM firmware already uses these registers and no extra interrupt pin.
* `AccessorySensors::dock_status()` increments `DockPinRaw.sample_seq` **only after a successful GPIOA I2C read**. A failed read does not advance it. The WROOM `aux` UART payload now exposes `dock.seq` and `dock.age_ms`, without increasing the motor/safety authority of those pins.
* `desk_robot.aux.validate_aux()` rejects malformed/missing sequence fields, ages 500ms or older for allegedly valid samples, and any attempt to assert `charging_verified=true`.
* `desk_robot.dock_evidence.observe_dock_evidence()` requires three nonzero acquisition IDs that advance under the unsigned 32-bit half-range rule (rollover is supported), unchanged normalized pin observations, and the same nonzero WROOM boot ID in both `force.boot_id` and `proximity.boot_id` across all three replies. Missing or changed epochs, replayed IDs, or changed pins fail the stability check. Stable contradictory pins can still produce an explicit fault classification; `stable_three_samples` does not mean safe seating. Consumer freshness includes request latency: `dock.age_ms` plus elapsed request time must be below 500 ms. Each read is bounded by a 2 s timeout, the requested gap is 0.25–1.0 s (default 0.30 s), and excess scheduling delay beyond the gap plus 500 ms invalidates the observation window. No motor drive, contact power enable or charging permission is introduced.
* Host tests in `code/firmware/body/tests/optional_i2c_io_tests.cpp` use the existing deterministic Wire emulator to confirm that sequence numbers only advance on successful dock GPIOA acquisitions, including failed transfer injection. `code/tests/test_dock_evidence.py` tests repeated/reordered Mac snapshots, future/stale status, contradictory seat input and false charge assertions.
* BQ24075 candidate `CHG`/`PGOOD` status outputs are open drain and indicate **chip state**, not bidirectional battery current. The [TI BQ24075 datasheet](https://www.ti.com/lit/ds/symlink/bq24075.pdf) describes power-path and charge-state behavior. Three independent samples of asserted status pins can still mean **no net charge flowing into the battery** under system loads.

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
status samples, before indicating **raw** charge direction. Each pack sample
must have a nonzero advancing `pack_seq`, valid `pack_valid`, and explicit
`pack_age_ms` plus request time below 500 ms. All three raw currents must
exceed +20 mA to report `into_pack_unqualified`, or be below −20 mA to
report `out_of_pack_unqualified`; otherwise direction is `indeterminate`.
Only when the pin classification is `charger_reports_active` (both seat
inputs and both charger indicators asserted) and all three currents are
below −20 mA is `charger_indicator_net_discharge_conflict=true` reported. `charging_verified`, `charging_authorized`, and
`battery_current_measured` intentionally remain **false**; actual
shunt calibration, connector ratings, charger TS NTC fault sweep and
net battery charging must be verified with a separate instrument.
