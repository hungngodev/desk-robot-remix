# Buy this for the full five desk pets

## Irreversible-purchase engineering release gate: November 16, 2026

**CURRENT DECISION: NO FULL-FLEET PURCHASE AUTHORIZED.** All quantities below represent five fully equipped *design slots*, not validated final checkout items. A popular generic chip is not a guaranteed compatible carrier, and code compilation is not physically proven functionality. Do not transform a generic name into a merchant order without PCB revision, regulator, pinout, 3.3 V pullup, supply limit, fit, schematic and test evidence. A single borrowed/returnable sample can be used for qualification; the current user-owned hardware must be evaluated first.

**Independent checked manufacturer sources, with actionable decisions:**

1. **28BYJ48 + ULN2003 locomotion is NOT frozen.** `code/firmware/body/lib/StepperDrive/StepperDrive.h` sets `kStepperPercentLimit=40`, `kStepperFullScaleHalfStepsPerSecond=400` and `StepperDrive.cpp` drives **half steps**, so the source ceiling is **160 half steps/s**. A typical 28BYJ48 has **4096 half steps per output revolution**; theoretical source-commanded shaft speed = `160*60/4096 = 2.34375 RPM`, **before any load, slip or scheduling losses**. With an explicitly hypothetical 40 mm drive wheel, straight motion would be only `pi*0.04*2.34375/60 = 0.00491 m/s`. User wants genuine roaming; no achieved loaded speed, incline, stall, thermal or target speed is measured. **DO NOT buy the five additional steppers or ULN2003 boards yet.** Compare owned 28BYJ pair against a documented brushed N20 gearmotor plus already-owned DRV8833 (not a pin/firmware drop-in; check continuous/stall current and mechanical source). Datasheet/reference: https://docs.circuit.rocks/motors/28byj-48/ and https://www.pololu.com/product/2130 .
2. **5V boost part ratings are easy to misread.** Pololu U3V50F5 #2565 maximum 5A is a rated **INPUT** current (not guaranteed 5A output); output is thermal and input-voltage dependent. TI BQ24074 has a 1.5A programmed input limit and nominal 4.4V OUT, not a 5V motor regulator. No protected pack, power path, dock adapter, boost, fuse or charging contact circuit is approved. Use actual `code/scripts/power_preflight.py` only after simultaneous 5V peak/average loads and low-cell boost efficiency are measured. Sources https://www.pololu.com/product/2565/specs and https://www.ti.com/product/BQ24074 .
3. **VL53L4CD #3692 carrier is source-compatible with `esp32_full`, not optically qualified as 40 final safety sensors.** Pololu exposes 10k pullups from SDA/SCL to **VIN** (manufacturer connections: https://www.pololu.com/product/3692 ). For a WROOM at 3.3V, feed this exact carrier VIN from the qualified **3.3V** bus, NEVER the actuator 5V rail. 8 carrier PCBs per robot measure 0.5 x 0.7 inches each before connectors and optical clearance. Supply current ~25mA active typical/40mA peak per unit; for eight, ~200mA typical/320mA peak at 3.3V before other sensors. Compare physical actual cliff braking, black/gloss target, cable fit and sensor interference. Cheap VL53L0X is a separate isolated firmware experiment, not a source-compatible substitute. 40 sensors at $11.81 quantity tier = $472.40 before other hardware.
4. **SparkFun TCA9548A BOB-16784 electrical source is documented**: https://www.sparkfun.com/sparkfun-qwiic-mux-breakout-8-channel-tca9548a.html and https://github.com/sparkfun/Qwiic_Mux_TCA9548A . Strap A0 for second mux 0x71, keep 3.3V main/downstream, inspect fixed pullups. Physical Qwiic connectors do NOT mate directly with Pololu 0.1 inch through-hole ToF pins: budget/qualify the actual Qwiic breakout cable or soldered 4-wire connector to EACH carrier; board/enclosure fit not verified.
5. **XIAO Sense J3 GPIO collision remains an irreversible physical wiring gate.** The microSD expansion links use GPIO7/8/9 by default, while the existing Sense config uses 7/8 for I2S and 9 for optional RGB. Confirm shipped PCB revision and disconnect/isolate J3 before powering speaker wiring; Seeed https://wiki.seeedstudio.com/xiao_esp32s3_sense_filesystem/ .
6. **CAP1188 module address must be 0x28**; Microchip's ADDR_COMM **VDD** strap selects 0x28, common fixed resistor carriers may ship 0x29. No named non-Adafruit carrier with measured strap, 3.3V pullups and shell fit is approved. PN532 I2C carrier, mux clock stretching, NFC wake and physical antenna are also unqualified: do not buy all five on a generic product title. Microchip: https://ww1.microchip.com/downloads/en/DeviceDoc/00001620C.pdf ; PN532 reference https://github.com/Seeed-Studio/PN532 .
7. **The full mechanical chassis is not fitted/licensed for commercial batch production.** Original SMARS chassis and forklift ancestors have CC BY-NC-SA licensing. Do not order production fixtures or five mechanics kits until resolved and measured.
8. **No integrated full-robot acceptance record.** Real WROOM `esp32_full` and pinned Xiaozhi Sense builds, authenticated five-head audiovisual interruption, live local stop, servo grasp, printed fit, independent IR terminal approach, signed battery recharge current and room pod data pipeline are not fully verified. The latest hosted GitHub Actions jobs have failed without test steps. A source-level mocked test cannot certify the finished hardware.

