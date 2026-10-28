# First physical step: gripper test

Test your actual **flat key and candy** before buying the complete rover/head.
The existing mechanism's floor clearance and gripping ability are unproven.

1. From [Bluino's files page](https://www.thingiverse.com/thing:4253681/files),
   download `servo_case_arm.stl`, `arm_rack.stl`, `pinion_gear.stl`.
2. The author also links [fork_lift_e.stl](https://cdn.thingiverse.com/assets/9c/73/bb/a8/bd/fork_lift_e.stl)
   and [fork_lift_f.stl](https://cdn.thingiverse.com/assets/08/79/47/dc/a3/fork_lift_f.stl).
   Confirm their original license before redistribution.
3. Save them in `cad/originals/gripper/`. Use the source's assembly photos and
   print guidance. The download buttons did not expose direct STL links for the
   three bundled parts to the research tool; no STLs are downloaded here yet.
4. Measure the actual servo case and horn. Print one pocket/fit part first. Do not
   scale the whole rack and pinion to change a servo pocket.
5. Follow [wiring](../hardware/wiring.md) and [body build](build.md). Remove horns
   and loads first. `arm` centers the servos; attach horns only after centering.
   Test the linkage near 90° before approaching either software limit.

The serial bench helper described in `build.md` runs one bounded servo job and
maintains its control lease. Do not disable the 500 ms watchdog for manual tests.
An ACK means a commanded angle was accepted; it is not a grip/force measurement.

Weigh and photograph/describe each actual object. The key must start flat on the
intended surface. Do not prop it up to make a trial pass. Use wrapped candy and
record its shape. Check jaw opening, floor clearance and gear binding first.

Perform ten independent grip/lift attempts per category. Proposed success: the
object visibly leaves the surface by a measured 10 mm, stays held for three
seconds and is placed down under control. Record failures, slips and assistance
in `test-results/physical-trials.csv`. Goal: at least 8/10 per category.

Allowed remedies are small jaw tips, clearances, spacers and brackets. Fusion MCP
must be available before CAD editing; inspect the active design and preserve
originals. No CAD changes have been made. A new arm/chassis is outside this plan.
