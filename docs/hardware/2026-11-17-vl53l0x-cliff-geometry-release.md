# Eight low cost VL53L0X: actual cliff geometry release contract

**No five robot purchase approval.** The source selected is a particular
[ElectroPeak SEN-19-006 GY-530](https://electropeak.com/gy-530-vl53l0x-laser-range-finder)
rather than the premium VL53L4CD board. The vendor listed USD 1.44 per module on 2026-11-18 before shipping and tax, 10.5 x 13.3 mm envelope, 2.8 to 5 V supply, 30 mm
to 2 m sensing and I2C. This is a source candidate, not a schematic or tested
logic level. The frozen purchasing role is 8 per robot, 40 total.

Reuse: firmware `code/firmware/body/lib/TofBus/TofBus.cpp` uses the existing
pinned [Pololu VL53L0X source](https://github.com/pololu/vl53l0x-arduino),
TCA9548A 0x70 separate channels 0 through 7. Source checks reject
distance below 30 mm as invalid; it will not count a 13 mm optical path as
a reliable cliff sample.

## Actual bracket geometry, not a guessed chassis clearance

Current `docs/cad/remixes/one_robot_adapter_kit.scad` has:
* `tof_pcb_h = 13.3` mm (candidate carrier outline, not a measured lens offset)
* `face_z = tof_pcb_h + 7` mm
* lens opening center at `face_z / 2 + 1`, **11.15 mm above
  the printed adapter mounting plane**, calculated from provisional CAD

**Important unqualified mounting orientation:** The actual
`tof_adjustable` source drills the optical aperture through its upright face
with `rotate([90,0,0])`: the bore is parallel to the flat base mounting plane
and points horizontally when that base lies flat. It does **not** become a
downward cliff sensor merely because the lens center is 11.15 mm above its
base. All subsequent 11.15/31.15 mm path, 25 degree cone and wheel lead
calculations are only conditional geometry for a separately reoriented
sensor with measured lens height, downward optical axis, chassis mount and
wheel positions. A real 90 degree reorientation changes the source datum,
so do not transplant the 11.15 mm offset without measuring the final 3D
transform. The preflight now exports explicit `source_flat_base_points_optics_downward:
false` and `downward_optical_axis_reorientation_physically_verified: false`
flags. It cannot release motor movement or 40 ranger purchases.

Thus a flush desk mount has only **11.15 mm** nominal vertical optical
path, **below the production driver minimum 30 mm**. A chassis mounting
plane 20 mm above the desk produces **31.15 mm** nominal vertical optical
path, only 1.15 mm beyond the driver validity threshold on paper. It needs real margin and surface testing
rather than being accepted as universal. Physical mounting height, actual
lens position, optical direction and the chosen wheel/chassis are still
unmeasured.

Execute `python code/scripts/cliff_mount_preflight.py
--mount-above-desk-mm VALUE --tilt-deg VALUE
--sensor-ahead-of-wheel-mm VALUE --measured-worst-stopping-mm VALUE
--latency-ms VALUE --speed-mm-s VALUE` with actual numbers.

For an actual measured optical center use `--lens-above-desk-mm VALUE`
instead of `--mount-above-desk-mm VALUE` (never both). The latter remains
a provisional CAD datum calculation that adds 11.15 mm; it is not a
direct lens height. The straight-drive report records `lens_height_source`
to distinguish these modes. The separate 35/45/55 mm GY-530 trial coupons
specify support rim heights only; measure the installed lens above the
tabletop rather than entering the printed rim dimension. The per-lane
`--floor-mount-measurements` screen accepts direct measurements for
each of the four floor sensors. The planar coverage screen still uses
the provisional adapter datum and must not be confused with measured
per-lane lens geometry. None of these paper checks qualify the physical
cliff detector.
The script independently checks the firmware distance acceptance,
actual CAD lens position and ST's **25 degree system field of view**, then
calculates the available stopping offset. Primary source: [ST VL53L0X
DS11555 Rev 6, section 6.1, page 21](https://www.st.com/resource/en/datasheet/vl53l0x.pdf).
The manufacturer's range tables assume the full FoV is covered. A desk edge
violates that assumption, so its reported range may remain plausible while
some of its optical cone still intersects the table.

For a downward optical center at height `H`, nominal tilt `t` degrees
toward the front, and ST half FoV `b = 12.5 degrees`, the worst
backward floor echo footprint is bounded geometrically by
`rearward echo setback = max(0, -H * tan(t - b))`.
This geometric bound is a conservative **model**, not a guaranteed signal
response of a mixed/partial field or a measured false-negative probability.

The revised source requires:

`physical sensor ahead of leading wheel > highest observed loaded braking distance +
remaining sensor/controller latency * speed +
engineering clearance margin + rearward echo setback`.

The source also checks the closest and farthest optical path across the
full FoV against the **actual firmware** 30..1300 mm acceptance range, and
rejects tilt where the cone reaches the horizon. It deliberately gives no
extra braking credit for a forward tilted optical axis.

**Specific prior false positive:** with mount 20 mm above desk and current
11.15 mm adapter optical center, height is 31.15 mm. ST's 25 degree FoV
leaves `31.15 * tan(12.5 degrees) = 6.91 mm` of potential rearward floor
reflection. At speed 100 mm/s, assumed 80 ms sensor latency, 10 mm illustrative worst observed loaded stopping and 10 mm reserve, the required clearance is 28 mm **plus
6.91 mm**. A 32 mm ahead-of-wheel sensor looks safe under the previous
point-ray equation, but has just 25.09 mm effective lead and is now
correctly rejected by both the geometry code and committed regressions.

**November 17 fail-closed source corrections:** The planar four-floor-sensor
swept-contact check now requires the complete nominal FoV floor return path
to be inside the existing 30..1300 mm firmware range. In particular, a flush
adapter at only 11.15 mm nominal optical height may have ample geometric wheel lead
while yielding NO acceptable floor data; it must fail both criteria. The
forward `evaluate()` function no longer lets a p95-only stopping number
authorize a desk-edge geometry: the separate worst observed loaded stop
parameter is required, finite and at least the p95 diagnostic. The command
line now explicitly requests `--measured-worst-stopping-mm`. All test
examples that use 10 mm stopping are illustrative values, not physically
recorded robot brakes. Neither source correction proves a real edge stop.

A 25 degree FoV is not a proof of the exact location/strength of the last
return. With mixed reflections, lens windows, black table surfaces, ambient
light, multi-sensor interference and motor vibration, the actual time to
declare a cliff can be worse. The 25 degree footprint is a necessary
geometric screen, not a sufficient safety guarantee. Furthermore, p95
braking distance permits 5 percent exceedance; use measured worst-case
stopping over worst supplied voltage, load, turn, floor and fault condition
for the actual final safety margin. Neither p95 nor a CAD dimension alone
qualifies a high-consequence desk edge stop.

A sensor that reports a cliff only once the leading wheel reaches the edge
cannot prevent falling, even if its range reading is perfect. The firmware
`CliffGuard` latches invalid readings or out of range but hardware placement
and stopping inertia remain physical proof obligations.

## All-direction stopping, not just a forward ray

A forward lead calculation still cannot clear reverse, turn-in-place or
curved commands. The actual WROOM body source permits independent positive
and negative wheel speeds. For a differential drive with measured separation
`B` and left/right ground speeds `vL, vR`, the center translational
speed is `(vR+vL)/2`, the rotation rate is `(vR-vL)/B`, and a point
`(x,y)` on the chassis has instantaneous planar velocity
`(v - omega*y, omega*x)`. This is the standard publicly documented model
at [IEEE RAS University](https://www.ieee-ras.org/ras-university/?ras_page=docs%2Fchap2_sensing%2Fsensors-and-sensing)
and [York University's differential drive lab](https://www.eecs.yorku.ca/course_archive/2019-20/W/1011/labs/7/differential-drive-robot.html).
The pure Python `screen_planar_cliff_coverage` function in the EXISTING
`code/scripts/cliff_mount_preflight.py` implements these identities
without replacing any robot motor controller.

For every moving wheel or caster/other supporting contact, it calculates
that point's movement direction and speed, then checks whether at least one
of the **four downward** optical sensor positions is sufficiently ahead
along the point's actual movement tangent. It checks source-bound 25 degree
FoV rearward tabletop setback, observed worst braking distance, remaining
detection latency, and margin. Its strict default gives **zero lateral
coverage credit** absent qualified coverage measurements. An owner may
supply real lateral coverage, but cannot claim more than the sensor's
nominal optical footprint radius.

Run this pure function for the full set of reversible, straight, spin,
and maximum-curvature motor cases using the same actual on-chassis
sensor and support coordinates. An arrangement that passes straight
forward can fail on reverse or a zero-translation pivot. Example
regressions reproduce both patterns and require failure when exposed.
**It does NOT certify every possible curved trajectory or an actual
desk edge.** The four sensors need measured geometry, tilt, packet
freshness, return behavior and actual motor stop results before the design
may use their readings to permit near-edge motion.

The positions of **every load-bearing wheel/caster, corner and gripper
overhang** must be recorded, not only the two drive wheels. Overhanging
parts require their own collision/drop assessment; a fixed-body point
velocity alone does not model articulated gripper sweep. Mechanical CAD
interference, power path, communication fault and actuator stalls must
be separately checked. No wheel command or camera inference overrides a
local cliff stop.

## Real upstream driver and ST status semantics

The current WROOM bus is a justified remix rather than an invented second
VL53L0X driver. Pinned [Pololu VL53L0X Arduino source](https://github.com/pololu/vl53l0x-arduino/blob/master/VL53L0X.cpp)
initializes the device, sets the 0.25 MCPS final signal-rate threshold,
sets the 33 ms measurement budget, starts back-to-back continuous mode,
then waits on `RESULT_INTERRUPT_STATUS` (0x13), reads distance at
`RESULT_RANGE_STATUS + 10` (0x1e), and clears the interrupt (0x0b).
Our `TofBus` uses that same register sequence without blocking the safety
loop waiting for optical conversion.

**Do not confuse two different ST statuses.** Raw hardware device
status **11** indicates a good range before PAL processing, as documented in
[ST-derived VL53L0X API core source](https://android.googlesource.com/kernel/msm/+/f85e7d37509bbd17326f5281616a2425941a0ae8/drivers/input/misc/vl53L0/src/vl53l0_api_core.c).
The [official ST API UM2039](https://www.st.com/resource/en/user_manual/um2039-world-smallest-timeofflight-ranging-and-gesture-detection-sensor-application-programming-interface-stmicroelectronics.pdf)
exposes a processed RangeStatus **0** for a valid result, which can
also depend on signal and sigma checks. Thus the code's raw 11 check is
not an instruction to replace it with raw 0, **but neither is raw 11
a full guarantee** of trustworthy partial-field black-table results.
Rejecting raw non-11, no-target 8190 mm and out-of-band samples is a
necessary fail-closed behavior, not a manufacturer-certified cliff detector.

The final design MUST measure false-valid and false-invalid rates at
desk edges under partial FoV, black/gloss surfaces, strong ambient IR,
multiple simultaneously active neighboring VL53L0X sensors and hard
turning. An ST typical-range chart or an upstream library compile cannot
substitute for those observations. Retain physical checkout hold.

## Exact breakout electronics, no inferred five volt tolerance

The [ElectroPeak SEN-19-006 product page](https://electropeak.com/gy-530-vl53l0x-laser-range-finder)
states supply 2.8 to 5 V but **does not show its full regulator,
SDA/SCL voltage translation, or pullup network**.
A different [ElectroPeak GY-53](https://electropeak.com/gy-53-vl53l0x-laser-ranging-sensor-module)
explicitly documents I2C high = VIN. Do **not** assume these two modules
have the same PCB or safe input voltage; nor assume all generic GY-530
clones are electrically identical. Use only a measured qualified 3.3 V
sensor carrier and 3.3 V compatible WROOM and mux signals. Never wire a
5 V pullup directly into ESP32 GPIO21 or GPIO22.

## One prototype acceptance, before multiplying to 40 units

1. Identify the actual SEN-19-006 PCB revision and measure powered VIN,
   sensor VDD, both levels on SDA/SCL and logic rise times on each TCA lane.
2. Print the sensor mount and measure the optical center above a real desk;
   use the same 30 mm validity policy as the production firmware.
3. Qualify dark matte, glossy, wood, black laminate, gaps, cords and table
   edge under sunlight, desk lighting and vibration at expected robot tilt.
4. Collect loaded speed, full sensor scan age, braking distance and
   time-to-stop across robot battery voltages. Check both forward motion and
   pivot/side clearance with the actual wheel base.
5. Physically disconnect a ranger, leave a mux selected, cause a Wire stall,
   and demand a local stop without camera, cloud model or Mac permission.

The tool and its host test only prove arithmetic and source agreement.
They intentionally always return `40_sensor_fleet_purchase_approved: false`.
The central `code/scripts/procurement_release.py` now requires a separate
`cliff_sensor_mount_height_and_stopping_geometry` evidence receipt
independent of generic ranger and motor test claims.


## VL53L0X temperature calibration, explicit RG4 decision

ST's [VL53L0X datasheet](https://www.st.com/resource/en/datasheet/vl53l0x.pdf)
states that the VHV and phase temperature reference calibration must be
repeated if device temperature changes by more than 8 degrees Celsius from
initial calibration. The pinned [Pololu initialization implementation](https://github.com/pololu/vl53l0x-arduino/blob/master/VL53L0X.cpp)
performs this reference calibration inside `init()` and does not expose a
supported temperature-only recalibration API. Do not manufacture an
undocumented private-register sequence.

**Selected safety policy for the present hardware:** do not perform
periodic automatic reinitialization of an actively moving floor sensor.
Doing so would remove safety observations while driving and could confuse
the four-lane cliff guard. A deliberate temperature recalibration requires
first disarming local WROOM motor authority, then a full reinitialization
of every connected VL53L0X on its isolated 0x70 mux channel, followed by
fresh five-channel critical readings, explicit operator calibration review
and separate local rearm. A failed initialization or any stale/missing
measurement remains latched and cannot be silently excused by warming up.

The current XIAO/WROOM parts do NOT supply a calibrated VL53L0X die
temperature measurement to enforce the manufacturer's 8 degree delta.
Room SHT41/BMP280 ambient temperature is not a validated substitute for
sensor die temperature, especially near the regulator, motors or sunlight.
Therefore there is NO claimed automatic thermal recertification and no
permission for unattended near-edge motion. Characterize warmup and
temperature changes on the real installed board, then select a documented
disarmed recalibration procedure before physical release. Do not add a
new sensor or replace Pololu without a separately measured benefit.
