# Printable passive dock alignment gauge

This is an example **fit tester**, not the final charging dock.

Before the full cradle, render and print the smaller rail entry coupon:

```sh
openscad --export-format binstl -o dock_rail_entry_coupon.stl \\
  -D 'part="dock_rail_entry_coupon"' dock_passive_fit.scad
```

The default 96 mm track example yields a 126 by 48 by 15 mm coupon,
including the entire flare and 11 mm of straight guide. Measure the actual
track pair against its 114 mm entry mouth and 100 mm straight channel,
then update the track width and clearance parameters. It has no tag,
backstop, contacts, or charging function; passing does not qualify docking.
The default `part="dock_passive_fit"` still renders the full cradle.
`code/scripts/export_fit_kit.py` exports both models.

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


## Reversible two beam alignment coupon

The independent NEC transmitter electronics use two physically aimed 38 kHz
channels but their actual emitter carriers, current limiting, vertical aim
and beam overlap are not mechanically qualified. To check a **trial**
left/right separation without modifying or powering the full cradle, export:

```sh
openscad --export-format binstl -o dock_ir_pair_position_coupon.stl \\
  -D 'part="dock_ir_pair_position_coupon"' dock_passive_fit.scad
```

The nominal flat plate uses the same 126 mm dock width and has two
5.5 mm inspection bores at x=14 and x=112 mm, deliberately outside the
71.2 mm AprilTag paper pocket and its white quiet margin. The 98 mm
spacing is a starting reference, NOT measured IR bearing accuracy or
selected emitter housing. Measure the real LED/transmitter carrier,
receiver pair, beam angular response, line of sight to the approaching
pet and screw fit before adapting the final backstop. This coupon has
no emitter electronics, mounting authority, charging contacts or power.
Its exported source and watertight mesh are checked by the regular
`export_fit_kit.py` route.
