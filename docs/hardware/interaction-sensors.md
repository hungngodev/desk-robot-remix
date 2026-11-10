# Touch, handling and expressive interactions

Updated 2026-11-06. Required first additions: one head-touch input and one
six-axis motion sensor per robot. RGB lighting is optional. This specifies
integration and tests. The owned AT42QT1010 now has WROOM input polling,
debounced status and a local stop interlock in firmware, but no physical
wiring, shell test, flashing or qualifying trial has been completed.
The [photo inventory](photo-inventory-2026-11-04.md) now identifies an owned
BerryIMU and other spares. Hold a new prototype IMU purchase until the owned unit
has been identified and tested. The follow-up photo identifies an owned
Adafruit #1374 AT42QT1010 for robot one's head touch.

## Minimal hardware and current pin feasibility

| Part | Quantity per core | Proposed connection | Decision |
| --- | ---: | --- | --- |
| Owned AT42QT1010 touch breakout #1374 | 1 | WROOM GPIO34, powered at 3.3 V, common ground and momentary active-high OUT | One concealed head pad. Bench-test response through the shell and costume. TTP223 is a possible fleet equivalent |
| Owned BerryIMU accelerometer+gyro board | 1 | Proposed body I2C21/22 upstream of mux; exact older-board pins/supply/addresses to verify | Prototype reuse first. Likely V1, not proven; identify chips and acquire real samples before choosing driver. One photographed board does not cover five cores. LSM6DS3TR-C remains a conditional replacement only |
| Diffused RGB pixel + logic buffer/passives | 0 required;1 optional | Candidate SenseD10/GPIO9; qualified5V pixel, proper3.3-to-5V buffer | Optional mood/turn-taking glow. SD stays disabled/empty. Do not use body GPIO4 for the mux reset: it is a boot strapping pin and
the TCA9548A RESET must be pulled high to 3.3 V |
| Mechanical bumper switch | 0 required;1 optional | BodyGPIO35 with external3.3V pullup | Useful cheap collision reflex after a small mount; not a substitute for floor sensors |

BerryIMU supplies the required acceleration and gyro functions without requiring
use of its magnetometer/barometer. Do not use a compass as track odometry;
actuator magnets/current can disturb it. The GY-61 in the photos is consistent
with ADXL335 analog acceleration, not MPU6050 and not a gyro. Its three ADC lines
are less convenient than the existing I2C route. The mechanical tilt switch is
only a binary input. See the photo audit for revision and electrical checks.

MPU6050/GY-521 can be evaluated if separately owned and functioning. It is an older,
discontinued part, not the new five-unit baseline. Do not buy a9-axis compass for
these interactions: a six-axis accelerometer+gyro is sufficient. A LIS3DH-only
alternative measures acceleration/tilt but has no gyro; it is not an equivalent
six-axis substitution.

GPIO34/35/36/39 are input-only with no internal pullups. Keep one owner for body
I2C and bounded reads; IMU processing must not delay the floor/stop path. The IMU
addresses must be checked against mux0x70 and ToF0x29 before final allocation.
The optional BMP280 can conflict with a BerryIMU pressure sensor at0x77; leave
the redundant sensor disconnected unless that address collision is resolved.
Anonymous breakouts must have
verified supply, pullups and logic levels; an IC specification is not proof of
board-level5V tolerance. No BerryIMU envelope has been measured for this build.

For an optional5V NeoPixel, use a guaranteed compatible level buffer such as
SN74AHCT1G125, plus appropriate decoupling/data resistor. Native ESP-IDF
`espressif/led_strip` is the reviewed head integration route. A bare LED plus
resistor or the existing onboard indicator is a cheaper alternative; do not
assume direct3.3V data works with every5V RGB pixel. No LED route is compiled yet.
A visible laser supplies no additional sensing and the fixed head cannot aim it
independently; the first build uses eyes/audio and optional diffused light.

## Behavior contract

| Event | Reaction | Guard |
| --- | --- | --- |
| Head pat, stationary | Happy eyes/short sound, brief interaction state | Debounce/coalesce; no movement implicitly authorized |
| Touch during exploration | Body disarms drive locally on the debounced rising edge, holds last servo output and then reports the touch | Touch is not an automatic rearm/resume command; no arm while pressed |
| Double tap, stationary | Invite conversation or show attention | Respect active speech, quiet settings and cooldown |
| Deliberate long touch | Quiet/pause state | Never authorize motors through this gesture |
| Gentle tilt/rotation | Eyes lean/look curious; short sound if appropriate | Excessive tilt suppresses drive; thresholds are calibrated on actual hardware |
| Shake | Surprised/dizzy reaction | Reject normal track/servo vibration and own animated motion; cooldown repeated events |
| Suspected pickup | Stop tracks before expression/voice; held-like response | Fuse IMU transient/attitude, multiple floor-range changes and touch/context. IMU alone cannot prove a level robot is held still |
| Put down | Confirm fresh floor/attitude stability, display ready | Do not clear latched faults or resume canceled movement automatically |
| Clap/loud sound | Startle/attentive eyes | Existing mic, no added sensor. Adaptive room noise and cooldown; reject own TTS/motors. One mic cannot supply sound bearing |
| Person/hand/peekaboo | Look/recognize a visual event and react | Existing camera; use fresh events, confirmation and quiet/speech ownership. No claimed face identity or hand recognizer before its tests |
| Rest/quiet hours | Sleepy face and lower initiation rate | Use real Mac time/settings, not uptime modulo24. Personality energy is not battery charge |

