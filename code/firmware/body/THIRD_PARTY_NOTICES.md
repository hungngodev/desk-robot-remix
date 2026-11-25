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
The guarded WROOM stepper and guarded DC firmware now pin Pololu's VL53L0X Arduino library at release 1.3.1 for module initialization (Pololu MIT and STMicroelectronics BSD-3-Clause terms for ST API-derived portions; see complete pinned notice below). The critical runtime uses bounded nonblocking 0x13/0x14/0x0B I2C protocol reads instead of blocking in its readRangeContinuousMillimeters() method. Pinned library and manufacturer source are reused, not a custom sensor startup stack. Generic low-cost GY-530 board voltage, short-range optics and physical loaded desk stop remain unqualified. The previous VL53L4CD dependency is no longer selected.

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
a person or operate the charger or motors. The full pinned [BSD-3-Clause notice](../../../docs/licenses/Seeed-PN532-BSD-3-Clause.txt)
retains both original copyright holders (Adafruit Industries and Seeed Technology Inc.).
Include it in applicable source and binary distributions. The [upstream license](https://github.com/Seeed-Studio/PN532/blob/e61296876c1c3e66ef67156562c71324b389f5fa/LICENSE.md)
is retained as the revision-specific reference.
No real PN532 module, antenna, voltage or timing trial has passed.

## Pololu VL53L0X 1.3.1 complete upstream notice

Source: https://github.com/pololu/vl53l0x-arduino/blob/1.3.1/LICENSE.txt

Upstream license Git blob: `16b6dd0219e73573b153131899b4c7d7a9a4c12a`.
Retain both notices with applicable source and binary distributions.

```text
Copyright (c) 2017-2022 Pololu Corporation.  For more information, see

https://www.pololu.com/
https://forum.pololu.com/

Permission is hereby granted, free of charge, to any person
obtaining a copy of this software and associated documentation
files (the "Software"), to deal in the Software without
restriction, including without limitation the rights to use,
copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the
Software is furnished to do so, subject to the following
conditions:

The above copyright notice and this permission notice shall be
included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES
OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
OTHER DEALINGS IN THE SOFTWARE.

=================================================================

Most of the functionality of this library is based on the VL53L0X
API provided by ST (STSW-IMG005), and some of the explanatory
comments are quoted or paraphrased from the API source code, API
user manual (UM2039), and the VL53L0X datasheet.

The following applies to source code reproduced or derived from
the API:

-----------------------------------------------------------------

Copyright © 2016, STMicroelectronics International N.V.  All
rights reserved.

Redistribution and use in source and binary forms, with or
without modification, are permitted provided that the following
conditions are met:
* Redistributions of source code must retain the above copyright
notice, this list of conditions and the following disclaimer.
* Redistributions in binary form must reproduce the above
copyright notice, this list of conditions and the following
disclaimer in the documentation and/or other materials provided
with the distribution.
* Neither the name of STMicroelectronics nor the
names of its contributors may be used to endorse or promote
products derived from this software without specific prior
written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND
CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES,
INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, AND
NON-INFRINGEMENT OF INTELLECTUAL PROPERTY RIGHTS ARE DISCLAIMED.
IN NO EVENT SHALL STMICROELECTRONICS INTERNATIONAL N.V. BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT
OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS;
OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE
USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH
DAMAGE.

-----------------------------------------------------------------
```
