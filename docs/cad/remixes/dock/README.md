# Printable passive dock alignment gauge

This is an example **fit tester**, not the final charging dock.

Source: dock_passive_fit.scad in the same directory. Change
track_outer_width_mm and side_clearance_each_mm to measured values in
OpenSCAD or Fusion. A 96 mm example outer track width plus 2 mm
clearance per side creates a 100 mm final channel and a flared entry.

This model has no live battery contacts, charging circuit or automatic
approach motor permission. The high rear backstop is a convenient
surface for positioning a printed AprilTag board; mark and measure its
side size with calipers for the actual XIAO camera calibration. Do not
print the tag distorted or assume that the backstop is a safe contact stop.

Nominal model geometry checked locally via OpenSCAD's CGAL renderer
and trimesh: **126 by 138 by 93 mm**, single connected watertight
triangle surface. The vertical backstop now has a centered shallow pocket
for a **60 mm black AprilTag with 5 mm white paper border on each side**.
The calibration value `tag_side_mm` is the measured 60 mm black tag, NOT
the 70 mm paper square. Measure the physical camera lateral offset and yaw
relative to the robot's chassis before permitting any docking motion. This is a CAD topology check, not a real fit test or
charger qualification. The example STL is generated separately and may
not be the actual user's eventual dimensions.

To modify it in Fusion 360, import the example STL as a mesh for visual
reference, but use the editable SCAD source and the Fusion assembly guide
for real dimensional revisions; do not blindly scale the mesh and call
it a parametric dock.

See: ../FUSION_ONE_ROBOT_ASSEMBLY.md and
../FUSION_MEASUREMENT_SHEET.md.
