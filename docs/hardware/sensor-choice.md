# Which distance sensor to buy first

Updated 2026-11-24. The November 3 comparison of GODIYMODULES VL53L1X
and TENSTAR VL53L0X CJVL53L0XV2 was historical, not the current purchase list.

**Current selection:** follow [full-feature-plan.json](full-feature-plan.json).
The selected inexpensive range chip is VL53L0X. The exact pilot source candidate
is ElectroPeak GY-530 SEN-19-006 (nominal 10.5 by 13.3 mm PCB), not an approved
installed carrier. Buy or borrow **one** sample for stationary qualification;
seven additional first-robot modules and the fleet order remain on HOLD.
The selected handling IMU is MPU6050 / GY-521; retain the reported BerryIMU
only as a spare, not a second installed IMU or a reason to alter the chassis.
Do not substitute either sensor without the existing engineering decision and
qualification process.

| Sensor / ST datasheet | Ranging FoV and distance | Timing / update capability | Bare sensor current (nominal 2.8 V) | Project role |
| --- | --- | --- | --- | --- |
| [VL53L0X, DS11555 Rev 6](https://www.st.com/resource/en/datasheet/vl53l0x.pdf), §§5.4, 6.1–6.3 | 25° system FoV; up to 2 m under favorable long-range conditions; no guaranteed near-zero accuracy | 20 ms high-speed profile; 33 ms long-range budget; not a guaranteed application update rate | 19 mA typical active (33 ms default API); 40 mA peak | Selected eight-channel low-cost candidate; qualify exact standoff, optics and local stopping |
| [VL53L1X, DS12385 Rev 8](https://www.st.com/resource/en/datasheet/vl53l1x.pdf), §§6.4, 7.3–7.6 | 27° full diagonal FoV, ROI down to 15° diagonal; 40 mm minimum ensured; up to 4 m in darkness with 140 ms budget and bright target | Up to 50 Hz headline rate, not at the 4 m test condition | 16 mA typical / 18 mA max active in long mode; 40 mA peak | Optional front alternative, not a low-floor solution or drop-in driver |
| [VL53L4CD, DS13812 Rev 8](https://www.st.com/resource/en/datasheet/vl53l4cd.pdf), features and §5.4 | 18° diagonal FoV; 1 mm short-distance linearity, up to 1200 mm with full FoV | Up to 100 Hz | 22 mA typical / 24 mA max active with default driver; 40 mA peak | Former selection; technically relevant if L0X fails short-range qualification, not selected or interchangeable in firmware |
| [VL6180X, DocID026171 Rev 7](https://www.st.com/resource/en/datasheet/vl6180x.pdf), §§2.9, 3.1 | 0–100 mm characterized proximity range; longer distances conditional. 25° ranging FoV per carrier vendor (not the separate ALS FoV) | 15 ms maximum convergence time in §3.1 test conditions, not total conversion/update period | 1.7 mA average at 10 Hz, 50 mm, 17% target; 38 mA instantaneous peak on combined rails | Short-range alternative only after explicit selection review, separate driver and carrier qualification |

Current figures use different operating modes and cannot be ranked as equal-duty
power measurements. They exclude carrier regulators, LEDs, pull-ups, muxes and
other loads. Eight L0X devices can draw overlapping emitter pulses: plan for up
to 320 mA aggregate sensor peak as an arithmetic design case, not a measured
rail maximum or a complete current budget. An I2C mux isolates addressing, not
sensor supply or optical emissions. Measure actual simultaneous ranging current,
rail transients, crosstalk and end-to-end sample ages with all eight fitted.

Price is a supplier property, not a datasheet specification. For a same-vendor
reference, [Pololu's carrier comparison](https://www.pololu.com/category/306/carriers-for-st-time-of-flight-tof-distance-sensors)
lists single-unit USD prices (accessed 2026-11-24): L0X $19.95, L1X $22.95,
L4CD $13.95, and 6180X $19.95. These are premium carrier reference prices, not
the selected generic boards, delivered prices, stock or purchase approval. They
do not establish that L0X is cheaper on every carrier. The generic ElectroPeak
SEN-19-006 candidate and its historical quote are maintained only in the
[procurement generator](../../code/scripts/procurement_release.py) and generated
[shopping checklist](complete-shopping-checklist.md); verify current checkout,
shipping, tax, board variant and actual suitability before release.

The existing [WROOM ToF driver](../../code/firmware/body/lib/TofBus/TofBus.cpp)
sets a 33 ms measurement budget and starts continuous ranging via pinned Pololu
VL53L0X Arduino 1.3.1 (see [firmware profiles](../../code/firmware/body/platformio.ini)).
The budget is not a measured eight-lane refresh interval or cliff-stop latency.
The [Mac optical validator](../../code/laptop/src/desk_robot/tof_optics.py)
checks eight-lane raw signal/ambient 9.7 MCPS words, identity, validity masks and
sample ages (critical lanes below 200 ms, diagnostic lanes at most 350 ms).
These are read-only diagnostic freshness limits, not measured response times,
distance calibration or clearance authority. The [existing regression tests](../../code/tests/test_tof_optics.py)
exercise this provenance boundary; physical acceptance remains open.

A downward sensor checks whether the tabletop is still under its view. A forward
sensor checks obstacles ahead. **One module cannot do both jobs at once.** The
current full-core topology is four down + one forward (movement authority), and
left, right and rear (read-only), through the body-owned 3.3 V TCA9548A range mux.
A rear or side reading never grants motion authority.
No range sensor arrangement alone establishes that the robot cannot fall.

## Near-field correction to the drawing

The current rough image's sensor markers near 14 mm are **not approved L0X/L1X
mounts**. An ST employee discussion warns that L0X measurements below roughly 3 cm
are tricky; this is not a guaranteed 3 cm limit. Begin L0X bench experiments at
approximately 40–60 mm measured surface range, then qualify the actual module,
table, lighting and timing. [ST discussion](https://community.st.com/mems-sensors-48/minimum-distance-measurement-by-vl53l0x-34583).

Raised corner brackets are a possible small remix, but increase the footprint.
For a 25° full-FoV cone, a flat floor spot has approximate diameter:

`2 × height × tan(12.5°)`

At 40/50/60 mm height this is about 17.7/22.2/26.6 mm. The actual sensor response is
not a perfect hard-edged cone. Keep tracks, wires, costume, gripper and payload
out of that view. Derive lead from measured sample age, decision time and coast.

For illustration only, the concept's tracks occupy roughly x±48, y±47 mm. At 50 mm
height, putting the **whole** spot beyond relevant edges requires centers around
x±59.1, y±58.1 mm even before a stopping margin or PCB size. This is already a
118×116mm sensor-center rectangle. It is not a qualified mounting drawing.
Do not hide that width increase in the next product render.

Test one real raised L0X corner before final CAD. If the compact layout only
permits a 10–30 mm window height, keep that mounting location unqualified and
redesign the mount or explicitly reopen sensor selection; do not silently switch
to a different driver or pretend the L0X fits. Record per-lane measured lens
centers, carrier and connector envelopes, optical path, cable clearance and
loaded stop geometry in the [Fusion measurement sheet](../cad/FUSION_MEASUREMENT_SHEET.md).
The existing aperture/angle reference does not retain a PCB.

## Breakout and test requirements

TENSTAR/GODIYMODULES describe sellers; CJVL53L0XV2 describes a PCB variant. Verify
actual chip/board, voltage regulator, pullups and pin labels. A 5 V-compatible VIN
does not prove safe 3.3 V I²C signal levels. Bare VL6180X supply requirements differ
from L0X/L1X; do not apply a bare-chip rating to an unidentified breakout.

The selected range driver must report invalid/no-return/stale critical data as faults,
not clear floor. Use the WROOM local stop, calibrated surface intervals and
tether/catch trials. Never use the guide's universal 65 mm threshold or blind
reverse. Keep full fleet shopping pending a passing prototype.
