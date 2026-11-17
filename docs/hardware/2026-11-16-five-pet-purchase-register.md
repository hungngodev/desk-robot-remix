# Five pet complete procurement register

Source reconciliation: 2026-11-16. This is the canonical SINGLE full-fleet purchase candidate plan for PR #17, not an approved release of lithium contacts, drivetrain or unprinted geometry.

Fleet means **five fully featured robots and five independent docks** plus **one shared room station**. Adafruit hardware purchases are not required. Open source Adafruit library code reused by the existing owned Feather is fine.

**Order policy:** No blind irreversible fivefold hardware order. Use *Pilot quantity* to acquire a single sample system, validate all 3D fits, loads, contacts, chargers, native audio, and then buy the remaining identical copies. `Owned minimum` counts only reported minimum, while `Estimate` is subject to recount. New XIAO one ordered unreceived. Do not buy the missing five 28BYJ48 or ULN2003 motors while testing N20 guarded DC.

**Engineering source:** `docs/hardware/full-feature-plan.json`, `docs/hardware/fleet-inventory.json`, `code/firmware/body/platformio.ini` including `esp32_dc_full`, `code/firmware/dock`, `code/firmware/room_station`, `code/scripts/power_preflight.py`. The original 42 roles remain untouched in their source JSON; power and N20 replacement appear as components of the previously abstract system.

## Five identical pet and dock core roles

