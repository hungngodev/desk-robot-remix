> **Procurement consolidation November 16:** All purchase quantities and remaining counts now come only from [full-feature-plan.json](full-feature-plan.json), with [generated two shopping lists](complete-shopping-checklist.md) and [generated fleet CSV](fleet-components.csv). This page preserves historical ownership notes and supplier research, not a production purchase list. Do not use the old L0X or one-multiplexer estimates.

> **Current selected five robot shopping and wiring design:** [Complete full feature plan](full-feature-wiring-and-shopping.md) and [exact per-robot quantities](full-feature-plan.json). This file is an older combined ownership/prototype audit, not the purchase basket for all advanced add-ons. The $50 delivered cap still applies to the complete first prototype, including the previously paid XIAO; the full design has no approved costed checkout.

> 2026-11-10 inventory correction: user reports using the popular **MPU6050**. The matching existing WROOM driver, Mac preflight, USB diagnostics and test family are now implemented. The old BerryIMU first choice references later in this document are superseded. Count/measure the user's MPU6050 before any replacement order.

# Combined electronics inventory and build gaps

Reconciled 2026-11-06 against the earlier ownership reports, the reported
Sense order and [all 18 photos](photo-inventory-2026-11-04.md). All 18 match the
original audit hashes and group into ten module types. Exact quantities and
working condition for the photographed modules are unverified. The
[six-photo follow-up](photo-inventory-2026-11-04.md#2026-11-06-follow-up) confirms
an owned touch breakout and identifies the HiLetgo amplifier. The
[machine-readable inventory](fleet-inventory.json) tracks quantities separately
from reported estimates and purchases.

**The delivered prototype cap remains $50 including already-spent money.** The
old $40.33 owned-bank/five-L0X basket is historical. The revised distance sensors, 1S power kit
and remaining parts are unquoted; no whole-robot total or remaining headroom
is established. Unknown prices are not zero. [BOM](bom.json) and its checker now
keep known subtotal separate from an incomplete total.

## Reuse first

| Part | Per robot / five | Reported stock | Still to establish |
| --- | ---: | --- | --- |
| XIAO ESP32S3 Sense camera/PDM mic bundle |1 /5 | One paid, carrier-reported delivered; board uninspected | Verify physical markings, condition, accessories and fit before use. Do not repurchase the first head |
| ESP32-WROOM-32 |1 /5 | At least1; multiple reported, count unknown | Count and exact exposed board pins |
|0.96in SSD1306 OLED |1 /5 | At least1 | Count/controller/pin order and fitted bezel |
|5V28BYJ-48 |2 /10 |5 | **5 additional motors for the fleet**, subject to prototype validation |
|ULN2003 driver |2 /10 |5 | **5 additional drivers for the fleet** |
|MG90S positional servo |2 /10 | About10, user estimate | Count/type/condition, pocket/horn and loaded lift/grip fit |
| Adafruit AT42QT1010 momentary touch #1374 | 1 / 5 | At least 1 by package label | Bench-test the pad through the shell. Four more touch inputs if only one is owned |
| MPU6050 motion board | 1 / 5 | User reports using one; quantity, voltage breakout and working state unconfirmed | Preferred six axis IMU; exact module and available quantity to check before ordering four fleet equivalents |
| BerryIMU motion board | 0 required | At least one photographed, likely older V1 | Retained alternative/spare; no need to buy additional BerryIMUs when MPU6050 route works |
|Filament / DuPont ribbons | As needed | Filament and10 ribbons | Print mass/stock; DuPont is signal wiring, not main actuator power |

## Other reported and photographed stock

| Part | Evidence | Use |
| --- | --- | --- |
| HiLetgo HW-104 PAM8403 | One visible, bag marked 5 pieces | Conditional speaker amplifier reuse with an analog source |
| Adafruit DRV8833 #3297 and DFRobot FIT0774 | One each visible | Spare motor driver and optional vibration feedback |
| 5 V USB power bank | At least one reported. Output current unknown | Possible bench supply after checking the output under load |
| Adafruit Feather nRF52840 | One reported owned | Candidate controller for ONE shared read-only room station serving five pets, not five robot controllers. Existing firmware bench/full profiles are source evidence only; PCB, sensor rails, USB continuity and physical assembly remain unqualified |
| Adafruit USB-C breakout #4090 and DFRobot SER0043 continuous servo | One of each reported | Separate spares; the robot lift and jaw require positional MG90S servos |
| Adafruit MAX9814, Adafruit BMP280, PIR motion detector, reflective IR obstacle module, IR remote receiver, likely tilt/vibration switch, separate camera board, magnetic reed-switch module and GY-61 accelerometer | Nine photographed types in addition to the BerryIMU | Spares and optional experiments. See the photo audit for confidence and possible uses |

The earlier ESP32-S3 N8R8 mention was corrected by the user. The reported
XIAO ESP32S3 Sense order is the source of the planned head board. Its delivered
quantity and hardware revision remain open.

## Missing for one complete core

**Sensor purchase hold, 2026-11-09:** The old 4× VL6180X shopping recommendation is withdrawn from the active purchase basket because the manufacturer marks that part out of production. The five originally guarded lanes remain four downward cliff plus one forward obstacle sensor, but the CURRENT full first-unit design also requires three read-only left/right/rear VL53L0X lanes: eight matching carriers in all. The additional lanes do not authorize blind reversing or turning. The pinned Pololu VL53L0X library and critical safety firmware now select low-cost GY-530-compatible carriers for every role; verify actual carrier, cost, optics and physical stop before editing final print geometry and calculating final delivered cost. Historical listings remain in the research audit, **not** an approved order.

Unless newly reported as owned, plan to acquire these. Counts are per one / five
finished robots; quote and validate robot one before ordering the remaining sets.

| Part | One / five | Purpose / selection status |
| --- | ---: | --- |
|[MAX98357A I2S amplifier](https://electropeak.com/max98357-i2s-audio-amplifier-module)|1 /5 | Default speaker output; check the HiLetgo reuse option below before ordering |
| [Challenge CS20-02P110-04-1X 8 Ω 2 W rectangular speaker](https://www.digikey.com/en/products/detail/challenge-electronics/CS20-02P110-04-1X/30407069) | 1 / 5 | Active fixed candidate, 20 × 16 × 4.7 mm; the old 20 mm round 1 W part is retired. Match the rectangular front grille and measure output temperature, enclosure and double talk before buying. |
| Four VL53L0X downward cliff carriers, exact GY-530 PCB UNQUALIFIED | 4 / 20 | Range mux 0x70 lanes 0–3, local movement guard. Validate actual 3.3 V carrier/pullups, optical height, reflectance and loaded stopping before powered use; one low-cost sample may answer carrier identity, not approve all eight. |
| One VL53L0X forward guarded obstacle carrier, exact GY-530 PCB UNQUALIFIED | 1 / 5 | Range mux 0x70 lane 4. Confirm forward field and gripper clearance, 3.3 V bus and physical approach safety. |
| Three VL53L0X read-only left/right/rear carriers, exact GY-530 PCB UNQUALIFIED | 3 / 15 | Range mux 0x70 lanes 5–7; diagnostic observation only, never permission for reversing or blind spinning. Match carrier revision and verify fit, 3.3 V signaling and actual optical field. |
| [TCA9548A mux](https://electropeak.com/tca9548a-1-to-8-i2c-8-way-multi-channel-expansion-board) | 2 / 10 | One 0x70 range mux for all eight VL53L0X; ONE separate 0x71 accessory mux with isolated address and power constraints. PCB variant, 3.3 V pullups, reset routing and actual harness remain unqualified. |
|Matched rechargeable1S kit|1 set /5 sets | Cell+holder/pack, charging, protection, regulated5V output; integrated module may combine functions. Current capability/thermal/fit/quote not selected |
|Rated power wire, switch, connectors/fuse, fasteners, decoupling|1 set /5 sets | Exact sizes/ratings depend on selected power system and loaded tests |

No L1X upgrade, Uno, Pico, Pi, PCA9685, second camera, INMP441 or DC-motor driver
is required by this core. Optional lighting is one diffused RGB pixel plus a
suitable logic buffer/passives; no exposed laser is selected. A bumper, extra
touch zone, Hall game sensor or light sensor is an optional later addition, not
an unexplained required purchase. See [interaction plan](interaction-sensors.md).

The owned **MAX9814 is an analog microphone amplifier**, not a MAX98357A speaker
amplifier. Keep it spare because Sense already has a mic. The separate camera,
GY-61 accelerometer (no gyro), tilt switch, PIR, IR obstacle/remote modules,
BMP280 and reed switch are now recorded; they do not all need installing. The
reed switch could support a later magnet-accessory game. None is automatically
a qualified replacement for the floor array. LSM6DS3TR-C is a conditional IMU
fallback only if the selected MPU6050 is proven unsuitable; BerryIMU remains a photographed spare. Fleet IMU quantities remain open.

The new photo identifies the **HiLetgo HW-104 PAM8403 speaker amplifier**.
One board is visible and its bag says five pieces. Count the contents before
allocating five. A suitable DAC is needed to convert the Sense's digital I²S
output for the analog input. MAX98357A combines conversion and amplification
for the direct I²S path. Choose one route. For PAM8403, connect a speaker across
one channel's paired outputs and keep both leads isolated from ground.
[PAM8403 datasheet](https://www.diodes.com/datasheet/download/PAM8403.pdf).

## Camera and printable sources

Use the camera delivered with Sense; confirm its reported sensor ID rather than
buying OV2640/OV3660/OV5640 by name. Preserve the actual Sense pin map. Streaming
capture, selected frames, visual attention and model reasoning are separate work;
[the source map](../source-map.md) names reusable components.

Use the saved stepper-SMARS source for owned motor mounting and Bluino/SMARS for
closing grip. Compare Cozmars' actual head/packaging first for the desired style;
Sparky is an explicitly unprinted fallback candidate, not a final fitted shell.
Keep the head fixed under the two-servo lift/grip allocation. Small mounts,
bezel/clearance corrections, jaw tips and costumes are allowed; do not silently
redesign a drivetrain/arm to force compatibility.

## Procurement and validation

Amazon remains preferred where practical; historical supplier prices are not
Amazon prices or current delivered quotes. Record exact variants, package outlay,
shipping/tax and inventory before declaring the basket ready. Additional sensor
features do not silently raise the cap. All fit, audio interruption, power,
local edge/attitude stopping and physical pickup trials remain open.

`python3 scripts/check_budget.py` now uses the canonical first-unit plan
and source-locked evaluation cart, reports unknown landed costs, and keeps
purchase approval on HOLD. The strict release path is
`python3 scripts/procurement_release.py --require-first-robot --format first-robot-markdown --evidence ACTUAL_RECEIPTS.json`.
The superseded budget remains inspectable only with
`python3 scripts/check_budget.py --bom ../docs/hardware/bom.json`; this historical
view is not a buying authorization. Shipping and tax guesses never release the
current cart. [Historical Amazon and supplier observations](archive/supplier-comparison.md)
record the earlier baskets.
