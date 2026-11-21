# November 13: Nav2 docking recovery reuse boundary

Research owner: Robot Open Source Research. Reviewed PR #17 at `be298a3331d35a8856467be841f108fc6ff6fdb6` (1744 commits), 48 issue comments and 48 combined discussion entries; zero submitted reviews or review threads. This is design research, not a firmware change or physical acceptance.

## Upstream examined

* [Open Navigation docking framework](https://github.com/open-navigation/opennav_docking) describes staging, fresh visual alignment, contact detection, independent charging confirmation, bounded retry via staging and explicit error codes. It says the implementation migrated into Nav2 in June 2024. Its standalone repository is not a reason to add an obsolete second docking server.
* [Current Nav2 docking server](https://github.com/ros-navigation/navigation2/tree/main/nav2_docking) is ROS 2 C++ with lifecycle nodes, actions, transform and navigation dependencies. The [navigator source](https://github.com/ros-navigation/navigation2/blob/main/nav2_docking/opennav_docking/src/navigator.cpp) carries Apache 2.0 notice. This is a *pattern reference*, not a drop-in ESP32 or Mac dependency. No source copied.
* [Nav2 RecoveryNode](https://docs.nav2.org/rolling/configuration_and_development/configuration_guide/core_servers/bt_plugins/controls/RecoveryNode/) retries its primary action only after a successful recovery child, with a bounded retry count. This is the appropriate recovery principle; installing a second behavior tree runtime would duplicate the existing Mac coordinator.

## Concrete integration boundary

Current `code/laptop/src/desk_robot/dock_runtime.py` already has a single native AprilTag detector slot, a measured-calibration gate and nonauthorizing hold diagnostics. Preserve these owners. A docking attempt must distinguish **marker observed**, **approach permitted**, **physical contact observed**, and **battery current actually entering the pack**. Neither a JPEG/AprilTag detection nor a PGOOD pin means charging success. WROOM local cliff, bumper, stale ToF, dock contact and watchdog inhibit are authoritative at every movement step. Never use a recovery retry to clear their latch.

The useful Nav2 pattern is a **bounded staged recovery contract** in the existing coordinator: failed or stale AprilTag/IR evidence returns a typed hold; retry only after fresh independently sampled pose and WROOM safety status, with a new explicit one-use movement permit. A contact or charger ambiguity must terminate motion, not automatically reverse from an energized dock. A future test should simulate a fresh marker followed by IR disagreement, contact bounce, lost camera and charger PGOOD without measured pack current, and assert zero motor/charging authorization, no automatic fault reset and no phantom success.

**Not yet established:** whether the existing coordinator already implements each state/retry edge. Trace it before changing source, then add the smallest missing regression to `code/tests/test_dock_runtime.py` or the existing coordinator test owner. Do not copy ROS 2 docking control loops, claim a pinned Nav2 release without a lock, or add a second motor/charger state machine.

Verification: manufacturer or project documentation inspection and current dock runtime source inspection only. No pytest, C++ compile, firmware, dock, current or thermal measurements executed. One complete robot remains the acceptance target before five copies.
