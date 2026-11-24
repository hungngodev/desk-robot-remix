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

| Sensor | Relevant specification | Role in this project |
| --- | --- | --- |
| [VL53L0X](https://www.st.com/resource/en/datasheet/vl53l0x.pdf) | Up to 2 m, approximately 25° FoV; ST lists cliff detection as an application. The datasheet does not guarantee a useful near-zero range. | Selected eight-channel candidate: four downward, one forward, and three read-only side/rear positions **only after applicable physical qualification**. |
| [VL53L1X](https://www.st.com/resource/en/datasheet/vl53l1x.pdf) | Guaranteed minimum 40 mm; below this detection can occur but distance is inaccurate. Up to 4 m and programmable ROI. | Optional front/narrow-FoV upgrade. Longer maximum range does not solve a low-mounted floor sensor. Different driver, not a drop-in. |
| [VL6180X](https://www.st.com/resource/en/datasheet/vl6180x.pdf) | Specified 0–100 mm range; beyond 100 mm is conditional. | Better candidate for a floor window only 10–30 mm above the table. Separate driver and exact breakout voltage checks required. |

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
