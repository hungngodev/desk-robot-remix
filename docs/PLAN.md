# Desk Robot Remix build plan

Build and qualify one robot before making four copies. The
[product definition](product-definition.md) owns appearance, behavior and
acceptance criteria. The [parts list](hardware/parts.md) owns inventory and
shopping. This page owns the build order.

## Build order

| Stage | What to do | Ready when |
| --- | --- | --- |
| **1. Fit and parts** | Check the MG90S in the saved [gripper](guides/first-gripper-test.md) and the 28BYJ-48 in the [stepper chassis](cad/originals/smars-stepper/README.md). Confirm the Sense bundle, select the speaker path and matched rechargeable 1S kit, and check the complete delivered cost. Resolve the stepper remix's source terms before redistribution. | Fit samples clear the mechanism's travel and the complete prototype basket fits the **$50 delivered cap**. |
| **2. Drive and power** | Test the two owned stepper/ULN2003 pairs and two positional MG90S servos on a stand. Measure loaded current, temperature, stability and stop behavior. [Wiring](hardware/wiring.md) | Drive, lift and grip work under load within component ratings. |
| **3. Edge and obstacle sensing** | Bring up four downward VL6180X sensors, one forward VL53L0X and a TCA9548A mux. Calibrate on the actual desk and test faults and stops with a tether or catch setup. [Sensor design](research/2026-11-03-cliff-sensors.md) | The WROOM stops locally with measured margin on qualified surfaces and approaches. |
| **4. Head and conversation** | Bring up the Sense camera, onboard mic, OLED, speaker and UART. Test the owned AT42QT1010 through the shell and verify the BerryIMU revision and readings. Exercise echo cancellation and turn interruption. [Head setup](guides/modular-head.md) · [Audio gate](guides/audio-barge-in.md) · [Touch and IMU](hardware/interaction-sensors.md) | A person can interrupt ongoing speech by speaking. Touch and handling events pass bench and shell tests. |
| **5. Initiative and exploration** | Add fresh camera events and stationary expressions first. Add supervised, operator-enabled exploration after the local stops pass. Test quiet mode, preemption, pause and link loss. [Implementation tasks](plans/2026-11-03-active-desk-pet.md) | The robot reacts without a prompt, yields to the operator and stops safely when interrupted. |
| **6. Object pickup** | Test real flat keys and wrapped candy with the fitted lifting claw. [Pickup guide](guides/pickup-and-two-robots.md) | At least **8 of 10** attempts per object type lift it 10 mm, hold it for three seconds and place it under control. |
| **7. Duplicate** | Copy the qualified core four times, then assign distinct identities and calibrate each unit. Start group play with serialized speech and one moving robot at a time. [Fleet guide](guides/five-robots.md) | Five distinct robots complete ten coordinated utterances and each passes its own movement checks. |

## Design decisions that affect the build

- **Body.** The WROOM owns motion, sensors and the local stop. The XIAO Sense
  handles camera, audio and face. The Mac handles speech, vision, activity
  selection and memory. See the [interfaces](guides/interfaces.md).
- **Enclosure.** Compare Cozmars head packaging first and keep the saved,
  unprinted Sparky shell as a fallback. Both lift and grip retain their own
  servo. Limit CAD edits to mounts, bezel, clearance, jaw tips and removable
  accessories. See the [product definition](product-definition.md#case-choice-and-allowed-changes)
  and [concept views](cad/concepts/2026-11-03-rounded/README.md).
- **Motion.** Boot disarmed. The body enforces 250 ms drive limits and a 500 ms
  communication watchdog alongside local edge stops. The planned pet session
  stays enabled until paused or stopped. Faults and disconnects cancel it.
  Fault recovery requires a local clear. Resuming movement requires fresh
  operator enable. See the
  [control requirements](product-definition.md#control-and-compute-boundary).

## Current evidence

The Sense and body profiles compile. Portable stepper control and fault policy
have software tests, and five-robot mock conversation runs. The stepper build
refuses to arm while real sensor readings and measured calibration are missing.
Physical fit, power, speech interruption, pickup and fleet play are still open.

[Implementation progress](guides/firmware-foundation.md) · [Test evidence](records/verification.md) · [Reuse and licenses](source-map.md)
