# AprilTag detector task ownership review, 2026-11-12

Scope: one narrow lifecycle fix on PR #17. The full robot scope and all physical safety gates remain unchanged.

## Finding
The previous implementation acquired the process-wide detector semaphore before scheduling `asyncio.to_thread`, but released it only in the native function's `finally`. Cancellation before executor dispatch could skip that function entirely and leak the slot.

## Change
The asyncio task now owns release through a completion callback, which also retrieves late exceptions. `asyncio.shield` continues to prevent observer cancellation or `wait_for` expiry from cancelling the task. A running native call therefore retains the slot until its task completes; a never-dispatched task can also complete and release it. The existing busy hold, stale-pose check, and false motor/charging authorization are unchanged.

## Regression
Added `test_cancel_before_detector_dispatch_releases_slot`, using an instrumented `asyncio.to_thread` gate to force observer cancellation before dispatch, verify busy hold while pending, and verify recovery after dispatch. Existing blocked-detector timeout test remains.

## Verification and limits
GitHub accepted the source and test commits. No tests were executed in this iteration; no measured performance impact or physical verification is claimed. The regression is a proposed executable check, not passing evidence. Native code stuck forever still occupies the sole worker slot, intentionally failing closed. The next QA iteration should run `pytest code/tests/test_dock_runtime.py` with the repository's configured Python environment, then test late exceptions and executor shutdown.

## Coordination
Addresses the scheduling race reported in PR #17 comment 6821294601. This change avoids creating another PR and should be reviewed against concurrent QA and implementation commits before further edits.
