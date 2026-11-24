> **Authoritative buying quantities, November 16:** This page is retained for detailed wiring, I2C allocation and source verification. Its embedded static shopping tables are not maintained as a second purchasing ledger. Use [the generated two shopping lists](complete-shopping-checklist.md), [the generated 49-role CSV](fleet-components.csv) and [the sole hardware plan](full-feature-plan.json). In particular, full range is eight VL53L0X per robot and two muxes per robot, independent of earlier prototype figures. **All irreversible purchases remain on HOLD.**

# Final selected full five-pet hardware architecture

**Decision:** This is the selected complete-feature electrical and sensor allocation for five identical core pets. It is not a stripped-down robot. Exact board carrier, battery and printed fit are not physically qualified. The original $50 prototype cap remains unproven for the *entire* robot. Ranging is now explicitly the low-cost generic VL53L0X GY-530; do not reinstate premium carrier pricing.

**Use one Mac plus five identical Sense heads and WROOM bodies.** Reuse the owned motors and MG90S before buying duplicates. No second camera, additional onboard microphone, Raspberry Pi, or unrelated motor driver is required.

## Canonical procurement

This file is the wiring and architecture guide. It deliberately does **not**
maintain a second shopping table. The only static builder-facing inventory and
purchase lists are the two sections in
[complete-shopping-checklist.md](complete-shopping-checklist.md), generated
from [full-feature-plan.json](full-feature-plan.json) by
`code/scripts/procurement_release.py`.

For a one-unit quantity projection from that same source, run:

```bash
cd code
uv run --no-sync python scripts/procurement_release.py --format first-robot-markdown
```

That projection is still a HOLD until the physical and supplier receipts pass.
Reported stock, reference links and this wiring guide are never checkout
authority. Photo and ownership evidence stays in the dedicated photo inventory
records instead of being copied into another cart.

### Reading the 63-role audit without double-counting

The canonical plan contains 42 robot/dock parent roles, 7 shared-station
parent roles and 14 linked decisions (63 records total, **49 parent
purchasing roles**). Linked decisions are already covered by their parent
roles, not another 14 purchases. The
[63-role source ownership map](full-63-role-source-ownership.json) assigns
source, tests and remaining qualification to every record. The
[generated signal harness](one-robot-signal-harness.generated.md) is the
firmware-checked signal allocation, not a carrier pinout or a power schematic.
The fleet CSV's manufacturer/datasheet links and the separate pilot sample
references in `procurement_release.py` are not equivalent to exact qualified
carrier SKUs or delivered checkout receipts.

