# First physical step: gripper test

Use the reported **positional MG90S**, two required, actual ownership count
still to be checked. Verify each pocket/horn against the source SG90 mechanism.
SER0043 is continuous rotation and cannot hold a commanded claw/lift angle.
The preserved legacy DC profile is intentionally **actuator inert**, not a
servo-centering shortcut. The full guarded WROOM profiles include sensor
drivers but cannot attach either servo until the actual lift and jaw travel
calibrations are qualified. Follow the isolated one-shot centering fixture
in [the build guide](build.md#center-the-two-hornless-mg90s-before-measuring-installed-lift-travel).

Start with the actual **flat key and candy** and reversible mechanical fit
pieces before releasing the remaining complete first-unit purchases. The
already reported paid Sense is not a new purchase. The existing mechanism's
floor clearance and gripping ability are unproven.

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
5. Follow [wiring](../hardware/wiring.md) and [body build](build.md). Physically
   unplug drive motors and remove **both** servo horns, then use only the
   isolated USB one-shot fixture to command each unloaded servo to nominal
   90 degrees. The WROOM fixture uses GPIO18 for lift and GPIO19 for jaw,
   with 50 Hz PWM, as defined in `BodyPins.h`. Confirm its 400 ms PWM output has detached and **remove
   servo power** before attaching the horns or linkage. `arm` on the normal
   body firmware cannot be used for this unqualified step. Measure the
   actual safe lift travel and jaw geometry on a collision-free fixture
   before supplying any qualified firmware limits.

The serial bench helper described in `build.md` is for an already qualified
guarded body; it runs one bounded job and maintains its control lease. Do not
disable the 500 ms watchdog for manual tests. Before any loaded grasp, require
measured lift/jaw endpoints, [force calibration](force-feedback-gripper.md),
qualified servo supply, and the per-pose stability and clearance checks in
[the Fusion assembly](../cad/FUSION_ONE_ROBOT_ASSEMBLY.md). Begin on a supported
fixture with drive power disconnected. Stop on binding, unexpected motion,
invalid force evidence, instability or loss of the control lease. An ACK means
a commanded angle was accepted; it is not a grip/force measurement.

Weigh and photograph/describe each actual object. The key must start flat on the
intended surface. Do not prop it up to make a trial pass. Use wrapped candy and
record its shape. Check jaw opening, floor clearance and gear binding first.

Perform ten independent grip/lift attempts per category. Proposed success: the
object visibly leaves the surface by a measured 10 mm, stays held for three
seconds and is placed down under control. Record failures, slips and assistance
in [the physical trial sheet](../records/physical-trials.csv). Every row must include an
`assembly_id` identifying the same inspected physical chassis, power enclosure,
servo and gripper build for all twenty attempts. Use a short revisioned identifier
with letters, numbers, underscores, periods or hyphens. A rebuild requires a new
assembly ID and a fresh set of both ten-trial categories; never combine trials
from different physical assemblies even when firmware and jaw calibration match.
`check_trials.py` verifies the recorded identifier is consistent but cannot
physically authenticate it. Goal: at least 8/10 per category. From the
repository root, after recording all real trials, run:

```sh
python3 code/scripts/check_trials.py --robot robot-01 --require-pass
```

For a separate private record, supply `--file` with its actual CSV path.
A nonzero result is a hold; do not replace measured rows with simulated trials.
A zero exit from `--require-pass` alone is only the outcome score, not physical
qualification. For manifest-backed A5 evidence, also supply
`--run-manifest PATH --require-manifest` with the real run manifest binding the
CSV SHA-256, firmware, calibration, assembly, commit and named reviewer. The
script reports `MANIFEST_VERIFIED_PENDING_SIGNOFF`, not completed physical
signoff, even when the manifest and outcome score pass.

Allowed remedies are small jaw tips, clearances, spacers and brackets. Fusion MCP
must be available before CAD editing; inspect the active design and preserve
originals. No CAD changes have been made. A new arm/chassis is outside this plan.
