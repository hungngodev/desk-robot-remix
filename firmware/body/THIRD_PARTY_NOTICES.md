# Body firmware attribution

UART command and motor PWM conventions were adapted from VerdureBuddyRover (MIT),
copyright 2026 创客社区（Hacker space）. The full required notice is retained at
`../../licenses/VerdureBuddyRover-MIT.txt`. See `../../ATTRIBUTION.md`.

The portable parser, lease/watchdog, ramp, tests and hardware adapter add the
integration behavior described in the project. Arduino/ESP-IDF/platform packages
keep their own upstream notices and are not relicensed by this repository.

The new StepperDrive and CliffGuard policy are original integration code under
the repository MIT license. No wtlx sketches or unlicensed video code were copied.
No external ToF driver has been incorporated; its license/transport behavior must
be verified before future integration.
