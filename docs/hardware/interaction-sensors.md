> 2026-11-10 correction: the MPU6050 is the preferred six-axis sensor. The user reports using it; whether the photographed older BerryIMU is electrically correct remains unconfirmed. Existing prose referring to mandatory BerryIMU is historical. A valid MPU raw sample is **not** a tested tilt, shaking or held-state interlock. See the current WROOM driver and [official register map](https://invensense.tdk.com/wp-content/uploads/2015/02/MPU-6000-Register-Map.pdf).

# Touch, handling and expressive interactions

Updated 2026-11-06. Required first additions: one head-touch input and one
six-axis motion sensor per robot. RGB lighting is optional. This specifies
integration and tests. The owned AT42QT1010 now has WROOM input polling,
debounced status and a local stop interlock in firmware, but no physical
wiring, shell test, flashing or qualifying trial has been completed.
The [photo inventory](photo-inventory-2026-11-04.md) now identifies an owned
BerryIMU and other spares. A new WROOM boot-time WHO_AM_I probe now
reports likely V1/V2/V3 chip identity in `status.imu` using the existing
upstream I2C bus. This does not read actual acceleration/gyro data, implement
tilt interlocks or prove a mounted working sensor. Hold additional IMU purchases
until the owned unit is identified and tested. The follow-up photo identifies an owned
Adafruit #1374 AT42QT1010 for robot one's head touch.

## Minimal hardware and current pin feasibility

| Part | Quantity per core | Proposed connection | Decision |
| --- | ---: | --- | --- |
| Owned AT42QT1010 touch breakout #1374 | 1 | WROOM GPIO34, powered at 3.3 V, common ground and momentary active-high OUT | One concealed head pad. Bench-test response through the shell and costume. TTP223 is a possible fleet equivalent |
| MPU6050 / likely GY-521 module (user reported) | 1 | WROOM GPIO21 SDA / GPIO22 SCL upstream of TCA9548A; verify 3.3 V logic and actual breakout power path | **Preferred prototype IMU**, family 4. Boot WHO_AM_I register 0x75 must return 0x68 at bus address 0x68 or 0x69. Six-axis signed samples via register 0x3B. Physical mounting and handling classification still unqualified. Stock count unknown | 
| Photographed BerryIMU (optional compatible alternative) | 0 required | Same upstream I2C only if MPU6050 removed | Preserve V1/V2/V3 support; never join two unqualified IMUs or assume this photographed chip revision |
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
| Deliberate long touch | WROOM hold event enters Mac pet quiet mode, cancelling its active spontaneous reply | Never authorize motors or clear faults through this gesture; physical response still unqualified |
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
  library. The existing WROOM now compiles a bounded raw six-axis BerryIMU
  reader for the identified V1/V2/V3 chip, reusing the existing TofBus identity
  and upstream Wire bus. Actual voltage, identity and response remain physically
  untested. No calibrated safety reaction is enabled.

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
  edges and local uptime. One **raw sampled high** independently stops the
  current WROOM motor lease before three-sample gesture classification, and
  blocks a new arm while raw or stable input remains pressed. Candidate
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

## Read-only BerryIMU identity gate before any motion driver

The WROOM firmware now uses the **already initialized body Wire bus** to check
WHO_AM_I register 0x0F at the maker's known BerryIMU address candidates.
It briefly disconnects downstream TCA9548A ports for the probe; subsequent
ToF polls select their own channels again. The published chip pairs used only
for classification are: **V1 LSM9DS0** gyro 0xD4 and accel/mag 0x49,
**V2 LSM9DS1** gyro/accel 0x68 and magnetometer 0x3D, and
**V3 LSM6DSL/LIS3MDL** gyro/accel 0x6A and magnetometer 0x3D.
The board may use either documented address option, and a nonmatching pair
remains `family=0`, not an assumed driver or a claimed functioning IMU.

A bounded `status.imu` object exposes `family`, `gyro_id` and `aux_id`
for the direct USB inspection tool and through the existing Sense UART bridge.
Firmware now additionally configures the matching V1/V2/V3 accelerometer and
gyro at conservative data rates and samples six raw signed axes every 50ms.
The `status.imu` object retains the three original identity fields and adds
`valid`, `acc`, `gyro` and `age_ms`. Samples older than 200ms become invalid.
The same read-only fields appear in the existing local USB serial bench tool,
which reports `raw_six_axis_available=true` only for a currently
valid raw sample, while `attitude_interlock_active=false` and
`physical_qualification_pass=false` remain explicit. The readings do not
mean tilt is safe or calibrated.
Nothing grants movement, changes the five-sensor cliff decisions or clears
the locally latched faults.

The V1 candidate has mature reusable
[Adafruit LSM9DS0 Arduino code](https://github.com/adafruit/Adafruit_LSM9DS0_Library)
with a BSD license and
[SparkFun LSM9DS0 Arduino code](https://github.com/sparkfun/SparkFun_LSM9DS0_Arduino_Library)
with explicit Beerware reuse terms. Their I2C addresses and error handling must still be checked against the
**actual** chip and the existing 15ms I2C timeout. The selected code adapts
the OzzMaker register mappings directly rather than loading a second competing
sensor library. Keep its provenance and upstream terms under review.
V2/V3 use their respective chip register layouts, never V1 registers.

Qualification still needs a real stationary gravity sample, known PCB axes,
gyro bias, tilt/shake vibration rejection with steppers and servos operating,
pickup/setdown fusion with four downward ranges, timing and a local drive
inhibit when unsafe. None of those physical A11 tests has been performed.


## Six-axis sampling and actual mounting qualification

The latest WROOM code reuses `TofBus::probe_imu` rather than probing the I2C
bus twice. After identifying the model and addresses, the `BerryImu` adapter
reads three accelerometer and three gyroscope register pairs using the same
upstream 3.3V GPIO21/22 Wire bus. No second I2C controller, new user-facing
server or sensor-to-motor permission is created. The 320G family is explicitly
unsupported pending a matching register mapping and verification.

All values are raw signed register counts. They are **not** tilt degrees or
meters per second squared. First verify the breakout supply and printed pins,
then test a stationary gravity sample, each known physical axis, motion
vibration, motor noise, disconnect/reconnect, and the actual ages through
`code/scripts/serial_bench.py --inspect` with the robot on a catch tray.
The current six-axis driver does not implement local tilt stops or reliable
picked-up/set-down recognition. Those require calibrated board orientation,
noise thresholds and physical tests before trusted body interlocks can be armed.


## Required raw IMU heartbeat before local arm

The physical ESP32 WROOM firmware now requires an identified fresh BerryIMU
six-axis sample before accepting `arm`; a missing, invalid or older than
200ms sensor sample rejects arming. If it becomes missing or stale during an
armed movement, WROOM freezes servo targets, zeros both tracks and disarms
before its separate 500ms communication watchdog. The Mac checks the identical
raw readout through the existing authenticated head status before an operator
permit and again before a controlled job. Bench tests include a mid-drive
expired sample and verify that neither a fresh network request nor a status
read can resume motion automatically.

This heartbeat **does not implement a calibrated tilt, shake or held-state
interlock**. A fresh reading with a gravity vector is not proof that a robot
is on a desk or level. All movement remains blocked by the five real ToF
requirements until measured calibration and local USB rearm. Before any desk
trial, the operator must additionally establish each board axis, loaded
stopping distance, power integrity and tilt/held thresholds on a catch tray.


### BerryIMU upstream identity collision handling

This build adapts the paired WHO_AM_I approach from the existing OzzMaker
BerryIMU Arduino `detectIMU()` implementation. It scans both possible
acceleration/gyro addresses and the three known accessory addresses. Multiple
recognized devices on either side now produce **unknown**, rather than
selecting the first reply and driving potentially mismatched registers.
A 320G WHO_AM_I value `0x73` is observed for diagnosis but deliberately
cannot arm the V1/V2/V3 sampler. This is not equivalent to a physical revision
check or to a board voltage measurement. See OzzMaker's original quick-start
for V3 I2C versus SPI jumper settings.


### Extra inputs now connected to event provenance, not to motor permission

The WROOM `extras` status object includes an enabled physical mask, debounced
bumper/magnet/PIR rising counters, and current levels. A single real bumper
HIGH/LOW electrical contact trips motion locally before debounce, while the
same event can later cancel a Mac coordinator job. PIR reports an infrared
*change*, not an identified visitor; reed reports a magnetic closure, not a
particular hat. A Mac robot records these as that robot's firsthand events and
optional fleet sharing retains its reported source. Unplugged or unenabled
sensor inputs cannot invent an event. This does not establish physical
accuracy, installed pin voltage, or reliable detached/held handling.

Both the AT42QT1010's HIGH-on-touch hardware output and MPU6050's WHO_AM_I
are reviewed against vendor data. The optional BMP280 requires a different
Bosch compensated pressure/temperature sensor library and a mux lane rather
than silently reusing the six-axis MPU registers. No additional body sensor
board was purchased or claimed functional.


## Single-robot CAP1188 read-only USB diagnostics

The existing `code/scripts/serial_bench.py --inspect --samples 10` now reports `cap_touch.reported`, `cap_touch.valid`, `cap_touch.zone_mask` (0..255) and `cap_touch.rising_zone_events` from *actual* WROOM CAP1188 telemetry. It rejects partial, forged or out-of-range fields and always reports `physical_qualification_pass=false`; it never arms or recovers the local guard. This is the same USB inspection path used for five VL53L0X, MPU6050, bumper, PIR and reed. New Python tests include an 8-zone mask, missing fields, invalid types and counts. The actual electrode padding and through-shell physical trial remains open.
