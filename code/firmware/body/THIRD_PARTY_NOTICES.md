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
The stepper firmware now pins Pololu's VL53L4CD Arduino library to commit bc865905fc97085f40ca9edab478210c01195fde, derived from ST ULD, BSD 3-Clause Clear. Upstream notices remain with its package. The critical runtime uses bounded raw I2C sampling rather than Pololu's generic read parser due to its invalid-SPAD division. No actual sensor optical geometry or physical stop has been proven.

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
license at https://github.com/Seeed-Studio/PN532/blob/arduino/LICENSE .
No real PN532 module, antenna, voltage or timing trial has passed.
