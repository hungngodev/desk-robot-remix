> 2026-11-10: New user-reported MPU6050 is not one of these established photograph identities. Treat stock as reported, exact GY-521 model and quantities unverified. This photo audit continues to prove only what those pictures showed, not an MPU6050 image.

# Owned electronics — photo audit

Recorded 2026-11-04 from the user's 18 photographs. This identifies **10 module
types**, not 18 separate units. Front/back views and repeated angles are grouped
below. Record a minimum of one of each type; exact stock and working condition
remain unknown. The images establish appearance/ownership, not electrical tests.

## Identification and reuse decision

| Photos (IMG_ prefix, .JPG suffix) | Identification and confidence | Use in this robot |
| --- | --- | --- |
|3893 /3892 | **OzzMaker BerryIMU**, high confidence in family; silkscreen appears1.0, likely V1, chips not verified | Optional photographed spare now that the user reports using an MPU6050. Keep compatible software support, but do not presume both boards can be installed together |
|3891 /3890 | **Adafruit BMP280 pressure/temperature breakout**, high; front/back of STEMMA QT board | Optional ambient sensing. Not a gyroscope or cliff sensor; no requirement to install it |
|3889 | **Reflective infrared obstacle module**, high in function, exact Keyes/KY model unverified | Optional bench obstacle experiments. Not millimetre ToF and not a qualified substitute for the four downward sensors |
|3888 /3887 /3886 | **PIR motion detector**, high; board marked SB00622A-2-V1.3, exact vendor specifications unverified | Optional stationary desk/dock trigger. Its changing thermal view when the rover moves can trigger it; omit from the compact core |
|3885 /3884 | **Infrared remote receiver module**, high in function; KY-022-style, exact receiver/frequency unverified | Optional remote input after checking actual receiver and voltage. Does not measure distance or transmit IR |
|3883 | **Likely mechanical tilt/vibration switch module**, medium; photo too soft for exact model | Spare binary movement/tilt input. Cannot provide gyro readings or replace the full IMU |
|3882 /3881 | **Separate camera module**, high in category; board text appears CMY-1118 V1.0, exact sensor/interface unknown | Keep spare. Do not assume USB/UVC, UART, or compatibility with Sense's camera connector. Use the camera already included with Sense |
|3880 | **Magnetic reed-switch comparator module**, high in function, KY-025-style | Optional magnet-equipped accessory/feeding game. A reed switch is not a Hall IC; detection alone cannot identify which accessory is present |
|3879 /3878 | **GY-61 analog accelerometer**, consistent with ADXL335; high in category, chip marking not read | Spare for tilt/shake experiments, **no gyro**. Three analog outputs cost three ADC inputs; BerryIMU's I2C is the simpler prototype route |
|3877 /3876 | **Adafruit MAX9814 AGC electret microphone amplifier**, high; model and analog-output specifications visible | Spare audio input. Sense already includes its digital microphone. **This does not replace MAX98357A speaker output** or qualify voice interruption |

The large camera is not a Sharp distance sensor. No touch module, ToF breakout,
I2C mux, speaker-output amplifier, speaker or matched battery kit is identifiable
in this photo set. This does not assert that the user owns none elsewhere.

Rechecked 2026-11-06. All 18 files in
`/Users/hung/Downloads/electric components/` match the original audit hashes.
The resubmission confirms the same ten module types. See the
[photo index and hashes](photo-inventory-2026-11-04.json) and the
[combined inventory and build gaps](parts.md) for earlier reported parts.
The HiLetgo amplifier was originally recorded from the user's separate report.
See the follow-up below for its photo identification.

## Prototype change and fleet boundary

The prototype BOM now reserves the **owned BerryIMU at zero additional purchase
cost**, with inventory/compatibility checks still open. LSM6DS3TR-C moves to a
conditional fallback, not an additional required sensor. One photographed IMU
does not cover five robots: four further working equivalents remain unconfirmed
if only this one is available. All cores retain the same sensing/behavior
contract; no requirement is removed.

The original audit left TTP223 touch and MAX98357A plus speaker on the shopping list.
The follow-up below supersedes the touch purchase. Keep speaker output, four
downward VL6180X, one forward VL53L0X, TCA9548A, a matched 1S power system and
rated assembly and power parts on the
unconfirmed/missing list. Reflective IR and PIR are not automatic replacements
for local edge protection. No new camera, microphone, Uno, Pico or Pi is needed.

## Before wiring the owned IMU

1. Identify the exact PCB revision, header orientation and supply pins from
   matching OzzMaker documentation. The current shop page mainly describes V3;
   its voltage/connector details must not be generalized to this older unit.
2. Check the actual regulator/pullups and use verified3.3V-compatible logic.
   With drive disabled and actuator power disconnected, acquire I2C addresses
   and chip identity, then stationary acceleration and gyro samples.
