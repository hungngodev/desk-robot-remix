# Sixty three row source and purchase crosswalk

Checked against live draft PR 17 on 2026-11-16. This is an **audit, not a second cart or purchase approval**. The only counted source is `full-feature-plan.json`; the human sourced quote/candidate ledger is `2026-11-16-five-pet-purchase-register.md`. The plan now has 42 pet and dock roles, 7 shared station roles, and 14 `linked_subassemblies` explicitly tied to those parent roles. `code/scripts/procurement_release.py` requires separate reviewed decisions for all 14 linked entries before it could release an order; an unresolved entry blocks release. **There are 63 ledger rows, not 63 separately required SKUs.**

This report deliberately distinguishes a source path from real compatibility. A named file and a source level driver do not establish an exact PCB vendor, firmware build result, pin voltage, loaded power margin, optical cliff stopping, tested charging, or physical fit. Most parts remain HOLD. Full product purchase and the fivefold fleet copy require actual electrical and mechanical evidence.

## Primary 49 source owners

| Scope | Role | Five pet or station quantity | Inspected source owner | Verified scope on source inspection | Remaining qualification |
| --- | --- | ---: | --- | --- | --- |
| Pet or dock | `xiao_sense` | 5 | [source](../../code/firmware/head/sense/desk_robot_sense.cc) | Device code | Camera, PDM microphone, board and J3 electrical fit |
| Pet or dock | `wroom` | 5 | [source](../../code/firmware/body/src/main.cpp) | Device code | Exact WROOM PCB, real GPIO levels and 3.3V/5V rails |
| Pet or dock | `oled` | 5 | [source](../../code/firmware/head/sense/desk_robot_sense.cc) | Device code | Sense board display routing and physical bezel |
| Pet or dock | `stepper` | 10 | [source](../../code/firmware/body/src/main.cpp) | Motor code, variant on hold | Loaded drive torque and choice against DC motors |
| Pet or dock | `uln2003` | 10 | [source](../../code/firmware/body/platformio.ini) | Motor code, variant on hold | 28BYJ48 coil current and driver heat |
| Pet or dock | `mg90s` | 10 | [source](../../code/firmware/body/src/main.cpp) | PWM code | Real gripper travel, stall, force and fit |
| Pet or dock | `imu` | 5 | [source](../../code/firmware/body/lib/BerryImu/BerryImu.cpp) | Raw device code | Mount axis, tilt thresholds, real handling interlock |
| Pet or dock | `head_touch` | 5 | [source](../../code/firmware/body/src/main.cpp) | Safety input code | Actual AT42 logic level and unplug stop |
| Pet or dock | `max30102` | 5 | [source](../../code/firmware/body/lib/PulsePad/PulsePad.cpp) | Read only driver | Probe voltage, paw placement, fresh optical samples |
| Pet or dock | `cliff_obstacle` | 40 | [source](../../code/firmware/body/lib/TofBus/TofBus.cpp) | Guarded range source | Cheap carrier pullups, optical depth and loaded desk edge stop |
| Pet or dock | `i2c_mux` | 10 | [source](../../code/firmware/body/lib/TofBus/TofBus.cpp) | Mux readback source | Generic PCB layout, 0x70/0x71 address straps and bus rise time |
| Pet or dock | `amp` | 5 | [source](../../code/firmware/head/sense/sense_reference_codec.cc) | Audio source | 5V audio rail, board gain, thermal and interference |
| Pet or dock | `speaker` | 5 | [audio](../../code/firmware/head/sense/sense_reference_codec.cc), [2W fit coupon](../cad/remixes/speaker_rect_fit_gauge.scad) | Exact active Challenge CS20-02P110-04-1X, 8 ohm 2W, 20 x 16 x 4.7mm selected as a source SKU to replace unsuitable 1W model; nominal CAD mesh rendered but no hardware acceptance | Real seated geometry, 1cc sealed acoustics, sound pressure, voice double talk, maximum gain and thermal rise |
| Pet or dock | `cap1188` | 5 | [source](../../code/firmware/body/lib/ExpansionTouch/ExpansionTouch.cpp) | Read only touch code | Actual 0x29/0x28 breakout, electrodes and ESD |
| Pet or dock | `touch_electrodes` | 5 | [source](../../docs/hardware/full-feature-wiring-and-shopping.md) | Mechanical and wiring design | Electrode placement, shielding, insulation and noise |
| Pet or dock | `apds9960` | 5 | [source](../../code/firmware/body/lib/AccessorySensors/AccessorySensors.cpp) | Raw event driver | Carrier and reliable gesture conditions |
| Pet or dock | `fsr` | 10 | [source](../../code/firmware/body/lib/AccessorySensors/AccessorySensors.cpp) | ADC path only | Actual jaw/belly force curve and mechanical travel |
| Pet or dock | `ads1115` | 5 | [source](../../code/firmware/body/lib/AccessorySensors/AccessorySensors.cpp) | Raw ADC read source | Exact 3.3V carrier and reference input range |
| Pet or dock | `rgb` | 5 | [source](../../code/firmware/head/sense/desk_robot_sense.cc) | Config gated LED code | Sense J3 isolation and actual buffer plus RGB rail |
| Pet or dock | `logic_level` | 5 | [source](../../code/firmware/head/sense/desk_robot_sense.cc) | External electronics only | 74AHCT1G125 wiring, OE and 5V input thresholds |
| Pet or dock | `as5600` | 15 | [source](../../code/firmware/body/lib/AccessorySensors/AccessorySensors.cpp) | Raw angle driver | Magnet axial gap and calibrated wheel odometry |
| Pet or dock | `encoder_magnets` | 15 | [source](../../docs/hardware/full-feature-wiring-and-shopping.md) | Mechanical only | Diametric magnet orientation, shaft alignment, gap |
| Pet or dock | `ina226` | 5 | [source](../../code/firmware/body/lib/AccessorySensors/AccessorySensors.cpp) | Raw power read source | Shunt rating and calibration under loaded current |
| Pet or dock | `max17048` | 5 | [source](../../code/firmware/body/lib/AccessorySensors/AccessorySensors.cpp) | Raw gauge read source | Avoid second gauge if BQ27441 charger selected |
| Pet or dock | `cap_power` | 5 | [source](../../docs/hardware/charging-design-and-validation.md) | No qualified charger circuit | 1S protection, NTC, load sharing, contact isolation |
| Pet or dock | `sensor_3v3` | 5 | [source](../../code/scripts/power_preflight.py) | Power design only | Measured sensor current and regulator thermal margin |
| Pet or dock | `switch_power` | 5 | [source](../../docs/hardware/charging-design-and-validation.md) | Power design only | Fuse, rated leads, polarity and connector keying |
| Pet or dock | `bumper` | 10 | [source](../../code/firmware/body/src/main.cpp) | Local stop code | NC wired failure detection and physical collision trials |
| Pet or dock | `reed` | 5 | [source](../../code/firmware/body/lib/AccessorySensors/AccessorySensors.cpp) | Read only GPIOB source | Actual voltage, magnet geometry and debounce |
| Pet or dock | `pir` | 5 | [source](../../code/firmware/body/lib/AccessorySensors/AccessorySensors.cpp) | Read only GPIOB source | 3.3V high level and PIR polarity |
| Pet or dock | `bmp280` | 5 | [source](../../code/firmware/body/lib/AccessorySensors/AccessorySensors.cpp) | Read only driver | Owned breakout 0x76/0x77 and compensation |
| Pet or dock | `sht41` | 5 | [source](../../code/firmware/body/lib/AccessorySensors/AccessorySensors.cpp) | Read only CRC driver | Waterproofing, humidity response and carrier fit |
| Pet or dock | `pn532` | 5 | [source](../../code/firmware/body/lib/AccessorySensors/AccessorySensors.cpp) | Read only NFC protocol | I2C mode straps, IRQ/reset and antenna range |
| Pet or dock | `mcp23017` | 5 | [source](../../code/firmware/body/lib/AccessorySensors/AccessorySensors.cpp) | Required dock GPIO source | Wiring, contact polarity, sample freshness and fail closed |
| Pet or dock | `haptic_motor` | 5 | [source](../../code/firmware/body/lib/AccessorySensors/AccessorySensors.cpp), [scheduler](../../code/firmware/body/lib/AccessorySensors/HapticPulse.h), [lab wiring](haptic-one-shot-wiring.md) | Actual CAP1188-triggered, dock-gated MCP23017 GPB2 edge source in optional lab firmware, scheduler host test; standard motor power output deliberately OFF | Externally current-limited 3 V coin motor with CD74HC123 physical one-shot, oscilloscope confirmation of shutdown even on stuck-high I2C, motor thermal/current measurement |
| Pet or dock | `haptic_driver` | 5 | [source](../../code/firmware/body/lib/AccessorySensors/AccessorySensors.cpp) | Opt-in MCP23017 GPB2 haptic edge implemented and test fixtures committed, normal production profile OFF | [HC123 one-shot and AO3400 bench wiring](haptic-one-shot-wiring.md), physical pulse, 3V motor current and fault proof |
| Pet or dock | `dock_ir_receivers` | 10 | [source](../../code/firmware/body/lib/TerminalIr/TerminalIr.cpp) | RMT receiver source | Two real receivers, baffles, sunlight and frame loss |
| Pet or dock | `dock_ir_beacon_controller` | 5 | [source](../../code/firmware/dock/src/main.cpp) | Bench NEC source only | Production carrier pinout, flash and clock tolerance |
| Pet or dock | `dock_ir_emitter_channels` | 10 | [source](../../code/firmware/dock/src/main.cpp) | Bench logical output only | Separate power transistor current and optical cones |
| Pet or dock | `dock_contacts` | 5 | [source](../../docs/hardware/charging-design-and-validation.md) | Read only status, no released power netlist | Protected recessed contacts and independent true charge measurement |
| Pet or dock | `dock_fixture` | 5 | [source](../../docs/cad/remixes/dock/dock_passive_fit.scad) | Unqualified CAD fit reference | Print and measure dock, contact alignment and marker |
| Pet or dock | `assembly` | 5 | [source](../../docs/cad/remixes/one_robot_adapter_kit.scad) | Partial CAD fit kit | Final printed enclosure, battery cavity, harness clearance |
| Shared station | `scd40` | 1 | [source](../../code/firmware/room_station/src/main.cpp) | Station sensor source | Sensor airflow, I2C, accuracy and current |
| Shared station | `bme688` | 1 | [source](../../code/firmware/room_station/src/main.cpp) | Station sensor source | Gas warmup, 3.3V bus and interpretation |
| Shared station | `ld2410c` | 1 | [source](../../code/firmware/room_station/src/main.cpp) | Station UART source | 256000 UART, voltage and no person identity |
| Shared station | `soil_probe` | 1 | [firmware](../../code/firmware/room_station/src/main.cpp), [bounded ADC](../../code/firmware/room_station/src/soil_sample.h), [real calibration](../../code/laptop/src/desk_robot/soil_calibration.py), [wiring](../../code/firmware/room_station/README.md) | Three-sample median and rail/noise rejection implemented; Mac measured two-point relative calibration and five-pet shared read-only context integrated; OFF in default build | Actual 3.3V probe board, A0 voltage, genuine dry/wet measured ADC endpoints, corrosion/waterproofing, source build and on-device test |
| Shared station | `nfc_game_props` | 10 | [source](../../code/firmware/body/lib/AccessorySensors/AccessorySensors.cpp) | PN532 read only source | Tag RF read geometry and toy durability |
| Shared station | `amg8833` | 1 | [source](../../code/firmware/room_station/src/main.cpp) | Checked AMG8833 high-gain 0..80 C firmware and Mac decoder, no device test | Panasonic AMG8833 high gain (not AMG8834 low gain), exact sensor I2C bus, thermal validity and physical qualification still open |
| Shared station | `room_controller` | 1 | [source](../../code/firmware/room_station/src/main.cpp) | Feather candidate firmware source | Actual owned board and connector pin map |

