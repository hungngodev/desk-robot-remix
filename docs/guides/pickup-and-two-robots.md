> Updated 2026-11-03: this describes existing supervised pickup software.
> The new stepper/Sense/cliff/pet system is tracked in the [build plan](../PLAN.md).
> Five-channel VL53L0X acquisition and local interlocks exist in firmware, but physical optical
> calibration, servo fit, power, real pickup and controlled placement have not passed trials.
> Use a contained setup before operating any hardware.

# Measured pickup and the second robot

Run commands from the repository’s `code/` folder.

## Calibrate one robot

Use the assembled, fixed camera mount and the actual flat test surface. Record
image resolution and collect at least six well-spaced pixel/ground-mm pairs;
keep extra measured points for an independent reprojection check. A ground-plane
mapping does not establish object height, grip force or obstacle distance.

Copy `config/calibration.example.json` to an ignored `config/local.robot-01.json`.
Replace all example geometry with measured values, confirm motor polarity on
stands, set conservative open/closed/lift angles and measure the raised-jaw image
region. Set `measured=true` only after verification; reference that file in
`local.toml`. `calibration.simulation.json` is rejected in hardware mode.

First verify that both the raised object and the released object will be visible
to the fixed camera. The pickup algorithm checks upward displacement into the
raised-jaw region, stable in two fresh frames and outside the calibrated floor
area. It then commands a measured lower, confirms the object is over the release
area before opening the claw, withdraws the empty jaws and checks two fresh
frames for a stable object on the ground. No wheel movement occurs during this
placement phase. If the target is obscured, moves with the jaw, leaves the
frame or cannot be observed after release, the job fails rather than inventing
successful placement. The body receives a stop command in the job cleanup.
This is a camera-based software check, not measured grip force or contact.

The detector needs exactly one confident key/candy candidate in the bounded,
clear, flat work area. Lost/ambiguous targets, uncertain ACKs, no visible lift,
failed placement, camera faults and the configured job deadline stop the job.
Set a measured hardware hold interval of at least three seconds. The WROOM
software has independent four-corner cliff and front ranging, but these still
require actual optical calibration, stop-distance and fault trials. It does
not have complete collision avoidance. Use a tethered, contained test area.

After completing stand tests and measured calibration, enable movement for this
robot in private config, restart the coordinator, and perform one supervised job:

```sh
uv run desk-robot --config config/local.toml enable robot-01
uv run desk-robot --config config/local.toml pickup robot-01 key
uv run desk-robot --config config/local.toml job JOB_ID
uv run desk-robot --config config/local.toml stop robot-01
```

The permit lasts 30 seconds and is consumed by one job. A request returns a job
ID, not a completed pickup. During that window a spoken pickup request can use
the existing permit through `desk_robot_pickup`; the model cannot grant a permit.
Never retry an uncertain movement ACK automatically.

Repeat ten times for a flat key and ten for wrapped candy, record every attempt
and the object description/mass, lighting, firmware version and calibration. A physical pass requires at least 10 mm real lift, a three-second hold and
controlled placement under the criteria in the gripper guide, independently
8 of 10 times for each object. Successful camera evidence returns
`placed_visually_verified=true` but retains `physical_acceptance_pass=false`.
Actual physical measurements and trial records, not a simulated image sequence,
are necessary to pass acceptance. Do not substitute toy blocks for the required objects.

## Add robot two only after robot one passes

Build the second unit from the same validated mechanism. Give it a unique head
token, `robot-02` firmware ID, LAN address and Xiaozhi device ID. Measure its own
calibration; do not copy the first unit's geometry blindly. Confirm a command
to each ID affects only that unit and a stop never reaches the other one.

With both local audio paths tested:

```sh
uv run desk-robot --config config/local.toml chat robot-01 robot-02 --topic "Say hello and describe the desk" --turns 6
```

Six means **six total utterances**, alternating robots, not six per robot. The
shared speaker lock and digital transcript prevent an open-ended acoustic loop.
The normal robots do not drive during this chat. Stop a session through the
authenticated `/v1/conversation/stop` endpoint. Test normal completion, cancellation,
one head disconnecting and coordinator interruption; verify input suppression
ends and no speech overlaps. All physical two-robot tests are still unrun.

## Continue to five identical cores

After the first passes and routing/audio work on the second, follow
[the five-robot guide](five-robots.md) to add robot-03 through robot-05. Each gets
its own camera, screen, voice, lift/gripper, power source, credentials and measured
calibration. Five participants default to ten total utterances; pair sessions
retain the six-utterance limit. All physical fleet tests remain unrun.


### Live local health revalidation during the full grip and placement sequence

The existing calibrated pickup routine now reuses the same armed five range,
BerryIMU freshness, and touch checks as persistent exploration. It samples
immediately before alignment, after every 100ms adjustment pulse, before
closing or opening the gripper, during lift hold frames, and before observing
final placement. It never retries an uncertain movement ACK, automatically
clears a WROOM latch or treats a commanded servo angle as measured jaw height.
A newly disarmed WROOM or stale reading causes the existing coordinator finally
stop path to run. If the payload is held, the WROOM safety stop keeps the
holding PWM attached rather than deliberately dropping it. Hardware grip
strength and actual 10mm lift remain subject to the ten real trials each for
flat keys and wrapped candy.
