# AprilTag detector timeout: reuse and bounded execution research (2026-11-12)

## Scope and observed source
On PR #17, `code/laptop/src/desk_robot/dock_runtime.py` awaits `asyncio.wait_for(asyncio.to_thread(detect_apriltag, ...), timeout=2.0)`. Expected failures return `_hold()`, with motor, charging and physical acceptance all false. Independent QA noted that injected `TimeoutError` tests do not simulate a genuinely blocked worker. This note addresses **worker lifetime only**, not docking motion or charging authorization.

## Verified upstream behavior and provenance
* Python 3.12 `asyncio.to_thread` delegates to `loop.run_in_executor(None, ...)`: https://github.com/python/cpython/blob/3.12/Lib/asyncio/threads.py . Cancelling the awaiting coroutine does not forcibly terminate Python code already running in an executor thread. Python source is PSF licensed. Reuse standard library; no vendored source needed.
* Python 3.12 `asyncio.wait_for` cancels the awaited future on timeout, not an already executing synchronous function: https://github.com/python/cpython/blob/3.12/Lib/asyncio/tasks.py . Keep timeout for caller responsiveness, but do not treat it as a worker lifetime limit.
* AprilRobotics upstream AprilTag: https://github.com/AprilRobotics/apriltag ; BSD 2 Clause license: https://github.com/AprilRobotics/apriltag/blob/master/LICENSE.md . License permits reuse with copyright and disclaimer retention. This does **not** establish which Python detector wrapper or revision the repository actually pins. Confirm wrapper, license and thread safety before replacing detector calls.

## Alternatives and integration fit
1. **Existing detector plus a single in-flight slot**: smallest change. Reserve a slot before dispatch and release it only when the underlying thread actually finishes, not when the caller times out. A timed-out call returns hold; subsequent observations return a distinct busy hold until the slot clears. A worker completion callback must release the slot without using a timed-out result. Protect against callback races and exception retrieval. This bounds concurrent detector work per runtime instance, not its execution duration. A process restart may still be required for a permanently stuck native detector.
2. **Dedicated bounded ThreadPoolExecutor**: limits detector concurrency and isolates the default executor, but queued work must also be bounded. `max_workers=1` alone does not bound the executor queue. Shutdown cannot kill a stuck native thread. Adds lifecycle management and tests.
3. **Isolated worker process**: permits hard termination of a stalled detector, at the cost of JPEG serialization, process supervision, macOS spawn semantics, resource usage and recovery behavior. Consider only if real stalls are observed or hard lifetime bounds become mandatory.

## Recommended tiny implementation and acceptance tests
First write an asynchronous test with a real `threading.Event` blocking a fake detector, and an observation that actually reaches the two second timeout (or a safely injected shorter deadline). Assert the result is hold and all three authorization flags false. While the first worker remains blocked, issue a second observation and assert **no second detector invocation** and an explicit busy hold. Release the event and verify the slot clears, then verify a fresh observation can proceed. Add cancellation and worker exception cases. Tests must release events in `finally` to avoid leaking workers. Verify stale observations cannot be reused and that snapshot timeout handling remains unchanged. Preserve `asyncio.CancelledError` propagation. Measure peak concurrent detector calls and wall time rather than claiming native worker termination.

## Safety and coordination
Never allow a timed-out detector to publish a late pose, enable movement, or enable charging. Keep this as a narrow runtime boundary change on PR #17; do not introduce another AprilTag implementation. Existing QA finding on PR #17 already covers timeout risk. This note supplies the upstream code evidence and test acceptance plan for the implementation and QA loops. No firmware, wiring, CAD or charging safety is validated by this research.

## EXP-069 implementation follow-up (November 24)

The thread pool approach above was intentionally fail-closed but could not
recover from an indefinitely frozen C call. The replacement uses Python 3.11
standard-library asyncio subprocess pipes (PSF license), not fork of the
running Mac application or a second vision framework:
https://docs.python.org/3.11/library/asyncio-subprocess.html

The runtime warms two isolated children before dock capture when calibration
is configured. Only one child receives a JPEG at a time; the spare holds no
queued frame. Each request has a bounded JSON envelope and a sequence and
original receipt clock; the parent reconstructs the validated DockPose.
The existing 200 ms receipt lifetime includes serialization and IPC. On
timeout, crash, malformed IPC or cancellation, SIGKILL and bounded pipe
draining/reaping precede releasing the single-flight owner. The next caller
must acquire a new JPEG; it may use an already warm spare while replenishment
starts. Unconfirmed reaping closes the owner to all five pets. Shutdown
kills both children after physical STOP and replaces the pool only on
confirmed retirement. A process boundary is not a security sandbox.

Sandbox: the old shielded executor retained its slot after a real 200 ms
timeout. The new isolated process module and fault tests passed 13 cases on
Linux with Python 3.13 and OpenCV 4.13, including real generated AprilTag JPEG,
SIGSTOP/SIGKILL, hang, crash, malformed/oversized/duplicate IPC, timestamp and
sequence mismatch, NaN, cancellation and concurrent close. Each fault case
required a fresh frame on the prewarmed spare in under 500 ms. This is host
evidence, not macOS loaded timing, camera mount calibration, body STOP
acknowledgment or charging qualification.
