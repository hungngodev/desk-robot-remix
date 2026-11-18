# Which distance sensor to buy first

Updated 2026-11-03. The user is comparing GODIYMODULES VL53L1X (advertised 4–400 cm)
with TENSTAR VL53L0X CJVL53L0XV2 two/five-packs. No exact sensor order, price or
delivered PCB has been verified. Seller labels are not a new required component.

**Recommendation: keep VL53L0X as the inexpensive prototype candidate. Start with
two samples for stationary tests; one five-pack can equip robot one if the mount
qualifies. Do not buy 25 fleet sensors yet. VL53L1X is not a required upgrade.**

| Sensor | Relevant specification | Role in this project |
| --- | --- | --- |
| [VL53L0X](https://www.st.com/resource/en/datasheet/vl53l0x.pdf) | Up to 2 m, approximately 25° FoV; ST lists cliff detection as an application. The datasheet does not guarantee a useful near-zero range. | Budget candidate for front obstacle sensing and four downward positions **only after standoff/stop qualification**. |
| [VL53L1X](https://www.st.com/resource/en/datasheet/vl53l1x.pdf) | Guaranteed minimum 40 mm; below this detection can occur but distance is inaccurate. Up to 4 m and programmable ROI. | Optional front/narrow-FoV upgrade. Longer maximum range does not solve a low-mounted floor sensor. Different driver, not a drop-in. |
| [VL6180X](https://www.st.com/resource/en/datasheet/vl6180x.pdf) | Specified 0–100 mm range; beyond 100 mm is conditional. | Better candidate for a floor window only 10–30 mm above the table. Separate driver and exact breakout voltage checks required. |

A downward sensor checks whether the tabletop is still under its view. A forward
sensor checks obstacles ahead. **One module cannot do both jobs at once.** Initial
full-core topology remains four down + one forward through the body-owned mux.
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

Compare one real raised L0X corner with a low VL6180X option before final CAD.
If the compact layout only permits a 10–30 mm window height, change the downward
sensor choice rather than pretending the L0X fits. Front L0X can remain.

## Breakout and test requirements

TENSTAR/GODIYMODULES describe sellers; CJVL53L0XV2 describes a PCB variant. Verify
actual chip/board, voltage regulator, pullups and pin labels. A 5 V-compatible VIN
does not prove safe 3.3 V I²C signal levels. Bare VL6180X supply requirements differ
from L0X/L1X; do not apply a bare-chip rating to an unidentified breakout.

Different sensor drivers must report invalid/no-return/stale data as faults,
not clear floor. Use the WROOM local stop, calibrated surface intervals and
tether/catch trials. Never use the guide's universal 65 mm threshold or blind
reverse. Keep full fleet shopping pending a passing prototype.
