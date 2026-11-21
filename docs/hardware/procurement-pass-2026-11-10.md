> **SUPERSEDED November 16, preserved as historical November 10 audit.** This page's old 25 VL53L4CD and 5 TCA9548A estimates are obsolete and are NOT authorized purchases. The current selected design requires **40 generic VL53L0X GY-530 ranging sensors and 10 TCA9548A multiplexers** for the five robot fleet (eight sensors and two muxes per robot), subject to verifying the actual 3.3 V carrier PCB, pullups, mounting, electrical fit and physical safety. Consult the [canonical machine plan](full-feature-plan.json) and [generated owned and buy lists](complete-shopping-checklist.md) for quantities and release status. All component rows below remain a historical record, not an active cart.

# Purchase and owned stock reconciliation, November 10, 2026

This is not a purchase order. No physical inventory count, electrical bench acceptance,
CAD fit, final quote or shipping total has been established. Everything remains in
scope of the user's complete five pet system. Counts are required assembly quantities,
not claims that the parts have already arrived.

## Reported inventory and remaining total for a complete five robot fleet

| Component | Total required | Reported on hand or ordered | Remaining or check |
| --- | ---: | --- | --- |
| XIAO ESP32S3 Sense complete camera/mic bundle | 5 | At least one ordered at previously reported listing $18.87; delivery unverified | Four more **only if** one is actually supplied and no extras already owned |
| ESP32 WROOM controller | 5 | At least one, exact count unknown | Count stock first; potentially up to four |
| SSD1306 monochrome OLED | 5 | At least one | Count stock first; potentially up to four |
| 28BYJ48 5 V stepper | 10 | Five reported | Five additional for full fleet |
| ULN2003 stepper driver board | 10 | Five reported | Five additional for full fleet |
| MG90S positional lift/grip servos | 10 | Approximately ten reported, not individually checked | No automatic buy until function, torque and exact count verified |
| AT42QT1010 cap touch or tested equivalent | 5 | At least one photographed | Possibly four more |
| MPU6050 six axis IMU or tested Berry alternative | 5 | User now reports one MPU6050 used; one photographed BerryIMU optional spare | Count usable MPU modules; four more only if one qualifies |
| VL53L4CD compatible short range ToF carrier | 25 | None confirmed | Five per robot, 25 total; **do not order** before single carrier qualification and viable budget |
| TCA9548A I2C mux | 5 | None confirmed | One per robot, five total |
| MAX98357A I2S amplifier, or qualified DAC plus PAM8403 alternative | 5 paths | No MAX98357A confirmed; PAM8403 pictured, bag labeled five pieces | One safe audio output path per pet, actual stock and wiring first |
| 8 ohm 1 watt mini loudspeaker | 5 | None confirmed | One per pet |
| Protected rechargeable 1S cell plus holder/charge/protection/5 V boost | 5 matched kits | None confirmed | One qualified mobile power kit per pet, not just a loose battery |
| Rated wiring, power switch, fuse, connectors, fasteners, decoupling | 5 safe sets | DuPont signal leads on hand; no rated power distribution confirmed | Specify and quote after measured load/geometry |
| Printed tracked body/head/lift/claw and costume parts | 5 sets | Filament and saved CAD candidates reported, no assembled verified set | Print/fit/test the complete mechanism before duplicating |

Optional owned modules **not mandatory purchases** include BMP280 temperature/pressure,
PIR infrared movement detection, reflective IR board, reed switch and magnet,
analog MAX9814 mic, GY61 accelerometer, possible vibration switch, separate
camera, original BerryIMU, spare DRV8833, coin vibration motor and PAM8403
analogue speaker amplifier. Optional not proven already owned: bumper switch,
RGB LED plus 3.3 V to 5 V level conversion, light/gesture sensors, heart pad,
RFID/NFC, capacitive belly force sensor. Do not add all 75 research ideas to
the compact robot's required bill.

## Critical budget contradiction

The existing WROOM firmware uses five VL53L4CD roles: four separate downward
corners and one forward obstacle. Official Pololu currently lists its
[VL53L4CD carrier](https://www.pololu.com/product/3692) at **$13.95 each**
(2026-11-10 online listing). That *one official source choice* alone costs
**$69.75 for one pet's five sensors**, beyond the **$50 complete pet cap**.
The earlier Sense purchase listing is **$18.87** (not verified final receipt),
and the rest of the needed battery, sound and power hardware remains unquoted.
Do not claim $50 achievable with five of those official carriers, remove the
four downward corner roles, or silently substitute a different ToF model.
A verified compact equivalent carrier quote, or an explicitly approved
architecture/budget change, is needed before any spending. Similar named
VL53L4CX, VL53L0X, or VL6180X products are **not** firmware compatible by
assumption. A cheaper untested anonymous breakout may be dangerous for edge
sensing and cannot be marked purchase ready.

## Remaining physical and software gates

1. Confirm actual MPU6050 board silkscreen, WHO_AM_I register, 3.3 V breakout
   I2C pullups and mounted axes. A valid raw sample is NOT a tilt interlock.
2. Bench qualify ToF optics and real cliff stopping on a catch tray, including
   pivots, low contrast surfaces and loaded power.
3. Confirm the speaker amp route and actual audio reference timing, natural
   interruption latency, AEC and camera co-activity with the assembled head.
4. Print the tracked body and jaws, measure MG90S travel, loaded lift, key
   and wrapped candy hold and placement trials.
5. Select battery, fuse, charging/protection and actual measured peak supply.
6. Fit optional bumper, reed, PIR and BMP only after voltage, external resistor,
   pin occupancy and extra I2C lane verification.
7. Repeat all acceptance tests for each of five physical robots, not just the
   simulated software group.

Status: **procurement blocked pending price/physical qualification**. No purchase
was placed by this review.
