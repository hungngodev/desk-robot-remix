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
