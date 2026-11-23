> **HISTORICAL SUPPLIER RESEARCH (2026-11-16):** [Earlier fleet supplier candidates](2026-11-16-five-pet-purchase-register.md) are reference research, NOT a second checkout cart. The authoritative projection below has 42 pet/dock parent roles, 7 shared-station parent roles and 14 linked decisions ALREADY COVERED BY THEIR PARENTS. Do not add the 14 to the parent quantities. One paid XIAO with carrier-reported delivery pending inspection remains the only confirmed historical payment in this register. Historical seller links are not current delivered quotes or physical qualification; drivetrain, chargers, wiring, printing and loaded operation remain HOLD.

# Five desk pets, five docks, and the shared room station

Generated from docs/hardware/full-feature-plan.json by code/scripts/procurement_release.py. This file is a projection of the plan, never a second editable bill of materials.

**FULL FLEET PURCHASE: HOLD. No complete electrical, mechanical or physical acceptance.** Quantities are design slots, not certified supplier checkouts. Estimated owned counts and ordered units have not been inspected.

## 1. Owned or ordered, as reported

| Component | Reported on hand, unverified | Estimated on hand, unverified | Ordered, inspection pending |
| --- | ---: | ---: | ---: |
| XIAO ESP32S3 Sense camera + microphone | 0 | 0 | 1 |
| ESP32 WROOM32 development board | 1 | 0 | 0 |
| SSD1306 0.96 inch OLED | 1 | 0 | 0 |
| 28BYJ48 5V stepper motor | 5 | 0 | 0 |
| ULN2003 driver for 28BYJ48 | 5 | 0 | 0 |
| MG90S positional servo | 0 | 10 | 0 |
| MPU6050 GY521 compatible six axis breakout | 1 | 0 | 0 |
| AT42QT1010 momentary capacitive head touch | 1 | 0 | 0 |
| MAX30102 optical heartbeat paw pad breakout | 0 | 5 | 0 |
| Magnetic reed switch | 1 | 0 | 0 |
| PIR thermal motion sensor | 1 | 0 | 0 |
| BMP280 pressure and temperature module | 1 | 0 | 0 |
| 3V coin vibration motor | 1 | 0 | 0 |
| Station controller with timestamped USB serial protocol, reuse owned Feather nRF52840 if feasible | 1 | 0 | 0 |

Other reported spares are not interchangeable with chosen modules: BerryIMU, MAX9814, an extra camera, GY61, PAM8403, spare DRV8833 and assorted IR sensors. The reported-owned Feather nRF52840 still needs carrier inspection, firmware, power and USB qualification before it becomes the approved station controller.

## 2. Remaining components or unqualified roles

