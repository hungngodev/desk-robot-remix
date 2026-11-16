# Buy this for the full five desk pets

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
| Eight ToF ranging slots, original code VL53L4CD; generic VL53L0X is cheaper but NOT firmware compatible yet | **8** (4 floor, front, left, right, rear); buy ONE low-cost VL53L0X for measured comparison, HOLD other seven and all fleet units |
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

**Source-of-truth warning:** This section records the one-robot purchase candidates and the exact unresolved purchase gates. Prices are **USD estimated generic component targets** from recent public listings and prior quotes, NOT verified landed offers. Package/shipping/tax and 3.3 V/PCB variants vary. Do not order a complete robot or five sets yet. The only immediate new sample purchase authorized for comparison is **one generic VL53L0X** after confirming its PCB regulator and logic voltage. Prefer cheap, documented generic boards; do not buy Adafruit branded hardware. Owned boards can retain their original brand.

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
| Core 1 | GY530 / VL53L0X ToF candidate | 8 target, **1 sample now** | $16–32 for 8 | SAMPLE; current firmware is VL53L4CD, real 30–60mm cliff reliability unverified |
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

* **Cheap range sensor decision:** Buy **ONE generic GY530 VL53L0X sample only**, target $2 to $5 before shipping. [ST VL53L0X](https://www.st.com/en/imaging-and-photonics-solutions/vl53l0x.html) and [Pololu Arduino code](https://github.com/pololu/vl53l0x-arduino) support a real driver path, but at 30 to 60 mm desk distance success is not established. Check matte/dark/glossy surfaces and local stop margins. Eight production sensors remain **HOLD**; do not assume eight cheap carriers will work just because one powers up.
* **CAP1188 generic compatibility:** Firmware `ExpansionTouch` checks device ID at `0x28`; manufacturer [Microchip CAP1188 Table 4-1](https://ww1.microchip.com/downloads/en/DeviceDoc/00001620C.pdf) specifies address set by hardware `ADDR_COMM` resistor. For 0x28 strap that input to VDD on a board that permits it and power-cycle before bus scan. Do not buy a cheap fixed 0x29 board and expect source to work unchanged. Low cost 2026 generic historical listing approx $3.38 to $4.85, **not a current guaranteed checkout price**.
* **TCA9548A:** Two identical generic I2C mux chips are valid, BUT A0 must be strap low for `0x70` and high for `0x71`, exact 3.3V pullups checked. [TI datasheet](https://www.ti.com/lit/ds/symlink/tca9548a.pdf).
* **MCP23017:** Generic Microchip I2C 16 GPIO chip is correct, not an Adafruit requirement. Full motion source refuses arming with absent/stale required dock GPIO input on mux `0x71 CH5`. [Microchip official part](https://www.microchip.com/en-us/product/MCP23017). A random MCP23**S**17 SPI version is not compatible.
* **MAX98357A:** Correct direct digital I2S amplifier family, but exact pinout, Sense SD J3 and speaker current limit remain physical gates. Existing PAM8403 is analog and not an equivalent drop-in.
* **MAX30102:** Existing SparkFun MAX3010x upstream is a code and board **reference**, not a branded product requirement. Owner claimed approx five modules but has not photographically verified quantity; don't buy more.
* **No bulk-ready power module:** BQ24074 or MCP73871 alone does not supply the independently rated 5V actuator rail. Battery, thermal/protection, boost, charger, contacts and entire body current must be measured. Room pod also lacks verified serial firmware and full Mac consumption.

**CI actual latest head check:** GitHub Actions run 43910444982 completed with four failing jobs and no observable test steps; **not** proof of source test success or source failure. Local private clone DNS also unavailable. No actual prototype, live audio, loaded stop, charge, fitted CAD, real five-robot integration or commercial licensed production clearance is demonstrated. Hence `prices_complete=false`, `qualified_assumptions=false` and `physical_trial_count=0` must stay unchanged in the authoritative plan.

### Agent assignments and mandatory acceptance gates

Master PR [procurement comment](https://github.com/hungngodev/desk-robot-remix/pull/17#issuecomment-6922090288) and numbered comments 01–12 cover: ranging, bus carrier voltages, power/charge, docking, CAD/licensing, audio, brain, touch, extra sensors, toys, room pod and CI. Refresh live head/comments before edits; use actual source and tests. Present one complete robot with measured local stop and real safe battery charge, measured jaw/key pickup, XIAO acoustic interrupt, full multimodal observation and five-robot digital coordination before naming any bill of materials production-ready.
