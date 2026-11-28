# Grasp qualification: reuse boundaries, not another actuator owner

Research checkpoint 2026-11-13. Canonical draft PR #17; inspected head 777d5f4b8cc08dbf49b018dc3c2333fc8dcdb0ce. This is an upstream design comparison, **not** a claim of implemented or physically qualified grasp.

## Current-source clarification (2026-11-27)

Source inspected at `a203bedcfc62d6d1dd0a5340a0edee88b2a58658`; the November 13 proposal below is historical, not a fresh implementation backlog.

* The selected three AS5600 channels are twist nose, left track and right track, not jaw position. See [full-feature-plan.json](../hardware/full-feature-plan.json) and [AccessoryReadings.h](../../code/firmware/body/lib/AccessorySensors/AccessoryReadings.h). Do not add a fourth encoder or infer measured jaw travel from a servo command.
* [grasp_feedback.py](../../code/laptop/src/desk_robot/grasp_feedback.py) already implements `force_observation`, `guarded_grasp` and `verify_grasp_hold`. The motion/hold path requires the configured robot identity, independent jaw validity, nonclipped raw ADC, nonzero WROOM boot and jaw sequence, acquisition age below 500 ms (including request time), and fresh forward conversions in the same boot. Read-only legacy decoding is less restrictive and must not authorize motion. [aux.py](../../code/laptop/src/desk_robot/aux.py) validates independent belly and jaw channels; composite validity is not a substitute for the jaw verdict at the motion boundary.
* [controller.py](../../code/laptop/src/desk_robot/controller.py) owns pickup and calls the existing guarded grasp and hold checks. Servo position is commanded, not measured. The tactile result explicitly reports `position_measured=false`, `force_newtons_measured=false` and `physical_acceptance_pass=false`. The visual placement receipt is also not physical acceptance. Existing [grasp regressions](../../code/tests/test_grasp_feedback.py) cover clipped/stale feedback, foreign identity, replay and reboot; do not build a duplicate observation or actuator owner.

The remaining measured-force and jaw-geometry work is physical qualification, not a reason to change the approved sensor allocation. Preserve the original real-object acceptance trials and physical HOLD. This clarification is source inspection only, not a new test execution or hardware result.

## Existing robot behavior

The existing supervised pickup path uses a single Coordinator permit, WROOM local stop, calibrated camera geometry, a three second hold, two fresh visual confirmations and a controlled placement. The pickup guide explicitly distinguishes `placed_visually_verified` from `physical_acceptance_pass`. FSR402/ADS1115 and AS5600 are selected for the full robot but force and jaw geometry remain unmeasured. Preserve the WROOM actuator authority and existing abort semantics. Do not infer force from commanded servo angle.

## Upstream evaluation

* Hugging Face LeRobot `src/lerobot/robots/robot.py`, https://github.com/huggingface/lerobot/blob/main/src/lerobot/robots/robot.py (read 2026-11-13): Apache 2.0 header; its `get_observation()`, `send_action()`, `calibrate()` and per robot calibration identity establish a useful typed observation/action boundary. This Python framework targets supported robotics hardware, not this ESP32 servo/FSR chain. **Reuse interface semantics only**, do not transplant LeRobot's motor bus or a policy into the existing safety loop. Before copying code, lock an exact commit and preserve its Apache notice.
* ROS 2 `ros2_controllers` Humble release 2.54.1 (2026-10-05), https://index.ros.org/p/ros2_controllers/: Apache 2.0, includes gripper and joint trajectory controllers. Not a drop in fit for a Mac plus ESP32 WROOM firmware stack; adopting ROS control would add a competing command authority and substantial runtime dependency. **Do not integrate** for this robot.
* Existing repo source terms: `docs/ATTRIBUTION.md` records the original SMARS gripper CC BY 4.0, forklift CC BY NC SA 4.0 and ancestry restrictions. Neither software license authorizes unrestricted redistribution of the derived mechanical assembly. Check each modified STL's ancestry before final CAD publication.

## Smallest next implementation and deterministic regression

Use the existing gripper command and telemetry owner. Add a bounded typed **read only** grasp observation containing robot identity, boot/acquisition identity, sample age, FSR ADC validity and saturation, jaw angle validity if separately measured (historical proposal; no selected jaw encoder), calibration revision, and current job ID. Invalid, stale, mismatched or uncalibrated force and angle must never be promoted to measured grasp success. Do not permit this read only observation to issue movement or bypass local WROOM stop.

First trace current FSR/ADS1115 and AS5600 driver and Mac job receipt wiring; **do not implement this contract if already present**. Test invalid ADC, disconnected FSR, sensor saturation, delayed sample from a previous WROOM boot, jaw angle mismatch, conflicting robot ID, force loss during hold and stale force during release. The acceptance gate remains at least 8 of 10 real key pickups and 8 of 10 real wrapped candy pickups with 10 mm lift, three second hold and controlled placement. Test fixtures alone cannot pass it.

## Evidence and coordination

This research added no firmware or Mac source and executed no tests. All 35 PR issue comments and 35 merged discussion entries were retrieved; review submissions and threads were empty. Recent comments prioritize restoring executable verification. The last observed GitHub Actions jobs failed before recorded steps, so no full suite verdict is available. Coordinate implementation with the canonical PR #17 worker; do not create a separate PR, motor owner, or redundant abstraction. The next owner should first inspect current source and existing tests, then add the smallest missing read only provenance check and a deterministic negative regression. Power, charger and motor safety take priority over this grasp enhancement.
