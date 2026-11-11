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
and trimesh: **126 by 138 by 81 mm**, single connected watertight
triangle surface. This is a CAD topology check, not a real fit test or
charger qualification. The example STL is generated separately and may
not be the actual user's eventual dimensions.

To modify it in Fusion 360, import the example STL as a mesh for visual
reference, but use the editable SCAD source and the Fusion assembly guide
for real dimensional revisions; do not blindly scale the mesh and call
it a parametric dock.

See: ../FUSION_ONE_ROBOT_ASSEMBLY.md and
../FUSION_MEASUREMENT_SHEET.md.
