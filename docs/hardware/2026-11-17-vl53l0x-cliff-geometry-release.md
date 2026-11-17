# Eight low cost VL53L0X: actual cliff geometry release contract

**No five robot purchase approval.** The source selected is a particular
[ElectroPeak SEN-19-006 GY-530](https://electropeak.com/gy-530-vl53l0x-laser-range-finder)
rather than the premium VL53L4CD board. The vendor advertises USD 1.76 per
module before shipping, 10.5 x 13.3 mm envelope, 2.8 to 5 V supply, 30 mm
to 2 m sensing and I2C. This is a source candidate, not a schematic or tested
logic level. The frozen purchasing role is 8 per robot, 40 total.

Reuse: firmware `code/firmware/body/lib/TofBus/TofBus.cpp` uses the existing
pinned [Pololu VL53L0X source](https://github.com/pololu/vl53l0x-arduino),
TCA9548A 0x70 separate channels 0 through 7. Source checks reject
distance below 30 mm as invalid; it will not count a 13 mm optical path as
a reliable cliff sample.

## Actual bracket geometry, not a guessed chassis clearance

Current `docs/cad/remixes/one_robot_adapter_kit.scad` has:
* `tof_pcb_h = 18` mm
* `face_z = tof_pcb_h + 7` mm
* lens opening center at `face_z / 2 + 1`, **13.5 mm above
  the printed adapter mounting plane**

Thus a flush desk mount has only **13.5 mm** floor optical path, **below
the production driver minimum 30 mm**. A chassis mounting plane 20 mm
above the desk produces **33.5 mm** vertical optical path, barely inside
the source valid range on paper. It needs real margin and surface testing
rather than being accepted as universal. Physical mounting height, actual
lens position, optical direction and the chosen wheel/chassis are still
unmeasured.

Execute `python code/scripts/cliff_mount_preflight.py
--mount-above-desk-mm VALUE --tilt-deg VALUE
--sensor-ahead-of-wheel-mm VALUE --measured-stopping-mm VALUE
--latency-ms VALUE --speed-mm-s VALUE` with actual numbers.
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

`physical sensor ahead of leading wheel > p95 braking distance +
remaining sensor/controller latency * speed +
engineering clearance margin + rearward echo setback`.

The source also checks the closest and farthest optical path across the
full FoV against the **actual firmware** 30..1300 mm acceptance range, and
rejects tilt where the cone reaches the horizon. It deliberately gives no
extra braking credit for a forward tilted optical axis.

**Specific prior false positive:** with mount 20 mm above desk and current
13.5 mm adapter optical center, height is 33.5 mm. ST's 25 degree FoV
leaves `33.5 * tan(12.5 degrees) = 7.43 mm` of potential rearward floor
reflection. At speed 100 mm/s, assumed 80 ms sensor latency, 10 mm observed
p95 stopping and 10 mm reserve, the required clearance is 28 mm **plus
7.43 mm**. A 32 mm ahead-of-wheel sensor looks safe under the previous
point-ray equation, but has just 24.57 mm effective lead and is now
correctly rejected by both the geometry code and committed regressions.

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