**Order release requires** a frozen exact SKU/PCB revision per required row; valid upstream license and compatible firmware; electrical input, I2C and 5V current budgets; dimensionally fitted printable enclosure; real bench loaded motor/cliff/voice/charging/IR/grasp measurements; and full-source build/tests on the exact release commit. If any are absent, procurement remains **BLOCKED**. This gate is required precisely because components cannot be changed or returned once purchased.


## Canonical five-robot order ledger (November 16 2026)

**Scope: five identical full-feature tracked pets, five docks, and one shared room/game pod.** This is a COMPLETE QUANTITY LEDGER, not a certification to purchase five copies. Stock counts are user reported, not physically counted. A HOLD item is a required role whose exact electrical or fitted module is still unqualified. Never infer physical acceptance from firmware or a vendor datasheet. **This ledger supersedes conflicting older staged wording below while retaining historical evidence.** No new Adafruit branded boards are requested; already-owned hardware may be reused.

### List 1: user-reported owned or ordered

| Item | Count reported | Important qualification |
| --- | ---: | --- |
| ESP32 WROOM32 | 1 or more | Devboard revision and fit uncounted |
| Seeed XIAO ESP32S3 Sense camera/mic | 1 ordered minimum | Arrival and PCB/J3 revision unconfirmed |
| SSD1306 0.96 inch OLED | 1 or more | Verify display controller, I2C and size |
| 28BYJ48 5V stepper + ULN2003 driver | 5 of each | Need 10 of each for five pets |
| MG90S positional servos | around 10 | Potentially enough, recount and loaded-test |
| MPU6050 and AT42QT1010 | at least 1 each | At least one head touch photographed |
| MAX30102 paw optical | around 5 CLAIMED | Recount before buying; not photo confirmed |
| BMP280, PIR, reed switch, 3V coin motor | at least 1 each | Reported/photo, physical condition unknown |
| Feather nRF52840 | 1 | Candidate USB shared room station controller |
| Jumper ribbons, filament, USB power bank | several / uncounted | Signal-only DuPont; bank power rating not proved |
| BerryIMU, GY61, DRV8833, PAM8403, MAX9814, spare camera/IR, USB-C breakout, continuous servo | various spares | Do not buy duplicates or substitute analog amp for I2S |

### List 2: everything still needed for the ENTIRE project

"Buy" is the remaining target for five complete robots after the minimum reported stock. Physical stock may reduce this further. "Conditional" denotes reported quantities or speculative fitted variant. "HOLD" denotes no specific safe final SKU before a real bench or mechanical qualification.

