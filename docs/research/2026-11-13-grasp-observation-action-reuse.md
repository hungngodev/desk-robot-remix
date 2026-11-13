# Grasp qualification: reuse boundaries, not another actuator owner

Research checkpoint 2026-11-13. Canonical draft PR #17; inspected head 777d5f4b8cc08dbf49b018dc3c2333fc8dcdb0ce. This is an upstream design comparison, **not** a claim of implemented or physically qualified grasp.

## Existing robot behavior

The existing supervised pickup path uses a single Coordinator permit, WROOM local stop, calibrated camera geometry, a three second hold, two fresh visual confirmations and a controlled placement. The pickup guide explicitly distinguishes `placed_visually_verified` from `physical_acceptance_pass`. FSR402/ADS1115 and AS5600 are selected for the full robot but force and jaw geometry remain unmeasured. Preserve the WROOM actuator authority and existing abort semantics. Do not infer force from commanded servo angle.

## Upstream evaluation

* Hugging Face LeRobot `src/lerobot/robots/robot.py`, https://github.com/huggingface/lerobot/blob/main/src/lerobot/robots/robot.py (read 2026-11-13): Apache 2.0 header; its `get_observation()`, `send_action()`, `calibrate()` and per robot calibration identity establish a useful typed observation/action boundary. This Python framework targets supported robotics hardware, not this ESP32 servo/FSR chain. **Reuse interface semantics only**, do not transplant LeRobot's motor bus or a policy into the existing safety loop. Before copying code, lock an exact commit and preserve its Apache notice.
* ROS 2 `ros2_controllers` Humble release 2.54.1 (2026-10-05), https://index.ros.org/p/ros2_controllers/: Apache 2.0, includes gripper and joint trajectory controllers. Not a drop in fit for a Mac plus ESP32 WROOM firmware stack; adopting ROS control would add a competing command authority and substantial runtime dependency. **Do not integrate** for this robot.
* Existing repo source terms: `docs/ATTRIBUTION.md` records the original SMARS gripper CC BY 4.0, forklift CC BY NC SA 4.0 and ancestry restrictions. Neither software license authorizes unrestricted redistribution of the derived mechanical assembly. Check each modified STL's ancestry before final CAD publication.

## Smallest next implementation and deterministic regression

Use the existing gripper command and telemetry owner. Add a bounded typed **read only** grasp observation containing robot identity, boot/acquisition identity, sample age, FSR ADC validity and saturation, AS5600 jaw angle validity, calibration revision, and current job ID. Invalid, stale, mismatched or uncalibrated force and angle must never be promoted to measured grasp success. Do not permit this read only observation to issue movement or bypass local WROOM stop.

First trace current FSR/ADS1115 and AS5600 driver and Mac job receipt wiring; **do not implement this contract if already present**. Test invalid ADC, disconnected FSR, sensor saturation, delayed sample from a previous WROOM boot, jaw angle mismatch, conflicting robot ID, force loss during hold and stale force during release. The acceptance gate remains at least 8 of 10 real key pickups and 8 of 10 real wrapped candy pickups with 10 mm lift, three second hold and controlled placement. Test fixtures alone cannot pass it.

## Evidence and coordination

This research added no firmware or Mac source and executed no tests. All 35 PR issue comments and 35 merged discussion entries were retrieved; review submissions and threads were empty. Recent comments prioritize restoring executable verification. The last observed GitHub Actions jobs failed before recorded steps, so no full suite verdict is available. Coordinate implementation with the canonical PR #17 worker; do not create a separate PR, motor owner, or redundant abstraction. The next owner should first inspect current source and existing tests, then add the smallest missing read only provenance check and a deterministic negative regression. Power, charger and motor safety take priority over this grasp enhancement.
