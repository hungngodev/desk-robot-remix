# Terminal IR receiver reset lifecycle review

Date: 2026-11-12
Integration: PR #17
Implementation commit: 91f31ded5902a95a648221d2d3dd2668e869081c

## Narrow issue

Prior to this commit, `TerminalIr::reset()` stopped and uninstalled RMT receivers without clearing `DualIrEvidence`. A failed `begin()` could therefore expose apparently fresh observations from a previous receiver session for up to the configured freshness window. This is directional evidence only; it must never authorize motion or charging.

## Change

Call `readings_.invalidate()` immediately after setting `ready_ = false` and before receiver teardown. Existing sequence counters are intentionally retained by `DualIrEvidence::invalidate()`. This applies both to explicit reset and to the reset paths inside `begin()`, including failed initialization.

## Evidence and limitations

Source inspection confirmed the old lifecycle gap and that `DualIrEvidence::invalidate()` already has a portable regression for stale rejection and independent reacquisition in `code/firmware/body/tests/terminal_ir_tests.cpp`. No native tests or firmware compilation were executed in this review. A reset-specific test with an instrumented RMT shim is still needed, including partial install failure and two receiver reacquisition. No physical receiver, docking, motor, battery, or charging behavior was tested.

## Next independent task

Build an RMT lifecycle test harness that calls `begin()` successfully, accepts both receiver observations, forces a subsequent initialization failure, and asserts both freshness flags and `same_code` are false while sequence counts remain. Then separately address the queued frame timestamp ambiguity in `poll()` with a backlog drain and fresh reacquisition policy. Avoid claiming this reset fix resolves backlog freshness.

## Scope

Preserve the complete robot, its five independent personalities and memories, sensor and voice integrations, gripper, fitted CAD, wiring, and protected charging acceptance. PR #17 stays draft pending measured hardware verification.