For example, the selected range sample candidate
[ElectroPeak SEN-19-006](https://electropeak.com/gy-530-vl53l0x-laser-range-finder)
is advertised as 2.8–5 V supply, 30 mA maximum and 30 mm–2 m range;
the seller's [reference pinout](https://electropeak.com/learn/interfacing-gy-530-vl53l0x-laser-distance-module-with-arduino/)
labels VCC, GND, SDA and SCL. The product also describes shutdown and
interrupt signals; do not infer the delivered header order or pull-up voltage
from that reference drawing. The selected WROOM bus is 3.3 V logic and remains
unpowered until the actual carrier's VIN, regulator, pull-ups and GPIO levels
are checked. One bench sample is not authorization for the remaining seven
per robot. Likewise, the
[Challenge CS20-02P110-04-1X](https://www.digikey.com/en/products/detail/challenge-electronics/CS20-02P110-04-1X/30407069)
listing identifies an 8 Ω, 2 W speaker, not proof of the assembled acoustic
enclosure. Do not ground either differential speaker terminal.

To inspect the existing pilot evidence without creating a third shopping list,
run `cd code` then
`uv run --no-sync python scripts/procurement_release.py --format pilot-samples-markdown`.
Every exact delivered module still needs its manufacturer or seller SKU,
PCB revision, live supplier stock/checkout receipt, rated supply and logic
levels, connector/pin orientation and applicable physical validation.
Passive assembly roles need a measured drawing/fit and material specification,
not an invented operating voltage. Unresolved linked designs need their
parent circuit/mechanical decision before an exact SKU can be frozen.
No purchase or physical release is granted by this audit.

## Fixed pin wiring

**Motor variants are mutually exclusive.** The following ULN2003 pin rows
apply only to the historical stepper build (`esp32_full` or
`esp32_stepper`), not the guarded DRV8833 alternative. The final drivetrain
purchase remains HOLD: the stepper build lacks a physically qualified
independent CPU-halt motor-rail cutoff. The DC build also requires its
independent CD74HC123 cutoff and nFAULT wiring to be physically qualified.
Do not connect or order both drivers as a single robot configuration.

| Body ESP32 WROOM GPIO | Function |
| --- | --- |
| 13, 14, 25, 26 | left ULN2003 stepper (STEP only) |
| 27, 32, 33, 23 | right ULN2003 stepper (STEP only) |
| 18 | lift servo |
| 19 | grip servo |
| 16 | head uart rx |
| 17 | head uart tx |
| 21 | sda |
| 22 | scl |
| 34 | head touch |
| 35 | bumper nc series |
| 36 | reserved left 38 kHz terminal dock IR demodulated input, read-only source decoder, not physically qualified |
| 39 | reserved right 38 kHz terminal dock IR demodulated input, read-only source decoder, not physically qualified |

For the **DC alternative only** (`esp32_dc_full`), the current
[firmware-checked signal harness](one-robot-signal-harness.generated.md)
maps GPIO25/26 to DRV8833 AIN1/AIN2 and GPIO27/32 to BIN1/BIN2.
GPIO23 is the CPU heartbeat input to the independent CD74HC123 channel 2,
not a direct connection to nSLEEP. DRV8833 nFAULT is active LOW and routed
to MCP23017 GPB3 on mux 0x71 channel 5 using the documented external bias
network; a disconnected harness must fail LOW. Verify exact carrier
exposure of nFAULT and nSLEEP, 3.3 V logic and cutoff behavior before any
loaded motion. Use [the DC watchdog guide](dc-motor-independent-watchdog.md)
and the generated harness rather than repurposing the stepper table.

| Head XIAO ESP32S3 Sense GPIO | Function |
| --- | --- |
| 5 | oled sda |
| 6 | oled scl |
| 4 | amp bclk |
| 7 | amp lrclk |
| 8 | amp din |
| 2 | head uart tx |
| 1 | head uart rx |
| 9 | rgb data |

**Extra input relocation without deleting the user's features:** The existing MCP23017 on TCA9548A 0x71 channel 5 now reads GPIOB0 (active low magnetic reed switch) and GPIOB1 (active high PIR output) as independent **slow**, read-only inputs. WROOM GPIO36 and GPIO39 are only **reserved** for separate timestamped terminal IR receivers. The current firmware now decodes complete 34-symbol NEC bursts using two independent bounded ESP-IDF 4.4 RMT receiver channels and exposes read-only evidence via UART, XIAO and Mac. Actual receiver polarity, optical timing, bearing calibration and final contact movement are not verified. It cannot energize charging contacts. Datasheet MCP23017 BANK=0: IODIRB 0x01, GPPUB 0x0D, GPIOB 0x13. Optional reed/PIR events still require compile-time opt-in and actual electrical qualification. This source arrangement fixes the signal allocation conflict, **not** the dock's real timing, physical fit or charger.

**NC bumper safety polarity:** Wire two normally-closed switches in **series** from WROOM GPIO35 to ground, with external pullup to 3.3V. Both unpressed contacts closed means normal LOW. Either collision, unplugged plug or broken lead opens circuit and reads HIGH. The enabled WROOM GPIO reader now treats HIGH as immediate motor stop. Actual circuit must be qualified before enabling this optional sensor.

**Do not attach another I2C master to the Sense OLED wires.** **Critical physical XIAO Sense J3 gate:** Seeed's official Sense microSD wiki says GPIO7 (SCK), GPIO8 (MISO), GPIO9 (MOSI) are physically shared with the SD slot and the slot link J3 is enabled by default on the camera/mic expansion board. Our I2S speaker uses GPIO7/8 and optional RGB uses GPIO9. The final assembly requires the exact shipped Sense revision be checked and the expansion board **J3 SD link physically cut/opened per Seeed's own official guide** if the pin map is retained. Remove the camera before modifying J3 and verify no SD slot function survives. Never install or initialize an SD card with this design. A compiler test cannot prove this mechanical electrical isolation. Reference: https://wiki.seeedstudio.com/xiao_esp32s3_sense_filesystem/ .

 Head and body exchange UART only (TX/RX crossed, plus GND), with separate regulated supplies and a common reference. Do not use GPIO34/35/36/39 as outputs or expect internal pull resistors. **XIAO external 5V cannot be tied directly to USB VBUS while both supplies are present**: Seeed's [official pin muxing guide](https://wiki.seeedstudio.com/xiao_esp32s3_pin_multiplexing/) requires a diode for an external source on its 5V pin. Choose and current/voltage-test a correctly oriented one-way path or mechanically exclusive USB/power mode for the exact board revision. Until qualified, robot power stays disconnected during USB flashing; never bypass the protected pack, fuse, regulated distribution or charger gate.

## I2C architecture

Upstream body SDA GPIO21, SCL GPIO22 at **3.3V logic** hosts MPU6050 at 0x68/0x69, first TCA9548A at **0x70**, second at **0x71** (A0 high, A1/A2 low). Both mux RESET pins are pulled high correctly; no unsafe GPIO4 strapping connection. Only one IMU is installed at a time. Original BerryIMU remains a spare.

### Mux A, address 0x70: movement and obstacle sensing first

| Lane | Module | Direction | Driver |
| --- | --- | --- | --- |
| 0 | VL53L0X, 0x29 | floor front left | Existing WROOM five-channel driver |
| 1 | VL53L0X, 0x29 | floor front right | Existing WROOM five-channel driver |
| 2 | VL53L0X, 0x29 | floor rear left | Existing WROOM five-channel driver |
| 3 | VL53L0X, 0x29 | floor rear right | Existing WROOM five-channel driver |
| 4 | VL53L0X, 0x29 | front obstacle | Existing WROOM five-channel driver |
| 5 | VL53L0X, 0x29 | left obstacle | Implemented read only in esp32_full; physical qualification pending |
| 6 | VL53L0X, 0x29 | right obstacle | Implemented read only in esp32_full; physical qualification pending |
| 7 | VL53L0X, 0x29 | rear obstacle | Implemented read only in esp32_full; physical qualification pending |

### Mux B, address 0x71: extra pet features, lower polling priority

| Lane | Module and address | Purpose |
| --- | --- | --- |
| 0 | CAP1188 (0x29), MAX30102 (0x57) | Petting electrodes and user-approved heartbeat pad |
| 1 | APDS9960 (0x39), AS5600 nose (0x36) | gesture + twist nose |
| 2 | ADS1115 (0x48) | force feedback |
| 3 | SHT41 (0x44), BMP280 (0x76) | humidity + reported pressure board |
| 4 | INA226 (0x40), MAX17048 (0x36) | current and battery fuel gauge |
| 5 | PN532 I2C (0x24), MCP23017 (0x20) | NFC and auxiliary digital control |
| 6 | AS5600 (0x36) | left wheel rotation |
| 7 | AS5600 (0x36) | right wheel rotation |

**MAX30102 paw interaction source update:** The selected pad's existing SparkFun-derived bounded FIFO parser now increments `pulse.seq` only when a new physical MAX30102 FIFO read succeeds. `BodyControl` carries that counter through the same read-only `/api/aux` path; Mac `PetController` now supports a per-robot, measured `paw_contact_ir_raw_threshold` and explicit `paw_contact_interactions_qualified` flag, two distinct new threshold-crossing acquisitions, a 25 percent release hysteresis, reset/replay handling, firsthand memory and the existing spontaneous speech arbiter. The flag defaults false for all five pet configurations. This treats a finger touching the LED pad as a playful optical interaction, **not** as real heart rate, SpO2, user identity or medical information. Real pad IR thresholds, finger geometry, LED exposure, susceptibility to room light and device current still require physical checks. Source and mock tests are committed in PR #17 but unverified by the failing GitHub Actions runner.

**MAX30102 correction:** The original HTML approved one **robot-mounted** heartbeat paw pad and reported a box of around five MAX30102 boards. Photo confirmation is missing, so count stock before purchasing. Reserve WROOM 0x71 mux lane 0 at 0x57, share lane with CAP1188 at the planned 0x29 (or the supported strapped 0x28 alternative) after voltage and breakout checks. **Never** use XIAO Sense GPIO41/42 because those are the PDM microphone wires. Opt-in playful feedback only, not medical use.

**CAP1188 rather than MPR121:** Microchip marks CAP1188 in production, whereas NXP archives MPR121. Use a cheap CAP1188 breakout at its common default **0x29**, with legacy strapped **0x28** also recognized by chip ID. Safety mux 0x70 must report NO selected lanes before touch mux 0x71 CH0 opens, and all optional channels must be closed before a critical range read. Equal 0x29 addresses are permitted only behind those isolated muxes, not on the same I2C segment. Actual stuck-bus electrical tests are still required. Its 8 electrodes cover head, back and belly; retain the existing dedicated AT42QT1010 as the **local physical stop touch**, never routed through an optional mux. Check actual breakout address-selection circuitry before ordering. Microchip [CAP1188 datasheet, Table 4-1](https://ww1.microchip.com/downloads/en/DeviceDoc/00001620C.pdf#page=12) specifies 0x29 with a 150 kΩ ADDR_COMM pull-down (±5%) and 0x28 with ADDR_COMM tied to VDD; these are IC strap definitions, not proof of the selected carrier wiring. Confirm the fitted resistor or strap and inspect the PCB-specific pinout before applying power.

**MCP23017:** the implemented source reads physical dock seat and charger status pins only. PN532 now uses bounded nonblocking I2C ready-byte and frame reads on the same mux lane without driving optional expander IRQ/reset pins; an actual carrier may require a reset and must be measured before the final wiring is frozen. The haptic edge source is now **implemented only in opt-in `esp32_full_haptic_lab`**, using MCP23017 GPB2, verified OLATB readback, fresh dock GPIOA inhibit and local CAP1188 event gating. Real motor power is **not qualified**: a generic 3.3V CD74HC123 independent hardware one-shot, AO3400 low-side MOSFET, diode, gate pulldown, and measured fault pulses are mandatory because an I2C expander can leave an output latched HIGH. Full wiring and bench gates: [haptic-one-shot-wiring.md](haptic-one-shot-wiring.md). Production profiles leave the effect disabled; do not describe real vibration as verified. Never put motor phases, servo lift/grip outputs, emergency stops, required head touch or optical cliff timing through the expander.

**PN532 shared bus qualification gate (November 13 source research):** NXP PN532 user manual UM0701-02 sections 6.2.4 and 6.3.3 documents I2C status/ACK/response framing, IRQ readiness and mandatory SCL clock stretching on wake from low power. The current bounded nonblocking Seeed BSD protocol adaptation avoids long software polling but does **not** establish that an actual ESP32 Wire controller and the selected PN532 breakout can safely coexist with the dock MCP23017 on mux 0x71 lane 5. An optional PN532 transaction that holds SCL, hangs a Wire transfer or leaves the mux selected must not compromise required dock GPIO freshness or WROOM cliff sensing. Keep NFC unqualified and read only. Before freezing wiring, instrument SCL/SDA and IRQ across repeated wake, tag held/removed, absent reader and brownout, including MCP23017 GPIO reads and 0x70 ToF sample freshness; capture worst case transfer duration, recovery and fault latching. Do not add a competing Adafruit BusIO PN532 driver merely to claim compatibility: Adafruit PN532 1.3.4 (BSD, requires BusIO) and Seeed Studio PN532 (BSD, supports I2C/SPI/HSU) are reference implementations, not proven drop in replacements for the existing mux owner. If physical I2C wake cannot be bounded, select a separately wired and pin audited SPI/HSU transport before declaring a final PCB, not a software safety bypass. Sources: [NXP UM0701-02](https://www.nxp.com/docs/en/user-guide/141520.pdf), [Seeed PN532](https://github.com/Seeed-Studio/PN532), [Adafruit PN532](https://github.com/adafruit/Adafruit-PN532), [Adafruit interface guide](https://learn.adafruit.com/adafruit-pn532-rfid-nfc/arduino-library). This is a design risk and proposed bench gate, not a reproduced hang or completed electrical test.

**Bus ownership:** existing WROOM ToF driver must run first; optional reads have lower priority and strict timeout. The existing WROOM ToF driver now probes a fitted 0x71 mux and disables all its lanes before each critical 0x70 range read; a failed reset of those optional lanes faults the local safety guard. No new sensor driver is claimed working until implemented and tested. No optional sensor is allowed to rearm a body, clear a fault, grant a permit, or monopolize the bus.

**Wheel encoders:** two AS5600s each live on their own mux channel 6 or 7 because both answer 0x36. A third AS5600 at channel 1 reads the nose. These provide measured magnetic angles only after proper mechanical coupling, not automatic absolute navigation. No optical encoder is silently assumed compatible with the existing tracked wheels.

## Power and physical build

One robot uses a protected matched **1S rechargeable pack**, safe charging with load sharing, a current-rated isolated 5V distribution for WROOM/head/steppers/servos and selected MAX98357A, with a separate rated 3.3V supply for sensor logic. The fixed speech speaker candidate is the 8 ohm 2 W rectangular Challenge CS20-02P110-04-1X, not the superseded round 1 W device. The MAX98357A 5V, 8ohm approximately 1.8W manufacturer output is a nominal test condition, not verified continuous installed speaker performance. Do not assume XIAO VBUS can be tied directly to the robot supply; validate reverse feed isolation, regulator surge, gain, clipping and acoustics. Every rail shares ground. Use a regulator, wiring, protection and battery discharge rating proven with actual simultaneous stepper, servo, WiFi, camera and TTS peaks; nominal boost listings and unmeasured 5V USB banks are not adequate evidence.

**Regulator interface incompatibility to resolve before schematic selection (2026-11-13):** TI specifies BQ24074 `VOUT` as a nominal 4.4 V power-path output, **not a regulated 5 V actuator rail**; Microchip MCP73871 likewise offers load sharing, not a guaranteed 5 V boost output. Neither part can directly replace the required independently rated 5 V regulator for the WROOM, XIAO head, ULN2003 motors and MG90S servos. The battery-backed boost/regulator must be qualified at minimum pack voltage and worst simultaneous motor, servo, WiFi, camera and speaker load, including input-current limiting, thermal behavior, brownout recovery and dock insertion/removal. The manufacturer's published charge-current and input-current maxima are not proof of system peak delivery. References: [TI BQ24074 product and Rev N datasheet](https://www.ti.com/product/BQ24074), [Microchip MCP73871 product and datasheet](https://www.microchip.com/en-us/product/mcp73871). This is a source specification check, not a selected circuit, tested rail, or license to enable charging.\n\n**November 13 charger reuse comparison, research only:** Do not mistake charger power path for a protected battery pack or a verified docking circuit. TI [BQ24074 Rev N](https://www.ti.com/lit/ds/symlink/bq24074.pdf) provides 1S power path, input current management, pack thermistor input and IC thermal regulation. The [Adafruit BQ24074 Eagle schematic and board](https://github.com/adafruit/Adafruit-BQ24074-PCB) are a documented reference, not a qualified dock contact design; the PCB files carry Creative Commons Attribution ShareAlike terms, so check the exact license before adapting or redistributing. Microchip [MCP73871](https://www.microchip.com/en-us/product/mcp73871) offers alternative 1S load sharing, charge safety timers, pack temperature sensing and power good/fault indicators, but its 1A maximum programmed charging current and 1.8A total input current ceiling require an actual simultaneous system load budget. Neither IC by itself establishes pack short circuit protection, boost regulator peak capacity, reverse contact polarity protection, safe hot contact insertion, thermal behavior, charge termination under dynamic load or independent charger state confirmation. **Decision deferred:** preserve current charge inhibit; select no schematic, charger board, dock wiring or shopping item until protected pack specification, regulator/load measurements and keyed contact electrical tests are recorded. No code, physical qualification or charger acceptance is implied.\n\n**Charger status sampling hazard (manufacturer source review, November 13):** The BQ24074 `PGOOD` output means valid input, not active battery charging. Its open drain `CHG` output can be high impedance for completed charge, disabled charging, or absent battery; the TI datasheet also documents approximately 2 Hz flashing for certain charge faults. A single MCP23017 GPIO snapshot, even if fresh within the WROOM 500 ms dock monitor window, cannot reliably classify a blinking fault or prove current entering the cell. Keep the existing any-contact/PGOOD motor inhibit independent of charging state. Before implementing an autonomous charging success indication, identify the exact selected charger revision, use qualified voltage/current/temperature observations and an independently verified charge state over multiple cycles, and bench test contact bounce, charger fault flashing, pack absence, thermal suspension and unplug. Do not change the motion gate or energize contacts based on this source review. Sources: [TI BQ24074 Rev N datasheet](https://www.ti.com/lit/ds/symlink/bq24074.pdf), [Microchip MCP73871 datasheet](https://ww1.microchip.com/downloads/en/DeviceDoc/MCP73871-Data-Sheet-20002090E.pdf). No circuit selected and no electrical or firmware test performed.\n\nThe head remains **fixed**, using the existing two MG90S servos for **lift and grip**. Its OLED and camera use the shipped Sense interface. WS2812B diffused heart uses Sense GPIO9 through a suitable level buffer after verifying SD is disabled. A coin vibration motor uses the existing reported motor and a separate rated low-side MOSFET, never a microcontroller output directly.

The dock has **five individual keyed cradles**, one for each pet, with camera-visible alignment markers, physical guidance, charge-input contacts, a short-safe charger input circuit and a contact detect switch. Contact never bypasses the rechargeable pack's protection circuit. Automatic docking and peer chasing are still separate physical acceptance items; none can be declared working from a CAD preview.

## Shared desktop accessory station, not five copies

| Shared station role | Selected quantity for one shared station | Plan |
| --- | ---: | --- |
| SCD40 real CO2 | 1 | ventilated stationary desk; purchasing still HOLD |
| BME688 VOC gas and ambient | 1 | ventilated stationary desk; purchasing still HOLD |
| LD2410C mmWave presence module | 1 | fixed room pod UART; purchasing still HOLD |
| Capacitive soil probe | 1 | external plant accessory; purchasing still HOLD |
| NFC game tags and magnets | 0 | OPTIONAL NOT SELECTED, DO NOT BUY; ten future game props are only a concept |
| AMG8833 thermal array | 0 | OPTIONAL NOT SELECTED, DO NOT BUY; future separate thermal station concept |

This legacy wiring reference is not a third shopping list. The only selected
MAX30102 pads are the five robot-mounted paw pads (one per pet), with stock
still unverified; there is no sixth station heartbeat pad. Exact selected
roles and conditional quantities come from `full-feature-plan.json` and its
two generated shopping lists. Optional NFC toy props and AMG8833 thermal
hardware have selected quantity zero and are not a default checkout.

The room accessory station may reuse the existing Feather nRF52840 over USB if its UART/I2C and firmware are verified; otherwise one generic ESP32C3. It publishes timestamped scoped context to the Mac and controls **no motors**. Human presence or heartbeat is **never** presented as identification, medical diagnosis or consent to monitor.

## What is selected versus still unverified

| Item | State |
| --- | --- |
| One Sense + WROOM, 2 ULN2003 motors, 2 MG90S, OLED, basic touch | Existing project firmware and documented wiring; real assembled verification pending |
| MPU6050 at upstream 0x68/0x69, five VL53L0X on mux A | Existing source support; physical mounting, voltage and safety tests pending |
| Additional 3 optical directions, second mux and 8 zone CAP1188 | Eight lanes and read-only side polling source implemented; eight physical sensor trials and measured safety margins still required |
| APDS9960, FSR/ADS1115, two wheel encoders, AS5600 nose, PN532, battery gauges, humidity | Low-priority mux raw drivers, bounded PN532 toy tag protocol and selected Mac interactions in source; no actual carrier, mounting, optical, power, NFC or physical motion qualification |
| Local safety stopping, battery charging, gripper lift, natural audio interrupt, autonomy, docking | No physical acceptance; must pass full published trials before declaring done |
| Room station, heartbeat, VOC/CO2, presence, thermal, plant and toys | Named external accessory architecture; opt-in source and driver integration required |

## Deliberate exclusions from the fixed head build

Do **not** buy another BerryIMU, extra camera, separate microphone, Pi, duplicate environmental sensors, both RC522 and PN532, both MPR121 and CAP1188, or an analog DAC to use PAM8403. Do **not** buy an unqualified pan/tilt head or powered ears/tail attachment: those are distinct mechanical variants that would change the explicit fixed-head and two-servo requirements. Original 75 sensor ideas and 46 game/behavior ideas remain catalogued in [source-map](../source-map.md), not all declared physically necessary purchases.

## Supplier specification references

- https://www.ti.com/lit/ds/symlink/tca9548a.pdf
- https://www.microchip.com/en-us/product/CAP1188
- https://www.microchip.com/en-us/product/mcp23017
- https://www.ti.com/product/ADS1115
- https://www.ti.com/product/INA226
- https://www.analog.com/en/products/max17048.html
- https://sensirion.com/products/catalog/SHT41
- https://www.nxp.com/products/MPR121
- https://www.st.com/en/imaging-and-photonics-solutions/vl53l0x.html
- https://www.analog.com/media/en/technical-documentation/data-sheets/AS5600_DS000365_5-00.pdf

The accompanying [machine-readable plan](full-feature-plan.json) is the source for parts quantities and lane allocations. It deliberately records unqualified hardware instead of pretending a zero physical-trial count is a pass.


## Active CAP1188 telemetry pipeline, November 10

A new bounded WROOM adapter reads Microchip CAP1188 ID 0xFD = 0x50 and manufacturer 0xFE = 0x5D on expansion mux 0x71 lane 0, default address 0x29, or address 0x28 on a strapped carrier, after both required manufacturer and product IDs are verified. It reads actual 8-bit touch status at register 0x03 every 80ms, temporarily disconnecting the range mux and closing the optional mux before leaving. Missing and wrong-ID devices cannot forge touch reports. `BodyControl` tracks zone mask, source validity and observed rising-zone counters, without granting motor authority or replacing the independent AT42QT1010 stop pad. The existing authenticated Mac head-status poll now stores qualifying rising contacts as private firsthand petting memories, ignoring first samples, reconnect resets and malformed deltas. Both C++ and Python tests were added; these are software tests only. The physical electrode geometry and through-case capacitance still require trials.


## Additional left, right and rear VL53L0X source reuse

The new `esp32_full` firmware profile initializes and samples all eight TCA9548A `0x70` lanes using the **same pinned Pololu VL53L0X Arduino source** as the original critical five, without a new ranging library. Channels 0 to 4 continue to feed the local floor/front CliffGuard; channels 5 to 7 are left, right and rear diagnostic samples with validity and age. A failed full eight sensor boot does not authorize movement. The existing `esp32_stepper` five sensor profile remains available for testing owned hardware before the three additional carriers are installed. Hardware side/rear clearance thresholds, skid, chassis sweep and stopping trial evidence are still required before these lanes can authorize reversing or turning. [Correct pinned Pololu VL53L0X library](https://github.com/pololu/vl53l0x-arduino).


## Real eight channel USB bench report

The preexisting USB `serial_bench.py --inspect` output now parses the **actual** `side_ranges` WROOM telemetry into three named left/right/rear range observations, with raw distances, ages, presence/validity and `motion_certified=false`. It is read-only; forged masks, nonexistent channels, stale source formats or any attempt to claim `motion_certified=true` are rejected. An unconnected five sensor WROOM still reports side sensing absent, not three fabricated values. This can be reused for a future measured swept-turn calibration, but is not its acceptance evidence.


**Eight lane scheduling correction:** The full firmware no longer cycles 0 through 7 equally. It samples mandatory floor and front lanes 0,1,2,3,4, then **one** of optional left/right/rear lanes 5,6,7 before returning to critical sensors. Each optional direction rotates once per six polling calls. This preserves a five sensor safety sample window while keeping all eight channels alive and honestly diagnostic. The scheduler has a new portable C++ unit test (100 cycles); no actual I2C timing or loaded floor-stop measurement has been claimed.


### Regenerating the body and head signal harness from live firmware

The one-robot signal list is now generated directly from the machine-readable pin allocation and the actual WROOM `BodyPins.h` and XIAO `sense/config.h`. This avoids manual discrepancies in motor phases, UART crossing, OLED/I2S, PDM and both TCA9548A channel sets. From the repository root:

```sh
python3 code/scripts/emit_wiring_manifest.py --out docs/hardware/one-robot-signal-harness.generated.md
```

The generator rejects conflicting pins, firmware map changes, duplicate addresses on one mux lane, missing 0x70/0x71 lanes and critical cliff order drift. Review `code/tests/test_assembly_harness.py` for executable source-contract tests. **This is a signal harness, not a completed electrical schematic.** No physical power supply, boost charger, protected battery, terminal IR decoder, RGB SD J3 solder change or untested carrier VCC is inferred or enabled by the generator. Do not connect power just because a generated line exists.

### Current sensor source and behavior closure matrix

This table describes the **single canonical PR #17**. It separates real source code from hardware validation, and from unimplemented device outputs. Optional sensors share the selected source architecture; none of them can silently grant drive, charger or medical decisions.

| Sensor or accessory | Actual source behavior | Next qualification or missing source |
| --- | --- | --- |
| VL53L0X x8 through mux 0x70 | Four corner cliff plus front WROOM guard; left, right and rear raw readings plus calibrated Mac proximity events | Verify all eight carrier voltages, optical geometry, short-range performance and local stop margin |
| MPU6050, optional BerryIMU | Real I2C six-axis identity and bounded raw telemetry; opt-in handling and shake memories | Calibrate mounting, gravity vector, held state and physical motion |
| AT42QT1010 and CAP1188 | Local direct head-touch stop, taps, doubles and hold-to-quiet; eight read-only petting electrodes | Shell thickness, false touches, debounce and physical stop times |
| MAX30102 paw optical | SparkFun-derived bounded red/IR FIFO, fresh acquisition counter, two-sample optical touch events, per-robot memory | Verify actual module, current, finger contact threshold; **no BPM or medical output** |
| APDS9960 | Proximity and gesture FIFO edge decoder, opt-in Mac reactions | Actual gesture range, lighting and source freshness |
| ADS1115 with two FSR pads | Raw belly/jaw force, optional squeeze event, bounded guarded jaw approach | Mechanical placement, real baseline, force limit and calibrated key/candy trials |
| AS5600 x3 | Three raw measured magnetic angles, optional nose-twist interaction | Magnet placement, left/right wheel direction, speed/odometry integration and trials |
| SHT41 | CRC checked temperature/humidity readings with new acquisition counter; opt-in confirmed local ambient change memory | Check actual vent placement, self-heating, humidity and threshold calibration |
| BMP280 | Manufacturer ID, compensated raw pressure/temperature, spaced successful acquisition sequence and age; optional opt-in local pressure-change interaction through Mac memory/camera triggers | Physical sensor placement, breakout voltage and real pressure threshold trial remain unqualified; never claim predicted weather, pressure-based altitude, or motor authority |
| INA226 and MAX17048 | Raw bus/shunt and cell/SOC diagnostics, low-battery interaction | Calibrate actual shunt and pack, measure current and validate charging; no invented amps |
| NC bumpers, PIR and reed | Optional local bumper stop, PIR/magnet event counters with typed Mac memory | Verify actual 3.3V inputs and enable compile flags after wiring |
| PN532 NFC toy reader | **New** bounded Seeed protocol adaptation on 0x71 lane 5: SAM init, finite RF activation retries, ISO14443A UID checksum, read-only nonsecret game token and new-presented counter; existing Mac private toy event consumer | Real board mode/voltage, 400 kHz I2C ready-byte behavior, RF latency, antenna, current and fixture trial; no authentication |
| MCP23017 dock monitor | Required fresh dock seat and PGOOD/CHG input snapshots in full WROOM profile | Hardware-qualified 1S charger, protected pack, hot removal, verified current |
| WS2812B RGB heart and haptic coin motor | RGB is config gated; haptic GPB2 edge and dock-first source are implemented in an isolated lab profile, **not physically qualified** | Verify XIAO SD J3, RGB power/level buffer, and separate HC123 one-shot plus MOSFET coin driver on real hardware; do not confuse source compile with physical acceptance |
| Dual IR terminal dock receivers | Two legacy RMT RX channels on WROOM GPIO36/39, read-only strict NEC parser and authenticated Mac evidence; no measured bearing or final actuator integration | Verify actual board pins and GPIO36/39 erratum, simultaneous RMT captures, measured optical homing, safe contacts and charging circuit |
| SCD40 CO2, BME688 raw gas, LD2410C presence, AMG8833 thermal, soil probe | **Actual shared station source exists:** `code/firmware/room_station/src/main.cpp` uses pinned Sensirion SCD4x, BME68x, AMG88xx and LD2410 upstream drivers on the reported owned Feather; `room_station.py` validates bounded timestamped USB readings and the Mac camera hub offers consented short-lived shared context to five pets. Soil ADC is explicitly disabled by default (`ROOM_SOIL_FITTED=0`); neither gas resistance nor radar establishes VOC concentration or person identity | No complete firmware build, real station wiring, thermal or optical trial, live USB reconnection, five physical receivers, powered soil ADC, or measured latency. This is source integration, **not hardware approval** |

**Physical acceptance remains open.** The source level PN532 adapter has portable parser tests plus deterministic I2C slot tests, but was not compiled on GitHub Actions or exercised with the real PN532 carrier. Its vendor BSD protocol framing is adapted to avoid the upstream blocking poll that would delay WROOM cliff sensing. The UID game token uses FNV and is cloneable; never use it for access control or identity.



### November 13 PN532 shared bus timeout qualification

Research checkpoint at PR #17 head `c2f3e32ccd0c0412081a16f39ec370f361f1d0c6`. This is a source review, not a measured fault or hardware acceptance.

NXP PN532 UM0701-02 section 6.3.3 and Figure 66 documents SCL stretching on I2C wake from power down (normally below 2 ms with appropriate quartz and layout): https://www.nxp.com/docs/en/user-guide/141520.pdf . The existing bounded PN532 frame adaptation is derived from Seeed's PN532 protocol library (verify the exact vendored BSD notices in docs/ATTRIBUTION.md), rather than adding a blocking reader: https://github.com/Seeed-Studio/PN532 . Espressif Arduino ESP32 documents `Wire.setTimeOut` (50 ms default): https://github.com/espressif/arduino-esp32/blob/master/docs/en/api/i2c.rst . **Do not assume the configured 15 ms always bounds a stuck transfer:** an older ESP32 driver issue reports an effective one second lower wait in some IDF versions, which requires testing against this project's exact pinned PlatformIO/Arduino core, not extrapolating from current upstream: https://github.com/espressif/arduino-esp32/issues/8056 .

Current source: `TofBus::begin` configures `wire_.setTimeOut(15)`; `AccessorySensors::poll` reads MCP23017 GPIOA before optional PN532 on shared mux 0x71 lane 5; `AccessorySensors::invalidate_cached` clears cached dock validity on mux errors; `BodyControl::set_accessories` rejects expired or provenance-mutated dock records and retains the contact lockout. These safeguards do **not** prove that a blocked `Wire.requestFrom` returns before local motor deadlines. The safety critical test is the elapsed wall clock of a real blocked transaction while motors are armed, including watchdog execution and GPIOA age; a mocked NACK is insufficient to simulate SCL held low.

Next owner action: inspect the pinned Arduino Wire implementation and the WROOM main loop scheduling; add an injectable fake Wire stall regression to `guarded_body_tests` or the accessory bus tests proving no rearm on stale dock GPIO, plus a real logic analyzer SCL/SDA/IRQ capture with PN532 powered down, disconnected and wedged. If the real driver can block longer than the motor safety deadline, implement a fail closed scheduling or independent hardware stop mechanism before approving the shared wiring. Do not add a second I2C master or bypass MCP23017 freshness. Charging electronics and physical docking remain unqualified.
