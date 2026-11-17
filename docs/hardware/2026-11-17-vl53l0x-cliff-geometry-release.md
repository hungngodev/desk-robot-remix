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
The script independently checks the existing firmware threshold and CAD
lens center, then calculates a conservative required forward offset:

`required lead = p95 measured braking distance + actual unaccounted
sensor/controller latency * speed + clearance margin`.

A sensor that reports a cliff only once the leading wheel reaches the edge
cannot prevent falling, even if its range reading is perfect. The firmware
`CliffGuard` latches invalid readings or out of range but hardware placement
and stopping inertia remain physical proof obligations.

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
