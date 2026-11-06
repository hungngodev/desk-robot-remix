# First physical step: gripper test

Updated 2026-11-03: use the reported **positional MG90S**, two required, count
unknown. Verify its pocket/horn fit against the source SG90 mechanism. SER0043
is continuous rotation and cannot hold a commanded claw/lift angle. Use the explicit legacy DC profile only for servo-only tests with motors
disconnected. The new stepper profile has tested control but no sensor I/O or
calibration supplied, so it refuses arming.

Test your actual **flat key and candy** before buying the complete rover/head.
The existing mechanism's floor clearance and gripping ability are unproven.

1. The original `servo_case_arm.stl`, `arm_rack.stl` and `pinion_gear.stl` are
   [saved locally](../cad/originals/gripper/README.md) from
   [Bluino's files page](https://www.thingiverse.com/thing:4253681/files), CC BY 4.0.
2. The two linked lift files and assembly PDF are also
   [saved locally](../cad/originals/forklift/README.md). Their original source is
   [Forklift module for SMARS #3027255](https://www.thingiverse.com/thing:3027255),
   by tristomietitoredeituit, **CC BY-NC-SA 4.0**, separate from Bluino's terms.
3. Use the source's assembly photos and print guidance. The three bundled parts'
   hashes and bounds are recorded locally, as are the two original lift pieces.
   STL has no unit metadata: compare dimensions against your
   measured servo before slicing, and do not treat a valid file as verified fit.
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
in [the physical trial sheet](../records/physical-trials.csv). Goal: at least 8/10 per category.

Allowed remedies are small jaw tips, clearances, spacers and brackets. Fusion MCP
must be available before CAD editing; inspect the active design and preserve
originals. No CAD changes have been made. A new arm/chassis is outside this plan.