| Group | Required part or module | Total installed | Buy remaining | Status or exact reference |
| --- | --- | ---: | ---: | --- |
| Compute | XIAO ESP32S3 Sense camera/mic complete kit | 5 | 4 if one ordered | Seeed Sense PCB / J3 GPIO isolation test |
| Compute | ESP32 WROOM32 development board | 5 | 4 | Match footprint and known pinout |
| Compute | SSD1306 0.96 inch I2C OLED | 5 | 4 | 3.3 V head bus |
| Motion | 28BYJ48 5V stepper | 10 | 5 | HOLD full loaded torque/heat trial before bulk |
| Motion | Matching ULN2003 phase driver | 10 | 5 | Only with 5V 28BYJ48; not DRV8833 |
| Motion | MG90S positional servo | 10 | 0 if ten owned | Recount; buy missing only |
| Sensing | MPU6050 GY521 six-axis module | 5 | 4 | Check source ID 0x68 and 3.3 V carrier |
| Sensing | AT42QT1010 head touch | 5 | 4 | Direct physical STOP pad |
| Sensing | MAX30102 optical paw sensor | 5 | 0–5 | Recount claimed five, 3.3 V breakout |
| Navigation | VL53L4CD short-range ToF carrier | 40 | 40 | Pololu #3692 source-compatible; HOLD 39 pending actual optical fit/budget; other chip requires driver |
| Bus | TCA9548A eight-channel I2C mux | 10 | 10 | SparkFun BOB-16784 reference; 0x70/0x71 and 3.3 V pullups |
| Audio | MAX98357A I2S mono amplifier | 5 | 5 | SparkFun DEV-14809 reference; XIAO GPIO4/7/8 and SD J3 isolation |
| Audio | 20mm 8ohm 1W speaker | 5 | 5 | SparkFun COM-26553 reference; output gain MUST be limited |
| Touch | CAP1188 eight-electrode 3.3V I2C breakout | 5 | 5 | HOLD exact non-Adafruit carrier with physical 0x28 address strap |
| Touch | Copper tape electrodes and insulation | 40 electrodes | 1 sufficient roll/kit | Size electrode patches to shells |
| Interaction | APDS9960 gesture/proximity/color sensor | 5 | 5 | Chip matching firmware 0x39; exact breakout 3.3V pending |
| Interaction | FSR402 equivalent force resistors | 10 | 10 | 2 per pet; physical jaw/belly calibration |
| Interaction | ADS1115 four-channel ADC | 5 | 5 | 3.3V / 0x48 compatible |
| Interaction | AS5600 magnetic rotation modules | 15 | 15 | 3 per pet; mechanical fit pending |
| Interaction | Matching DIAMETRIC magnets | 15 | 15 | HOLD magnet diameter and air gap |
| Interaction | PN532 13.56MHz NFC I2C reader | 5 | 5 | HOLD exact 3.3V logic and I2C wake/stretch; NOT RC522 |
| Interaction | SHT41 temp/humidity breakout | 5 | 5 | CRC source exists, not an AHT10 replacement |
| Interaction | BMP280 pressure/temp breakout | 5 | 4 | Reuse one owned |
| Interaction | Optional PIR sensor at 3.3V output | 5 | 4 | Input only MCP23017 GPIOB |
| Interaction | Optional reed switch | 5 | 4 | Consider one owned 3144 hall only after test |
| Interaction | 3V coin vibration motor | 5 | 4 | One reported owned, output not integrated |
| Interaction | AO3400 MOSFET, flyback diode, pulldown | 5 circuits | 5 circuits | HOLD approved GPIO output and circuit |
| Lighting | WS2812B diffused RGB pixel | 5 | 5 | HOLD XIAO J3 isolation and source enable |
| Lighting | 74AHCT1G125 3.3V/5V data buffer | 5 | 5 | Verify package and 5V supply |
| Safety | Normally closed chassis bump switches | 10 | 10 | 2 per robot, external pullup GPIO35 |
| Safety | MCP23017 I2C GPIO expander | 5 | 5 | Waveshare SKU15391 3.3V compatible 0x20 reference; fitted size TBD |
| Power | 1S protected rechargeable pack | 5 | 5 | HOLD chemistry, capacity, protection, max discharge, shape |
| Power | 1S charger with real load-sharing power path | 5 | 5 | HOLD exact validated module (BQ24074/MCP73871 alone not 5V) |
| Power | 5V regulated boost converter, measured sustained and peak rating | 5 | 5 | HOLD measured simultaneous motor+servo+WiFi+speaker load |
| Power | Dedicated 3.3V sensor regulator | 5 | 5 | HOLD measured I2C and sensor load |
| Power | INA226 current monitor and calibrated shunt | 5 of each | 5 of each | HOLD actual shunt value/trace ampacity |
| Power | MAX17048 single-cell fuel gauge | 5 | 5 | Match selected protected pack |
| Power | Charger NTC temperature probe | 5 | 0–5 | Only if not integrated in packs |
| Power | Switch and correctly rated fuse/holder | 5 sets | 5 sets | HOLD final current/fuse spec |
| Power | Proper power wire, keyed JST connectors, capacitors, resistors | 5 sets | 5 sets | No high-current Dupont wiring |
| Power | One-way USB/external 5V isolation components | 5 sets | 5 sets | HOLD actual XIAO revision and power design |
| Dock | Recessed keyed spring pogo charging contact pairs | 5 mated sets | 5 sets | HOLD charger protection; no live bare battery pads |
| Dock | Independent normally-closed seat switches | 10 | 10 | 2 per dock, MCP23017 GPIOA |
| Dock | 38kHz demodulated receiver | 10 | 10 | 2 per robot, actual optical proof pending |
| Dock | Encoded 940nm IR emitter + transistor driver and resistors | 5 sets | 5 sets + LED spares | HOLD encoder circuit, geometry and interference |
| Dock | Current-limited independent contact safety circuit | 5 | 5 | HOLD circuit schematic + reverse polarity |
| Dock | Rated 5V dock adapter with cable/connector | 5 | 5 | HOLD charger/input current and headroom |
| Dock | Printed docking cradle, alignment, AprilTag marker, shrouds | 5 sets | PRINT 5 | Fit and physical autonomous dock trial pending |
| Mechanics | Printed tracked chassis, tracks, wheels, lift, gripper, head, mounts | 5 complete sets | PRINT 5 | HOLD physical fit and commercial license clearance |
| Mechanics | Shafts, springs, gears, bushings/bearings, rubber feet | 5 fitted sets | 5 sets | HOLD final printed dimensions |
| Assembly | M2/M3 screws/nuts/inserts, headers, perfboard, heat shrink | 1 shared assorted bulk supply | Buy as needed | Existing filament/reusable tools first |
| Room station | SCD40 genuine NDIR CO2 sensor | 1 | 1 | Station firmware/Mac link not completed |
| Room station | BME688 VOC/environment sensor | 1 | 1 | Station firmware/Mac link not completed |
| Room station | LD2410C UART mmWave presence module | 1 | 1 | Station firmware/Mac link not completed |
| Room station | Capacitive soil moisture probe | 1 | 1 optional | Plant accessory |
| Room station | AMG8833 8×8 thermal sensor | 1 | 1 optional | Thermal gameplay, not core camera |
| Room station | NTAG213 NFC tokens, safe magnets and removable game props | 1 assorted set | 1 set | Toy/pet ID must be separate from access permissions |
| Room station | USB station controller | 1 | 0 if Feather usable, else 1 ESP32C3 | Validate firmware and pin allocation |
| Room station | Ventilated printed case, USB cable and wiring | 1 set | 1 set | PRINT shell; USB power & serial validation |
| Shared bench | Current-limited 5V/variable bench PSU, DMM, logic analyzer, calipers, solder/crimp tools | 1 shared station | Buy only if makerspace lacks | Required for qualification, not each robot |

