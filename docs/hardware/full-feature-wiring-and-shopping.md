# Final selected full five-pet hardware architecture

**Decision:** This is the selected complete-feature electrical and sensor allocation for five identical core pets. It is not a stripped-down robot. Exact board carrier, battery and printed fit are not physically qualified. The original $50 total prototype cap is incompatible with the selected ranging carriers; do not invent a false price.

**Use one Mac plus five identical Sense heads and WROOM bodies.** Reuse the owned motors and MG90S before buying duplicates. No second camera, additional onboard microphone, Raspberry Pi, or unrelated motor driver is required.

## What you already have

| Module | Known quantity or status |
| --- | --- |
| ESP32 WROOM32 | At least 1 |
| XIAO ESP32S3 Sense | At least 1 ordered; delivery count unknown |
| SSD1306 OLED | At least 1 |
| 28BYJ48 5V motors | 5 |
| ULN2003 drivers | 5 |
| MG90S positional servos | About 10, not counted |
| MPU6050 | At least 1 reported |
| AT42QT1010 touch | At least 1 photographed |
| BerryIMU | At least 1, spare |
| BMP280, PIR, reed, vibration motor | At least 1 each photographed |
| PAM8403, MAX9814, GY61, IR modules | Spares reported |
| Filament and jumper ribbons | Reported owned; counts/condition not fully verified |

## Buy and allocate per finished robot

**Full five is the real target:** The table includes the extra interaction features, not just the five-sensor prototype. Buying the first unit of a selected module to verify the pinout, I2C voltage, height and optical performance is a purchasing quality check, not a feature cut.

### Main body, head and safety

| Component | 1 robot | 5 robots total | Inventory note |
| --- | ---: | ---: | --- |
| XIAO ESP32S3 Sense camera + microphone | 1 | 5 | One ordered; verify arrival |
| ESP32 WROOM32 development board | 1 | 5 | 1 reported owned |
| SSD1306 0.96 inch OLED | 1 | 5 | 1 reported owned |
| 28BYJ48 5V stepper motor | 2 | 10 | 5 reported owned |
| ULN2003 driver for 28BYJ48 | 2 | 10 | 5 reported owned |
| MG90S positional servo | 2 | 10 | Count stock before buying |
| MPU6050 GY521 compatible six axis breakout | 1 | 5 | 1 reported owned |
| AT42QT1010 momentary capacitive head touch | 1 | 5 | 1 reported owned |
| VL53L4CD time of flight carrier | 8 | 40 | None verified owned |
| TCA9548A 8 channel 3.3V compatible I2C multiplexer | 2 | 10 | None verified owned |
| MAX98357A I2S mono amplifier | 1 | 5 | None verified owned |
| 8 ohm 1 watt approximately 20 mm speaker | 1 | 5 | None verified owned |
| Matched protected rechargeable 1S power assembly with charge and load sharing | 1 | 5 | None verified owned |
| Dedicated regulated 3.3V expansion sensor supply | 1 | 5 | None verified owned |
| Rated switch, fuse, power leads, JST style keyed connectors, decoupling | 1 | 5 | None verified owned |
| Filament, printed chassis/head/gripper mounts, fasteners, inserts, insulated harness | 1 | 5 | None verified owned |

### Additional interactions, sensing and games

| Component | 1 robot | 5 robots total | Inventory note |
| --- | ---: | ---: | --- |
| CAP1188 8 zone capacitive touch breakout | 1 | 5 | None verified owned |
| MAX30102 optical heartbeat paw pad breakout | 1 | 5 | HTML claims about five owned, photo confirmation missing |
| Copper tape touch electrode and insulating backing set | 1 | 5 | None verified owned |
| APDS9960 gesture proximity color light module | 1 | 5 | None verified owned |
| FSR402 type force sensing resistor | 2 | 10 | None verified owned |
| ADS1115 4 channel ADC breakout | 1 | 5 | None verified owned |
| Single diffused WS2812B RGB pixel | 1 | 5 | None verified owned |
| 74AHCT1G125 3.3V to 5V RGB buffer | 1 | 5 | None verified owned |
| AS5600 magnetic rotary angle breakout | 3 | 15 | None verified owned |
| Diametric AS5600 compatible magnets | 3 | 15 | None verified owned |
| INA226 current voltage monitor with rated external shunt | 1 | 5 | None verified owned |
| MAX17048 single cell fuel gauge | 1 | 5 | None verified owned |
| Normally closed micro bumper switch | 2 | 10 | None verified owned |
| Magnetic reed switch | 1 | 5 | 1 reported owned |
| PIR thermal motion sensor | 1 | 5 | 1 reported owned |
| BMP280 pressure and temperature module | 1 | 5 | 1 reported owned |
| SHT41 humidity and temperature module | 1 | 5 | None verified owned |
| PN532 I2C NFC reader module with IRQ/reset pins | 1 | 5 | None verified owned |
| MCP23017 16 channel I2C GPIO expander | 1 | 5 | None verified owned |
| 3V coin vibration motor | 1 | 5 | 1 reported owned |
| AO3400 class logic MOSFET, flyback diode and pulldown | 1 | 5 | None verified owned |
| Keyed charging contacts and alignment switch set | 1 | 5 | None verified owned |
| Printed docking cradle, printed camera marker and 5V charging input | 1 | 5 | None verified owned |

