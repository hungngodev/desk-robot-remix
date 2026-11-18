# AprilTag worker bounded execution, November 12, 2026

Canonical integration target: PR #17. This is a narrow response to the independent QA finding and the prior research in docs/research/2026-11-12-apriltag-worker-timeout-reuse.md.

## Implementation

The existing detector and calibration remain unchanged. A process local bounded semaphore now admits at most one AprilTag native detection at a time. The detector worker itself releases the slot in a finally block. A timeout returns the existing nonauthorizing hold response, but cannot release the slot while the native worker continues. A concurrent observation returns source `apriltag_detector_busy`. The worker task is shielded from deadline cancellation and its late exception is retrieved. This avoids a queue of stuck native detector calls. Cancellation of the requesting coroutine still propagates. No motion or charging authority is added.

## Regression

Added `test_detector_timeout_does_not_queue_another_native_worker` to `code/tests/test_dock_runtime.py`. It blocks a real worker beyond the 2 second deadline, checks concurrent rejection, verifies safe hold and no second native invocation, releases the worker and checks recovery. This is a source level test committed to PR #17. **Not executed in this run**. No CI, device or physical charging evidence is claimed.

## Limitations and followups

A permanently stuck native detector still occupies one thread and the slot indefinitely; the guard bounds concurrency but does not terminate a C extension. If real hardware shows irrecoverable hangs, evaluate process isolation with an explicit termination protocol. Test cancellation while detection runs, late exception reporting, and multi robot contention. Confirm CI executes Python tests on the exact integration head. Preserve all five robot requirements and the local WROOM safety interlocks. No claims of physical docking, charger acceptance or fitted CAD are implied.
