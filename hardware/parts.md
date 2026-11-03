# Components — revised for owned parts and edge sensing

Checked 2026-11-03. **Conditional first-robot target: $35.45 before delivery/tax;
$50 delivered cap.** Assumes two usable owned MG90S servos and a suitable owned
bank; neither servo quantity nor bank rating is confirmed. No order is ready.

## Buy candidates for one robot

| Component | One / five robots | Unit USD | First robot | Link and qualification |
| --- | ---: | ---: | ---: | --- |
| XIAO ESP32S3 **Sense bundle**, SKU 113991115 | 1 / 5 | 13.99 | 13.99 | [Official Seeed](https://www.seeedstudio.com/XIAO-ESP32S3-Sense-p-5639.html). Camera + PDM microphone included; not bare XIAO or accessory-only. 8 MB flash/PSRAM, actual camera revision to verify. |
| MAX98357 I²S amplifier | 1 / 5 | 1.95 | 1.95 | [SEN-17-139](https://electropeak.com/max98357-i2s-audio-amplifier-module). Verify actual A/I²S variant and pin labels. |
| 20 mm, 8 Ω, 1 W speaker | 1 / 5 | 0.29 | 0.29 | [SEN-17-105](https://electropeak.com/8-ohm-1w-20mm-diameter-speaker). 3.75 mm thick; mount/acoustics untested. |
| GY-530 VL53L0X ToF modules | 5 / 25 | 1.75 | 8.75 | [SEN-19-018](https://electropeak.com/gy-530-vl53l0x-laser-ranging-sensor-module-double-hole). Four down, one forward; height/surface/FOV tests required. |
| TCA9548A I²C multiplexer | 1 / 5 | 0.47 | 0.47 | [Eight-channel breakout](https://electropeak.com/tca9548a-1-to-8-i2c-8-way-multi-channel-expansion-board). Check 3.3 V pullups and reset pin. |
| Rated power lead, switch, connectors, wiring and fasteners | 1 set / 5 sets | 8.00 | 8.00 | Allowance; includes actuator power conductors, not just owned signal jumpers. |
| Power decoupling components | 1 set / 5 sets | 2.00 | 2.00 | Allowance; select after current/noise measurements. |
| **Conditional parts target** | | | **35.45** | **$14.55 left for all delivery, tax and missing reused parts.** |

Item prices are dated observations, not reservations or delivered quotes. The
[head quote record](../docs/research/2026-11-03-head-budget.md) and
[sensor record](../docs/research/2026-11-03-cliff-sensors.md) preserve evidence.
No separate INMP441, new OLED, N20, DRV8833, SG90, Uno, Pico or Pi is currently
needed for the proposed first robot. A separate microphone is only reconsidered
if the selected Sense hardware cannot meet actual audio requirements.

## Reuse and missing fleet quantities

| Reported owned part | Per robot / five | Known stock | Gap or qualification |
| --- | ---: | --- | --- |
| ESP32-WROOM-32 board | 1 / 5 | At least one; count unknown | Body MCU remains useful. No S3 is owned. |
| 0.96-inch SSD1306 I²C OLED, GME12864-11 | 1 / 5 | At least one | Verify pins/controller/voltage and bezel fit; fleet count unknown. |
| 5 V 28BYJ-48 stepper | 2 / 10 | **5** | **5 more for fleet**; no purchase quote yet. Slow speed/loaded torque need tests. |
| ULN2003 stepper board | 2 / 10 | **5** | **5 more for fleet**; verify actual boards and wiring. |
| MG90S positional servo | 2 / 10 | Count unknown | Need two usable servos for prototype; quantity/fit/load check pending. |
| 5 V USB power bank | 1 / 5 | At least one | Rating, weight, mount, auto-off and load test; exact fleet count unknown. |
| Filament | Sliced mass per core | Reported owned | Confirm sufficient quantity and printer access. Service printing is extra. |
| DuPont jumper ribbons | Cut lengths per core | **10 ribbons** | Signals; do not use as an assumed high-current power harness. |
| SER0043 continuous servo | 0 / 0 | **1** | Spare; cannot hold commanded claw/lift angles. |

Keep [inventory](fleet-inventory.json) and [quantity sheet](fleet-components.csv)
current. Five times $35.45 is **not** a full fleet price: prototype reuse cannot
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
- **Case:** [saved EVA 3MF](../cad/originals/eva-head/README.md), with a small
  measured OLED bezel, camera spacer and removable rover bracket if feasible.
- Add small downward-sensor mounts and removable hats without covering optics,
  audio, antenna, USB, switch or gripper/track motion. No new structural frame.

VL53L0X minimum usable standoff and final body geometry are purchase gates. If
mounting cannot qualify with small brackets, test low-mounted IR sensors as the
explicit alternative; do not silently redesign the chassis or promise universal
edge protection. A floor sensor cannot also measure the claw's object distance.

## Procurement gate

Finish a combined delivered cart under $50, using exact variants and actual
owned counts. Reject accessory-only prices and check all vendor delivery/tax.
Confirm Sense pin/8 MB feasibility, drawing/owned-part fit preflight and bank
label/cable/mount suitability for prototype procurement. Actual build, fit, load
and sensor stopping tests are separate qualification gates before roaming/fleet
replication; they do not prevent acquiring the first quoted sensor samples. Build one; buy four duplicate sets only after physical
acceptance. No purchases or flashing were performed.

```sh
python3 scripts/check_budget.py
python3 scripts/check_budget.py --shipping 0 --tax 0 --require-ready
```

The second command deliberately fails today even with zero charges: allowances,
servo inventory and procurement preflight are unresolved. Physical qualification
checks are recorded separately in the BOM and are not satisfied by this command. Zero supplied here
is a gate demonstration, not a claimed free-delivery quote.