## Additional fourteen rows, without duplicate buying

| Supplementary register entry | Quantity | Parent primary role | Disposition | Pilot shown | Physical blocker |
| --- | ---: | --- | --- | ---: | --- |
| N20 100:1 MP 6V motors | 10 | `stepper` | Unselected motor alternative | 0 | Two per pet, 10 fleet; source motor driver option, tracks still to fit; Owned 28BYJ48 must be load tested first; $22.03 premium not selected for purchasing |
| DRV8833 dual H bridge | 5 | `stepper` | Unselected motor alternative; guarded source profile exists | 0 | Reuse reportedly owned spare DRV8833 first and verify 3.3V logic, driver polarity, 5V/low-cell motor load and real current. Pololu premium carrier not an approved purchase |
| BQ24075 battery power path and BQ27441 gauge | 5 | `cap_power` | Unselected charger and gauge alternative | 0 | One per pet, bench verify net charge and thermistor; Duplicate with separate MAX17048; select one gauge and verify pack NTC |
| 5V switching regulator | 5 | `cap_power` | Candidate, unselected power subsystem | 0 | One per pet, low cell current/thermal test; Low cell power input and thermal qualification missing |
| Protected NTC 1S battery pack | 5 | `cap_power` | Needed physical subsystem, exact pack unselected | 0 | Five eventual, order only once fit and load measured |
| Independent 5V dock adapter | 5 | `dock_fixture` | Needed physical subsystem, connector unselected | 1 | 5 eventual adapters; connector and protective circuit unselected |
| Dock IR LED transistor/resistor driver channel | 10 | `dock_ir_emitter_channels` | Needed hardware subsystem, netlist unselected | 2 | 2 per dock, 10 total; current and switching validated on pilot |
| Shared room controller | 1 | `room_controller` | Already counted in station role | 0 | Exactly one shared station not five |
| True room CO2 sensor | 1 | `scd40` | Already counted in station role | 1 | Exactly one shared station |
| Room gas/environment sensor | 1 | `bme688` | Already counted in station role | 1 | Exactly one station, raw gas not VOC ppm |
| Room presence radar | 1 | `ld2410c` | Already counted in station role | 1 | Exactly one station, 256000 baud UART carrier |
| Room thermal 8x8 array | 1 | `amg8833` | Already counted in station role | 0 | Exactly one station, no identity classification; Shared station optional: cost/added value and exact 3.3V bus must be proven |
| Optional capacitive soil probe | 1 | `soil_probe` | Already counted in station role | 0 | Shared station optional and disabled in firmware |
| Optional NFC toy stickers | 10 | `nfc_game_props` | Already counted in station role | 0 | 10 game tokens optional, not access control |