3. The maker's V1 example uses0x1E for accel/magnetometer and0x6A for gyro;
   these are **candidate addresses, not measurements** of this board. Verify all
   devices before fixing the firmware profile. Do not hardcode LSM6 register
   addresses or use the LSM6 driver for an LSM9DS0/LSM9DS1 unit.
4. Proposed bus remains WROOM21/22 upstream of the mux. Do not connect the
   independent Sense OLED bus. Keep reads bounded so floor/stop work wins.
   If both the BerryIMU's pressure sensor and optional BMP280 answer0x77,
   resolve that collision before enabling both; the extra BMP280 is unnecessary.
5. Secure the board with known axes; calibrate bias and test loaded vibration,
   tilt/shake and suspected pickup using A11 in the interaction plan. An IMU
   alone cannot prove a level, stationary robot is being held. No automatic
   rearm or motion resume follows putdown.

No final pins or new sensor driver were implemented here. Actual module fit,
motion classification and local stopping still require physical qualification.

## Sources checked

- [OzzMaker version comparison](https://ozzmaker.com/product/berryimu-accelerometer-gyroscope-magnetometer-barometricaltitude-sensor/): V1 uses LSM9DS0/BMP180, V2 LSM9DS1/BMP280, V3 LSM6DSL/LIS3MDL/BMP388. All supply acceleration and gyro sensing. The photographed revision remains provisional.
- [OzzMaker Arduino examples](https://github.com/ozzmaker/BerryIMU/tree/master/arduino-BerryIMU) and [V1 registers](https://github.com/ozzmaker/BerryIMU/blob/master/arduino-BerryIMU/LSM9DS0.h): version detection/register reference; no source imported or copied. Check terms and review bounded acquisition before integration.
- [Adafruit MAX9814](https://www.adafruit.com/product/1713): analog microphone output; distinct from [MAX98357A I2S speaker amplifier](https://www.adafruit.com/product/3006).
- [Analog Devices ADXL335](https://www.analog.com/en/products/adxl335.html): three-axis analog acceleration, no gyro; chip supply1.8–3.6V does not establish an anonymous GY-61 board's input rating.
- [Adafruit BMP280 guide](https://learn.adafruit.com/adafruit-bmp280-barometric-pressure-plus-temperature-sensor-breakout/overview): pressure/temperature, STEMMA QT and header variants.
- [Adafruit PIR guide](https://learn.adafruit.com/pir-passive-infrared-proximity-motion-sensor/overview): changing thermal scene detection; does not give distance or person count. Exact photographed module ratings remain unverified.
- [Joy-IT kit taxonomy](https://sensorkit.joy-it.net/en/), [IR receiver](https://sensorkit.joy-it.net/en/sensors/ky-022), [reed module](https://sensorkit.joy-it.net/en/sensors/ky-025): functional comparisons, not proof that generic pictured boards share their precise ratings or pin order.

Photos are observations; manufacturer descriptions are source claims; reuse and
omission decisions above are engineering judgments. Nothing is declared working
solely from its appearance.

## 2026-11-06 follow-up

Six additional photos are in `/Users/hung/Downloads/electric components/`.
Quantities below describe the photos and packaging. Operation remains untested.

| Photos | Identification | Project disposition |
| --- | --- | --- |
| IMG_3907.JPG | Adafruit #1374 AT42QT1010 momentary capacitive touch, identified by package label | Reuse for robot one's head pad. Proposed 3.3 V supply and active-high digital OUT to WROOM GPIO34. Check response through the shell and costume. [Adafruit](https://www.adafruit.com/product/1374) |
| IMG_3906.JPG | DFRobot FIT0774 10 × 2.7 mm coin vibration motor | Optional tactile feedback. The motor is rated 3 V and specified for 1.5–4.2 V. Use a switched motor supply within that range and check for interference with the IMU and mic. [DFRobot](https://www.dfrobot.com/product-2297.html) |
| IMG_3902.JPG | HiLetgo HW-104, chip marked PAM8403. Bag marked 5 pieces, one board visible | Analog-input speaker amp. Requires a DAC with the digital Sense output. Choose one audio path. [Diodes](https://www.diodes.com/datasheet/download/PAM8403.pdf) |
| IMG_3905.JPG | KY-025-style magnetic reed-switch module matching IMG_3880 | Optional magnet accessory. The photo does not establish a second physical unit |
| IMG_3904.JPG and IMG_3903.JPG | Front and back of one Adafruit DRV8833 #3297 | Spare dual H-bridge for motor experiments. The stock 5-wire 28BYJ-48 drive and its phase wiring use ULN2003. [Adafruit](https://www.adafruit.com/product/3297) |
