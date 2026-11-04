# Components — revised for owned parts and edge sensing

Updated 2026-11-03. **Keep the XIAO ESP32S3 Sense the user has purchased.** The
pasted listing displays **$18.87**; quantity, selected variant, receipt charges
and arrival remain unconfirmed. Planning assumes one complete Sense bundle at
that reported price, rather than a second head purchase.

**Conditional first-robot total: $40.33**, comprising the reported $18.87 head
purchase plus **$21.46 further parts/allowances**, before delivery, tax and any
missing reused parts. **The $50 delivered cap includes the amount already spent**;
$9.67 remains for all charges or changes. This is not a completed delivered quote.
Two usable owned MG90S and a suitable owned bank are still assumptions. User
estimates about ten MG90S; the bank is unidentified with no readable rating label.

## Amazon preference

[Earlier Amazon observations](amazon-parts.md) are historical. Removing the
already-purchased head from that basket leaves **$43.84 in remaining package
purchases and allowances**; adding the reported $18.87 head gives **$62.71 before
charges**. Those dated prices are not new quotes. Do not reorder a Sense head or
silently raise the cap. The active $40.33 supplier-based target is a different basket.

## Buy candidates for one robot

| Component | One / five robots | Unit USD | First robot | Link and qualification |
| --- | ---: | ---: | ---: | --- |
| **Purchased** XIAO ESP32S3 Sense listing | 1 assumed / 5 eventually | 18.87 reported | 18.87 | [User's listing](https://www.aliexpress.us/item/3256810060131517.html). Described as camera + digital microphone bundle; actual variant, quantity, receipt and arrival to confirm. Standard Sense has 8 MB flash/PSRAM. Keep this head; no replacement purchase planned. |
| MAX98357 I²S amplifier | 1 / 5 | 1.95 | 1.95 | [SEN-17-139](https://electropeak.com/max98357-i2s-audio-amplifier-module). Verify actual A/I²S variant and pin labels. |
| 20 mm, 8 Ω, 1 W speaker | 1 / 5 | 0.29 | 0.29 | [SEN-17-105](https://electropeak.com/8-ohm-1w-20mm-diameter-speaker). 3.75 mm thick; mount/acoustics untested. |
| GY-530 VL53L0X ToF modules, eventual first-core allowance | 5 / 25 eventual | 1.75 | 8.75 | [SEN-19-018](https://electropeak.com/gy-530-vl53l0x-laser-ranging-sensor-module-double-hole). Supplier example, not a quote for TENSTAR/GODIYMODULES. Start with two samples; at most one five-pack before qualification. Four down/one forward remains conditional on mounting tests. |
| TCA9548A I²C multiplexer | 1 / 5 | 0.47 | 0.47 | [Eight-channel breakout](https://electropeak.com/tca9548a-1-to-8-i2c-8-way-multi-channel-expansion-board). Check 3.3 V pullups and reset pin. |
| Rated power lead, switch, connectors, wiring and fasteners | 1 set / 5 sets | 8.00 | 8.00 | Allowance; includes actuator power conductors, not just owned signal jumpers. |
| Power decoupling components | 1 set / 5 sets | 2.00 | 2.00 | Allowance; select after current/noise measurements. |
| **Conditional cumulative parts target** | | | **40.33** | **Includes reported head purchase; $9.67 left for all delivery, tax and missing reused parts.** |

Item prices are dated observations, not reservations or delivered quotes. The
earlier [head quote record](../docs/research/2026-11-03-head-budget.md) and
[sensor record](../docs/research/2026-11-03-cliff-sensors.md) preserve evidence.
No separate INMP441, new OLED, N20, DRV8833, SG90, Uno, Pico or Pi is currently
needed for the proposed first robot. A separate microphone is only reconsidered
if the purchased hardware cannot meet actual audio requirements. Required voice
interruption is a software/audio integration and physical-test gate, not evidence
that the purchased Sense must be replaced. See [the audio plan](../docs/audio-barge-in.md).

## Sensor purchase decision

**VL53L1X is not a required upgrade.** Its longer maximum range does not solve
close-range tabletop sensing. Keep the inexpensive L0X as a sample candidate:
two modules for stationary floor/front tests, or at most one five-pack for robot
one if the cost is preferable. The full-core BOM budgets five eventual modules;
two samples alone do not provide the complete cliff array. **Do not buy 25 fleet
sensors yet.** [Sensor choice and source evidence](sensor-choice.md).

The rough drawing's sensor markers near **14 mm are not valid L0X/L1X mounting
instructions**. Compare one raised L0X corner at approximately 40–60 mm measured
surface range against a compact VL6180X option at 10–30 mm height. Raised brackets
increase the optical footprint and rover width. Table surface, lighting, invalid
readings, full track/gripper/payload clearance and stopping margin all require
tests. The forward obstacle sensor remains a separate role.

## Reuse and missing fleet quantities

| Reported owned part | Per robot / five | Known stock | Gap or qualification |
| --- | ---: | --- | --- |
| ESP32-WROOM-32 board | 1 / 5 | At least one; count unknown | Body MCU remains useful alongside the purchased Sense. |
| XIAO ESP32S3 Sense | 1 / 5 | Purchase reported; exact quantity/arrival unknown | Budget assumes one complete bundle at displayed $18.87. Confirm the actual package; do not infer five heads or multiply a one-time offer by five. |
| 0.96-inch SSD1306 I²C OLED, GME12864-11 | 1 / 5 | At least one | Verify pins/controller/voltage and bezel fit; fleet count unknown. |
| 5 V 28BYJ-48 stepper | 2 / 10 | **5** | **5 more for fleet**; no purchase quote yet. Slow speed/loaded torque need tests. |
| ULN2003 stepper board | 2 / 10 | **5** | **5 more for fleet**; verify actual boards and wiring. |
| MG90S positional servo | 2 / 10 | **About 10, user estimate** | Potentially covers all five. Confirm count/type/condition and fit/load; no extras planned yet. |
| 5 V USB power bank | 1 / 5 | At least one; no readable rating label | Model/current unknown; identify if possible and verify loaded voltage, mount and auto-off. Fleet count unknown. |
| Filament | Sliced mass per core | Reported owned | Confirm sufficient quantity and printer access. Service printing is extra. |
| DuPont jumper ribbons | Cut lengths per core | **10 ribbons** | Signals; do not use as an assumed high-current power harness. |
| SER0043 continuous servo | 0 / 0 | **1** | Spare; cannot hold commanded claw/lift angles. |

Keep [inventory](fleet-inventory.json) and [quantity sheet](fleet-components.csv)
current. Five times $40.33 is **not** a full fleet price: prototype reuse cannot
be assumed five times, and shipping/tax/missing motors, boards and servos remain
unquoted. Sensor/mux electronics alone are $9.22 per core / $46.10 for five.

## Existing print files, not a new chassis

- **Stepper body candidate:** [SMARS 28BYJ-48 remix #2778904](https://www.thingiverse.com/thing:2778904/files),
  linked by [wtlx's build](https://github.com/wtlx/smars-28byj-48).
  [Access/license record](../cad/originals/smars-stepper/README.md). Two unmodified print files are saved with hashes; resolve the recorded source-chain license difference and measure fit before printing. The saved #2662828
  N20 chassis/wheels do not accept these steppers as-is.
- **Lift/grip:** [saved Bluino parts](../cad/originals/gripper/README.md) and
  [linked forklift](../cad/originals/forklift/README.md). MG90S fit and combined
  mounting to the stepper base are unproven; allow small pockets/spacers only.
  The two positional servos remain **lift + grip**; no powered neck is added.
- **Case:** user chose a rounder existing shell. [Saved Sparky v0.1.0](../cad/originals/sparky-head/README.md)
  is the fit-check candidate, with an OLED insert, Sense/camera/audio mounts and
  small rover retention. Source is explicitly unprinted/estimated. EVA is historical.
- Add small downward-sensor mounts and removable hats without covering optics,
  audio, antenna, USB, switch or gripper/track motion. No new structural frame.

VL53L0X usable standoff and final body geometry remain qualification gates. If
compact mounting only permits a 10–30 mm floor window, test VL6180X for the four
downward roles; front L0X can remain. This is an explicit conditional alternative,
not a qualified substitution. Do not silently redesign the chassis or promise
universal edge protection. A floor sensor cannot also measure a claw object.

## Procurement gate

Finish a combined delivered cart under $50, using exact variants and actual
owned counts. Reject accessory-only prices and check all vendor delivery/tax.
Confirm Sense pin/8 MB feasibility, drawing/owned-part fit preflight and bank
label/cable/mount suitability for prototype procurement. Actual build, fit, load
and sensor stopping tests are separate qualification gates before roaming/fleet
replication; they do not prevent acquiring the first quoted sensor samples. Build one; buy four duplicate sets only after physical
acceptance. The user reports the Sense purchase; the assistant made no purchase
and no hardware has been flashed.

```sh
python3 scripts/check_budget.py
python3 scripts/check_budget.py --shipping 0 --tax 0 --require-ready
```

The second command deliberately fails today even with zero charges: allowances,
servo inventory and procurement preflight are unresolved. Physical qualification
checks are recorded separately in the BOM and are not satisfied by this command. Zero supplied here
is a gate demonstration, not a claimed free-delivery quote.

[Historical supplier comparison](supplier-comparison.md) preserves earlier price
observations. The active conditional total is **$40.33 including the reported
head purchase**, before charges; shipping remains unquoted.