## Real gaps to close before purchase

1. **No final power architecture:** battery chemistry, exact protection PCB, connector, actual NTC path, charger input, genuine cell current proof, regulator and insulated contact wiring remain undecided. Do not buy both BQ27441 and MAX17048. The proposed 86 mm protected pack does not fit the nominal 68 mm cavity.
2. **Motor choice unselected:** stepper stock is reported, but N20 and DRV8833 are alternatives. Physical running current, torque, stopping distance, track geometry, wheel encoder magnetic fit and 5V loads decide which is selected.
3. **Source is not physical release:** 8 inexpensive VL53L0X per robot are supported in source but generic carrier voltage, pullups, optical interference and cliff emergency stop require tests. Both TCA9548A board addresses must be set and isolated as designed.
4. **No complete printable robot and dock:** existing CAD is a fit kit and passive scaffold. Do not infer finished editable assembly, safe wire bends or qualified charging contact alignment.
5. **Actuation progress, still no purchase approval:** active GPB2 haptic edge and tested pure trigger scheduler now exist in the opt-in WROOM lab profile, with CAP1188 event gating, dock-first MCP23017 sampling, OLATB readback, and a dedicated bus fault C++ fixture. Real coin motor power still requires the generic HC123 independent one-shot, AO3400, diode and genuine oscilloscope, current and thermal evidence. The regular full robot profiles deliberately keep haptic power OFF. RGB is also config gated until Sense J3 isolation and physical power tests.
6. **Room station thermal fault fixed in source, not flashed:** the earlier Adafruit AMG8833 void reader did not propagate I2C read failures. Current source checks each I2C pixel transaction and only emits a complete, plausible fresh frame. A portable decoder test is available; compile the full Feather firmware and test the actual physical device before considering its role verified.
7. **Shopping evidence not a SKU:** generic part names, catalogue chip datasheets, old seller prices and upstream library references must not become final order links without an exact PCB schematic, landed total price and measured compatibility. The 14 supplemental rows contain alternatives and aliases; never add all their counts to the 49 physical roles.

