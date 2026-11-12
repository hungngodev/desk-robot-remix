# One robot, one table: reported inventory and purchase needs

**One robot only.** The five-pet architecture is retained in [product definition](../product-definition.md); do not multiply anything by five here. This is a simple one-item-per-row index so photos or purchase links can be attached after physically confirming the exact module. All reference photos shown in chat are stock reference photos, **not** the user's saved photos.

| Component | Have or buy | One-robot quantity and note |
| --- | --- | --- |
| ESP32 WROOM32 | Have | 1, reported |
| XIAO ESP32S3 Sense with camera and microphone | Ordered | 1, confirm arrival |
| SSD1306 0.96 inch OLED | Have | 1 |
| 28BYJ48 5V stepper motor | Have | 5 reported, use 2 |
| ULN2003 stepper driver | Have | 5 reported, use 2 |
| MG90S positional servo | Have | about 10 reported, use 2 |
| MPU6050 gyroscope/accelerometer | Have | 1 reported |
| AT42QT1010 basic head touch | Have | 1 photographed |
| MAX30102 heartbeat paw pad | Confirm | HTML says ~5 owned; photo audit did not verify |
| BerryIMU older breakout | Have | 1 spare |
| BMP280 pressure/temperature | Have | 1 photographed |
| PIR sensor | Have | 1 photographed |
| Magnetic reed switch | Have | 1 photographed |
| Reflective IR obstacle sensor | Have | 1 spare |
| IR remote receiver | Have | 1 spare |
| Mechanical vibration/tilt switch | Have | at least 1 spare |
| 3V vibration coin motor | Have | 1 photographed |
| PAM8403 analog speaker amplifier | Have | 1 spare, not digital audio |
| MAX9814 analog microphone | Have | 1 spare |
| GY61 analog accelerometer | Have | 1 spare |
| Separate camera module | Have | 1 spare, model unknown |
| DRV8833 H bridge driver | Have | 1 spare |
| Feather nRF52840 controller | Have | 1, optional station |
| USB C breakout | Have | 1 spare |
| DFRobot continuous rotation servo | Have | 1 spare |
| Power bank | Have | 1, output rating unverified |
| DuPont jumper ribbons | Have | 10 signal-wire ribbons |
| 3D printer filament | Have | reported, amount to check |
| VL53L4CD time of flight carrier | Buy | 8 units; the current full WROOM firmware contains eight VL53L4CD channels: four floor, one front and three side/rear read-only. No physical breakout, I2C timing or placement has been qualified. |
| TCA9548A 8 channel 3.3V compatible I2C multiplexer | Buy | 2 units; Two per pet. 0x70 for range, 0x71 for extra sensors. |
| MAX98357A I2S mono amplifier | Buy | 1  |
| 8 ohm 1 watt approximately 20 mm speaker | Buy | 1  |
| CAP1188 8 zone capacitive touch breakout | Buy | 1 ; Eight zones, not the originally brainstormed 12-zone MPR121. Unqualified generic breakout. |
| Copper tape touch electrode and insulating backing set | Buy | 1  |
| APDS9960 gesture proximity color light module | Buy | 1  |
| FSR402 type force sensing resistor | Buy | 2 units |
| ADS1115 4 channel ADC breakout | Buy | 1  |
| AS5600 magnetic rotary angle breakout | Buy | 3 units; 2 wheel angles + 1 nose; actual mechanical fit not proven |
| Diametric AS5600 compatible magnets | Buy | 3 units |
| PN532 I2C NFC reader module with IRQ/reset pins | Buy | 1  |
| MCP23017 16 channel I2C GPIO expander | Buy | 1  |
| Single diffused WS2812B RGB pixel | Buy | 1  |
| 74AHCT1G125 3.3V to 5V RGB buffer | Buy | 1  |
| INA226 current voltage monitor with rated external shunt | Buy | 1  |
| MAX17048 single cell fuel gauge | Buy | 1  |
| SHT41 humidity and temperature module | Buy | 1  |
| Normally closed micro bumper switch | Buy | 2 units |
| AO3400 class logic MOSFET, flyback diode and pulldown | Buy | 1  |
| Matched protected rechargeable 1S power assembly with charge and load sharing | Buy | 1 ; Battery/charger/load-sharing circuit needs actual measured peak current before final model purchase |
| Dedicated regulated 3.3V expansion sensor supply | Buy | 1  |
| Rated switch, fuse, power leads, JST style keyed connectors, decoupling | Buy | 1  |
| Keyed charging contacts and alignment switch set | Buy | 1 ; Charging contact protection unqualified |
| Printed docking cradle, printed camera marker and 5V charging input | Buy | 1 ; Dock motion and AprilTag perception exist in source; final dual IR bearing, stopped contact alignment, actual safe charger, fit and physical dock trials are NOT qualified |
| Filament, printed chassis/head/gripper mounts, fasteners, inserts, insulated harness | Buy | 1  |
| SCD40 CO2 module | Buy if installing environment station | 1, not part of safety core |
| BME688 VOC air quality module | Buy if installing environment station | 1 |
| LD2410C presence radar | Buy if installing environment station | 1 |
| Capacitive soil sensor | Buy if installing plant interaction | 1 |
| AMG8833 thermal grid sensor | Buy if installing thermal station | 1 |
| NFC tags and magnetic accessories | Buy | 1 game set |
| Room controller ESP32C3 | No buy unless Feather incompatible | 0 if owned Feather works |

**Source audit:** Original [1.07MB HTML full link and idea audit](../research/2026-11-10-original-html-link-and-hardware-audit.md). All 131 original unique links are preserved, all 200 source-map categories have no missing entry. This does not mean every repository was integrated. Thirty GitHub source roots were checked for current public metadata; details and exceptions in audit.

**Cannot call this hardware-complete:****Bumper wiring correction:** Optional normally-closed switches with GPIO35 external pullup: normal LOW; pressed or disconnected HIGH causes immediate local WROOM stop. Do not enable until physical continuity tests pass.

**Important for the XIAO you ordered:** The planned speaker uses GPIO7/8 and RGB GPIO9. The Sense's microSD expansion link J3 occupies those pins by default, so a physical revision-checked J3 disable/isolation is required before wiring. [Seeed official J3 instructions](https://wiki.seeedstudio.com/xiao_esp32s3_sense_filesystem/). No electronics claimed tested.

**Cannot call this hardware-complete:** no final current-rated protected battery charger and power path is chosen, the five critical ToF lanes have no physical fault/stop trial, the three added read-only lanes have no physical range qualification, PN532 bounded read only source exists but has no physical carrier or RF trial, body fit/stop latency and speech barge-in have no physical acceptance. Avoid bulk purchasing unqualified breakouts. Original $50 budget cap is not achievable with the selected rich sensor layout at known reference prices. Generic modules can be purchased from non-Adafruit vendors, but breakout voltage and pin ordering still require actual checking.