**Full profile boot requirement:** The selected MCP23017 dock/status input module is now mandatory for `esp32_full` to allow arming. Allowing a completely absent or unresponsive dock board as an optional peripheral would defeat contact safety. Keep one module per robot in the existing parts list, plus the two independent normally closed seat switches and chip status pins; do not invent current sensing from PGOOD/CHG. The `esp32_stepper` staging profile can be used for unpowered bench checks before the dock electronics are assembled, but it does not qualify the full robot for free roaming or powered docking.

The selected full `esp32_full` profile already contains source code to read **eight VL53L4CDs** from TCA9548A `0x70`: four independent downward cliff channels, one forward obstacle channel, and **three additional left, right, rear read-only channels**. The earlier `esp32_stepper` profile reads the five safety/facing channels only. The additional readings feed Mac event detection but **never grant motor permission or an automatic retreat**. All eight boards need actual carrier voltage, orientation, short-range performance, stale-data handling and stopping-envelope measurements before full movement approval. The source driver is not evidence that eight modules are already bought, wired or physically operational.

## Fixed pin wiring

| Body ESP32 WROOM GPIO | Function |
| --- | --- |
| 13, 14, 25, 26 | left stepper |
| 27, 32, 33, 23 | right stepper |
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
| 0 | VL53L4CD, 0x29 | floor front left | Existing WROOM five-channel driver |
| 1 | VL53L4CD, 0x29 | floor front right | Existing WROOM five-channel driver |
| 2 | VL53L4CD, 0x29 | floor rear left | Existing WROOM five-channel driver |
| 3 | VL53L4CD, 0x29 | floor rear right | Existing WROOM five-channel driver |
| 4 | VL53L4CD, 0x29 | front obstacle | Existing WROOM five-channel driver |
| 5 | VL53L4CD, 0x29 | left obstacle | Implemented read only in esp32_full; physical qualification pending |
| 6 | VL53L4CD, 0x29 | right obstacle | Implemented read only in esp32_full; physical qualification pending |
| 7 | VL53L4CD, 0x29 | rear obstacle | Implemented read only in esp32_full; physical qualification pending |

### Mux B, address 0x71: extra pet features, lower polling priority

| Lane | Module and address | Purpose |
| --- | --- | --- |
| 0 | CAP1188 (0x28), MAX30102 (0x57) | Petting electrodes and user-approved heartbeat pad |
| 1 | APDS9960 (0x39), AS5600 nose (0x36) | gesture + twist nose |
| 2 | ADS1115 (0x48) | force feedback |
| 3 | SHT41 (0x44), BMP280 (0x76) | humidity + reported pressure board |
| 4 | INA226 (0x40), MAX17048 (0x36) | current and battery fuel gauge |
| 5 | PN532 I2C (0x24), MCP23017 (0x20) | NFC and auxiliary digital control |
| 6 | AS5600 (0x36) | left wheel rotation |
| 7 | AS5600 (0x36) | right wheel rotation |

**MAX30102 paw interaction source update:** The selected pad's existing SparkFun-derived bounded FIFO parser now increments `pulse.seq` only when a new physical MAX30102 FIFO read succeeds. `BodyControl` carries that counter through the same read-only `/api/aux` path; Mac `PetController` now supports a per-robot, measured `paw_contact_ir_raw_threshold` and explicit `paw_contact_interactions_qualified` flag, two distinct new threshold-crossing acquisitions, a 25 percent release hysteresis, reset/replay handling, firsthand memory and the existing spontaneous speech arbiter. The flag defaults false for all five pet configurations. This treats a finger touching the LED pad as a playful optical interaction, **not** as real heart rate, SpO2, user identity or medical information. Real pad IR thresholds, finger geometry, LED exposure, susceptibility to room light and device current still require physical checks. Source and mock tests are committed in PR #17 but unverified by the failing GitHub Actions runner.

**MAX30102 correction:** The original HTML approved one **robot-mounted** heartbeat paw pad and reported a box of around five MAX30102 boards. Photo confirmation is missing, so count stock before purchasing. Reserve WROOM 0x71 mux lane 0 at 0x57, share lane with CAP1188 0x28 after voltage and breakout checks. **Never** use XIAO Sense GPIO41/42 because those are the PDM microphone wires. Opt-in playful feedback only, not medical use.

