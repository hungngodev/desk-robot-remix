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
| VL53L4CD short range distance sensor carrier | **8** (4 floor, front, left, right, rear) |
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

One full robot has eight VL53L4CD modules, so **40 total for five** if no stock exists. Ten TCA9548A boards total. The extra side and rear ranging lanes are selected but not yet supported by the existing five-channel firmware.

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

**Engineering status:** Electrical bus and pin assignments are selected, documented and collision checked. The five sensor safety code exists; the extra modules, physical battery rating, enclosure fit, charging dock and 8 beam safety trials are not yet qualified. Do not claim a complete assembled robot until those tests are recorded. [Full wiring details](full-feature-wiring-and-shopping.md).
