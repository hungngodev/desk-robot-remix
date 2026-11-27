# November 13 Nav2 docking reuse boundary and charging truth

Research owner: Robot Open Source Research. PR #17 only. Starting head `cbeebc2a6f80d891074c11206b2a8c3fa27fbbf1`. Retrieved all 35 PR issue comments, submitted reviews (none), and review threads (none). Source and docs at that research checkpoint already included the bounded two-receiver NEC queue freshness gate, AprilTag worker ownership, required MCP23017 dock evidence and charge inhibit. Do not duplicate those implementations.

## Upstream verified and fit

Open Navigation `opennav_docking` is Apache 2.0 licensed (repository LICENSE). It migrated into Nav2 in June 2024. Source: https://github.com/open-navigation/opennav_docking and https://github.com/open-navigation/opennav_docking/blob/main/LICENSE . The Nav2 documentation at https://docs.nav2.org/rolling/configuration_and_development/configuration_guide/core_servers/configuring_docking_server/ and https://github.com/ros-navigation/docs.nav2.org/blob/rolling/docs/tutorials/general_tutorials/using_docking.md explicitly separate staging, detected pose refinement, approach/contact and **confirmed charging**. It provides bounded retries and separate failure results. The SimpleChargingDock example can optionally equate a docked state with charging when battery status is unavailable. **Do not copy that permissive option:** on this robot contact, dock GPIO and charging current are separate independent facts.

Decision: reuse the established state transitions and failure taxonomy as a *design reference*, not ROS2/Nav2 binaries, its controller or an extra movement authority. A ROS2 deployment would add a large incompatible runtime and compete with the existing Mac coordinator and WROOM motor/cliff/bumper gates. No upstream code or geometry is copied, so no new license notices are required for this note. If future code is transplanted, pin an exact source commit and retain Apache 2.0 license/NOTICE and modification notices.

## One missing acceptance boundary

A plausible AprilTag pose or a pair of fresh NEC observations is **localization evidence only**. It cannot certify that the contacts seated, that the pack protection is intact or that qualified charge current actually flows. The existing WROOM MCP23017 dock status remains the independent contact owner. The charger and protected 1S electrical design are not physically qualified. Never mark a docking job successful or enable a charge contact solely because approach pose error is small, because one IR receiver fires, because PGOOD alone asserts, or because an application timeout elapses.

The minimal existing-owner contract to inspect before changing source:

1. Mac coordinator may request staging and pose refinement, but all movement commands still pass WROOM fresh cliff/bumper/IMU and contact interlocks.
2. Two independent receiver observations must be fresh, correctly paired, nonreplayed and recovered after poll stalls; missing either side aborts terminal alignment rather than falling back to blind movement.
3. A contact event disarms motor drive regardless of higher level request. Charging qualification must be reported independently from contact, based on the selected protected power path and physically measured battery current/thermal conditions.
4. The conceptual failure/result taxonomy is approach failure, contact seen but charge unverified, confirmed charging, and safety abort. These are design distinctions, not literal current API result strings; contact alone must never be advertised as successful charging.
5. Retry must return to a safe staging state only after fresh WROOM authorization; no automatic movement after contact or brownout.

## Original proposed executable regression

Before any refactor, locate the existing dock job result producer and its tests at the current PR head. Inject fresh AprilTag plus dual IR evidence but no measured charger current: assert no charging success. Repeat with contact asserted and PGOOD true but no verified current: still not success. Inject a stale left receiver, a fresh right receiver, a WROOM contact fault, and a brownout in separate cases: no new motor permit and no charging success. A valid independently measured charge state should be possible only after a qualified charger hardware design exists; do not fake that physical verification in host tests. If current source already enforces these outcomes, record exact file/test evidence and choose a different bug instead of duplicating a guard.

No code, tests, firmware builds, charger measurements, dock trials or CAD qualification were performed in this research note. This is an upstream architecture and license comparison, not assembly readiness. Preserve the full one-robot then five-personality fleet scope.

## November 26 source reconciliation (DRX-1670)

At reviewed head `40ecebe489490a2020098d8d3fe9f5f7ef4ab918`, the existing runtime and tests implement the distinction without adopting the proposed result names. `code/tests/test_dock_motion.py` asserts that guarded approach outcomes can finish with job state `succeeded` and result `phase: hold`, with `charging_authorized` and `physical_acceptance_pass` false; contact during the approach can instead fail the job with the body disarmed. A completed software job is not a completed physical dock or charge.

`code/laptop/src/desk_robot/dock_evidence.py` independently classifies three fresh, stable MCP23017 samples. Both seat switches plus PGOOD and CHG produce `charger_reports_active`, not confirmed charging. Fresh, independently sequenced INA226 readings can report `into_pack_unqualified`, `out_of_pack_unqualified` or `indeterminate`; sustained net discharge with CHG asserted is reported as a conflict. The diagnostic still returns `physical_contact_verified`, `battery_current_measured`, `charger_electrically_qualified`, `charging_verified`, `motor_authorized` and `charging_authorized` false. See `code/tests/test_dock_evidence.py`, including `test_three_stable_charger_indications_are_not_battery_proof` and `test_new_ina226_current_receipts_report_direction_without_charger_authority`, and the existing contact and replay cases in `code/tests/test_dock_motion.py`.

This reconciliation is source inspection, not a new test execution or an electrical acceptance receipt. The physical HOLD and independently measured net charge, thermal and contact gates remain unchanged.