**Actual buying order:** first confirm user-owned quantities and source-compatible sample electronics; bench-test one complete robot on a protected current-limited supply, qualify 1S pack plus charger/boost/dock contacts and final print geometry, then buy the remaining matched fleet copies. This ordering avoids paying for 39 sensors, four power systems and unlicensed bodies that may need replacement.

**Not an approved production bulk PO:** no actual loaded stop trial, five-head voice proof, calibrated grasp, powered recharge, fitted CAD, or clean current-commit CI is recorded. Avoid blanket safety/compatibility guarantees. Published Pololu #3692 price tier for 25+ is $11.81 each, hence 40 reference sensors alone cost $472.40 before any other part. Exact prices are not committed checkout quotes.


**Selected full robot, not a reduced starter.** Generic modules only. User reported stock is not a physical recount. Every row is a real selected role or a clearly separate room accessory. All quantity totals come from [the electrical allocation](full-feature-plan.json). Exact power module and enclosure measurements still require real hardware.

## Already have or ordered

| Part | Previously reported |
| --- | --- |
| ESP32 WROOM32 | At least 1 |
| XIAO ESP32S3 Sense, camera and microphone | At least 1 ordered |
| SSD1306 0.96 inch OLED | At least 1 |
| 28BYJ48 5V stepper | 5 |
| ULN2003 stepper driver | 5 |
| MG90S positional servo | About 10, uncounted |
| MPU6050 breakout | At least 1 |
| AT42QT1010 head touch pad | At least 1 photographed |
| BerryIMU | At least 1, backup only |
| BMP280, PIR, reed switch, coin vibration motor | At least 1 of each photographed |
| Filament, DuPont signal jumpers, PAM8403, MAX9814, IR and spare electronics | Already reported, count/condition variable |

## Purchase for ONE full pet

| Search for generic module | Quantity |
| --- | ---: |
| Eight ToF ranging slots, original code VL53L4CD; generic VL53L0X is cheaper but NOT firmware compatible yet | **8** (4 floor, front, left, right, rear); buy ONE exact Pololu VL53L4CD carrier #3692 for measured comparison, HOLD other seven and all fleet units. VL53L0X is a separate driver-change experiment, not an installed equivalent |
| TCA9548A I2C multiplexer | **2** (0x70 safety, 0x71 extras) |
| MAX98357A I2S mono amplifier and 8 ohm 1 W 20mm speaker | 1 each |
| CAP1188 8 zone I2C capacitive touch module, selectable address 0x28 | 1 |
| MAX30102 optical heartbeat paw pad | 1, reported owned in HTML, count/photo unverified |
| Copper touch electrode tape and insulation | 1 set |
| APDS9960 color, gesture, proximity and light sensor | 1 |
| FSR402 type force pad | 2 |
| ADS1115 4-channel ADC board | 1 |
| AS5600 magnetic rotary sensor + diametric magnet | 3 each (2 wheels, 1 nose) |
| INA226 power monitor with correctly rated shunt | 1 |
| MAX17048 1S Li-ion fuel gauge module | 1 |
| PN532 NFC reader with I2C, IRQ and reset | 1 |
| MCP23017 I2C GPIO expansion module | 1 |
| SHT41 humidity/temperature board | 1 |
| WS2812B single diffused RGB LED + 74AHCT1G125 level shifter | 1 each |
| Normally closed bumper microswitch | 2 |
| MOSFET, pulldown and flyback diode for reused vibration motor | 1 set |
| Protected matched rechargeable 1S cell/pack + charger/load sharing + regulated 5V output | 1 rated power set |
| Separate 3.3V sensor regulator, switch, fuse, connectors, rated wire and capacitors | 1 set |
| Keyed charge contacts and matching dock cradle with alignment markers | 1 set |
| Printed head, tracks, drive, lift, gripper, mounts, M2/M3 screws/inserts | 1 set, reuse filament |

**Do not rebuy** MPU6050, touch, two existing steppers, two drivers, two positional MG90S, Sense, WROOM, or OLED for pet one unless a real count or electrical test says they are missing/broken. Your owned PAM8403 is not the MAX98357A digital output route.

