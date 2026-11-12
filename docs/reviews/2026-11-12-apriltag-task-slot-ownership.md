# AprilTag native detector lifetime and cancellation, 2026-11-12

Scope: one narrow lifecycle fix in the canonical draft PR #17. The full robot scope and all physical safety gates remain unchanged.

## Root cause and chronology

The first bounded AprilTag implementation held a process-wide `threading.BoundedSemaphore(1)` through the synchronous detector's `finally`. That correctly preserved native lifetime but could leak the slot if a pending `asyncio.to_thread` coroutine was cancelled before dispatch.

The next implementation released the slot from the completion callback of a shielded `asyncio.Task`. This fixed pre-dispatch cancellation but introduced a second race: an event loop can cancel the `asyncio.Task` during shutdown even while its already-dispatched native thread continues. That task's done callback then releases the slot before detector completion. A second observation can incorrectly enter a concurrent native detector.

## Source fix on the same PR

`code/laptop/src/desk_robot/dock_runtime.py` now retains the actual `concurrent.futures.Future` from a single-worker standard-library `ThreadPoolExecutor`. The process-wide semaphore is acquired before submission, with only one native job admitted. Its release callback is attached to that **native future**, not an `asyncio` task or wrapper. Submission failure releases immediately. A cancelled queued future releases without running; a cancelled asyncio wrapper while native code is already executing cannot release the slot early. Ordinary observer cancellation and two-second timeout remain bounded and return no motor/charging authorization. Late native exceptions are retrieved, but stale results are never consumed after timeout.

This uses Python's standard library rather than introducing a new AprilTag binding, media stack, motor controller or subprocess. `asyncio.wrap_future` and `asyncio.shield` are solely for the observer's await and do **not** own native-worker lifetime.

## Regression changes

`code/tests/test_dock_runtime.py` now replaces the pre-dispatch to_thread gate with a pending native `Future`, explicitly cancelling it after the observer is cancelled. A second new regression blocks a real executor thread using `threading.Event`, cancels the asyncio future wrapper, and asserts another observation is held busy until the native function actually completes. Both assert that no motor or charger permission is gained. The earlier timeout, late-release and stale AprilTag tests are retained.

**Evidence classification:** source commits and test definitions exist on PR #17. A small isolated local Python harness confirmed (1) cancellation of the asyncio wrapper does not unlock an active native future and (2) cancellation of a not-yet-dispatched native future clears the slot. That harness is **not** execution of the repository pytest suite, firmware compilation, real AprilTag native library or physical docking.

## Remaining boundaries

A native C detector stalled forever can still occupy its one worker indefinitely. That intentionally denies new observations and motion. If real native hangs require recovery, evaluate a supervised killable worker process separately and measure cost on the Mac; do not silently add one now. Dock calibration, camera exposure timestamps, physical terminal IR bearing, safe charging electronics, battery current, dock contacts, robot fit, and real hardware measurements are still unqualified.

Next verification: run `pytest code/tests/test_dock_runtime.py` in the project's configured environment, then whole Python tests, firmware checks, and actual non-authorizing dock observation with measured camera geometry. Do not label this completed hardware acceptance.
