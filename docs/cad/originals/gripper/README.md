# Bluino SMARS gripper — original files

Downloaded unchanged from [Bluino's files page](https://www.thingiverse.com/thing:4253681/files):

- [servo_case_arm.stl](servo_case_arm.stl)
- [arm_rack.stl](arm_rack.stl)
- [pinion_gear.stl](pinion_gear.stl)

Author **bluino**, **[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)**
as linked by the source page. Direct download URLs, hashes, file sizes, triangle
counts and coordinate bounds are in [source.json](source.json). Preserve this
attribution and identify any changes on future remixes. Original files stay here.

These binary STL files have no unit metadata. Verify millimeter interpretation
against the original assembly and your measured servo before slicing. A valid
file and measured bounds do not establish watertightness, printability or fit.
No mesh repair or other geometry change has been performed.

### EXP-053 source topology screen

At reviewed PR commit `6e673ae365e55744e85000b13ba7c4ed39fc33d0`,
the original binary STL files were decoded directly and triangle edge
incidence counted using exact Float32 vertex coordinates:

| Original | Triangles | Boundary edges (one face) | Nonmanifold edges (more than two faces) |
| --- | ---: | ---: | ---: |
| arm_rack.stl | 344 | 4 | 14 |
| pinion_gear.stl | 1364 | 0 | 0 |
| servo_case_arm.stl | 8062 | 50 | 63 |

Rounding coordinates to 0.001 mm gave the same counts. This screen does not
establish connected-shell validity, winding, strength or mesh fit. The canonical
Fusion scaffold also invokes the existing strict STL checker and reports a
jaw topology HOLD without modifying these licensed originals. The case and rack
must remain reference geometry until an attributed derived copy is repaired
using [Fusion Mesh Repair](https://help.autodesk.com/cloudhelp/ENU/Fusion-Mesh/files/MESH-REPAIR.htm)
or an equivalent reviewed method. Compare tooth pitch, shaft datum, rack guide,
horn screw seat and all critical dimensions before and after repair; do not
use a global shrink, scale or wrap to hide teeth interference. A passing mesh
check does not establish backlash, usable endpoint angles, FSR pressure or
mechanical fit. No repair has been performed here.

The author separately links `fork_lift_e.stl` and `fork_lift_f.stl`. Those original
files and their assembly PDF are [saved separately](../forklift/README.md), with
tristomietitoredeituit's CC BY-NC-SA 4.0 attribution. Do not apply Bluino's
CC BY 4.0 license to them. The rover/chassis and hardware are separate parts.

Follow [the first gripper test](../../../guides/first-gripper-test.md), starting
with a servo-pocket fit sample and real flat-key/candy trials.
