# Historical DC-build budget audit — 2026-10-30

Superseded on 2026-11-03 by [current parts](../hardware/parts.md) and the
[Sense/sensor budget research](research/2026-11-03-head-budget.md). The amounts
and N20/SG90/SH1106 selection below are historical, not the active shopping list.

## Ten distinct checks of the earlier cheaper build

Checked 2026-10-30. Ten checks mean different cost/compatibility questions, not
ten copies of a search or ten successful physical tests. **There are open gates.**

| # | Check | Evidence and decision | Status |
| --- | --- | --- | --- |
| 1 | Ordinary arm servos | [Bluino arm](https://www.thingiverse.com/thing:4253681) and saved assembly reference use SG90-style mechanisms. [SN482](https://www.sinoning.com/product/1pcs-sg90-9g-mini-micro-servo-for-rc-250-450-helicopter-airplane-car-robot/) is $1.49, 23×12.2×29 mm; use two positional servos, check actual fit/load. | Price checked; hardware pending |
| 2 | Cheapest drive without rebuilding | SMARS original chassis is saved, 78×70×33 mm. [M1 N20](https://www.sinoning.com/product/1pcs-n20-micro-reducer-motor-5v-6v-3v-dc-long-shaft-reducer-motor-metal-gear/) is $1.99 with 12×10 mm gearbox / 3 mm D shaft. Retain N20 form; reject TT/servo swaps needing new mounts. | Envelope/reference checked; wheel fit/traction pending |
| 3 | Cheap motor driver | [Generic module](https://www.sinoning.com/product/drv8833-2channel-dc-motor-driver-module-board-1-5a-3v-10v/) is $0.50. Seller sleep/fault prose is swapped. [TI](https://www.ti.com/product/DRV8833) distinguishes 500 mA RMS PW from 1.5 A RMS PWP/RTY; package/board cooling must be identified. | Price checked; current/thermal gate open |
| 4 | Real camera bundle price | PCBFUN [listing](https://www.aliexpress.com/item/1005007884506760.html), selected **Module and OV2640**: $7.11 + $5.60 shown shipping. $1.53 is an expansion accessory. Listing has N16R8 claim; PDF retrieval returned 403. No verified schematic or pin-map match. | Quote checked; firmware/GPIO/programmer compatibility open |
| 5 | Display that matches the existing direction | [LCD-01-103](https://electropeak.com/1-3-i2c-128x64-white-oled-display-module) is $2.98, SH1106, four-pin I²C, 35.4×33.5 mm. Reject cheaper bare 30-pin glass / 0.96-inch substitutions as equal-fit parts. | Electrical specification checked; mounts pending |
| 6 | Reuse audio drivers | [INMP441](https://www.sinoning.com/product/omnidirectional-microphone-module-i2s-interface-inmp441-mems-high-precision-low-power-ultra-small-volume-for-esp32/) $2.09; [MAX98357](https://electropeak.com/max98357-i2s-audio-amplifier-module) $1.95. Existing Xiaozhi I²S firmware compiled. [SEN-17-105 speaker](https://electropeak.com/8-ohm-1w-20mm-diameter-speaker) is $0.29, 8 Ω / 1 W, 20×3.75 mm; no hardware audio/fit test. | Driver reuse compiled; physical audio/fit open |
| 7 | Remove battery/charger/buck expense | Owned bank can provide regulated 5 V only after label/load/cable/mount verification. User's “yes” did not supply a current rating. [Adafruit #4090](https://www.adafruit.com/product/4090) is specified up to 1.5 A; it is not a verified 3 A actuator branch. | $29.50 saving conditional; power gate open |
| 8 | Existing case and mechanism files | Original EVA 3MF, Bluino arm, SMARS chassis/tracks and lift files saved with hashes/licenses. No shell/chassis invented. Removable bracket/spacers and small lens/clearance changes permitted; mounts, bank weight and gripper sweep unmeasured. | Sources saved; physical fit open |
| 9 | One design multiplied by five | Same core for all five; identity/token/address/calibration per unit, hats/costumes only. Software supports two rounds / ten total utterances for five, one transmission at a time, digital transcript to all peers. | Automated fleet tests; no five physical robots |
| 10 | Delivered cap and honest fleet arithmetic | New first-unit target $36.88 leaves $13.12 for all charges/changes. Five-core arithmetic $184.40 excludes unknown extra banks/controllers and all charges. Inventory counts, several quotes, combined shipping/tax and physical gates remain open. | **Not purchase ready** |

The active budget checker refuses readiness while allowances, fit or named
hardware gates remain unresolved. No completed CAD export, successful pickup,
measured playback or delivered $50 basket is claimed by this audit.