Keep local reflexes, expression and high-level planning separate. Body input or
floor/attitude faults stop drive before any Mac/LLM round trip. Head-local visual
reactions can remain responsive offline. The Mac combines recent typed events
with each robot's activity/mood and chooses higher-level comments/tasks.
Existing bounded movement, watchdog and local-only fault recovery stay in force;
the current unqualified sensor build still cannot arm.

Proposed event vocabulary: touch tap/double/hold, tilt/shake, suspected-held,
put-down, bumper, loud-sound and person/scene change. Carry robot identity and
observation time, reject stale/reconnected events and never equate a reaction
with permission to drive. Extend the existing UART/event boundary deliberately;
these are not existing supported wire commands.

## Actual code to reuse

- [Stackchan-agent Behavior.hpp](https://github.com/botamochi6277/stackchan-agent/blob/bfb98fb8bdb4f8ecc4b7c1c4f9bc90ee5227e613/include/Behavior.hpp)
  is MIT, hardware-independent and PC-tested. It supplies idle/attentive/
  interacting/talking/sleeping/low-battery states and an idle action picker.
  Adapt its inputs and expression outputs; head-motion actions become eyes/sounds
  unless separately permitted body movement is appropriate.
- Its [SoundMonitor.hpp](https://github.com/botamochi6277/stackchan-agent/blob/bfb98fb8bdb4f8ecc4b7c1c4f9bc90ee5227e613/include/SoundMonitor.hpp)
  supplies adaptive-noise/RMS/cooldown logic. Add own-playback/motor context.
- FocusBot supplies inspected touch/IMU interaction ideas, but missing copying
  terms and blocking touch delays make it an unsuitable direct code base.
  Yumo supplies reaction/choreography ideas under PolyForm Noncommercial terms.
- Reachy supplies speech/listening arbitration and orientation reporting;
  Google's agent supplies camera-event handling. Neither automatically supplies
  our held-state fusion. See [complete source map](../source-map.md).
- WROOM driver route: identify the owned BerryIMU version first; use the maker's
  version-detection/register examples as a reviewed reference, not an assumed
  drop-in LSM6 driver. LSM6DS/BusIO/Unified Sensor applies only to that conditional
  replacement. The AT42QT1010 needs a digital event adapter rather than a special
  library. No BerryIMU driver has been imported, compiled or physically tested.

## Optional later ideas, without a sensor shopping spree

A second touch zone can distinguish head/back contact; multiple zones are needed
for directional stroking. The **owned reed-switch module** and a magnet-equipped
accessory can enable a simple feeding/presence game without buying a Hall sensor;
it cannot identify different accessories by itself. Keep the module optional
until its pin/mount/voltage checks pass. A simple light sensor can support dark-room sleep;
camera auto-exposure is not a calibrated lux reading. A small jaw/contact switch
can provide contact evidence, but not gripping force or proof of pickup.
Battery-aware behavior requires the selected power module's qualified status or
a real monitor; no mood meter or raw assumed voltage means remaining capacity.
All of these stay optional until their small mount/pin/cost benefit is established.
Do not add an ultrasonic sensor, second camera or extra controller solely to
produce another reaction already possible with the existing camera/mic/ToFs.

## Acceptance before duplication

- A10: detect tap/double/hold through actual case; suppress bounce/repeated events;
  touching during motion stops/pauses before the expression path. Existing body
  firmware now distinguishes single tap, double tap and long hold using debounced
  edges and local uptime, while retaining immediate local motion stop. Candidate
  software windows are a short touch up to 600 ms, a second tap ending within
  350 ms of the first release, and a hold of at least 900 ms. The final windows
  and touch response through the shell still require measured trials. Typed
  counters flow through the existing head UART status to firsthand Mac memory.
  It cannot rearm.
- A11: recognize intended tilt/shake and suspected handling while rejecting normal
  loaded motor/servo vibration. Held/unsafe attitude inhibits tracks. Putdown,
  reconnect and reboot do not automatically resume them. Record thresholds/data.
- A12: repeated loud self-speech/motor activity does not startle the robot; real
  external sound/touch events remain responsive during camera/audio load.
- Optional LED: verify voltage/buffer/pin/SD assumptions and load; quiet mode and
  fault status remain consistent. No laser is required.
- Repeat on every built unit. Source code, host tests and hardware acceptance
  remain separately recorded.

Primary electrical references include
[Adafruit AT42QT1010](https://www.adafruit.com/product/1374),
[Tontek TTP223](https://www.tontek.com.tw/uploads/product/244/TTP223-CA6_V2.0_EN.pdf),
[ST LSM6DS3TR-C](https://www.st.com/en/mems-and-sensors/lsm6ds3tr-c.html),
[Adafruit pinouts](https://learn.adafruit.com/adafruit-lsm6ds3tr-c-6-dof-accel-gyro-imu/pinouts),
[Espressif GPIO](https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/peripherals/gpio.html),
[LED driver](https://components.espressif.com/components/espressif/led_strip),
[TI level buffer](https://www.ti.com/product/SN74AHCT1G125).
