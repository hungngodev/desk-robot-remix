# Body firmware attribution

UART command and motor PWM conventions were adapted from VerdureBuddyRover (MIT),
copyright 2026 创客社区（Hacker space）. The full required notice is retained at
[VerdureBuddyRover MIT license](../../../docs/licenses/VerdureBuddyRover-MIT.txt).
See [project attribution](../../../docs/ATTRIBUTION.md).

The portable parser, lease/watchdog, ramp, tests and hardware adapter add the
integration behavior described in the project. Arduino/ESP-IDF/platform packages
keep their own upstream notices and are not relicensed by this repository.

The new StepperDrive and CliffGuard policy are original integration code under
the repository MIT license. No wtlx sketches or unlicensed video code were copied.
The guarded WROOM stepper and guarded DC firmware now pin Pololu's VL53L0X Arduino library at release 1.3.1, MIT licensed, for module initialization. The critical runtime uses bounded nonblocking 0x13/0x14/0x0B I2C protocol reads instead of blocking in its readRangeContinuousMillimeters() method. Pinned library and manufacturer source are reused, not a custom sensor startup stack. Generic low-cost GY-530 board voltage, short-range optics and physical loaded desk stop remain unqualified. The previous VL53L4CD dependency is no longer selected.

BerryIMU six-axis raw I2C access and model classification adapt register
identities and layout from OzzMaker's public Arduino BerryIMU source at
https://github.com/ozzmaker/BerryIMU/tree/master/arduino-BerryIMU .
No complete third-party driver/sketch is bundled. The shared Wire adapter,
readonly telemetry and tests were integrated locally. Physical revision,
accelerometer calibration, attitude and held-state safety remain unverified.


PN532 read-only NFC toy support is original, small nonblocking integration
code that follows **Seeed Studio PN532**, BSD-3-Clause command and framing
conventions, https://github.com/Seeed-Studio/PN532/tree/arduino/src .
The upstream library's synchronous ACK, response and card wait loops were
NOT linked into the local WROOM cliff safety loop. The new bounded frame
adapter under `lib/AccessorySensors/Pn532Frames.h` retains explicit source
attribution and parses only ISO14443A UID game tokens. It cannot authenticate
a person or operate the charger or motors. Check the retained upstream
license at https://github.com/Seeed-Studio/PN532/blob/e61296876c1c3e66ef67156562c71324b389f5fa/LICENSE.md .
No real PN532 module, antenna, voltage or timing trial has passed.