## Other FOUR pets, after checking stock

| Addition required for the fleet | Quantity to acquire |
| --- | ---: |
| Stepper motors and ULN2003 drivers | **5 of each** |
| WROOM32, Sense boards, OLEDs, MPU6050 and dedicated touch pads | **Up to 4 of each** |
| MG90S positional servos | **Zero if the reported ten work** |
| Every fully selected module in the one-pet shopping table | Four more complete matching sets |

One full robot requires eight confirmed-compatible ToF modules, therefore **40 total for five** if no stock exists. Ten TCA9548A boards total. **Current esp32_full firmware implements eight VL53L4CD lanes; left/right/rear are read-only diagnostics, not safe automatic reverse/turn permissions.** Switching to generic VL53L0X requires a new driver and actual safety tests before the full purchase.

## One shared room and game accessory station

| Shared extra feature | Purchase or reuse |
| --- | --- |
| SCD40 real CO2 sensor | 1 |
| BME688 VOC and air quality sensor | 1 |
| LD2410C presence radar | 1 |
| Capacitive soil probe | 1 if plant game wanted |
| AMG8833 thermal array | 1 if thermal game wanted |
| NFC tags, magnetic hats, game pieces | One shared prop set |
| Station controller | Try owned Feather nRF52840 over USB; otherwise 1 generic ESP32C3 |

**Not needed:** MPR121 and CAP1188 together, a separate camera or microphone, another BerryIMU, a Raspberry Pi, an extra analog amplifier/DAC, RC522 plus PN532, or five CO2 sensors for one room. NXP's MPR121 is discontinued, while Microchip's CAP1188 remains in production.

