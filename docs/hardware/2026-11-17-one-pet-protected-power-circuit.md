# Complete one pet 1S protected power circuit and physical sizing contract

**Design decision:** one protected single-cell pack, one TI BQ24075 1.5A
power-path charger source reference, one dedicated buck/boost 5V rail from
the charger's battery-dependent OUT, one independent protected 3.3V sensor
rail, separate actuator and audio 5V distribution, and one high-side INA226
current monitor with a physically matched five milliohm Kelvin shunt. Keep
the built-in MAX17048 telemetry only if the chosen actual charger PCB does
not instead include an integrated BQ27441. **THIS IS A POWER SCHEMATIC
CONTRACT, NOT A FABRICATED OR TESTED PCB. NO LIVE LI-ION OR DOCK WIRING IS
AUTHORIZED FROM THIS DOCUMENT.**

## Actual IC pins, evidence and modes

Manufacturer [TI BQ24075 datasheet Rev N](https://www.ti.com/lit/ds/symlink/bq24075.pdf)
is the only allowed source for the *ordinary BQ24075 RGT0016C* package.
Do not substitute BQ24074, BQ24075T, BQ24075-Q1 or a breakout with
unknown pullups/NTC bypass without independently verifying its pinout.

| Proposed net | BQ24075 pin | Function and strict assembly rule |
| --- | --- | --- |
| FUSED_DOCK_5V | IN 13 | Use a current-limited, reverse-safe, **normally unpowered** physically protected dock contact circuit and qualified input bypass |
| CHARGER_VSS / PACK_MINUS | VSS 8 + thermal pad | Single return point, rated high current copper and Kelvin ADC sense routing |
| PACK_CHARGE_SIDE | BAT 2,3 | Add TI's required BAT ceramic decoupling; **do not connect raw battery to XIAO 5V** |
| PACK_SENSE_SHUNT_PLUS | INA226 IN+ | Connect to BAT side of exactly one approved 5mOhm 2W Kelvin shunt |
| PROTECTED_PACK_PLUS | INA226 IN- | Other side of shunt to correct pack protection external P+ through *rated keyed connector*, never bare cell B+ |
| PACK_NTC_10K | TS 1 | Actual 10k pack thermistor third lead, selected and checked to manufacturer's required B-temperature curve, not the board's fixed 10k bypass |
| SYSTEM_UNREGULATED | OUT 10,11 | About battery domain when undocked, as high as 5.6V under qualified dock input; **always** route through correct VIN-rated buck/boost before fixed 5V |
| CHARGER_PWR_GOOD | PGOOD 7 | Open drain through 3.3V pullup to MCP23017 0x20 GPA2 (read only) |
| CHARGER_CYCLE_INDICATION | CHG 9 | Open drain through 3.3V pullup to MCP23017 0x20 GPA3 (read only); **not measured battery charge** |
| CHARGE_HW_ENABLE | CE 4 | Hardware defined inactive until TS, input protection and safe electrical defaults verified; WROOM does not own charge authority |
| CHARGER_INPUT_CONFIGURATION | EN2 5, EN1 6, ILIM 12 | Set real dock input limit no higher than manufacturer's **1.5A**; source model selection is not a resistor network |
| CHARGER_TIMERS | TMR 14, ISET 16 | Exact TI calculations, termination and battery allowable charge rating require values and fault verification |
| SYSTEM_OFF | SYSOFF 15 | Fixed default in schematic with no accidental floating logic or charger-less motor restart |
| 3V3 expansion | Pololu #2873 candidate; VIN from protected regulated 5V logic rail | Upstream of actuator cutoff, not raw 1S/BQ24075 OUT or USB VBUS; default 3.3V output, supply both WROOM I2C muxes and all 3.3V I2C carriers; measure actual pullups across 16 lanes; physical HOLD |
| 5V_MOTORS | Regulated 5V boost branch | Motors and dual MG90S through correct rated fuse, wire and local bulk; not powered from XIAO or raw USB VBUS |
| 5V_AUDIO | Regulated 5V boost branch | MAX98357A local 0.1uF and 10uF decoupling; 8ohm 2W speaker differential |
| 5V_XIAO | Boost through Schottky | External 5V to XIAO 5V via Seeed prescribed series diode; keep laptop USB from backfeeding motors |
| INA226 readout | 0x71 mux channel 4, address 0x40 | WROOM reads signed shunt µV as **raw** pack mA, 3.3V bus, source sequence increments only after a successful acquisition |

**DRX-1775 sensor rail budget (design only):** Follow the [purchase register](2026-11-16-five-pet-purchase-register.md) for the provisional 0.700 A startup headroom and measured worst-case 5V VIN startup/inrush and continuous load. The 3 V cutoff and startup minimum are published; restart hysteresis magnitude is not established. Include the branch once in aggregate 5V and docked load measurements, apply the existing sizing reserve, and keep physical HOLD until rail sequencing, backfeed, sensor-loss latch and deliberate local rearm are proven with actuator power disconnected.

**Schematic omissions that are NOT allowed in production:** exact passive
values per TI datasheet, charger capacitors and thermal copper area, battery
protector MOSFET trip specification, input transient/ESD clamp, dock
contact hot-short and reversal protection, 5V regulator EN and its UVLO,
switch fuse, connector mating/polarity, battery tray isolation and strain
relief, NTC network and chamber sweep, vehicle current measurements.
**DRX-554 charge-temperature gate:** the project permits cell charging only
within 0 to 45 C (or the narrower cell manufacturer range). TI SLUS810N
section 9.3.6 specifies a nominal 0 to 50 C window for 103AT-2 and states
that its illustrated external resistors cannot narrow the window. A connected
NTC alone is therefore insufficient. CHG can stay low during TS suspension.
See https://www.ti.com/lit/ds/symlink/bq24075.pdf (pp. 29–30).
Require a reviewed independent hardware inhibit design with worst-case trip
limits, hysteresis, tolerance, and sensor open/short behavior; keep CE inactive
and dock contacts unpowered pending qualification. `guaranteed_charge_window_c`
in the paper preflight is a declared worst-case interval, not a measurement
or charge permission. Confirm using a reviewed battery simulator and resistance
fault fixture, not by charging a real cell outside its rated range. No new
GPIO, thermistor model, comparator circuit or charger SKU is selected here.

This document is deliberately not misrepresented as complete Gerber or
production release evidence.

## One physical battery current, not charger LED state

Current through INA226 positive-side Kelvin shunt:
`Ipack_mA = Vshunt_uV / 5` when `Rshunt=0.005 ohm`.
INA226's signed range is about +/-81.92 mV. At 10A, shunt drop is
50mV, Joule dissipation = `I^2R = 0.5 W`. Design not only resistor
watts but **PCB copper, real high pulse duty, calibration tolerance,
temperature coefficient, trace drop and Kelvin geometry**. Candidate
source reference: Vishay WSL25125L000FEA18 5mOhm 2W 2512 resistor.
Use exact manufacturer datasheet and an actual in-stock SKU before buying.
The *supply rail* must not rely on the INA226 being present for motor
safety. The register may fail and still leave the BQ24075 power path on.

`AccessorySensors.cpp` uses `DESK_ROBOT_PACK_SHUNT_MOHM=5` **only in**
`esp32_dc_integrated_lab`. Firmware returns `pack_ma`, `pack_valid`,
`pack_seq`, with `current_calibrated:false`. The normal firmware
has no asserted current measurement. Mac `aux.py` validates signed
mA against raw `shunt_uv`. `dock_evidence.py` requires THREE real
increasing hardware acquisition IDs before classifying raw direction
(`into_pack_unqualified`, `out_of_pack_unqualified`,
`indeterminate`) and NEVER asserts `charging_verified` or enables
a charge circuit. The 5mOhm resistor is NOT a battery current-limit
element; protection remains a separate external requirement.

## Calculated electrical and mechanical acceptance

Use `code/scripts/power_preflight.py::screen_one_cell_power_stack` as
the single paper model for actual source current at **3.0V depleted cell**,
separately derated output at the real worst converter input, exact entire
protected pack and **lead/connector ampacity**, recharge load while the
entire robot is docked with **motors disarmed**, 5.6V BQ24075 maximum
docked OUT, TS NTC connected instead of fixed bypass, and full battery
tray clearance. The result `all_power_stages_compatible_on_paper=true`
can only mean the numbers supplied are mutually consistent. It always
reports `qualified_1s_dock_safe_to_buy=false` and
`all_power_stages_physically_verified=false` until independent tests.

For a fuse in the shared 1S pack path, supply
`pack_path_fuse_derated_hold_a` from the exact manufacturer's hold-current
rating at the maximum applicable enclosure temperature. Missing or insufficient
ratings prevent a complete paper pass. The conservative screen compares
against the margin-inclusive **pack-side peak**, not the 5V load current
or the fuse trip rating. Include simultaneous wheel stalls, servo loads,
audio, camera, WiFi and any independent regulator input in the measured
total demand (use equivalent 5V load if necessary). This is not a fuse
selection or proof of safe interruption: actual time-current response,
short-circuit ratings, PCM coordination, voltage drop, converter inrush
and separately fused branches still require independent design review and
bench qualification. Manufacturer reference:
https://www.littelfuse.com/products/fuses-overcurrent-protection/polyswitch-resettable-pptc-devices


Published [Pololu #4082 S13V30F5](https://www.pololu.com/product/4082)
has a correct **2.8V to 22V** VIN window and a real STEP mechanical model,
but its advertised **3A** is measured near 5V input and is NOT a valid
3.0V input guaranteed 3A source; expensive at ~$17.95 each.
Do not lock that PCB into the final affordable cart without verifying
the current curve at the actual low cell voltage. Ordinary 5V-only
step-down modules fail the 5.6V charger or low cell corner.

Manufacturer sourced batteries evaluated by
`code/scripts/screen_vendor_battery_harness.py` now include ten
variants. The earlier 68x35x14mm coupon has been revised to 86x35x14mm
in the CAD source. Neither coupon establishes physical fit of the
complete protected and terminated packs with lead relief. The THOR pack advertises
optional NTC and an incomplete bare assembly outline, so even its
dimensions cannot prove fit. The final candidate must contain **PCM,
matched cell, 10k NTC and verified cable/connector**, rated for the
combined **measured** DC motors, two MG90S stall, audio and WiFi/camera
peak and the actual boost input demand. Enlarge tray only as part of
one measured fully assembled licensed robot CAD, not a coupon alone.

## Acceptance must catch actual predictable faults

Source contract C++ sanitizer and Python tests cover signed current,
limits, wraparound, replay, absent shunt, battery connector ampacity,
docked load sharing and 3V/5.6V converter limits. Actual bench receipt
still needs: no pack connected -> power path remains electrically safe;
open/shorted NTC -> charging thermally inhibited; reversed contact and
hot short -> external protected dock cuts input; one motor stall and two
MG90S worst load -> head/AFE/WROOM remain powered without rail collapse;
body CPU freeze -> **independent** DRV8833 nSLEEP timer cuts bridges;
weak/dark/gloss floor -> 8 GY530 sensors and loaded braking pass geometry;
real docked battery current positive with independent ammeter and no
fake CHG indication. Finally measure physical fit, mass, center of gravity,
connector bend and gripper sweep in the **complete** Fusion assembly.

No live electronics, thermal, docking or printed envelope test has yet
been executed on the user's assembled robot. **Fleet and one-pet
power shopping remain HOLD pending real source qualification.**
