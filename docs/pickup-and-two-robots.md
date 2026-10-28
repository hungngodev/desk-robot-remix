# Measured pickup and the second robot

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

First verify that the raised object is visible to the fixed camera. The current
algorithm requires upward displacement into the raised-jaw region, stable in two
fresh frames and outside the calibrated floor area. If the lifted object leaves
view, this configuration cannot verify a pickup; adjust a small mounting angle
or region from measurements, not by setting a fake successful status.

The detector needs exactly one confident key/candy candidate in the bounded,
clear, flat work area. Lost/ambiguous targets, uncertain ACKs, no visible lift,
camera faults and a 45-second deadline stop the job. There is no cliff detector
or collision avoidance; use a contained test area away from desk edges.

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
and the object description/mass, lighting, firmware version and calibration. A
physical pass requires visible lift/hold/place-down under the criteria in the
gripper guide. Visual software evidence never automatically passes a physical
trial. Do not substitute toy blocks for the required objects.

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