| Scope | Component | Fleet required | Conditional remaining | Status | Vendor reference or design blocker | Power reference | Verified checkout quote |
| --- | --- | ---: | ---: | --- | --- | --- | --- |
| pet or dock | XIAO ESP32S3 Sense camera + microphone | 5 | 4 | HOLD | At least one ordered; do not duplicate order |  |  |
| pet or dock | ESP32 WROOM32 development board | 5 | 4 | HOLD | Already reported at least one |  |  |
| pet or dock | SSD1306 0.96 inch OLED | 5 | 4 | HOLD | Already reported at least one |  |  |
| pet or dock | 28BYJ48 5V stepper motor | 10 | 5 | HOLD MOTOR CHOICE | 5 reported owned; do not order missing five until loaded drivetrain selection |  |  |
| pet or dock | ULN2003 driver for 28BYJ48 | 10 | 5 | HOLD MOTOR CHOICE | 5 reported owned; do not order missing five until loaded drivetrain selection |  |  |
| pet or dock | MG90S positional servo | 10 | 0 | HOLD | About 10 estimated owned; recount before buying |  |  |
| pet or dock | MPU6050 GY521 compatible six axis breakout | 5 | 4 | HOLD | At least one reported; BerryIMU preserved as spare |  |  |
| pet or dock | AT42QT1010 momentary capacitive head touch | 5 | 4 | HOLD | At least one photographed; retain as independent local stop |  |  |
| pet or dock | MAX30102 optical heartbeat paw pad breakout | 5 | 0 | HOLD | Original user HTML says this is APPROVED as a robot-mounted paw pad and claims about five are already owned. Independent photo audit did not establish exact stock. No purchase before recount and module voltage check. Use WROOM I2C 0x57, not Sense GPIO41/42 PDM mic. |  |  |
| pet or dock | VL53L0X GY-530 small carrier candidate ElectroPeak SEN-19-006 | 40 | 40 | HOLD | ElectroPeak SEN-19-006: https://electropeak.com/gy-530-vl53l0x-laser-range-finder |  |  |
| pet or dock | TCA9548A 8 channel 3.3V compatible I2C multiplexer | 10 | 10 | HOLD | Generic TCA9548A: https://www.ti.com/product/TCA9548A |  |  |
| pet or dock | MAX98357A I2S mono amplifier | 5 | 5 | HOLD | Generic MAX98357A: https://www.analog.com/en/products/max98357a.html |  |  |
| pet or dock | Challenge Electronics CS20-02P110-04-1X 8 ohm 2 watt 20 x 16 mm speaker | 5 | 5 | HOLD | Challenge Electronics CS20-02P110-04-1X: https://www.digikey.com/en/products/detail/challenge-electronics/CS20-02P110-04-1X/30407069 |  |  |
| pet or dock | CAP1188 8 zone capacitive touch breakout | 5 | 5 | HOLD | Choose generic 3.3V CAP1188 I2C breakout at common 0x29 or strapped 0x28; range 0x70 mux is verified off before 0x71 lane0 opens |  |  |
| pet or dock | Copper tape touch electrode and insulating backing set | 5 | 5 | HOLD | Eight zones per pet, not more controllers |  |  |
| pet or dock | APDS9960 gesture proximity color light module | 5 | 5 | HOLD | One multifunction optical sensor |  |  |
| pet or dock | FSR402 type force sensing resistor | 10 | 10 | HOLD | One belly, one gripper; not proof of loaded grip without calibration |  |  |
| pet or dock | ADS1115 4 channel ADC breakout | 5 | 5 | HOLD | 3.3V analog input for two FSR dividers |  |  |
| pet or dock | Single diffused WS2812B RGB pixel | 5 | 5 | HOLD | Sense GPIO9, dedicated logic buffer |  |  |
| pet or dock | 74AHCT1G125 3.3V to 5V RGB buffer | 5 | 5 | HOLD | 5V part and input threshold from vendor spec |  |  |
| pet or dock | AS5600 magnetic rotary angle breakout | 15 | 15 | HOLD | Three AS5600 roles per pet: two actual measured wheel-angle/displacement channels for first-unit remembered-object navigation and one twist-nose input, on isolated mux segments. Wheel coupling, actual gear ratio, wrap rate, magnetic gap, source timing and encoder-to-wheel transmission remain unqualified. AS5600 board alone is not a complete mounted encoder. |  |  |
| pet or dock | Diametric AS5600 compatible magnets | 15 | 15 | HOLD | Three diametric magnets per pet, mechanically paired with AS5600 only when shaft coupling and axial gap are physically measured. Require the correct magnet size, polarity, bracket clearance and drive-shaft support; do not order either the final wheel encoder hardware or its brackets before selected drivetrain and mount compatibility are checked. |  |  |
| pet or dock | INA226 current voltage monitor with rated external shunt | 5 | 5 | HOLD | Existing INA226 0x40 firmware now has a dedicated signed pack-line current source in opt-in esp32_dc_integrated_lab for EXACT five milliohm Kelvin shunt. Candidate resistor Vishay WSL25125L000FEA18, 0.005 ohm 1 percent 2 watt 2512, LCSC C844694 around $0.52 each before shipping versus DigiKey around $1.78 each. Exact resistor pinout and rating source https://www.lcsc.com/product-detail/C844694.html. This selects the low-cost RESISTOR VALUE and reference SKU, not an electrically qualified generic INA226 breakout or charger board. Check actual installed shunt, proper Kelvin layout, high current 2W copper dissipation, connector, source calibration and polarity before installing battery. |  |  |
| pet or dock | MAX17048 single cell fuel gauge | 5 | 5 | HOLD | Connect to matched protected 1S battery rail |  |  |
| pet or dock | Matched protected rechargeable 1S power assembly with charge and load sharing | 5 | 5 | HOLD | Regulated 5V distribution, fused wiring and properly rated continuous boost; exact module after measured load |  |  |
| pet or dock | Dedicated regulated 3.3V expansion sensor supply | 5 | 5 | HOLD | Regulator and bulk/decoupling based on verified sensor power |  |  |
| pet or dock | Rated switch, fuse, power leads, JST style keyed connectors, decoupling | 5 | 5 | HOLD | One rated assembly kit; no high current DuPont wires. Include a rated Schottky diode only in the external 5V feed to XIAO Sense (anode on fused robot boost, cathode on XIAO 5V) so USB flashing cannot backfeed servos. Source reuse: Seeed official XIAO external 5V instructions and MIT cgro00/desk-robot 1N5817 diode plus 470uF local 5V servo bulk. These are reference components, NOT proof this robot's two motor plus two servo supply is adequately sized. Design a local MAX98357A 0.1uF plus 10uF bypass per manufacturer, separately verify diode current and heat, power rail ripple, connector polarity and boost transients. |  |  |
| pet or dock | Normally closed micro bumper switch | 10 | 10 | HOLD | Two NC in series to WROOM GPIO35 with external pullup |  |  |
| pet or dock | Magnetic reed switch | 5 | 4 | HOLD | One owned; optional read-only MCP23017 GPIOB0 active-low reed input on mux 0x71 lane 5. WROOM GPIO36 is reserved exclusively for left terminal IR receiver. |  |  |
| pet or dock | PIR thermal motion sensor | 5 | 4 | HOLD | One owned; optional read-only MCP23017 GPIOB1 active-high PIR input on mux 0x71 lane 5, level verified <=3.3V. WROOM GPIO39 is reserved exclusively for right terminal IR receiver. |  |  |
| pet or dock | BMP280 pressure and temperature module | 5 | 4 | HOLD | One photographed; do not mistake for humidity sensor |  |  |
| pet or dock | SHT41 humidity and temperature module | 5 | 5 | HOLD | Breath reaction with condensation resistant mounting |  |  |
| pet or dock | PN532 I2C NFC reader module with IRQ/reset pins | 5 | 5 | HOLD | Select genuine 3.3V I2C PN532 breakout at 0x24; WROOM already has bounded read-only Seeed-derived SAM and tag polling. Current source polls without controlling reset/IRQ pins through MCP23017. Verify the exact carrier mode straps, startup/reset requirements, I2C readiness and mechanical antenna fit before physical qualification. |  |  |
| pet or dock | MCP23017 16 channel I2C GPIO expander | 5 | 5 | HOLD | Generic MCP23017: https://www.microchip.com/en-us/product/MCP23017 |  |  |
| pet or dock | 3V coin vibration motor | 5 | 4 | HOLD | One photographed; buy further units after count |  |  |
| pet or dock | AO3400 haptic driver with CD74HC123 hardware one-shot, flyback and pulldown | 5 | 5 | HOLD | MCP23017 GPB2 triggers a generic 3.3V HC123 hardware one-shot into a MOSFET motor stage; CAP1188 local petting event, dock-first source gating and OLATB readback are implemented in opt-in esp32_full_haptic_lab and esp32_dc_integrated_lab, NOT production power-qualified. Verify exact timer board, pulse bound, motor current/thermal and fail-off during I2C stall. See docs/hardware/haptic-one-shot-wiring.md. |  |  |
| pet or dock | Two 38 kHz demodulated IR receivers, Vishay TSOP38438 reference, mounted behind separate directional baffles | 10 | 10 | HOLD | One receiver to WROOM GPIO36 and one to GPIO39; 3.3V supply, active LOW, external bias and the correct physical TSOP pin order. Reuse reference Vishay TSOP38438 datasheet and ESP32 RMT receiver source. Receiver chip candidate only, no measured sunlight immunity, range or fit. |  |  |
| pet or dock | Independent powered 38 kHz classic NEC dock beacon controller and programmable board | 5 | 5 | HOLD | One per dock, not a second robot MCU. Source reuse candidate: Arduino-IRremote MIT sendNEC on supported AVR, or design adaptation of Apache-2.0 OOMWOO CH32V003 dock PCB. OOMWOO's 20V 4S power and contact switching CANNOT be reused for this robot's 1S/5V charger. Source-reused Arduino Nano ATmega328P BENCH emitter now exists at code/firmware/dock (Arduino-IRremote 4.7.1). Exact final compact controller, flashing/debug provision, physical carrier and optical/thermal behavior remain unqualified; no production SKU. |  |  |
| pet or dock | Two independently aimed 940 nm 38 kHz infrared LED emitter channels with rated transistor driver and current limiting per dock | 10 | 10 | HOLD | Two aimed LED channels per dock driven simultaneously with the SAME classic NEC frame, because current WROOM DualIrEvidence requires equal code at both receivers. Based on OOMWOO IR BEACON KiCad Apache-2.0 design, but OOMWOO separate left/right codes are NOT compatible unchanged; number of LEDs per channel, driver, resistor and final 5V supply must be dimensioned, no naked LED wired to MCU pin. Protocol and baffle must be measured against WROOM dual receiver RMT NEC decoder, never authorize charging by light. |  |  |
| pet or dock | Keyed charging contacts and alignment switch set | 5 | 5 | HOLD | Matched protected 1S charger INPUT only, never directly to bare cell. Include two independent normally closed seat/position switches and independently sampled charger PGOOD, with protected unpowered recessed contacts until safe charger netlist is reviewed. |  |  |
| pet or dock | Printed docking cradle, printed camera marker and 5V charging input | 5 | 5 | HOLD | Physical autonomous docking unqualified; separately mounted dock per pet |  |  |
| pet or dock | Filament, printed chassis/head/gripper mounts, fasteners, inserts, insulated harness | 5 | 5 | HOLD | Parent assembly includes reported filament, printed chassis/head/gripper, two physical wheel-encoder brackets or qualified integrated mounts, magnet fixtures, optic and camera alignment, each pet's dock fit fixtures, fasteners/inserts/insulated cables and proper rated power connectors. These passive parts are owned here and MUST NOT be charged again as linked encoder purchases. Exact printed mass, actual mount, revision, pack fit and delivered consumables remain unresolved. |  |  |
| shared station | SCD40 real CO2 | 1 | 1 | HOLD | ventilated stationary desk | 3.3 V candidate rail; 205 mA peak max; 18 mA periodic average max; exact fitted current unqualified |  |
| shared station | BME688 VOC gas and ambient | 1 | 1 | HOLD | ventilated stationary desk | 3.3 V candidate rail; 12 mA custom mode max; exact fitted current unqualified |  |
| shared station | LD2410C mmWave presence module | 1 | 1 | HOLD | fixed room pod UART | 5 V candidate rail; 79 mA reference average; supply capacity > 200 mA; exact fitted current unqualified |  |
| shared station | Capacitive soil probe | 1 | 1 | HOLD | external plant accessory | 3.3 V candidate rail; exact fitted current unqualified |  |
| shared station | NFC game tags and magnets | 0 | 0 | OPTIONAL NOT SELECTED, DO NOT BUY | conditional optional shared game props; preserve the game feature but do not add loose tags to the default checkout |  |  |
| shared station | AMG8833 thermal array | 0 | 0 | OPTIONAL NOT SELECTED, DO NOT BUY | conditional optional separate thermal station; not selected for the core first robot or default fleet checkout | 3.3 V candidate rail; 4.5 mA reference typical; exact fitted current unqualified |  |
| shared station | Station controller with timestamped USB serial protocol, reuse owned Feather nRF52840 if feasible | 1 | 0 | HOLD | ventilated stationary USB enclosure; no motor or charge authority; reported-owned Feather nRF52840 is a candidate, not yet an approved controller | 3.3 V regulator 500 mA peak; exact fitted current unqualified |  |
| linked detail (not additive) | N20 100:1 MP 6V motor alternative | 10 if selected | not independently counted | HOLD SUBASSEMBLY DECISION | Linked parent stepper; disposition unresolved; see the canonical 14-row source register before buying | | |
| linked detail (not additive) | DRV8833 dual H bridge alternative | 5 if selected | not independently counted | HOLD SUBASSEMBLY DECISION | Linked parent uln2003; disposition unresolved; see the canonical 14-row source register before buying | | |
| linked detail (not additive) | BQ24075 power path plus BQ27441 gauge alternative | 5 if selected | not independently counted | HOLD SUBASSEMBLY DECISION | Linked parent cap_power; disposition unresolved; see the canonical 14-row source register before buying | | |
| linked detail (not additive) | 5V switching regulator | 5 if selected | not independently counted | HOLD SUBASSEMBLY DECISION | Linked parent cap_power; disposition unresolved; see the canonical 14-row source register before buying | | |
| linked detail (not additive) | Protected 1S pack with connected NTC | 5 if selected | not independently counted | HOLD SUBASSEMBLY DECISION | Linked parent cap_power; disposition unresolved; see the canonical 14-row source register before buying | | |
| linked detail (not additive) | Independent rated 5V dock adapter | 5 if selected | not independently counted | HOLD SUBASSEMBLY DECISION | Linked parent dock_fixture; disposition unresolved; see the canonical 14-row source register before buying | | |
| linked detail (not additive) | Dock IR transmitter transistor and resistor channels | 10 if selected | not independently counted | HOLD SUBASSEMBLY DECISION | Linked parent dock_ir_emitter_channels; disposition unresolved; see the canonical 14-row source register before buying | | |
| linked detail (not additive) | Shared room controller actual board | 1 if selected | not independently counted | HOLD SUBASSEMBLY DECISION | Linked parent room_controller; disposition unresolved; see the canonical 14-row source register before buying | | |
| linked detail (not additive) | Shared station SCD40 | 1 if selected | not independently counted | HOLD SUBASSEMBLY DECISION | Linked parent scd40; disposition unresolved; see the canonical 14-row source register before buying | | |
| linked detail (not additive) | Shared station BME688 | 1 if selected | not independently counted | HOLD SUBASSEMBLY DECISION | Linked parent bme688; disposition unresolved; see the canonical 14-row source register before buying | | |
| linked detail (not additive) | Shared station LD2410C | 1 if selected | not independently counted | HOLD SUBASSEMBLY DECISION | Linked parent ld2410c; disposition unresolved; see the canonical 14-row source register before buying | | |
| linked detail (not additive) | Shared station AMG8833 | 1 if selected | not independently counted | HOLD SUBASSEMBLY DECISION | Linked parent amg8833; disposition deferred_optional; see the canonical 14-row source register before buying | | |
| linked detail (not additive) | Shared station soil probe | 1 if selected | not independently counted | HOLD SUBASSEMBLY DECISION | Linked parent soil_probe; disposition unresolved; see the canonical 14-row source register before buying | | |
| linked detail (not additive) | Shared NFC toy tokens | 10 if selected | not independently counted | HOLD SUBASSEMBLY DECISION | Linked parent nfc_game_props; disposition deferred_optional; see the canonical 14-row source register before buying | | |

A zero remaining quantity can mean a component is estimated owned or ordered, NOT physically counted, delivered or qualified. Recount the estimated ten MG90S and five MAX30102 and verify arrival of the one ordered XIAO Sense before buying duplicates.

Existing 28BYJ48 and ULN2003 totals belong to the STEP motor variant. The new guarded DC firmware does not mean that N20 motors have been selected, fitted or load tested. Do not buy the missing steppers or new N20 motors before that decision.

Protected single-cell charging, contact isolation, IR baffles, station USB readings, and commercially reusable fitted CAD remain unqualified. Do not energize any lithium charging circuit based on this design ledger.