| Role | Part and current seller candidate | Per pet | Five needed | Reported owned | Estimated owned | Ordered | Fleet gap if estimate confirmed | Pilot | Quote each | Purchase gate |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `xiao_sense` | XIAO ESP32S3 Sense camera + microphone; [Seeed XIAO ESP32S3 Sense](https://www.seeedstudio.com/XIAO-ESP32S3-Sense-p-5639.html) | 1 | 5 | 0 | 0 | 1 | 4 | 0 | $18.90 | ORDERED 1 |
| `wroom` | ESP32 WROOM32 development board; [Espressif DevKitC 32E](https://docs.espressif.com/projects/esp-dev-kits/en/latest/esp32/esp32-devkitc/user_guide.html) | 1 | 5 | 1 | 0 | 0 | 4 | 0 | Unquoted | BOARD REV |
| `oled` | SSD1306 0.96 inch OLED; [Waveshare OLED A #9085](https://www.waveshare.com/0.96inch-oled-a.htm) | 1 | 5 | 1 | 0 | 0 | 4 | 1 | $7.99 | MODULE CHECK |
| `stepper` | 28BYJ48 5V stepper motor; NOT SELECTED Module/carrier selection required | 2 | 10 | 5 | 0 | 0 | 0 | 0 | Unquoted | LEGACY |
| `uln2003` | ULN2003 driver for 28BYJ48; NOT SELECTED Module/carrier selection required | 2 | 10 | 5 | 0 | 0 | 0 | 0 | Unquoted | LEGACY |
| `mg90s` | MG90S positional servo; NOT SELECTED Module/carrier selection required | 2 | 10 | 0 | 10 | 0 | 0 | 0 | Unquoted | SOURCE / FIT |
| `imu` | MPU6050 GY521 compatible six axis breakout; [Keyestudio KS0170 GY521 MPU6050](https://www.keyestudio.com/products/keyestudio-gy-521-mpu6050-3-axis-gyroscope-and-accelerometer-module-for-arduino) | 1 | 5 | 1 | 0 | 0 | 4 | 1 | $9.00 | PILOT I2C |
| `head_touch` | AT42QT1010 momentary capacitive head touch; [SparkFun SEN 12041 AT42QT1010](https://www.sparkfun.com/sparkfun-capacitive-touch-breakout-at42qt1010.html) | 1 | 5 | 1 | 0 | 0 | 4 | 1 | $3.95 | SOURCE MATCH |
| `max30102` | MAX30102 optical heartbeat paw pad breakout; NOT SELECTED Module/carrier selection required | 1 | 5 | 0 | 5 | 0 | 0 | 0 | Unquoted | SOURCE / FIT |
| `cliff_obstacle` | VL53L4CD time of flight carrier; [Pololu #3692](https://www.pololu.com/product/3692/specs) | 8 | 40 | 0 | 0 | 0 | 40 | 8 | $11.81 | PILOT FIT |
| `i2c_mux` | TCA9548A 8 channel 3.3V compatible I2C multiplexer; [SparkFun BOB 16784](https://www.sparkfun.com/sparkfun-qwiic-mux-breakout-8-channel-tca9548a.html) | 2 | 10 | 0 | 0 | 0 | 10 | 2 | $6.60 | PILOT FIT |
| `amp` | MAX98357A I2S mono amplifier; [SparkFun DEV 14809](https://www.sparkfun.com/sparkfun-i2s-audio-breakout-max98357a.html) | 1 | 5 | 0 | 0 | 0 | 5 | 1 | $7.50 | PIN CHECK |
| `speaker` | 8 ohm 1 watt approximately 20 mm speaker; [SparkFun COM 26553](https://www.sparkfun.com/mini-speaker-1w-8-ohm.html) | 1 | 5 | 0 | 0 | 0 | 5 | 1 | $1.25 | FIT |
| `cap1188` | CAP1188 8 zone capacitive touch breakout; [PMD Way 314070](https://pmdway.com/products/cap1188-i2c-spi-8-key-capacitive-touch-sensor-breakout-board) | 1 | 5 | 0 | 0 | 0 | 5 | 1 | $20.55 | 0x28 STRAP |
| `touch_electrodes` | Copper tape touch electrode and insulating backing set; NOT SELECTED Module/carrier selection required | 1 | 5 | 0 | 0 | 0 | 5 | 1 | Unquoted | SOURCE / FIT |
| `apds9960` | APDS9960 gesture proximity color light module; [Soldered APDS9960 module](https://www.mouser.com/c/?q=APDS9960) | 1 | 5 | 0 | 0 | 0 | 5 | 1 | Unquoted | CARRIER |
| `fsr` | FSR402 type force sensing resistor; [SparkFun SEN 09375](https://www.sparkfun.com/force-sensitive-resistor-0-5.html) | 2 | 10 | 0 | 0 | 0 | 10 | 2 | $10.95 | FIT |
| `ads1115` | ADS1115 4 channel ADC breakout; [Whadda WPI453](https://www.jameco.com/z/WPI453-Velleman-Velleman-4-Channel-ADS1115-16-Bit-ADC-I2C-Module-by-Whadda_2354647.html) | 1 | 5 | 0 | 0 | 0 | 5 | 1 | $17.95 | FIT |
| `rgb` | Single diffused WS2812B RGB pixel; [SparkFun BOB 13282](https://www.sparkfun.com/sparkfun-rgb-led-breakout-ws2812b.html) | 1 | 5 | 0 | 0 | 0 | 5 | 1 | $1.50 | PILOT FIT |
| `logic_level` | 74AHCT1G125 3.3V to 5V RGB buffer; [TI SN74AHCT1G125](https://www.ti.com/product/SN74AHCT1G125) | 1 | 5 | 0 | 0 | 0 | 5 | 1 | Unquoted | CARRIER |
| `as5600` | AS5600 magnetic rotary angle breakout; [Seeed 101020692](https://www.seeedstudio.com/Grove-12-bit-Magnetic-Rotary-Position-Sensor-AS5600-p-4192.html) | 3 | 15 | 0 | 0 | 0 | 15 | 3 | $6.50 | SHAFT FIT |
| `encoder_magnets` | Diametric AS5600 compatible magnets; NOT SELECTED Module/carrier selection required | 3 | 15 | 0 | 0 | 0 | 15 | 3 | Unquoted | SOURCE / FIT |
| `ina226` | INA226 current voltage monitor with rated external shunt; NOT SELECTED Module/carrier selection required | 1 | 5 | 0 | 0 | 0 | 5 | 1 | Unquoted | SOURCE / FIT |
| `max17048` | MAX17048 single cell fuel gauge; [SparkFun SPX 17715](https://www.sparkfun.com/qwiic-fuel-gauge-max17048.html) | 1 | 5 | 0 | 0 | 0 | 5 | 1 | $5.95 | STOCK / REDUNDANCY |
| `cap_power` | Matched protected rechargeable 1S power assembly with charge and load sharing; NOT SELECTED Module/carrier selection required | 1 | 5 | 0 | 0 | 0 | 0 | 0 | Unquoted | SOURCE / FIT |
| `sensor_3v3` | Dedicated regulated 3.3V expansion sensor supply; [Pololu #2873](https://www.pololu.com/product/2873) | 1 | 5 | 0 | 0 | 0 | 5 | 1 | $5.47 | POWER PILOT |
| `switch_power` | Rated switch, fuse, power leads, JST style keyed connectors, decoupling; NOT SELECTED Module/carrier selection required | 1 | 5 | 0 | 0 | 0 | 5 | 1 | Unquoted | SOURCE / FIT |
| `bumper` | Normally closed micro bumper switch; NOT SELECTED Module/carrier selection required | 2 | 10 | 0 | 0 | 0 | 10 | 2 | Unquoted | SOURCE / FIT |
| `reed` | Magnetic reed switch; [Seeed Grove Magnetic Switch 101020038](https://www.seeedstudio.com/Grove-Magnetic-Switch.html) | 1 | 5 | 1 | 0 | 0 | 4 | 1 | $3.20 | PILOT GPIO |
| `pir` | PIR thermal motion sensor; [Seeed Grove Adjustable PIR 101020617](https://www.seeedstudio.com/Grove-Adjustable-PIR-Motion-Sensor.html) | 1 | 5 | 1 | 0 | 0 | 4 | 1 | $7.00 | PILOT FIT |
| `bmp280` | BMP280 pressure and temperature module; [Seeed Grove BMP280 101020192](https://www.seeedstudio.com/Grove-Barometer-Sensor-BMP280.html) | 1 | 5 | 1 | 0 | 0 | 4 | 1 | $9.80 | PILOT FIT |
| `sht41` | SHT41 humidity and temperature module; [7Semi SHT41 ES 13515](https://7semi.com/7semi-sht41-temperature-humidity-sensor-breakout-i2c-qwiic-sht41-breakout/) | 1 | 5 | 0 | 0 | 0 | 5 | 1 | $7.40 | OUT OF STOCK |
| `pn532` | PN532 I2C NFC reader module with IRQ/reset pins; [Seeed 113020006](https://www.seeedstudio.com/Grove-NFC.html) | 1 | 5 | 0 | 0 | 0 | 5 | 1 | $17.50 | I2C MODE |
| `mcp23017` | MCP23017 16 channel I2C GPIO expander; [Waveshare 15391](https://www.waveshare.com/mcp23017-io-expansion-board.htm) | 1 | 5 | 0 | 0 | 0 | 5 | 1 | $5.99 | 38x23 FIT |
| `haptic_motor` | 3V coin vibration motor; [SparkFun ROB 08449 3V](https://www.sparkfun.com/vibration-motor.html) | 1 | 5 | 1 | 0 | 0 | 4 | 1 | $2.95 | PILOT POWER |
| `haptic_driver` | AO3400 class logic MOSFET, flyback diode and pulldown; NOT SELECTED Module/carrier selection required | 1 | 5 | 0 | 0 | 0 | 5 | 1 | Unquoted | SOURCE / FIT |
| `dock_ir_receivers` | Two 38 kHz demodulated IR receivers, Vishay TSOP38438 reference, mounted behind separate directional baffles; [Vishay TSOP38438](https://www.mouser.com/c/?q=TSOP38438) | 2 | 10 | 0 | 0 | 0 | 10 | 2 | $0.79 | PILOT OPTICS |
| `dock_ir_beacon_controller` | Independent powered 38 kHz classic NEC dock beacon controller and programmable board; [Seeed Seeeduino Nano 102010268](https://www.seeedstudio.com/Seeeduino-Nano-p-4111.html) | 1 | 5 | 0 | 0 | 0 | 5 | 1 | $8.99 | BENCH FIRMWARE |
| `dock_ir_emitter_channels` | Two independently aimed 940 nm 38 kHz infrared LED emitter channels with rated transistor driver and current limiting per dock; [Vishay TSAL6200](https://www.digikey.com/en/products/detail/vishay-semiconductor-opto-division/TSAL6200/1681339) | 2 | 10 | 0 | 0 | 0 | 10 | 2 | $0.35 | PILOT OPTICS |
| `dock_contacts` | Keyed charging contacts and alignment switch set; NOT SELECTED Module/carrier selection required | 1 | 5 | 0 | 0 | 0 | 5 | 1 | Unquoted | SOURCE / FIT |
| `dock_fixture` | Printed docking cradle, printed camera marker and 5V charging input; NOT SELECTED Module/carrier selection required | 1 | 5 | 0 | 0 | 0 | 5 | 1 | Unquoted | SOURCE / FIT |
| `assembly` | Filament, printed chassis/head/gripper mounts, fasteners, inserts, insulated harness; NOT SELECTED Module/carrier selection required | 1 | 5 | 0 | 0 | 0 | 5 | 1 | Unquoted | SOURCE / FIT |

## Explicit drivetrain, 1S power path and one shared station add-ons

These extra purchase rows realize abstract BOM assemblies; do not count them as a duplicate second robot or charger.

| Item | Candidate source | Count per pet or station | Five pets or single station | Quote each | Pilot | Qualification note |
|---|---|---:|---:|---:|---:|---|
| N20 100:1 MP 6V motors | [Pololu #2367](https://www.pololu.com/product/2367/specs) | 2 | 10 | $22.03 | 2 | Two per pet, 10 fleet; source motor driver option, tracks still to fit |
| DRV8833 dual H bridge | [Pololu #2130](https://www.pololu.com/product/2130) | 1 | 5 | $10.07 | 1 | One per pet, 5 fleet; user reported spare uncounted |
| BQ24075 battery power path and BQ27441 gauge | [SparkFun PRT 13777](https://www.sparkfun.com/sparkfun-battery-babysitter-lipo-battery-manager.html) | 1 | 5 | $23.95 | 1 | One per pet, bench verify net charge and thermistor |
| 5V switching regulator | [Pololu #4082 S13V30F5](https://www.pololu.com/product/4082) | 1 | 5 | $16.51 | 1 | One per pet, low cell current/thermal test |
| Protected NTC 1S battery pack | UNSELECTED pack SKU needed | 1 | 5 | Unquoted | 0 | Five eventual, order only once fit and load measured |
| Independent 5V dock adapter | [Mean Well GST18A05 P1J](https://www.meanwell.com/Upload/PDF/GST18A/GST18A-SPEC.PDF) | 1 | 5 | Unquoted | 1 | 5 eventual adapters; connector and protective circuit unselected |
| Dock IR LED transistor/resistor driver channel | UNSELECTED driver PCB needed | 2 | 10 | Unquoted | 2 | 2 per dock, 10 total; current and switching validated on pilot |
| Shared room controller | OWNED Feather nRF52840 | 1 | 1 | Unquoted | 0 | Exactly one shared station not five |
| True room CO2 sensor | [7Semi SCD40 ES 12129](https://7semi.com/7semi-scd40-co2-temperature-and-humidity-sensor-breakout-i2c-qwiic/) | 1 | 1 | $33.00 | 1 | Exactly one shared station |
| Room gas/environment sensor | [Pimoroni BME688](https://shop.pimoroni.com/products/bme688-breakout) | 1 | 1 | Unquoted | 1 | Exactly one station, raw gas not VOC ppm |
| Room presence radar | [Hi Link LD2410C](https://github.com/ncmreynolds/ld2410) | 1 | 1 | Unquoted | 1 | Exactly one station, 256000 baud UART carrier |
| Room thermal 8x8 array | [SparkFun SEN 14607](https://www.sparkfun.com/sparkfun-grid-eye-infrared-array-breakout-amg8833-qwiic.html) | 1 | 1 | $49.95 | 1 | Exactly one station, no identity classification |
| Optional capacitive soil probe | UNSELECTED 3.3V ADC variant | 1 | 1 | Unquoted | 0 | Shared station optional and disabled in firmware |
| Optional NFC toy stickers | Generic NTAG213 | 10 | 10 | Unquoted | 0 | 10 game tokens optional, not access control |

\nVendor gate notes: Seeeduino Nano is ATmega328P compatible but its dock image still needs actual PlatformIO compilation and flashing. The Seeed adjustable PIR reports active HIGH and thus matches the MCP23017 GPIOB1 firmware, unlike the SparkFun JST PIR active LOW. MPU6050 module I2C signal pullups must be checked against 3.3V before connecting WROOM.\n\n## Verified protected pack candidate and critical charging thermistor mismatch

* [LiPol Battery Co. LPHD7430085](https://lipo-battery.com/high-rate-discharge-lipo-battery-lphd7430085-5a-3-7v-2000mah-7-4wh/) is a SPECIFIC candidate with 1S 3.7V 2000mAh, protection PCM, 10k NTC, listed 5A max discharge, 7.4 x 30 x 86 mm housing and **three-pin Molex 43645-0300**. This is NOT a purchasing approval because the printed chassis and battery cavity have no measured size, current or connector proof.
* **Actual mechanical mismatch:** the current unqualified `docs/cad/remixes/remaining_fit_gauges.scad` sets `power_l = 68` mm, while the proposed LPHD7430085 protected pack itself is **86 mm long** before wires and strain relief. That default fit gauge cannot accommodate this specific pack. The cavity, retention and clearance must be redesigned and printed before any five-pack order. Neither the gauge nor the pack is a released final geometry.
* SparkFun [PRT-13777 Battery Babysitter](https://www.sparkfun.com/sparkfun-battery-babysitter-lipo-battery-manager.html) has a 2-pin LiPo connection and a published BQ24075 schematic which ties TS to a 10k bypass and gauge BIN. Its default design **must NOT be assumed to monitor the LPHD7430085 third-wire thermistor**. Source: [SparkFun schematic](https://github.com/sparkfun/Battery_Babysitter) and [TS discussion](https://community.sparkfun.com/t/battery-babysitter-unknow-connection-bq24075s-ts-pin-to-bq27441s-bin/40099). A qualified PCB level TS circuit, independent thermal protection and a properly keyed harness need design review before the battery and charger can become a full fleet order.
* TI BQ24075 OUT is battery-domain system load, NOT a fixed 5V motor rail. Pololu #4082 maximum continuous 5V output depends on low-cell input voltage and actual thermal load. A printed mock-up and bench adapter can precede safely connected battery trials.

## Stop conditions before bulk purchase

1. Count all existing MG90S and MAX30102 units and inspect incoming XIAO Sense. Avoid duplicates.
2. Choose a track/sprocket chassis and qualified noncommercial-only license with measured mounting for 2 N20 motors, 8 TOF carriers, FSR gripper, speaker and battery. A TT-motor 3D model is not a drop-in N20 model.
3. Compile `esp32_dc_full` on a real ESP32 and perform loaded motion, 1 cm/edge drop cliff, stop/reverse, receiver, I2C and watchdog timing. Existing Actions jobs have failed before test steps; a committed test is not a passed build.
4. Select one **real protected 1S cell with correct PCM, NTC, connector polarity and capacity** after measuring peak current. BQ24075 power OUT is not regulated 5V. The Pololu boost's claimed 3A depends on battery/input voltage and thermal conditions. Verify simultaneous system idle plus measured *signed battery* charging current, overcurrent, full charge and disconnection.
5. Build one truly recessed/current limited dock contact PCB; independently verify two NC seated switches, PGOOD, input polarity and no energized exposed contacts.
6. Validate one complete XIAO mic/camera/Speaker/WiFi/OLED full load, local barge-in/AEC, grip load and all five fleet behavior before production.

**Honest purchasing status:** 56 physical and assembly roles accounted for with active motor/power substitutions. Exact pack, carrier revisions and printed fixture sizes still missing, so full fleet release is NOT confirmed. Vendor price snippets are time-sensitive and quotes exclude tax, shipping and stock validation. A vendor page link gives exact listing photos where available, not proof that the delivered carrier matches.

Supersedes scattered partial one-robot shopping proposals as the intended five-pet candidate comparison. Must not mark `complete` or merge PR #17 without device measurements.