## Verification receipts and next review

The current script `code/scripts/procurement_release.py` refuses fleet release until source and physical evidence receipts are supplied. The new `code/tests/test_full_purchase_register_integrity.py` adds structural checks for all 14 supplement names, parent count, 42 plus 7 primary roles and unselected pilot amounts. Source parsing in this audit was performed against the live GitHub content. Do not claim the host `pytest`, PlatformIO, ESP-IDF, physical charger, source fit or fleet trial passed merely because this table was generated.

## 2026-11-16 price correction for one room thermal sensor

The currently quoted SparkFun SEN-14607 is **$49.95** for one shared AMG8833 8 by 8 array, not five robot units. Same chip candidates located in primary seller listings:

| Exact seller candidate | Public listed unit price | URL | Status |
| --- | ---: | --- | --- |
| SparkFun SEN-14607 | $49.95 | https://www.sparkfun.com/sparkfun-grid-eye-infrared-array-breakout-amg8833-qwiic.html | Original comparison quote, not automatic order |
| ElectroPeak GY-AMG8833 SEN-05-022 | $21.95 | https://electropeak.com/gy-amg8833-ir-8x8-infrared-thermal-imaging-array-sensor-module | Lower cost candidate; landed shipping and PCB pullup evidence absent |
| Seeed Grove AMG8833 101020557 | $29.00 | https://www.seeedstudio.com/Grove-Infrared-Temperature-Sensor-Array-AMG8833.html | Midprice alternative; Grove socket/PCB fit requires review |
| ShillehTek AMG8833 NB146 | $27.99 | https://shillehtek.com/products/amg8833-ir-thermal-camera-sensor-arduino-esp32 | Soldered header option, shipping and exact electrical fit still unknown |

The pinned firmware uses the original AMG8833 I2C register layout and assumes the board is strapped to address 0x69. **Do not buy based on chip name and quoted price alone**. The exact listing PCB, actual voltage rail and SDA/SCL pullups, ADO address state, optical mounting and total delivered cost remain unverified. These four are candidate comparisons, not four additional bill of materials lines. Do not purchase an Adafruit branded sensor board.