**XIAO Sense physical pin gate:** GPIO7/8 I2S speaker and GPIO9 RGB share the camera expansion microSD circuit. Seeed says the J3 link must be opened to isolate SD before this pin map is physically wired; check actual board revision and do not insert an SD card. [Vendor instruction](https://wiki.seeedstudio.com/xiao_esp32s3_sense_filesystem/).

**Engineering status:** Electrical bus and pin assignments are selected, documented and collision checked. The five sensor safety code exists; the extra modules, physical battery rating, enclosure fit, charging dock and 8 beam safety trials are not yet qualified. Do not claim a complete assembled robot until those tests are recorded. [Full wiring details](full-feature-wiring-and-shopping.md).


## November 16 consolidated staged generic-price procurement review

**Source-of-truth warning:** This section records the one-robot purchase candidates and the exact unresolved purchase gates. Prices are **USD estimated generic component targets** from recent public listings and prior quotes, NOT verified landed offers. Package/shipping/tax and 3.3 V/PCB variants vary. Do not order a complete robot or five sets yet. The only immediate ranging sample is **one genuine Pololu VL53L4CD #3692**, with VIN supplied from the 3.3 V bus, before purchasing the other seven or any fleet copies. Generic VL53L0X requires a different driver and is not an approved current-firmware replacement. Prefer cheap, documented generic boards; do not buy Adafruit branded hardware. Owned boards can retain their original brand.

**Status vocabulary:** `SAMPLE` means one-unit experiment, `HOLD` means the role is selected but exact purchase requires electrical/fit/software evidence, `MATCH` means existing firmware supports the exact CHIP but carrier/behavior still need testing, `PRINT` reuse filament. The programmatic `full-feature-plan.json` still owns electrical allocation. These prices do not silently change its selected drivers.

### Existing owned components ACTUALLY selected in current source

| Reported owned/ordered | Used role | Status |
| --- | --- | --- |
| WROOM32 1+, Sense camera/mic 1 ordered, SSD1306 1+ | Body physical safety; pinned Xiaozhi head | Source integrated; boards not physically qualified |
| 28BYJ48 5 and ULN2003 5; MG90S ~10 | Per robot 2 wheels, 2 drivers, 2 grip/lift | Source integrated; quantity and loaded fit unverified |
| MPU6050 1+; AT42QT1010 1 | Handling; dedicated head stop/pat | Source integrated; real calibration/stop trial open |
| BMP280 1 | Optional temperature and pressure events | Raw and opt-in Mac logic; opt-in defaults false |
| PIR 1, reed 1 | Optional slow read-only presence/magnet events | GPIOB code exists; compile flags and voltage bench open |
| MAX30102 ~5 CLAIMED, not photo verified | Opt-in nonmedical paw optical contact | Raw FIFO + Mac source; recount before any buy |
| Filament and signal jumpers | Print and SIGNAL harness | Reuse; not rated power leads |

**Owned but NOT current installed/implemented purchase roles:** BerryIMU spare, PAM8403, MAX9814, DRV8833, spare camera, GY61, reflective IR, tilt switch, power bank, USB-C breakout, continuous servo; owned coin vibration motor has a selected haptic role but the output driver is NOT integrated. Newly photographed 3144-style Hall board is a potential reed replacement, not wired or software-qualified. Owned Feather nRF52840 is a candidate for the room station, which is not implemented end to end.

### One robot, stage-ordered candidate shopping with USD price targets

| Stage | Generic part | Quantity | Estimated USD component total | Gate |
| --- | --- | ---: | ---: | --- |
| Core 1 | Pololu VL53L4CD carrier #3692 (source-compatible sample; not yet physically cliff-qualified) | 8 target, **1 sample now** | $111.60 for 8 at $13.95 each | SAMPLE; run 3.3 V I2C, loaded 30–60mm cliff, black/gloss surface and stop trials before remaining seven; generic VL53L0X needs its own driver |
| Core 1 | TCA9548A 8 channel I2C mux | 2 | $2–6 | MATCH, verify 3.3V breakout |
| Core 1 | MCP23017 GPIO expander | 1 | $2–5 | MATCH, mandatory fresh dock IO in full profile |
| Core 1 | NC collision bumper | 2 | $1–3 | HOLD physical pullup/fault test |
| Core 1 | MAX98357A I2S speaker amplifier | 1 | $2–4 | MATCH, Sense SD J3 isolation required |
| Core 1 | 20mm 8-ohm 1W speaker | 1 | $1–3 | HOLD acoustic cavity and output wiring |
| Power 2 | protected genuine 1S battery pack with matched cell protection | 1 | $8–18 | HOLD pack current/size/source |
| Power 2 | real 1S charging and load-sharing module, not TP4056-alone | 1 | $8–20 | HOLD no qualified board yet |
| Power 2 | rated 5V boost DC/DC | 1 | $4–12 | HOLD peak/low-cell load test |
| Power 2 | 3.3V sensor regulator | 1 | $1–4 | HOLD total sensor current |
| Power 2 | INA226 with appropriately rated shunt | 1 | $2–5 | MATCH, actual calibration open |
| Power 2 | MAX17048 cell fuel gauge | 1 | $3–6 | MATCH, actual pack matching open |
| Power 2 | 10k NTC compatible battery temperature probe | 1 if not integrated | $0.30–1 | HOLD charger/pack NTC spec |
| Power 2 | rated power switch and fuse | 1 set | $2–5 | HOLD actual current rating |
| Power 2 | JST/keyed connectors + appropriately sized power wire | 1 set | $3–8 | HOLD polarity and ampacity |
| Power 2 | capacitors, pullup/pulldown, decoupling and resistors | 1 set | $2–5 | MATCH design after PCB |
| Power 2 | XIAO one-way USB/external 5V isolation components | 1 set | $0.50–3 | HOLD board pin revision check |
| Mechanics 3 | tracked chassis, wheels, shafts, mounts | 1 printable fitted set | $2–8 filament equivalent | PRINT; licensed original geometry and fit not accepted |
| Mechanics 3 | lift and gripper parts | 1 printable fitted set | $1–4 | PRINT; force trials open |
| Mechanics 3 | head, OLED, camera mounts | 1 printable fitted set | $1–4 | PRINT; mic, lens, camera clearances open |
| Mechanics 3 | M2/M3 screws, nuts and heat-set inserts | 1 set | $3–8 | MATCH after measured CAD |
| Mechanics 3 | perfboard, headers, heatshrink, insulation | 1 set | $2–6 | MATCH after signal harness |
| Mechanics 3 | USB data cable | as needed | $0–5 | MATCH; possible already owned |
| Dock 4 | keyed pogo charging contact pairs | 1 set | $2–7 | HOLD charger electrical safety |
| Dock 4 | independent NC docking seat limit switches | 2 | $1–3 | HOLD real polarity test |
| Dock 4 | demodulated 38kHz IR receivers | 2 | $1–4 | MATCH read-only RMT; real frequency not confirmed from old IR receiver |
| Dock 4 | encoded 940nm IR beacon LED/driver | 1 set | $1–4 | HOLD transmitter source absent |
| Dock 4 | independent isolated current-limited contact safety circuit | 1 | $4–15 | HOLD design not selected |
| Dock 4 | 5V dock adapter correctly rated | 1 | $5–12 | HOLD input peak/charger spec |
| Dock 4 | printed dock/battery cradle | 1 fitted set | $2–6 | PRINT; no actual charge validation |
| Dock 4 | printed AprilTag marker | 1 | $0–1 | PRINT; real camera calibration open |
| Interaction 5 | CAP1188 8 electrode touch controller address strapped 0x28 | 1 | $4–7 | MATCH address and shell trials |
| Interaction 5 | conductive copper tape, adhesive and insulation | 1 set | $1–3 | HOLD touch shells |
| Interaction 5 | APDS9960 gesture/color/proximity/light | 1 | $2–5 | MATCH gesture calibration |
| Interaction 5 | generic FSR402-type force pads | 2 | $4–8 | MATCH with calibration, no Newton claim |
| Interaction 5 | ADS1115 ADC board | 1 | $1–3 | MATCH raw force acquisition |
| Interaction 5 | AS5600 angle encoder breakout | 3 | $6–12 | MATCH raw only; 2 wheels + nose |
| Interaction 5 | diameter/airgap-appropriate DIAMETRIC magnets | 3 | $1–3 | HOLD shaft/mechanical fit |
| Interaction 5 | generic PN532 I2C NFC | 1 | $3–7 | MATCH source, wake/clock stretch test |
| Interaction 5 | SHT41 humidity and temperature | 1 | $3–7 | MATCH CRC source; AHT10 NOT drop-in |
| Interaction 5 | WS2812B diffused RGB LED | 1 | $0.30–1 | HOLD final GPIO/SD J3 and code |
| Interaction 5 | 74AHCT1G125 3.3 to 5V buffer | 1 | $0.50–2 | HOLD LED physical revision |
| Interaction 5 | AO3400 MOSFET, diode and pulldown for owned 3V coin motor | 1 set | $0.50–2 | HOLD motor driver source missing |

For the one robot the above targets sum to **approximately $109–287** (including estimated consumed filament), **excluding tax, shipping and any required hardware already paid for**. This is not a commercial quote. No MAX30102 rebuy until count verified; no AHT10 substitute while current code reads SHT41.

### One shared room/game station for all five robots

| Generic part | Quantity | USD target | Gate |
| --- | ---: | ---: | --- |
| LD2410C mmWave radar | 1 | $4–9 | HOLD room pod not yet implemented |
| genuine SCD40 NDIR CO2 | 1 | $18–30 | HOLD no counterfeit eCO2 substitute |
| BME688 gas VOC/ambient | 1 | $5–11 | HOLD true behavior limitations |
| optional capacitive soil probe | 1 | $1–3 | OPTIONAL game |
| optional AMG8833 8x8 thermal | 1 | $20–30 | OPTIONAL thermal, not core vision |
| NFC tags/magnetic hats and game objects | one set | $2–6 | HOLD before NFC physical proof |
| Room controller: reuse owned Feather; ESP32C3 fallback only | 0 or 1 | $0–5 | HOLD on actual firmware fit |
| Ventilated printed station case | 1 | $1–4 | PRINT after geometry |
| **Shared total including optional items** | | **$51–98** | not required to qualify roaming core |

### Fleet expansion only after first robot physical qualification

Four more each of XIAO Sense, WROOM32, OLED, MPU6050, AT42QT1010 and every other per-robot selected item unless stock confirms more; five additional 28BYJ48 plus five ULN2003 for ten total; existing ~10 MG90S may cover all five. Total 40 selected ToF roles, 10 TCA9548A. Room pod is shared, not five sets. Do not bulk-buy on listings alone.

### November 16 independent source and manufacturer check, procurement decision

**Checked current branch code, not a hypothetical circuit:** Pololu `VL53L4CD` commit bc865905 remains the eight lane production driver; `VL53L0X` is **not** binary/register compatible. A separate physically disarmed `esp32_vl53l0x_bench` target now exists at `code/firmware/body/src/vl53l0x_bench.cpp`, pinned to VERIFIED Pololu Git tag `1.3.1`. Production sources explicitly exclude the bench entry point. It selects only mux `0x70 CH0`, reads back mux control, logs one raw measurement and never grants motor authorization. Static source checks passed 11/11; this is **not** a PlatformIO build or optical trial.

* **Cheap range sensor comparison decision:** The current source-compatible reference is **ONE genuine Pololu VL53L4CD #3692**. Buy **at most ONE generic GY530 VL53L0X as an OPTIONAL disarmed comparison sample**, target $2 to $5 before shipping, only if evaluating a firmware and safety architecture change. Neither sample authorizes buying the remaining 39 modules. [ST VL53L0X](https://www.st.com/en/imaging-and-photonics-solutions/vl53l0x.html) and [Pololu Arduino code](https://github.com/pololu/vl53l0x-arduino) support a real driver path, but at 30 to 60 mm desk distance success is not established. Check matte/dark/glossy surfaces and local stop margins. Eight production sensors remain **HOLD**; do not assume eight cheap carriers will work just because one powers up.
* **CAP1188 generic compatibility:** Firmware `ExpansionTouch` checks device ID at `0x28`; manufacturer [Microchip CAP1188 Table 4-1](https://ww1.microchip.com/downloads/en/DeviceDoc/00001620C.pdf) specifies address set by hardware `ADDR_COMM` resistor. For 0x28 strap that input to VDD on a board that permits it and power-cycle before bus scan. Do not buy a cheap fixed 0x29 board and expect source to work unchanged. Low cost 2026 generic historical listing approx $3.38 to $4.85, **not a current guaranteed checkout price**.
* **TCA9548A:** Two identical generic I2C mux chips are valid, BUT A0 must be strap low for `0x70` and high for `0x71`, exact 3.3V pullups checked. [TI datasheet](https://www.ti.com/lit/ds/symlink/tca9548a.pdf).
* **MCP23017:** Generic Microchip I2C 16 GPIO chip is correct, not an Adafruit requirement. Full motion source refuses arming with absent/stale required dock GPIO input on mux `0x71 CH5`. [Microchip official part](https://www.microchip.com/en-us/product/MCP23017). A random MCP23**S**17 SPI version is not compatible.
* **MAX98357A:** Correct direct digital I2S amplifier family, but exact pinout, Sense SD J3 and speaker current limit remain physical gates. Existing PAM8403 is analog and not an equivalent drop-in.
* **MAX30102:** Existing SparkFun MAX3010x upstream is a code and board **reference**, not a branded product requirement. Owner claimed approx five modules but has not photographically verified quantity; don't buy more.
* **No bulk-ready power module:** BQ24074 or MCP73871 alone does not supply the independently rated 5V actuator rail. Battery, thermal/protection, boost, charger, contacts and entire body current must be measured. Room pod also lacks verified serial firmware and full Mac consumption.

**CI actual latest head check:** GitHub Actions run 43910444982 completed with four failing jobs and no observable test steps; **not** proof of source test success or source failure. Local private clone DNS also unavailable. No actual prototype, live audio, loaded stop, charge, fitted CAD, real five-robot integration or commercial licensed production clearance is demonstrated. Hence `prices_complete=false`, `qualified_assumptions=false` and `physical_trial_count=0` must stay unchanged in the authoritative plan.

### Agent assignments and mandatory acceptance gates

Master PR [procurement comment](https://github.com/hungngodev/desk-robot-remix/pull/17#issuecomment-6922090288) and numbered comments 01–12 cover: ranging, bus carrier voltages, power/charge, docking, CAD/licensing, audio, brain, touch, extra sensors, toys, room pod and CI. Refresh live head/comments before edits; use actual source and tests. Present one complete robot with measured local stop and real safe battery charge, measured jaw/key pickup, XIAO acoustic interrupt, full multimodal observation and five-robot digital coordination before naming any bill of materials production-ready.


## November 16 independent exact-module procurement gate

This section supersedes any older line in this checklist that implied a generic VL53L0X was a drop-in purchase for the current VL53L4CD guard. This is **one-robot bench procurement, not a completed production BOM**. Every board below has a published, verifiable part number and 3.3 V integration path in the existing source. The current final fitted enclosure and the powered robot are still unqualified; do not order five copies of any item.

| Manufacturer part and direct non-Adafruit vendor link | Buy for ONE robot hardware bench | Proven connection / condition |
| --- | ---: | --- |
| [SparkFun TCA9548A mux BOB-16784](https://www.sparkfun.com/sparkfun-qwiic-mux-breakout-8-channel-tca9548a.html) | 2 | WROOM 3.3 V SDA/SCL, set 0x70 and 0x71 using address solder jumper; inspect all pullups and both control register reads |
| [Pololu VL53L4CD carrier 3692](https://www.pololu.com/product/3692) | 1 sample | Exact supported Pololu chip/register driver, 3.3 V to VIN ensures 3.3 V I2C high; verify true cliff stopping before 7 more |
| [Waveshare MCP23017 IO expansion SKU15391](https://www.waveshare.com/mcp23017-io-expansion-board.htm) | 1 sample | 3.3 V VCC and I2C address 0x20; set address straps per board revision; 38 x 23 mm board fit still pending |
| [SparkFun MAX98357A DEV-14809](https://www.sparkfun.com/sparkfun-i2s-audio-breakout-max98357a.html) | 1 | Existing Sense GPIO4/7/8 I2S; physically isolate camera expansion J3, adjust gain and keep differential speaker leads isolated |
| [SparkFun 20mm 8ohm 1W speaker COM-26553](https://www.sparkfun.com/mini-speaker-1w-8-ohm.html) | 1 | Audio load for DEV-14809, gain/output limited to protect 1W driver; test mic feedback and acoustic cavity |

**No Adafruit purchase.** Previously reported owned Adafruit-branded touch hardware may be reused. **Do not approve CAP1188 yet:** its I2C address is resistor-selected and current code requires 0x28; a generic 0x29 carrier without correctly accessible ADDR_COMM is incompatible. A documented non-Adafruit breakout has not yet been verified. Microchip source: https://ww1.microchip.com/downloads/en/DeviceDoc/00001620C.pdf .

**Do not approve an unexamined PN532.** The old Elechouse V3 documentation specifies 5 V TTL on I2C/UART, unsafe to assume for this WROOM 3.3 V bus: https://www.elechouse.com/elechouse/images/product/PN532_module_V3/ . A new 3.3 V PV532 V3.5 substitute has different chip provenance and lacks actual driver/fit tests. Do not authorize it as a drop-in.

**Mobile battery and charger are blocked, not forgotten.** A documented charger IC and published current ratings cannot replace measured worst-case 5 V continuous/peak load, protected pack selection, NTC, real power-sharing/current and unpowered dock contact acceptance. The Seeed XIAO onboard 100mA charger cannot serve motors/servos. 8 Pololu #3692 modules at single-unit prices cost $111.60 before power and the other sensors, contradicting the old $50/robot target. Refer to `one-robot-power-gate.md` and `charging-design-and-validation.md`.