**CAP1188 rather than MPR121:** Microchip marks CAP1188 in production, whereas NXP archives MPR121. Use a CAP1188 I2C breakout configured to **0x28**, not its common breakout default 0x29, so it cannot share the same address as the optical modules even if a mux lane is left selected. Its 8 electrodes cover head, back and belly; retain the existing dedicated AT42QT1010 as the **local physical stop touch**, never routed through an optional mux. Check actual breakout address-selection circuitry before ordering.

**MCP23017:** the implemented source reads physical dock seat and charger status pins only. PN532 now uses bounded nonblocking I2C ready-byte and frame reads on the same mux lane without driving optional expander IRQ/reset pins; an actual carrier may require a reset and must be measured before the final wiring is frozen. Haptic switching and the expander output pin assignments are **not implemented** and must not be described as working. All future outputs need hardware-safe default pull resistors. Never put motor phases, servo lift/grip outputs, emergency stops, required head touch or optical cliff timing through the expander.

**PN532 shared bus qualification gate (November 13 source research):** NXP PN532 user manual UM0701-02 sections 6.2.4 and 6.3.3 documents I2C status/ACK/response framing, IRQ readiness and mandatory SCL clock stretching on wake from low power. The current bounded nonblocking Seeed BSD protocol adaptation avoids long software polling but does **not** establish that an actual ESP32 Wire controller and the selected PN532 breakout can safely coexist with the dock MCP23017 on mux 0x71 lane 5. An optional PN532 transaction that holds SCL, hangs a Wire transfer or leaves the mux selected must not compromise required dock GPIO freshness or WROOM cliff sensing. Keep NFC unqualified and read only. Before freezing wiring, instrument SCL/SDA and IRQ across repeated wake, tag held/removed, absent reader and brownout, including MCP23017 GPIO reads and 0x70 ToF sample freshness; capture worst case transfer duration, recovery and fault latching. Do not add a competing Adafruit BusIO PN532 driver merely to claim compatibility: Adafruit PN532 1.3.4 (BSD, requires BusIO) and Seeed Studio PN532 (BSD, supports I2C/SPI/HSU) are reference implementations, not proven drop in replacements for the existing mux owner. If physical I2C wake cannot be bounded, select a separately wired and pin audited SPI/HSU transport before declaring a final PCB, not a software safety bypass. Sources: [NXP UM0701-02](https://www.nxp.com/docs/en/user-guide/141520.pdf), [Seeed PN532](https://github.com/Seeed-Studio/PN532), [Adafruit PN532](https://github.com/adafruit/Adafruit-PN532), [Adafruit interface guide](https://learn.adafruit.com/adafruit-pn532-rfid-nfc/arduino-library). This is a design risk and proposed bench gate, not a reproduced hang or completed electrical test.

**Bus ownership:** existing WROOM ToF driver must run first; optional reads have lower priority and strict timeout. The existing WROOM ToF driver now probes a fitted 0x71 mux and disables all its lanes before each critical 0x70 range read; a failed reset of those optional lanes faults the local safety guard. No new sensor driver is claimed working until implemented and tested. No optional sensor is allowed to rearm a body, clear a fault, grant a permit, or monopolize the bus.

**Wheel encoders:** two AS5600s each live on their own mux channel 6 or 7 because both answer 0x36. A third AS5600 at channel 1 reads the nose. These provide measured magnetic angles only after proper mechanical coupling, not automatic absolute navigation. No optical encoder is silently assumed compatible with the existing tracked wheels.

## Power and physical build

One robot uses a protected matched **1S rechargeable pack**, safe charging with load sharing, regulated 5V rail for WROOM/head/steppers/servo/speaker, and a rated independent 3.3V rail for optional breakout sensors. Every rail shares ground. Use a regulator, wiring, protection and battery discharge rating proven with actual simultaneous stepper, servo, WiFi, camera and TTS peaks; nominal boost listings and unmeasured 5V USB banks are not adequate evidence.

The head remains **fixed**, using the existing two MG90S servos for **lift and grip**. Its OLED and camera use the shipped Sense interface. WS2812B diffused heart uses Sense GPIO9 through a suitable level buffer after verifying SD is disabled. A coin vibration motor uses the existing reported motor and a separate rated low-side MOSFET, never a microcontroller output directly.

The dock has **five individual keyed cradles**, one for each pet, with camera-visible alignment markers, physical guidance, charge-input contacts, a short-safe charger input circuit and a contact detect switch. Contact never bypasses the rechargeable pack's protection circuit. Automatic docking and peer chasing are still separate physical acceptance items; none can be declared working from a CAD preview.

## Shared desktop accessory station, not five copies

| Station sensor/game | Quantity for five pets | Plan |
| --- | ---: | --- |
| SCD40 real CO2 | 1 | ventilated stationary desk |
| BME688 VOC gas and ambient | 1 | ventilated stationary desk |
| LD2410C mmWave presence module | 1 | fixed room pod UART |
| MAX30102 heartbeat pad | 1 | consented tabletop contact accessory |
| Capacitive soil probe | 1 | external plant accessory |
| NFC game tags and magnets | 10 | shared interactive toys |
| AMG8833 thermal array | 1 | optional separate thermal station; not needed for core camera vision |

The room accessory station may reuse the existing Feather nRF52840 over USB if its UART/I2C and firmware are verified; otherwise one generic ESP32C3. It publishes timestamped scoped context to the Mac and controls **no motors**. Human presence or heartbeat is **never** presented as identification, medical diagnosis or consent to monitor.

## What is selected versus still unverified

| Item | State |
| --- | --- |
| One Sense + WROOM, 2 ULN2003 motors, 2 MG90S, OLED, basic touch | Existing project firmware and documented wiring; real assembled verification pending |
| MPU6050 at upstream 0x68/0x69, five VL53L4CD on mux A | Existing source support; physical mounting, voltage and safety tests pending |
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
- https://www.pololu.com/product/3692
- https://www.analog.com/media/en/technical-documentation/data-sheets/AS5600_DS000365_5-00.pdf

The accompanying [machine-readable plan](full-feature-plan.json) is the source for parts quantities and lane allocations. It deliberately records unqualified hardware instead of pretending a zero physical-trial count is a pass.


## Active CAP1188 telemetry pipeline, November 10

A new bounded WROOM adapter reads Microchip CAP1188 ID 0xFD = 0x50 and manufacturer 0xFE = 0x5D on expansion mux 0x71 lane 0, address 0x28 after its address strap is verified. It reads actual 8-bit touch status at register 0x03 every 80ms, temporarily disconnecting the range mux and closing the optional mux before leaving. Missing and wrong-ID devices cannot forge touch reports. `BodyControl` tracks zone mask, source validity and observed rising-zone counters, without granting motor authority or replacing the independent AT42QT1010 stop pad. The existing authenticated Mac head-status poll now stores qualifying rising contacts as private firsthand petting memories, ignoring first samples, reconnect resets and malformed deltas. Both C++ and Python tests were added; these are software tests only. The physical electrode geometry and through-case capacitance still require trials.


## Additional left, right and rear VL53L4CD source reuse

The new `esp32_full` firmware profile initializes and samples all eight TCA9548A `0x70` lanes using the **same pinned Pololu VL53L4CD Arduino source** as the original critical five, without a new ranging library. Channels 0 to 4 continue to feed the local floor/front CliffGuard; channels 5 to 7 are left, right and rear diagnostic samples with validity and age. A failed full eight sensor boot does not authorize movement. The existing `esp32_stepper` five sensor profile remains available for testing owned hardware before the three additional carriers are installed. Hardware side/rear clearance thresholds, skid, chassis sweep and stopping trial evidence are still required before these lanes can authorize reversing or turning. [Pololu library](https://github.com/pololu/vl53l4cd-arduino).


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
| VL53L4CD x8 through mux 0x70 | Four corner cliff plus front WROOM guard; left, right and rear raw readings plus calibrated Mac proximity events | Verify all eight carrier voltages, optical geometry, short-range performance and local stop margin |
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
| WS2812B RGB heart and haptic coin motor | Parts and pin/driver allocation, but **no confirmed final on-device effect driver** | After XIAO SD J3 isolation and GPIO ownership checks, implement and bench-qualify guarded LEDs and MOSFET PWM |
| Dual IR terminal dock receivers | Two legacy RMT RX channels on WROOM GPIO36/39, read-only strict NEC parser and authenticated Mac evidence; no measured bearing or final actuator integration | Verify actual board pins and GPIO36/39 erratum, simultaneous RMT captures, measured optical homing, safe contacts and charging circuit |
| SCD40 CO2, BME688 VOC, LD2410C presence, AMG8833 thermal, soil probe | Preserved as optional external room/plant station extensions, not quietly omitted from research | Separate powered and electrically qualified room station protocol and opt-in integration |

**Physical acceptance remains open.** The source level PN532 adapter has portable parser tests plus deterministic I2C slot tests, but was not compiled on GitHub Actions or exercised with the real PN532 carrier. Its vendor BSD protocol framing is adapted to avoid the upstream blocking poll that would delay WROOM cliff sensing. The UID game token uses FNV and is cloneable; never use it for access control or identity.

