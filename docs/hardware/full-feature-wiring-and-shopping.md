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

The five optical safety sensors already have a source driver. The full selected expansion allocates **three more VL53L4CDs** for left, right and rear. All eight modules must use a compatible verified breakout; extra three lanes are allocated but firmware still reads five, and no all-direction roaming is physically approved.

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
| 36 | reed |
| 39 | pir |

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

**Do not attach another I2C master to the Sense OLED wires.** Head and body exchange UART only (TX/RX crossed, plus GND), with separate regulated supplies and a common reference. Do not use GPIO34/35/36/39 as outputs or expect internal pull resistors.

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
| 5 | VL53L4CD, 0x29 | left obstacle | Needs driver extension and physical qualification |
| 6 | VL53L4CD, 0x29 | right obstacle | Needs driver extension and physical qualification |
| 7 | VL53L4CD, 0x29 | rear obstacle | Needs driver extension and physical qualification |

### Mux B, address 0x71: extra pet features, lower polling priority

| Lane | Module and address | Purpose |
| --- | --- | --- |
| 0 | CAP1188 (0x28) | eight petting electrodes |
| 1 | APDS9960 (0x39), AS5600 nose (0x36) | gesture + twist nose |
| 2 | ADS1115 (0x48) | force feedback |
| 3 | SHT41 (0x44), BMP280 (0x76) | humidity + reported pressure board |
| 4 | INA226 (0x40), MAX17048 (0x36) | current and battery fuel gauge |
| 5 | PN532 I2C (0x24), MCP23017 (0x20) | NFC and auxiliary digital control |
| 6 | AS5600 (0x36) | left wheel rotation |
| 7 | AS5600 (0x36) | right wheel rotation |

**CAP1188 rather than MPR121:** Microchip marks CAP1188 in production, whereas NXP archives MPR121. Use a CAP1188 I2C breakout configured to **0x28**, not its common breakout default 0x29, so it cannot share the same address as the optical modules even if a mux lane is left selected. Its 8 electrodes cover head, back and belly; retain the existing dedicated AT42QT1010 as the **local physical stop touch**, never routed through an optional mux. Check actual breakout address-selection circuitry before ordering.

**MCP23017:** controls only noncritical PN532 IRQ/reset and haptic switch, plus dock detection. All outputs must have hardware-safe default pull resistors. Never put motor phases, servo lift/grip outputs, emergency stops, required head touch or optical cliff timing through the expander.

**Bus ownership:** existing WROOM ToF driver must run first; optional reads have lower priority and strict timeout. The new mux must remain disabled until the new sensor drivers are written and verified. No optional sensor is allowed to rearm a body, clear a fault, grant a permit, or monopolize the bus.

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
| Additional 3 optical directions, second mux and 8 zone CAP1188 | Logical address and pin allocation finalized; new firmware driver/poll scheduler required |
| APDS9960, FSR/ADS1115, two wheel encoders, AS5600 nose, PN532, battery gauges, humidity | Exact low-priority mux lanes finalized; boards, mounting and code **not** yet qualified |
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
