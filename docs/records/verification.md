# Exact head verification summary

This section is the first checkpoint for parallel engineering agents. Never
treat the historical pass in this table as proof for the live PR head. Check
[PR #17 checks](https://github.com/hungngodev/desk-robot-remix/pull/17/checks)
and the exact commit SHA **before** changing any acceptance flag. This document
is not automatically refreshed by GitHub Actions.

| Verification gate | Exact evidence | Status at November 17 review |
| --- | --- | --- |
| Current PR #17 head | [Latest commits](https://github.com/hungngodev/desk-robot-remix/pull/17/commits) | Must fetch live SHA; no pinned current green claim |
| Python and head host tests | [Historical run 44203205736](https://github.com/hungngodev/desk-robot-remix/actions/runs/44203205736), SHA `91c248a034d0f3ee4b8d8b93608cacc6dadc8fe3` | PASS on older SHA only |
| C++ sanitizer tests | Same historical run and exact SHA | PASS on older SHA only |
| ESP32 WROOM PlatformIO | Same historical run and exact SHA | PASS on older SHA only |
| XIAO Sense ESP IDF 6.1 | Same historical run and exact SHA | PASS on older SHA only |
| All four jobs on the current head | [Live checks](https://github.com/hungngodev/desk-robot-remix/pull/17/checks) | UNVERIFIED until current SHA has completed successfully |
| Live speech and camera | Device evidence and A2 acoustic trial logs | NO physical qualification |
| Loaded motor stop and hardware cutoff | Independent motor rail and CPU halt measurements | NO physical qualification |
| Protected pack, charger and dock | Manufacturer matched PCB/pack and current/thermal/contact trials | NO physical qualification |
| Print fit and gripper | Full measured mechanical assembly and calibration | NO physical qualification |

Never close a physical safety or buying gate from synthetic tests,
documentation improvements or a historical all green CI run.

## November 17 source edge-case burn-down: vision, cliff telemetry, procurement

This checkpoint implements three missing acceptance details identified after rereading
the original long-form requirements and uploaded 61 KB architecture audit.
Only existing PR #17 and its canonical Mac + XIAO Sense + WROOM design were modified.
Source and regression commits, each applied with an expected-head lease:

1. `987855c8`: `VisualChangeGate` now rejects NaN, Infinity, nonnumeric or
   boolean frame change thresholds and confirmation counts, and bounds the
   positive integer confirmation count to 16. Regression:
   `code/tests/test_pet.py::test_visual_change_gate_rejects_invalid_confirmation_budget`
   and change fraction variants. This prevents accidental one-frame triggering
   or silent never-trigger behavior; actual motion optical calibration is
   still unmeasured.
2. `da53b76a`: `CliffGuard::diagnostic` now reports `valid=false` when a
   sample reaches its configured freshness deadline, while retaining
   `present`, raw distance and age for fault diagnosis. Previously the
   physical guard rejected stale values but the JSON `ranges.valid_mask`
   could still describe them as valid. The local STOP latch and rearm
   authority were not modified. Regression:
   `code/firmware/body/tests/cliff_tests.cpp::diagnostics_expire_validity_without_clearing_raw_or_latched_fault`
   covers the exact deadline, preserved raw sample, read-only behavior and
   uint32 timer rollover.
3. `f49219b4`: procurement blocks Adafruit branded **new** hardware when
   the evidence names a generic reseller but the SKU, brand, product name,
   product URL, resolved item or revision still identifies Adafruit.
   Previously only the vendor string was checked. The same guard applies to
   pet roles, shared room parts and selected linked decisions.
   Regression: `code/tests/test_procurement_release.py::test_adafruit_brand_hidden_behind_generic_reseller_is_still_blocked`.
   Already-owned boards and software library reuse are not prohibited.

**Verification status:** source changes and regression files are committed and
read back through GitHub. These tests have NOT been reported green on the
new exact head by this checkpoint. Previous successful software CI run
`44166153833` belongs to historical commit `b7ec77fc`, not these edits.
Recheck GitHub Actions for the exact current commit, including Python tests,
C++ sanitizers, XIAO Sense ESP-IDF firmware and WROOM PlatformIO build;
never carry an older PASS forward to a newer SHA.

**Physical and purchasing gates remain HOLD.**
`docs/hardware/full-feature-plan.json` still records
`physical_trial_count=0`, `prices_complete=false` and
`qualified_assumptions=false`. Real loaded stopping distance, external
CD74HC123 to DRV8833 nSLEEP cutoff with CPU-halt trial, 3.3 V carrier
electrical tests, device AEC and audio flush, full charger/pack/dock/IR
power trials, fitted CAD and grasp validation cannot be certified from
source or simulated test passes. No new PR, board swap, extra audio
framework, new Adafruit purchase or automated unsafe cliff recovery.



### November 17 handling callback order regression, execution pending
Starting head `aa93165480db476ee66a6a80dbdfd8bf3ce020d9`. `HandlingGate.observe` previously reset the active pose for any host callback time `now <= last_at`, even when an older queued callback arrived after a newer sample. Source `43855edddcc3f1710178912f738026654ff6564d` now rejects this out-of-order callback without changing current pose; forward gaps still invalidate calibration. Test source `783b37ba892cda6444cc2cad8aa8e768890d4ea0` adds `test_out_of_order_host_callback_does_not_erase_newer_pose`, checking stale callback, current sample, and genuine forward gap. **UNEXECUTED**: no pytest command, firmware build or device trial ran in this pass. Required: `cd code && PYTHONPATH=laptop/src python -m pytest -q tests/test_handling.py`. Read-only handling only, no physical tilt safety claim. PR #17 remains draft.
## November 17 manual sequential fixing pass: room callback diagnostic persistence

Starting PR #17 head `000d3f57ff52f64f3e19df02612f808938042af8`. Source commit `f27dba32916d099875bf0464a0b9c7e566948f91` now resets `RoomSerialFeed.last_error` only when a new serial port opens, instead of erasing a recorded application callback exception after the previous reader exits normally. Regression source commit `4ca5d1cebc61aee652b13d1c1ba0a4eb59e94c3b` adds `test_room_callback_failure_is_not_erased_by_clean_reader_shutdown` to `code/tests/test_room_station.py`. Exact modified GitHub source and regression blobs were independently fetched and confirmed on new PR head; test **NOT EXECUTED** because shell Git cannot resolve github.com and no runnable checkout exists here. Run `cd code && PYTHONPATH=laptop/src python -m pytest -q tests/test_room_station.py -k callback_failure_is_not_erased_by_clean_reader_shutdown` followed by the full room station tests. Remaining high severity: application callback blocking can prevent the USB worker from terminating on cancellation. No physical USB, charging, motor or five pet qualification.


## November 16: bounded multimodal shutdown source commit 6ef2979ce34184cf7d5af5845da437a434866260 and deterministic stream cancellation regression commit 98410775fced39b1a1ec56f4e6dbf94dbbe1ef70. The previous unbounded gather of capture, stream, look, sensor and proactive tasks is replaced with a 0.5 second bounded wait; unfinished task owners remain registered until real completion with identity guarded callbacks. Local git ls-remote failed DNS, exit 128. Focused pytest NOT EXECUTED. Run cd code && PYTHONPATH=laptop/src python -m pytest -q tests/test_multimodal.py -k close_bounds_cancellation_resistant_stream_worker; then full multimodal suite. No physical qualification.


## November 16 bounded camera shutdown ownership regression

Owner Robot Code Fixes and Cleanup. Starting PR #17 head 9a401efbadeb2f6f1964b5eec4badee27c1c36f9. Source commit 3c9964982e046e490e0fc73497eefc18e0179ba0 keeps cancellation resistant physical XIAO snapshot tasks in the ownership registry until actual completion, with bounded 0.5 second shutdown wait and identity guarded completion cleanup. Test commit 06d06b731c55ff746ccc2776b7a9724a9aaac803 adds a deterministic Event barrier regression for a snapshot adapter that suppresses cancellation. The source and test were committed through GitHub contents API; regression NOT EXECUTED. Local git ls-remote failed github.com DNS resolution, exit 128. Required: cd code && PYTHONPATH=laptop/src python -m pytest -q tests/test_multimodal.py -k close_preserves_cancellation_resistant_physical_snapshot_ownership, then full multimodal suite. No device, acoustic, dock, charge or motor qualification. PR stays draft.

## November 16 failed MJPEG replacement reconnect regression

Owner Robot Integration Fixes. At PR #17 head 0688717123687a24bfc4fabf6870a21f6a0ab7e0, reconciled 84 issue comments, 84 combined discussion entries, zero submitted reviews and zero inline review threads. Test commit 4ff1c7bfae89fabf8f2e58c8d33273ba28aba7ec adds a deterministic failed replacement stream case to code/tests/test_transport_calibration.py. It holds an old stream open, makes the replacement return HTTP 503, then verifies that old frames cannot revive camera connection or supply a snapshot. STATUS TEST_COMMITTED_NOT_EXECUTED. Local git ls-remote github.com failed DNS resolution, exit 128. Required: cd code && PYTHONPATH=laptop/src python -m pytest -q tests/test_transport_calibration.py -k failed_replacement_mjpeg_stream, followed by camera transport suite and supervisor restart tests. No hardware or firmware verification; PR stays draft.

## November 15 retired camera boot replay test fixture correction

Owner: Robot Integration Fixes. At PR #17 head 5e25198188beb5e64417868220fe52b1afb89628, reconciled 84 issue comments and 84 combined discussion entries, zero submitted reviews and zero inline review threads. Source test commit 2f02f14f42f96c0b583897fa4332b3769afe79af corrects a remaining literal backslash JPEG marker assertion in test_mjpeg_stream_rejects_old_boot_replay_after_real_head_reset. The prior assertion checked for ASCII backslash x characters even though _stream_part emits binary JPEG SOI. This is a test fixture correction, not a production change. Static check located exactly one bad assertion; no pytest suite or physical test was executed. Required: cd code && PYTHONPATH=laptop/src python -m pytest -q tests/test_transport_calibration.py -k old_boot_replay_after_real_head_reset, then camera transport suite. PR #17 remains draft. No physical qualification.

## November 15 XIAO MJPEG reconnect stream ownership fence\n\nOwner: Robot Integration Fixes. Initial PR #17 head 39cb7dd8a3d771a374286ed4e1cc85f6e502ec2d. Source e902e2c61b8683c103cb88618f928af8b0868c7c fences live camera state by stream generation; regression 0fb57d6566bab8b3ec021ad4937ec0d821b93c88 checks old stream cannot overwrite or clear a newer stream. Handoff 876b065ce84242931d72b48dacf2fc98d0907061. STATUS SOURCE_AND_TEST_COMMITTED_NOT_EXECUTED. Actual local git ls-remote failed github.com DNS resolution exit 128. Required: cd code && PYTHONPATH=laptop/src python -m pytest -q tests/test_transport_calibration.py -k replaced_mjpeg_stream, then full suite. No firmware, camera hardware, motion or charging verification. PR remains draft.\n\n

## November 15 proactive alternate speaker mid-send consent revocation

Owner: Robot Code Fixes and Cleanup. Source f1a0809695a9f8376d836ca2669e4191a49b7d57 adds a post-await permission recheck in Conversation.say_proactive for alternate and simulated speakers, routing a late opt-out through the existing interrupt cleanup rather than reporting success. Regression 2e33b8e0b0af3bda0f17a2001537db6fb51d51b0 uses asyncio Events to revoke permission while a non-Kokoro speaker is waiting, then asserts an interrupt request and both lease releases. The existing Kokoro bridge check and Xiaozhi safety owner remain unchanged. STATUS SOURCE_AND_TEST_COMMITTED_NOT_EXECUTED. Container git ls-remote failed to resolve github.com, exit 128. The test has not passed; no physical STOP or acoustic confirmation is claimed. Next: cd code && PYTHONPATH=laptop/src python -m pytest -q tests/test_api_conversation.py -k proactive_consent_revoked_during_alternate_speaker_send, then the full conversation suite and real head STOP verification. PR #17 remains draft.
## November 15 terminal IR right receiver two-packet regression, unexecuted

On PR #17 starting head 29d0d92f6c899551ead72c90e6c6a6814cde52e0, test commit 679056bcf108a1b726417eedf3311d6bdf5746f2 adds a mirrored right-side double NEC packet rejection case to code/firmware/body/tests/terminal_ir_tests.cpp. It checks that a clean left frame does not excuse an ambiguous right batch and that the right gate recovers after an isolated later packet. This is a regression fixture, not a host pass or physical safety qualification. Local git ls-remote github.com failed DNS resolution, exit 128; no test or firmware build executed. Run `g++ -std=c++17 -Wall -Wextra -Werror -fsanitize=address,undefined -Icode/firmware/body/lib/TerminalIr code/firmware/body/tests/terminal_ir_tests.cpp -o /tmp/terminal_ir_tests && /tmp/terminal_ir_tests` on current branch head, then body firmware compile and measured receiver tests. PR stays draft.

## November 15 terminal IR queue gate C++ compile repair, not executed

PR #17 starting head 84c397fe11af032908b757749c2a4d62193e1e9f. `NecBurst.h` contained literal backslash n sequences inside a line comment that swallowed the declaration of `acceptable` in `IrFrameQueueGate::finish`. Source fix commit `090c5fb2b24f680da41fac3d0d919d4598880477` restores physical newlines and the original fail closed `packets <= 1` guard. Existing `terminal_ir_tests.cpp` is the intended regression harness. Container `git ls-remote https://github.com/hungngodev/desk-robot-remix.git HEAD` exit 128, `Could not resolve host: github.com`; g++ exists but the exact repository test was NOT executed. No PlatformIO, ESP-IDF or physical measurements. Next: compile the current exact terminal_ir_tests.cpp with current NecBurst.h under g++ with ASan/UBSan, then WROOM build and hardware validation. PR remains draft.

## November 15 proactive group priority after speaker lease: source committed, regression unexecuted

Starting PR #17 head 5b9fabdef7601b4b9380f8396b70527c58edc5d7. Source debd77bb8e147adeb676438697a06b61706be9f0 checks for newly active group conversation after waiting for the proactive speaker lock; regression e3bab63feb384a5a8b60d587f3905c2fe21b5b2b covers the interleaving. Local git ls-remote failed DNS, exit 128. No pytest, firmware build or physical test executed. Next exact test: cd code && PYTHONPATH=laptop/src python -m pytest -q tests/test_api_conversation.py -k proactive_group_activated_while_waiting_for_speaker_lock. Full conversation tests and five pet acoustic output remain unverified.

## November 15 proactive speech permission lease race: source committed, test not executed

PR #17 start head d5892a7a7d18c809f80e8464db3e405e23f70522. Source commit 409ec395a092836f36490454769cdfee82dcaea4 rechecks proactive speech permission after the session and speaker lease awaits. Regression commit 16f0329766e97808144efd84ca62bd70d0e8598c adds two async lock contention cases. Local git ls-remote https://github.com/hungngodev/desk-robot-remix.git HEAD failed DNS resolution, exit 128; pytest, builds, device tests and physical validation NOT EXECUTED. Required: cd code && PYTHONPATH=laptop/src python -m pytest -q tests/test_api_conversation.py -k proactive_consent_revoked_while_waiting_for_speech_lease; follow with full test_api_conversation.py. No acoustic ACK or battery/motor qualification inferred.

## November 13 current turn tool receipt priority, not executed

Source commit `b66269e` and regression commit `46578b2` prevent a read-only tool receipt before the latest authenticated human voice from receiving current ASR request priority in `compose_brain_context`. Old evidence remains explicitly historical and available when budget allows. This does not prove request identity or playback. Local `git ls-remote` failed DNS resolution of github.com; pytest, native C++, PlatformIO, ESP-IDF and physical tests were **not executed**. Required check on exact current head: `cd code && PYTHONPATH=laptop/src python -m pytest -q tests/test_brain_context.py`. Follow with an authenticated robot/turn epoch regression through the existing Xiaozhi and Mac tool dispatcher.

## November 13 architecture voice-boundary regression, unexecuted

`769c591` adds `test_new_voice_without_completed_asr_cannot_reuse_prior_question`; `3a6e001` removes the `heard_count` prerequisite from the newest-first `human_voice` boundary fence in `brain_context.py`. This fixes the no-new-ASR case without altering motion, charging, audio transport, or tool dispatch. **No test executed**: `git ls-remote https://github.com/hungngodev/desk-robot-remix.git HEAD` failed `Could not resolve host: github.com`. Existing full suite status is unchanged. Required executable check: `cd code && PYTHONPATH=laptop/src python -m pytest -q tests/test_brain_context.py`, plus the two existing boundary regressions, on the exact current PR head.

## November 13 architecture regression awaiting execution

Starting branch commit `9bec190fbbefc3c43c29dd54782c3bdbb91bd2de`. `brain_context.py` commit `988bb226` now recognizes independent tool requests across both recent completed ASR fragments rather than stopping after one recognized request. Test commit `ed3ed09` adds a deterministic mixed visual question, battery question, unrelated memory tool and touch case. **No tests executed in this iteration.** No physical, firmware or audio evidence. Next run `cd code && python -m pytest -q tests/test_brain_context.py` against current exact blobs and record exit code; verify context remains within 400 characters. This is a prompt salience change only, never a motor or charging authorization.\n\n# Verification and physical trials


## November 12 evening: executable brain recall and cross-robot camera epoch fence

**Canonical PR #17 source changes:** `0ec93dc` fixes the previously reversed
memory slice in `compose_brain_context` that omitted **newest** SQLite
episodes and operator-curated facts when more than six were available.
Latest context now selects the newest distinct six by timestamp independent
of which ordering the caller supplied, prioritizes fresh entries within
the 600/500 character budgets, and then presents them chronologically.
`07f994aa` adds tests for both input orders, duplicate revisions and
budget behavior.

**Actually executed local Python 3.13.5:** The exact **current GitHub blob**
`code/laptop/src/desk_robot/brain_context.py`
`83706aea3a6aeb5f8e3e9b581a2fd9debce1a219` was reproduced and
`git hash-object` matched. With isolated `Memory` and `CoreFact`
dataclasses matching the repository shapes, **five focused pytest tests
passed** (`5 passed in 0.04s`): input-order equivalence, duplicate
revision recency, bounded multimodal source labels, novelty provenance,
and empty-context safety. This is exact pure module execution using
a local dependency stub, **not** the repository's full pytest suite or
proof that all PR tests pass.

**Actual camera/observer code, source/test checks only:** `5dd00c8` adds
turn/question epoch checks to low-priority XIAO camera CPU preprocessing,
so a human interruption that starts and ends before JPEG preprocessing
completes cannot publish an obsolete frame. `904ddac` adds test cases for
direct optional capture, sensor capture and external pet offer.
`0eeeb38` extends fleet-wide human turn time to camera receipts that
were acquired before another pet's voice but offered after speech ended.
`800d3f2` guards `PetController._observe` before and after its
asynchronous scene-model work to prevent this stale photo from initiating
playful speech or a false firsthand memory. `690d11f` adds the cross-pet
observer regression. Live GitHub file readback confirmed ten source/test
contract checks, but **none of the newly added camera or PetController
regressions executed** here. They require full repository Python deps.

**CI qualification still missing:** GitHub Actions run
[43353820010](https://github.com/hungngodev/desk-robot-remix/actions/runs/43353820010)
reports all four jobs failed with `steps=null`; no compiler/test
diagnostic can safely be inferred. Run `cd code && uv run --no-sync
pytest -q tests/test_brain_context.py tests/test_multimodal.py
tests/test_pet.py` on an actual provisioned runner, preserving
source SHA and failure output. This checkpoint does not qualify the
physical Sense camera exposure clock, audio echo cancellation, battery
charger, fitted print assembly, grasp, dock or five-robot acoustics.



## November 12 next robot brain source checkpoint: intent epoch and physical job continuity

**Real source code committed in PR #17**: `1946af90` installs a pinned
Xiaozhi `intentHandler.py` turn epoch guard, capturing generation before
slow model intent detection; old tool replies, obsolete context replies,
and the nested model speech output are rejected after human barge or
registered head replacement. Pinned upstream original anchors were
independently checked in GitHub and all **8 anchors matched uniquely**.
The isolated pinned intent worker regression
`code/tests/test_xiaozhi_intent_guard.py` (`5ff57a7e`) tests delayed
tool work, delayed nested language model speech, valid uninterrupted
responses and generation captured before LLM detection; overlay map
contract `28bd583e`. This is NOT an executed Python test.

**Accepted robot jobs survive voice epochs and WiFi reconnects:** Mac
`Coordinator.jobs` already contains per-robot job identity and status.
New authenticated read-only `GET
/v1/robots/{robot_id}/jobs/latest-pickup` (`070511aa`) returns only
the requesting robot's latest pickup, with explicit
`available=false, physical_grasp_verified=false` for no record.
Xiaozhi's `desk_robot_job` now reads this Mac owner instead of an
ephemeral WebSocket attribute (`1d1b92b8`). Mutating pickup and STOP
requests retain their original physical HTTP completion semantics, but
if newer speech supersedes their previous reply, the model sees only
silent payload-free `Action.NONE` (`0d2972ab`, `b648af43`).
No action is retried or declared physically successful. New source tests
`1de6f176` and `c30cd4a8` verify reconnection, single-robot
privacy, accepted/pending state and STOP silent receipts.
Ten latest direct GitHub file content checks returned expected
contract markers; this is static verification, **not** Python execution.

Next executed suites on a checkout containing pinned Xiaozhi server:
`cd code && uv run --no-sync pytest -q
tests/test_xiaozhi_intent_guard.py tests/test_xiaozhi_tool_resilience.py
tests/test_server_bridge.py tests/test_multimodal_api.py`.
All full GitHub Actions jobs still report pre-step failures without
runner name or steps, and the app cannot retrieve their annotation
body (though GitHub check-run API reports 2 annotations per job).
Source status alone cannot certify audio interruption, physical gripper,
charging, mechanics, docking or five real powered units.



## November 12 pinned Xiaozhi tool speech and multi-call contract repair

**Source evidence:** In the exact pinned upstream xinnan-tech/xiaozhi-esp32-server
revision `d9c2e8c5`, `plugins_func/register.py` defines
`ActionResponse(action,result,response)`, not `.content`. Yet the pinned
`UnifiedToolHandler._combine_responses` directly accessed
`response.content`, making grouped/parallel tool calls fail when they tried
to combine Mac camera/memory/status outputs. The pinned
`core/handle/intentHandler.py` processes `Action.REQLLM` by requesting
a **new spoken LLM reply** even if the preceding tool was superseded
by newer human VAD. For `Action.NONE`, its backward-compatible fallback
still speaks when a result/response is present. These are source-observed
behavioral defects, not hypothetical API semantics.

**Actual source fixes:** `code/laptop/server/install_overlay.py` anchored
`patch_unified_tool_handler` now reads the actual `.result` attribute
from each tool, JSON-encodes structured results and filters silent
`Action.NONE` results, preserving the pinned upstream checkout and the
existing 8-worker plugin pool (`1eb4d120`). Existing tool wrappers call
`read_only_response` for look, situation, memories and job: if and only if
the Mac marks an old tool superseded by new speech/reconnect, return
`ActionResponse(Action.NONE)` with **NO result and NO response** so no
old speech is generated; valid and recoverable errors retain REQLLM;
physical STOP and guarded pickup retain their separate ACK ownership
(`452910f9`). New tests `d7be4d80`, `6507b62e`, `3ec87b28`
check silent old output and actual pinned combined tool results.

**Execution evidence:** all above source changes committed to same PR #17.
The test additions have **NOT RUN** in this chat. Last observed GitHub Actions
run [43350904666](https://github.com/hungngodev/desk-robot-remix/actions/runs/43350904666)
failed all four jobs with `steps=null`, so compilation/pytest state remains
unknown. Do not call green. Before escalating framework or hardware
claims, run `cd code && uv run --no-sync pytest -q
tests/test_xiaozhi_tool_resilience.py tests/test_server_bridge.py
tests/test_streamed_ollama.py tests/test_brain_context.py
tests/test_multimodal_api.py`, then actual pinned server overlay and
XIAO AEC tests on devices. This is only software source qualification.
Real charging, signed current, full fitted CAD, gripper, docking, playback
and five connected robots are still open.


## November 12 scoped robot brain and context integration source audit

**Only PR #17, no other branch.** Live GitHub blob readback after commits
`99a2b140`, `b086d061`, `1760bb09`, `0fc4d241`, `923021f0`,
`7d429340`, `a3f30a1f`, `415621e2`, `0c46d487` and `a28fba8c`
confirmed **10 source/test contract checks**: (1) completed stream segments
persist only to speaking pet with transmission-only provenance after an
abort; (2) failed second chunk and (3) cancelled stream regression tests
exist; (4) voice/tool/sensor/spoken/camera fairness and (5) crowded-frame
regressions exist; (6) camera/monitor outage preserves bounded transmitted
speech, (7) deliberate full reset clears it, (8) repeated camera receipts
are collapsed in a 400-character interaction budget, (9) native Omni and
proactive speech both use `compose_brain_context` with per-pet consent, and
(10) its API regression verifies no cross-pet leakage or ASR eyewitness
promotion. These are **exact source readback assertions, NOT pytest
executions**. Full Python 3.11 and ESP-IDF/PlatformIO builds are still
blocked by GitHub Actions pre-step failures, with no valid build logs.
Reproduce using `cd code && uv run --no-sync pytest -q
tests/test_streamed_ollama.py tests/test_brain_context.py
tests/test_multimodal_api.py` once an actual checkout/runner works.

**Research and architecture decision:** one Mac event and conversation owner,
Xiaozhi audio VAD and speaker, existing Mac image sampler, per-robot
SQLite, WROOM motor safety. Adopt turn/interrupt frames from LiveKit and
Pipecat, expression ownership from Reachy Mini, small stable identity versus
episodes from Letta/Mem0, persistent checkpoints only where truly needed
from LangGraph, and observation versus action separation from LeRobot/Nav2.
This is not a claim to have copied or executed any of those projects.
See `docs/guides/multimodal-voice-video-orchestration.md`.
No physical speaker playback acknowledgement or demonstrated model tools
in optional MiniCPM native audio; do not upgrade a model capability claim.
Likewise no actual protected battery/charger, fitted complete CAD assembly,
physical grasp, live AEC, dock or five-pet acceptance has passed.



## November 12 current Mac brain orchestration, exact evidence boundary

**Scope:** all modifications on existing draft PR #17. The current source
reuses Xiaozhi's current socket and VAD generation, the existing Mac camera
hub, one `Conversation` speaker lease and five separate SQLite files.
No second agent runtime, memory server, camera process or motor authority.

**Actually executed locally:**

* Exact GitHub `code/laptop/src/desk_robot/memory.py` blob
  `09907bdb8ae6927a623e0e5472fdd83837c9de37`, verified with
  `git hash-object`, passed direct Python assertions for lexical relevant
  episode recall, plural normalization, five distinct private SQLite
  stores, eyewitness vs peer report labels, bounded 250 episodes, capped
  24 operator-curated core facts, invalid input rejection, idempotent
  updates and per-pet deletion.
* Exact GitHub `code/laptop/src/desk_robot/brain_context.py` blob
  `53533ecbbe9f6918ff4ce7aff1ec16fc9edd8a19`, verified with
  `git hash-object`, passed direct Python assertions for context source
  labels, duplicate removal, exclusion of raw camera bytes, independent
  600/500/400-character budgets, context of the pet's preceding
  transmitted remark **without false playback ACK**, and suppression
  of redundant unsolicited lines from the same pet but not peers/old words.
* Independently re-read 13 current GitHub code and test files together:
  **20/20 static integration assertions passed** for private memories,
  curated preferences, current tool cancellation signals, status/STOP
  isolation, chronological media/tool timeline, 800ms post-VAD initiative
  pause, controlled API permissions and actual committed regression sources.

**Committed but NOT yet executed in the full application test environment:**
`test_brain_context.py`, `test_brain_core_memory.py`,
`test_brain_memory_retrieval.py`, newly expanded
`test_multimodal.py`, `test_server_bridge.py` and
`test_xiaozhi_tool_resilience.py`. The current connected GitHub Actions
jobs still fail before usable steps; no pinned Python 3.11/whole
dependency suite, ESP-IDF, PlatformIO, complete native C++ sanitizers,
actual XIAO AEC/camera timings or five live robots have been qualified.

**Implementation detail:** A real Xiaozhi VAD edge sets the old
`tool_turn_cancel_event` so obsolete read-only VLM/memory/status
HTTP requests are cancelled promptly. The existing MAC tool socket and
voice generation check still rejects late responses. Actual STOP and
guarded motion jobs do **not** use speculative cancellation. The live
`desk_robot_situation` tool is independent of durable memory consent;
`desk_robot_memories` remains opt-in. Recent transmitted pet words
may survive a new human VAD for a brief follow-up, but old VLM guesses
are cleared and no physical speaker playback is falsely certified.

**Still open** for product acceptance: full CI execution, source-verified
power path and charging, all board/breakout revisions, fitted printable
Fusion assembly, real simultaneous microphone/camera interruption,
calibrated gripper and terminal docking, licensed commercial mechanics
and five physical robot trials. No build-ready or charging claim.



## November 12 executed targeted native speech and printable prototype checks

**This record is for canonical PR #17 source only.** Executed in an isolated local mirror of exact GitHub blobs, not a full repository checkout. Git object SHA matching was confirmed before running:

| File | Verified Git blob SHA |
| --- | --- |
| `code/laptop/src/desk_robot/realtime_omni_protocol.py` | `393401be31ffeed0ff9bcb7059e8efe236196cf2` |
| `code/tests/test_realtime_omni_protocol.py` | `34587ab3a9101d13aa72941e4481370720fb44a4` |
| `code/scripts/export_fit_kit.py` | `ff943e69178a9b44a7870c995136cf9592ccebdd` |
| `code/tests/test_export_fit_kit.py` | `b72441efeda059200a91e38ef72ca9c5a81c6a3f` |
| `docs/cad/remixes/one_robot_adapter_kit.scad` | `c0e792f64724731ade6b54e293c37662f1a56b3b` |
| `docs/cad/remixes/remaining_fit_gauges.scad` | `540201b724adc2d68dd6ca69ba308d79d7474a81` |

**Actually executed**, local Python 3.13.5 and OpenSCAD 2021.01:

```sh
PYTHONPATH=/tmp/desk-robot-verified/code/laptop/src python3 -m pytest -q /tmp/desk-robot-verified/code/tests/test_realtime_omni_protocol.py
# 24 passed in 0.07s
python3 -m pytest -q /tmp/desk-robot-verified/code/tests/test_export_fit_kit.py
# 4 passed in 3.85s
```

This validates native audio/video *protocol* JPEG boundaries, complete one-second model units, receipt identity, stale response cancellation, rapid double barge-in epochs and no fabricated playback ACK; and validates the CAD exporter's batch behavior, failure handling and real OpenSCAD rendering. Exact source OpenSCAD render and geometry checks separately produced all **10/10** provisional STL files as one watertight component each with no invalid topology edges, **13,236** checked closed manifold edges. Output prototype ZIP (outside GitHub repository) SHA256 `1a4828cebd763c5c919b2ef2b39880e69a7f9c14845723b0d5770749b8a43ae9`.

**Not established:** no full pinned Python 3.11 lockfile suite, WROOM PlatformIO, native CMake sanitizer suite, Sense ESP-IDF build, physical AEC or speaker timing, measured GPIO/charging, fitted Fusion assembly, real 3D printer tolerances, docking, grasping, or five actual connected robots. The repo's four GitHub-hosted Actions jobs still fail before usable execution steps, so their source tests remain unknown. OpenSCAD output is **only prototype adapters and fit gauges** using provisional sizes, not a complete printable robot. The CI workflow now installs OpenSCAD so this real-source test runs when the provider starts jobs. Never use this targeted 28-test pass as grounds to mark physical acceptance, charger enable or batch approval.



## November 12 live camera, native voice and five pet source audit

**Sole target** draft PR #17; head identity to be retrieved before any future run. **No physical measurements or full repo test execution occurred during these changes.** The existing four GitHub Actions jobs continued failing before any recorded job steps; that is not evidence of a Python assertion, C++ compiler or ESP-IDF error.

**Pinned real upstream source checked:** `78/xiaozhi-esp32@c435f99a88066029ec2dbd2d758c8cc9d051565b`, file `main/boards/common/esp32_camera.cc`. Its `Capture()` handles `PIXFORMAT_JPEG` and `Explain()` handles `V4L2_PIX_FMT_JPEG`; its JPEG preview is intentionally not rendered. On that basis, Sense `desk_robot_sense.cc` now requests VGA native sensor JPEG, one PSRAM frame buffer, and WHEN_EMPTY capture (`1040831`). The existing overlaid `Esp32Camera::SnapshotJpeg()` validates SOI/EOI and 512 KiB before copying its framebuffer bytes (`11fcca2`), with new head source regression (`8027a09`). This is not a proven real OV3660/OV5640 capture, capture rate or AEC throughput.

**Actual source integration checks:** Mac `MultimodalOrchestrator.native_frame()` and lock coalescing, live JPEG receipt and grayscale motion headers, native `_camera` keyframe/motion/static refreshing, per VAD generation, deduplicated one-frame-per-receipt audio attachment, and initial VAD wake de-duplication are committed. A new `bench_head_camera.py` read-only stress tool measures actual GET camera/status HTTP latencies and source capture IDs when the board exists, without storing image data or sending any motor command. The tool is not yet run on real hardware. No microphone playback or human interruption latency can be inferred from it.

**Natural dialogue and security:** Authenticated legacy `desk_robot_look` tool results are fenced by current socket and human voice generation; older tool completions are rejected. Mac voice monitor gap invalidates queued VLM frames without releasing a still speaking person. Optional human native ASR text storage requires *separate* `voice_memory_tools_enabled` and `voice_transcript_memory_enabled`; text goes to the correct pet's SQLite as uncertain heard speech. Default flags remain false. In native model duplex, other pets' queued and speaking responses now get independent concurrent local flush requests on a new human VAD; failed flush does not falsely clear audio ownership. Existing backend MiniCPM realtime cannot claim native function calling without a compatible upstream protocol.

**New regression definitions, NOT RUN:** `code/tests/test_multimodal.py`, `code/tests/test_multimodal_api.py`, `code/tests/test_native_omni_xiaozhi.py`, `code/tests/test_runtime_voice_priority.py`, `code/tests/test_xiaozhi_tool_resilience.py`, `code/tests/test_head_camera_bench.py`, `code/firmware/head/tests/test_sense.py`. No new test pass count is claimed for these changes.

**Next measured checks:** on the finished XIAO Sense board run `cd code && uv run --no-sync python scripts/bench_head_camera.py --config config/local.toml --robot robot-01 --seconds 60 --camera-period 1 --status-period 0.2 --report ../docs/records/reports/sense-camera-real.json`, then collect true audio AEC barge latency under simultaneous camera and tool work and five real head speaker trials. Document firmware SHA, PCB/camera revision, 5V load, PSRAM available, camera FPS, p95/p99 device/voice latency, and acoustic silence. Keep `physical_aec_latency_measured=false`, `charging_verified=false`, `assembly_ready=false` until independent signed observations establish them.



## November 12 executable-contract drift discovered during static source review

A real latent USB status regression was present despite earlier assertions: current WROOM `kReplyCapacity=1536` and Sense `kMaxReply=1664`, but `code/scripts/serial_bench.py` still used `port.readline(1152)`. Commit `616cf84` changes the **existing** USB inspection path to a 1664 byte receive bound, retaining the no-retry safety behavior. Commit `3d9697c` repairs stale test contracts that expected old UART sizes, claimed PN532 was not integrated, and searched an obsolete one-line dock contact expression. Commits `fb18778` and `c23cad6` synchronize the actual PN532 nonblocking read-only driver status and status size documentation. The separate `test_dock_charge_pins.py` expected a single-line `case 5: dock_status(now_ms)` but real source uses two lines; `fb18c4b` corrects its exact escaped newline assertion.

**Real independent source computations:** fetched current `BodyControl.cpp`, `BodyControl.h`, `robot_bridge.cc`, USB reader and tests from GitHub. The status format contains 63 printf conversions, 688 literal bytes, estimated conservative worst-case **1498 bytes** using the repository test's documented conversion budgets, inside the **1536 byte** WROOM buffer with 38 bytes of margin; `1536 < 1664 < 2048` for body, bridge and UART ring. Seven exact source assertion checks passed for updated size, PN532 and dock literal alignment; the corrected `case 5:\\n` assertion was read back against the literal firmware newline and matched. **This is a static contract calculation, NOT a compile, serial trace, compiler sanitizer, or full pytest run.** An unpredictable longer dynamic string would still need runtime testing. Reverify on any modified status response and do not call product acceptance.



## November 12 XIAO power and J3 boundary audit, independently checked source

**Target:** canonical draft PR #17, not the default branch. A current head GitHub Actions run [43310129522](https://github.com/hungngodev/desk-robot-remix/actions/runs/43310129522) had four failed jobs and **no recorded steps or artifacts**; job logs returned `BlobNotFound`; the connected GitHub fetch does not allow check-run annotations. This is NOT a compiler verdict. A local private Git clone from this execution environment failed DNS resolution, so **no full pytest, native CMake, PlatformIO or Sense IDF** was executed for these additions.

**Actual independent readback:** GitHub branch files `code/scripts/emit_wiring_manifest.py`, `docs/hardware/one-robot-signal-harness.generated.md`, `code/tests/test_assembly_harness.py`, `docs/hardware/wiring.md` and `docs/hardware/full-feature-wiring-and-shopping.md` were read after commit. Six source assertions passed: the exact six-line XIAO warnings appear in the generator and checked-in harness, mandatory regression assertions name both boundaries, both wiring documents reference the official Seeed pin mux source, and the generated harness still ends with an explicit NO assembly gate. These are **static code/contract checks**, not executed Python tests or electrical evidence.

**New machine gates:** `code/scripts/verify_system.py` emits `sense_sd_j3_isolation_verified=false` and `sense_vbus_power_path_verified=false` even if all source stages pass. `test_verify_system.py` expects these flags to remain false. The motor supply, charger and dock contacts remain disabled/unqualified. See the [bench procedure](../hardware/wiring.md#xiao-external-power-and-sense-sd-j3-acceptance). Before product release, physically inspect the shipped Sense board, measure J3 isolation continuity, evaluate diode/reverse current and rail sag under head load with a current-limited bench supply, log actual instrument readings, then execute all repository tests. Neither readback nor a hypothetical wiring diagram qualifies a cell.


## November 12 authenticated VAD snapshot recovery: commit evidence

PR #17 commits `8e4ad80`, `b8dfd1a`, `75c7d76`, and `f8067e8` fix and test missed speech start/end reconciliation. The Mac now invokes the existing live `MultimodalOrchestrator` voice owner for recovered starts after urgently cancelling the fleet speech floor, preempting peer optional camera requests and updating visual-turn epochs. Recovered ends cancel the head's speech camera sampler. A real orchestrator regression and a small callback regression are checked in. **No repository pytest, Ruff, firmware compile, hardware camera or acoustic measurement executed for these changes in this session.** The most recently inspected completed Actions run, `43309538180`, failed all four jobs with `steps: null`; the new commit's subsequent runner state must be checked again. This is not evidence of a code failure or a green check. Physical VAD-to-silence and image exposure timing still need instrumented measurements.


Use the [trial sheet](physical-trials.csv) to record bench results. The
[report archive](reports) contains earlier machine-readable outputs. Entries
in historical reports preserve the commands and paths used at the time.
Earlier firmware artifacts are in the repository’s ignored
`.tools/pre-layout-builds/` folder. Within that folder, `head/` replaces the
old `firmware/head/build/` prefix and `body-platformio/` replaces
`firmware/body/.pio/`.



## November 12 latest exact-host and product release checkpoint

**Host source tests actually rerun against current GitHub file blobs:** Five standalone C++ programs (`range_scan`, `terminal_ir`, `pn532_frames`, `pulse_raw`, `accessory_math`) compile and execute with GNU C++11, `-Wall -Wextra -Wpedantic -Werror -fsanitize=address,undefined`; all five printed PASS. Their header/test `git hash-object` identities exactly match the current PR #17 source as retrieved November 12. The **current** `code/scripts/verify_system.py` blob `18507e21884369d6f16613746706a58c78a002e2` and `code/tests/test_verify_system.py` blob `eda1127391ad568738568abdfbbc486f28d6da3b` passed **5 real pytest cases** (Python 3.13.5, pytest 9.0.2); the fifth proves that a source suite PASS never certifies legal manufacturing rights or physical product acceptance.

**Native synchronous plugin pattern isolated harness:** eight concurrent `concurrent.futures.ThreadPoolExecutor` tasks occupied a `threading.BoundedSemaphore(8)`; cancelling the first asyncio wrapper did not permit a ninth task; after releasing native workers all capacity returned. Two checks PASS. This tests the concurrency primitive and mirrors the patched server overlay, but **is not the actual pinned Xiaozhi server integration pytest**, which remains unexecuted. Existing `code/tests/test_xiaozhi_tool_resilience.py` now includes the same production source regression; `code/tests/test_server_bridge.py` contract was reconciled to native future ownership after the older inline `run_in_executor` assertion became stale.

**Actions runner attempted again:** re-ran the four failed jobs on run [43306241566](https://github.com/hungngodev/desk-robot-remix/actions/runs/43306241566). The rerun was accepted, but all four jobs again finished FAILURE with **zero recorded steps**. Treat as inaccessible runner/provisioning/permissions or account environment blocker until the actual GitHub Actions UI provides diagnostic detail. Do not claim code failure or test pass from that run. A direct HTTPS checkout from the isolated host is blocked by DNS/egress as well.

**Separate batch release gate:** `docs/ATTRIBUTION.md` now records the original SMARS noncommercial mechanical license and its author's advertised commercial manufacture offer. Software/MIT releases are not evidence of commercial rights to chassis, tracks or forklift prints. `verify_system.py` emits `commercial_cad_rights_verified=false` and `commercial_batch_release_ready=false` alongside the already false charging, fitted CAD, five robot acoustics and assembly fields. Real commercial rights need applicable permission or replacement geometry; real electrical, acoustic, mechanism and printed fit tests still must pass. **Do not mark PR #17 assembly-ready.**


## 2026-11-12 live source cross-layer checks, not passing hardware evidence

**Canonical PR:** [#17](https://github.com/hungngodev/desk-robot-remix/pull/17). Four GitHub Actions jobs (Python and head, WROOM PlatformIO, Sense ESP-IDF and body C++ sanitizers) still fail before their first recorded step. The connector cannot retrieve the job logs. No new host, firmware or physical trial result is PASS. See the exact [runner diagnosis](../reviews/CI_RUNNER_PRESTEP_TRIAGE_2026_11_11.md) before treating a red status as a compiler error.

| Gate | Added source or regression | Current evidence |
| --- | --- | --- |
| Physical sensor event reaches video | All real initiative event kinds match `TRIGGERS`; `sensor_event` schedules a bounded real JPEG task from existing head, with per-head coalescing and source identity | Source committed, deterministic tests added, **NOT RUN** |
| Live human priority | Genuine VAD preempts a queued sensor camera and already queued model reply; rapid end/start replaces a cancelling speech worker | Source committed, mocked regression added, **NOT RUN** |
| Natural grounded one-pet remarks | Physical sensor and camera model prompts explicitly distinguished; expired local LLM replies cannot speak old event | Source committed, mocked regression added, **NOT RUN** |
| Optional two-pet social play | Explicit local privacy consent, two turns, rotating enabled peer, shared Xiaozhi owner, secondhand peer provenance and concurrent stop cleanup | Source committed, mocked regression added, **NOT RUN** |
| WROOM stop priority | A new actual WROOM fault first attempts to cancel Mac motion permit before optional camera sampling | Source committed, mocked regression added, **NOT RUN** |
| Wiring/source registry | `code/tests/test_integration_contracts.py` checks eight ToF lanes, unique GPIO pins, mux 0x70/0x71 and PN532/MCP23017 lane 5, owner source paths and consent | Source committed, **NOT RUN**, **NOT electrical acceptance** |
| Human VAD five-pet preemption concurrency | Mac launches each pet abort and independent coordinated social speaker stop concurrently instead of waiting for slow pet network cleanup first | Source and `test_runtime_voice_priority.py` stalled-head/error regressions committed, **NOT RUN**, no acoustic latency benchmark |
| Audio cleanup before lease release | Xiaozhi group speaker requests physical head decoder flush on stream failures or cancellation **inside** the active group lease; proactive TTS also aborts after partial bridge errors | Code and regression cases in `test_streamed_ollama.py` committed, **NOT RUN**, device DMA playback not measured |
| Active five-pet memory context | SQLite reads on worker threads under a five-second deadline with guaranteed owner release if a database fails | Source and `test_api_conversation.py` host cases added, **NOT RUN** |
| Xiaozhi voice tool fail closed | Existing plugin refuses forged device identity, private traceback leakage and automatic retries after Mac HTTP outage | Source and `test_xiaozhi_tool_resilience.py` mock cases added, **NOT RUN** |
| Physical GPIO map versus source | Firmware `BodyPins.h` and XIAO `sense/config.h` pin symbols match machine-readable plan or test fails | Static regression in `test_integration_contracts.py` committed, **NOT RUN**, cannot prove assembled wiring |
| Firmware checked one robot signal harness | `code/scripts/emit_wiring_manifest.py` enumerates both MCU GPIO maps, crossed UART, two motors, two MG90S, eight range lanes, eight accessory lanes, and explicit unresolved power/terminal IR pins. `test_assembly_harness.py` tests pin drift, duplicate addresses and full lane inventory. | Actual current GitHub source values were independently checked for 19 matching GPIO declarations; isolated generator fixture smoke ran locally. Full repository Python tests and all firmware compilers remain **NOT RUN** on current head; no electrical acceptance. |
| Terminal dock pin allocation conflict | Moves read-only slow reed/PIR to MCP23017 GPIOB0/B1 via BANK=0 0x01/0x0D/0x13; reserves direct WROOM GPIO36/39 for dual IR after checking the ESP32 erratum. Keeps compulsory GPIOA dock sample independent; fake Wire tests cover valid, failed optional GPIOB and separate dock status. | Source committed, static cross-file API check completed; host C++/PlatformIO tests **NOT RUN** on latest PR. Two-channel NEC decoding, physical baffles and charger still **NOT VERIFIED**. |
| Cross-head visual priority and current spoken-turn freshness | Any authenticated human VAD invalidates stale visual tools across all pets, disallows competing head requests; late background JPEGs after CPU prepare cannot publish; explicit camera questions require evidence from after the current turn began. | Source and four recent mock regressions committed in `test_multimodal.py`, **NOT RUN by failed CI**; true Sense exposure/real audio latency not measured. |
| Real optical/audio/power/cad | Five physical pets, real camera/VAD interruption, charge current, final fitted robot/dock and calibrated pickup | **NOT VERIFIED**, still required for assembly-only |

Earlier successfully logged checks remain *historical checks on older commits*, not a certification of this new source. To verify, capture a concrete runner or local terminal command, commit SHA, environment, output, exit code, hardware model, and measured pass/fail before updating this section. Never mark 100 loops or hardware trials done based on source inspections.

## 2026-11-09 independent GitHub Actions host and WROOM evidence

[Host verification run #8](https://github.com/hungngodev/desk-robot-remix/actions/runs/42675991038)
completed successfully against audit commit
`5adb54dd3b54ffa9c511e125099dbf1f5f6f0681`.
The earlier [run #6](https://github.com/hungngodev/desk-robot-remix/actions/runs/42675682437)
had 12 skipped tests because the Xiaozhi device upstream fixture was absent.
The CI workflow now restores the exact pinned upstream and runs those tests.
These are **automatically run on GitHub Ubuntu runners**, rather than copied
from a previous local checklist:

* Python plus head host tests: **116 passed, 0 skipped, 4 subtests passed**.
  The non-failing warning was Starlette's deprecated `httpx` testclient usage.
* Python Ruff lint: **passed** on the specified source directories.
* Body native CTest with address/undefined-behavior sanitizers: **23 of 23 passed**.
* PlatformIO build: **both** the guarded `esp32_stepper` profile and preserved
  `esp32dev` reference profile compiled successfully.

The CI work does **not** restore or compile the actual ESP-IDF Sense head target,
flash a board, supply the missing I2C sensors, or validate microphone AEC,
supply, stopping or gripper performance. The saved Sense firmware artifacts
from 2026-11-03 remain historical evidence, not a new successful head build.

The source document `ESP32 Deskpet Ideas.html` (not checked into Git) was
separately parsed locally on 2026-11-09: JavaScript parsed under Node v22,
567 links and 311 internal anchors were inspected, all internal anchors
resolved and no duplicate HTML element IDs were found. External link
validity, browser runtime behavior and electrical claims were **not** proven
by that static check. See the [engineering research audit](../research/2026-11-09-html-verification.md).

The physical trial CSV still contains zero tested attempts. The robot and
five-unit fleet **remain unverified physically**.

## 2026-11-06 folder reorganization

- From `code/`, `uv run --no-sync pytest -q tests firmware/head/tests` passed
  116 tests and four subtests after a locked dependency install.
- The body’s native CTest suite passed all 23 checks with sanitizers enabled.
  PlatformIO also built the default `esp32_stepper` firmware.
- The Sense overlay installed into a fresh build copy and
  `bash scripts/build_head.sh --board sense --help` loaded the installed
  ESP-IDF and reached the upstream build tool.
- The fleet demo ran a simulated pickup and ten simulated conversation turns.
  The budget and trial checkers read their relocated inputs. The physical trial
  sheet still contains zero attempts.

## Current firmware foundation

Sense8MB/PDM/SSD1306 head target and stepper/DC body profiles now compile.
Portable stepper timing and sensor-fault policy are integrated with local-only
recovery: normal job arm cannot clear a fault. The stepper hardware adapter
provides no sensor I/O or calibration, so it refuses arming. Pet animation,
scheduler, memory and pet-mode motion lease remain unimplemented.

No hardware is flashed, assembled or physically accepted; no geometry changed.
Host tests and compilation do not prove camera/audio, mechanical fit, real sensor
behavior, stopping distance or pickups. See
[firmware progress](../guides/firmware-foundation.md) and
[current evidence](reports/firmware-foundation-2026-11-03.json).

Two stepper originals are saved with hashes; source integrity is not mechanical
qualification. The twelve-video audit covers descriptions/resources and selected
code, not full-frame viewing. The $35.36 target belongs to the earlier basket.
See the [current parts list](../hardware/parts.md) for procurement status.

[Earlier plan-update verification](reports/plan-update-2026-11-03.json) records the prior
documentation-only checkpoint. The historical90 checks below are a separate older
baseline and do not include these new components.

## Product-definition and visual checkpoint — 2026-11-03

User chose a rounder existing head case. [Requirements/acceptance](../product-definition.md)
and [case audit](../research/2026-11-03-rounded-cases.md) now distinguish
requested behavior, current software, measured source geometry and physical gaps.
Sparky v0.1.0 originals and license are saved unchanged; its actual shell measures
about 56×52×54mm, not main/v0.2 dimensions. Source explicitly says not test-printed.

Four [source-based concept views](../cad/concepts/2026-11-03-rounded/README.md)
and an editable native layout were rendered in a separate background Blender 5.2.3
process and visually opened. Head/chassis are actual saved meshes; track/claw/
mount/sensor geometry is illustrative and the bank is not fitted. Originals were
not modified. No print files, fit, manufacturing audit or physical acceptance
result was produced by this visual. No runtime firmware changes in this checkpoint;
earlier software test/build evidence remains dated as above.
[Concept/document checks](reports/product-definition-2026-11-03.json) record source and
preview integrity, local links and the explicit physical-acceptance gap.

## Historical software baseline — 2026-10-30

The plan at that date was five identical cores with removable cosmetics, generic
SG90/N20 actuators, separate camera/OLED/audio modules and existing print files.
**90 checks pass: 60 Python, 20 body C++, 10 head overlay/protocol/snapshot.**
Five-robot mock conversation gives all five IDs two turns. No robot has been
printed, assembled, flashed or physically tested.

The **$36.88 first-prototype parts target** assumes one owned usable power bank
and WROOM. It excludes delivery/tax and includes three allowances; the $50 delivered
cap is not yet established. The $7.11 S3/OV2640 bundle is not qualified against
the compiled Freenove pinout/programming/case. Purchase readiness remains false.
See [ten checks](../hardware/archive/budget-audit.md) and [fleet guide](../guides/five-robots.md).

## Evidence

| Check | Result |
| --- | --- |
| WROOM firmware, PlatformIO 6.1.18/espressif32 6.9.0 | Previously built; exact artifact size/hash in [`build-artifacts.json`](reports/build-artifacts.json); no firmware changes this revision |
| Body portable C++ control tests with address/undefined-behavior sanitizers | 20/20 pass |
| Both head overlays, reversible install/remove/drift, pin/config checks, native protocol/ACK and fresh-JPEG boundary tests | 10/10 pass |
| Active modular S3 head, pinned ESP-IDF release/v6.1 | Build helper exits 0; app 2500528 bytes, merged 8658489 bytes; no flashing |
| Separate CoreS3 head, pinned ESP-IDF release/v6.1 | Build succeeds, app about 2.54 MiB; no flashing |
| Laptop API/control/calibration/transport/conversation/server adapter/budget/trial and head-identity checks | 60/60 pass |
| Earlier upstream Xiaozhi host suite against the CoreS3 build | 143 tests run, 142 pass, one skipped; historical evidence, not rerun for the modular variant |
| Ruff and whitespace checks | Pass |
| Simulation demo | Generated-image pickup logic succeeds; ten total round-robin utterances across five IDs; physical acceptance remains false |
| Budget/trial gates | Reject incomplete quotes and empty physical trial records as intended |
| Source restore | Four pinned upstream revisions verified; source clones unchanged |
| EVA case | Original 300027-byte 3MF saved; four actual meshes, millimeter units, bounds and SHA-256 verified; no geometry edits |
| Gripper/lift sources | Five original STLs saved, binary record lengths/bounds/hashes checked; original-author CC BY 4.0 versus CC BY-NC-SA 4.0 provenance resolved; no slicing/physical checks |
| SMARS sources | Four original matching screwless chassis/wheel/track STLs and original assembly PDF/ZIP saved; structure/bounds/hashes checked; documents not yet reviewed for print quantities |

The modular build is independent of the preserved CoreS3 copy. Its 15 generated
overlay files were compared byte-for-byte with the current overlay sources.
The actual sdkconfig selects 16 MB flash, octal PSRAM, camera SCCB I²C0 with the
new driver, and OLED I²C1. The camera driver's default I²C1 would conflict with
the OLED; explicit Kconfig selection and a compile guard prevent that setting.
Both dependency locks match the pinned project copy. No camera/audio/display
driver was rewritten. Compilation and fake capture/encoding tests do not prove
actual peripheral behavior or case fit.

Case/source records are under `cad/originals/`. All 13 original CAD/document
files matched saved hashes, STL binary lengths and archive/PDF structure checks.
This is source validation, not topology, slicing or physical-fit validation.
The EVA 3MF requires its four objects to be arranged on the print bed.

The skipped upstream host MCP test requires host C++23/cJSON/mbedTLS development
headers absent on this Mac. Firmware MCP code was compiled by the ESP-IDF build.
There is one non-failing Starlette test-client deprecation warning. Host C++
checks use the installed macOS SDK C++ include path described in [the build guide](../guides/build.md).

Firmware hashes and board identities are in [`build-artifacts.json`](reports/build-artifacts.json). Both head
verification configurations have
an **empty bridge token** and disabled wake word; it is a compile artifact, not
personalized local-server firmware. Generate private settings before any flash.
Build output and private settings are excluded from Git.

Useful local checks from the project root:

```sh
uv run --extra dev pytest -q
uv run --extra dev ruff check laptop/src laptop/server/overlay laptop/server/*.py tests scripts firmware/head/*.py
cmake --build .tools/body-host
ctest --test-dir .tools/body-host --output-on-failure
python3 -m unittest discover -s firmware/head/tests -v
bash scripts/build_head.sh --board modular
uv run desk-robot --config config/fleet.simulation.toml demo
python3 scripts/check_budget.py
python3 scripts/check_trials.py
```

Use the C++ include workaround in the build guide if the local compiler cannot
find standard headers. The upstream suite is run from its build copy with the
coordinator Python and the same include-path workaround.

## Five-unit additions verified 2026-10-30

- Two-to-five participants; distinct IDs, bounded dynamic limits (six/six/eight/ten),
  independent histories, every utterance delivered digitally to all peers.
- No overlapping transmissions; all-five mute/session cleanup on completion,
  cancellation, repeated stop, a canceled stop caller, stopped queued speech,
  encoding interruption and disconnected/replaced heads tested.
- API/CLI reject duplicates, oversized groups and invalid turn counts; legacy
  pair limits retained. Hardware fleet examples have motion off and blank real
  device IDs; each duplicate still needs its own measured calibration.
- Missing credentials append without rotation, reject symlinks/duplicate entries,
  retain existing file bytes and use mode 0600. Three new fleet credentials were
  added to ignored local.env; all previous content preserved and no values shown.
- Private head settings resolve the selected fleet's exact credential name.
  Temporary fifth-head fixture verifies ID/token selection, stale-setting removal,
  unchanged public config, restrictive permissions and no token output.
- Named head/power/current readiness gates prevent an allowance-based cheap list
  from being reported as order ready. Original CAD remains unchanged.

Current commands: `.venv/bin/pytest -q` (60 pass), Ruff plus whitespace checks
(pass), `ctest --test-dir .tools/body-host --output-on-failure` (20 pass), head
unittest suite (10 pass, with the documented local SDK C++ include path). No
runtime firmware source changed, so prior head/body builds are preserved rather
than presented as builds for the unqualified cheap camera board.

## Scope and quality review

The final integration keeps the stock camera/audio/display drivers and a unique
board identity, and adds a version-checked reversible overlay. The body has a
strict bounded parser, boot disarm, independent drive deadline and watchdog.
Invalid commands/status polls do not renew control. Watchdog keeps last servo
PWM; explicit disarm detaches. An uncertain ACK is never retried as movement.

The head starts its bridge after Wi-Fi/lwIP initialization; camera capture runs
outside the control HTTP task, and JPEG storage is released before deleting the
FreeRTOS task. Camera snapshots and upstream capture/explain share one lock.
The modular snapshot adapter captures anew before encoding, rejects failed or
unsupported frames and bounds encoded output. The OLED initially shows stock
monochrome emotion glyphs/text; smooth EVA-style eyes remain a later adapter.
Normal voice motion goes through the coordinator; raw head motion tools are
opt-in debugging to avoid competing commands or a stop that later resumes a job.

The coordinator consumes a short, per-robot operator permit, bounds job duration,
cancels on keepalive failure and sends stop on exit. Tests exercise invalid
calibration, wrong ACK/identity, camera/lost-target failures, cancellation,
deadlines and conversation limits. Model credentials cannot enable movement.
The speech adapter checks selected device identities, suppresses acoustic input
while routing digital transcripts and reports transmission rather than measured
playback. These are software checks and source review, not independent hardware
or mechanical certification.

## Still unverified / next actions

- Review original assembly documents for print quantities/orientation; perform
  slicer/topology/fit checks. Source files are collected, not edited or sliced;
  Fusion MCP was unavailable; no geometry changes have been made.
- Measure actual servo fit and flat-key floor clearance, print and bench-test the
  gripper. Perform ten trials per key/candy category before the full build.
- Qualify the cheap head board, actual generic driver package, motor/servo loaded
  currents and existing power bank rating/weight/mount. Finalize speaker mounting and
  delivered charges under $50; $36.88 is a target with allowances, not a cart.
- Confirm exact selected camera sensor/lens, display PCB mount, speaker size and
  head-to-rover bracket/clearance. No component is a measured case drop-in yet.
- Bench-test the compiled modular S3 head and fresh-JPEG adapter on actual
  modules. Confirm OLED address/orientation and camera sensor/byte order. The
  old CoreS3 image cannot be used on the Freenove board.
- Confirm the real WROOM board/USB port. No serial port has been selected and no
  firmware uploaded.
- Verify voltage stability, current/temperature, stopping time, motor polarity,
  camera frames, microphone, speaker and UART on real hardware.
- Install/run Qwen3, SenseVoice, Kokoro and YOLO-World weights/providers. They were
  not downloaded; FFmpeg is currently absent. Full voice/vision inference has not
  been exercised. The base demo uses mock speech and generated images.
- Measure camera geometry and raised-jaw visibility. A planar projection and two
  image detections can misidentify a pickup; human physical trials remain separate.
- Duplicate the validated core four times only after robot one achieves >=8/10
  per category. Test all-five addressing, physical audio timing, disconnects,
  cancellation and cosmetic clearance. Exact owned fleet inventory is unknown.

`physical-trials.csv` is an empty recording template. [`physical-summary.json`](reports/physical-summary.json)
correctly records zero actual attempts and no physical acceptance pass.


---

## Expanded full robot and five peer acceptance cases

*Additional planned verification and unresolved blockers; no new physical trials were conducted.*


No test is a "pass" merely because it appears in this document. Every result is initially **NOT ATTEMPTED** unless the original repo has an explicitly named host-only result. Keep raw measurements, recordings only with consent, commit hashes and per-unit calibration. Do not fabricate attempts or set the existing `docs/records/physical-trials.csv` to passing values.

## Evidence states

| State | Meaning | Cannot assert |
| --- | --- | --- |
| `concept_recorded` | Named idea is present, source/link/proposed value retained | That source is safe, licensed or executable |
| `source_inspected` | Named code/README/datasheet and pin/license checked at specific revision | That the code runs on this board |
| `host_software_passed` | Specified CI job and exact commit green, skipped tests reported | Physical robot safety, audio echo or motor torque |
| `firmware_build_passed` | Correct selected board firmware actually builds at pinned toolchain | That firmware flashed, sensor connected or voice worked |
| `bench_passed` | Real components measured under documented safe stand conditions | Real world operation on any surface/geometry |
| `assembled_robot_accepted` | One final robot passes all mandatory A1–A12 and special gates | Fleet equivalence |
| `fleet_accepted` | Five separately verified units pass identity, speech, social and applicable motion tests | Unrestricted simultaneous roaming, auto docking or all experimental sensors |

## Canonical product tests A1–A12, not negotiable

| ID | Test setup and minimum pass bar | Data to save |
| --- | --- | --- |
| **A1 Face/offline** | Five minutes stationary while Mac is delayed/disconnected. Local blink/gaze/expression stays responsive, no unsolicited physical motion. | Head build SHA, timestamps, FPS/heap, sample animation and no drive pulses |
| **A2 Audio/quiet** | Continuous ordinary speech over robot TTS, no button/phrase. **At least 19/20** trials visibly/audibly stop TTS in **<=500ms** from user speech onset. At least **18/20** recover intelligible *new* request including beginning. 10min echo-only robot speech: **zero false self-interruptions**. Ten-minute quiet mode: no unsolicited speech/motion. Test sustained turns, different users, 0.5m/1m, camera and active WiFi, then motors on a stand. | Speaker acoustic capture/stop latency, VAD/AEC reference logs, first-word transcript, false events, actual DMA/transport flush completion |
| **A3 Control authority** | In simulation operator pet enable stays valid beyond **300s** without reauthorization, until paused/stopped. Fault, stop, reconnect, restart and lost link cancel drive; manual/pickup preempt; no model/reconnect arming; 250ms pulses and 500ms watchdog still enforced; queued canceled activity never runs. | Trace of identity, control owner, permits, status, safe outputs and every denied command |
| **A4 Edge safety** | Every front-left, front-right, rear-left, rear-right and forward sensor invalid/stale/disconnect/mux fault tested. Tether/catch fixture. For all permitted forward/reverse/pivot and supported surfaces, measured detection + decision + coast leave positive margin before any support footprint crosses edge. Recovery **never** automatically reverses or rearms. | Sensor frame timestamps/validity, phase timing, measured wheel coast/sweep, surface/light, lead calculation, fault latch and local recovery |
| **A5 Real manipulation** | **>=8/10 actual flat key** and **>=8/10 actual wrapped candy** *independent* trials. Each real success moves object **>=10mm** up, retains **>=3s**, then places intentionally. Human-assisted or uncertain attempts count as failure. Blocks and magnetic cubes cannot replace required objects. | Object dimensions/mass, calibration, frames, true lift/hold/placement, slip, attempts, failed/assisted flag |
| **A6 Loaded power/mechanics** | Combined tracks/servo/voice/WiFi/camera operate within actual cell, regulator, wiring and module ratings without resets/brownouts, loose mounts, unguarded motion or invalid sensor views. | Voltage at logic/actuator loads, continuous/peak current, temperature, stall response, fuse/switch, camera/gripper occlusion, physical dimensions |
| **A7 Five peers** | Five separately identified physical robots complete 10 total coordinated utterances, exactly one speaker at a time, correct digital peer transcripts, no cross-head command/secret leak, no unpermitted motion; stop and reconnect cleanup. Calibrate and stop-test each unit before its first physical motion. | Per-robot ID/head, microphone state, speaker lease, turn ordering, failed/disconnected unit, secrets isolation |
| **A8 Independent activity** | Within five minutes of stationary non-quiet pet mode at least one attention, curiosity, rest or social activity **starts without a new user prompt**. Fleet spontaneous speech respects initial **>=120s** group cooldown. A local blink alone is not meaningful contextual speech proof. | Chosen candidate, reason, state, vetoes, event/clock, action/audio output, prompt provenance |
| **A9 Pushed visual context** | Person, hand, key, wrapped candy or scene change shown **without speaking/button** produces fresh camera observation and suitable reaction. Repeated stationary sighting not repeatedly announced; stale/disconnected frames cannot trigger scene claim/action. Quiet suppresses unsolicited speech. Concurrent audio/camera measured. Five camera views deduplicate one real event into at most one group announcement. | JPEG capture timestamp (separate from receipt), fresh/old/duplicate frame ID, semantic evidence, language accuracy, cooldown, speaker owner and latency |
| **A10 Head touch** | Real through-case pat/tap/hold detected, false bounce/repetition rejected; touching during exploration locally pauses before reaction; cannot arm/rearm. | Touch traces, shell/hand test, debounce, motion stop time, missed/double events |
| **A11 Tilt/handling** | Actual IMU revision identified; deliberate tilt/shake/suspected pickup and placement distinguish normal motor/servo vibration. Unsafe/held state inhibits tracks. Putdown/reconnect/reboot does not restart canceled motion. | Gyro/accel readings, floor corroboration, thresholds and confusion counts, safe outputs |
| **A12 Optional sounds/light** | If installed, loud sound/clap/whistle/LED behavior does not false-trigger from own speech/drive, has user opt-out and quiet rules, and conforms to pin/current limits. No audible signal itself authorizes movement. | Mic class trace, false positives, LED duty/current, thresholds and privacy state |

The current build has **no A1–A12 physical pass**. Historic host and CI checks test only parts of A3, cancellation state and protocol.

## Full experience scenarios beyond isolated A8 and A9

| ID | End-to-end story required | Must fail if |
| --- | --- | --- |
| `E01` | Robot sees a new key without a spoken command, becomes visually curious, comments accurately, remembers *its* observation and offers a reasonable next activity | Generic timer greeting, stale frame, hallucinated object, secretly armed tracks |
| `E02` | During that unsolicited sentence the human interrupts by ordinary speech. Old TTS stops within A2 gate, first words of human request captured, new turn takes ownership. | Mic muted by residual echo gate; Python queue cleared but ESP speaker continues; new request is lost |
| `E03` | Five camera feeds observe the same moving person. One group representative speaks. Each robot retains exactly its own actual observation provenance; peers receive labelled digital updates. | Five greetings, duplicate event flood, peer memory falsely recorded as personal eyesight |
| `E04` | Human enables quiet while unsolicited response is queued or playing. All pending spontaneous speech invalidated and no deferred continuation; local eyes may continue. | Stale callback later announces, speech queue resumes after reconnect |
| `E05` | Robot has a distinct personality and refers to a previous real encounter with correct robot/person uncertainty and time context | It manufactures a false memory, mixes identities or stores raw private footage by default |
| `E06` | Human manually enables pet exploration for >300s, robot periodically observes, looks, moves in bounded pulses and safely stops on any edge/health fault until operator recovery | LLM obtains motion authority, session silently expires every 120s, fault yields automatic reverse |
| `E07` | Robot can accept touch or handling while moving; tracks stop *locally* before it reacts or speaks, with no auto-resume on putdown | Event is handled only on Mac, robot reverses away from contact without coverage |
| `E08` | Five different robot voices play a cooperative game with ten digital turns, distinct histories and no acoustic self triggering | Duplicate transcript, two simultaneous TTS speakers, peer hears other robot as human |
| `E09` | Robot is asked to pick flat key and candy through existing camera/jaw sequence, reports failure truthfully, never claims grip solely from a servo command | Human assisted motion counted as independent success or object not physically lifted |
| `E10` | Mac/server disconnected: head continues safe local eyes, WROOM stops tracks immediately, no speech/motion retry until explicit recovery | "Offline" reported as working LLM, reconnect autoruns old activity |

## Proactive conversation quality tests, not just "said something"

A spontaneous comment passes *semantic grounding* if the phrase is supported by one fresh visual/sensor event, matches the correct object/person/action and does not assert nonexistent geometry/identity. Record human-rated `correct/relevant/uncertain/false` with representative real scenes and at least five repeated exposures. Compare generic scripted greeting baseline against event-grounded and memory-grounded speech. Define a meaningful false initiation ceiling from observed trial data *before* tuning it to pass; no fictitious threshold without samples. Distinguish `noticed`, `considered`, `silent_acted`, `spoken`, `suppressed` and `rejected` in event logs.

Five peer tests also need fairness: one robot cannot monopolize invitations, a quiet robot cannot be awakened by peer noise, and distinct voices/memories cannot silently leak private context between characters.

## Performance and resource budget tests

| Test | What to measure | Do not assume |
| --- | --- | --- |
| Audio p50/p95/p99 | Ordinary speech onset -> audible stop; first audio chunk; full real-time factor and echo reference drift | RIO ERLE 15–25dB guarantees success in this enclosure |
| Vision pipeline | True source capture time -> event -> local VLM result -> speech; stale rejection; false positives | 1fps means real-time comprehension or CPU can handle five live VLM frames |
| Shared Mac load | One, two and five active robots; STT + Qwen + VLM + Kokoro + video at simultaneous worst plausible demand; memory, thermal, latency | HTML's 13–16GB process estimate or MLX benchmarks are measured on this M1 Max |
| ToF | Optical mount at actual height and surface, read/status/age per channel, whole array worst age, I2C errors, stop margin | A mux makes simultaneous 40ms sample or a prior video threshold transferable |
| Power | Start, idle, speaker peak, two steppers, servo lift/grip, network peak, charge, undervoltage and dropout | IP5306 chip current rating equals a particular cheap breakout's safe 5V output |
| Mechanical | Servo spline, jaw closure, key/candy reach, lift, camera FOV occlusion, costume/tip stability | Printable STL, rendered overlay or successful motor PWM proves fit |
| Storage/memory | Per unit preference persistence, database corruption fallback, atomic write, cross-robot segregation, raw media retention off | Latest LLM reply represents persistent memory |

## Optional sensor expansion gates

Every installed optional device from the feature register must pass five common gates: **identified breakout and voltage**, **mechanical/electrical pin+bus+power and address compatibility**, **licensed known driver**, **bounded typed event with calibration/fault/quality**, and **actual scenario showing benefit without compromising A1–A12**. Specifically:

* Heart MAX30102: measured contact/quality with consent; a valid hardware signal is not a diagnosis. No head mic pin takeover.
* MPR121/APDS9960/SHT4x/BerryIMU/BME/INA219: I2C address and regulator/pullups, read status, aging and independent bus failure.
* Clap/whistle: post-AEC false positives in speech/music/drive, does not stop normal human conversation or arm motors.
* FSR/piezo/reed/Hall/magnets: benign actuator EMI/touch false signals, case fit and no spontaneous motion permission.
* AprilTag/docking: actual mapping error and fiducial uncertainty, safe swept path, charging contact and disconnection policy; none implied by a demo video.
* Thermal/gas/CO2/EDA/radio/Geiger or unusual environment: privacy/safety/licensing/energy reviews before any sensor wiring or claimed measurement.

Keep optional module reports separate from physical core acceptance. No physical expansion can bypass a failing required gate.

## Evidence record contract and template

Use `docs/records/physical-trials.csv` for actual trial rows; do not overwrite its schema. A useful accompanying run manifest records:

```text
run_id, timestamp, commit_sha, robot_id, build_and_tool_versions, board_revisions,
sensor_part_number, circuit_revision, calibration_sha, surface_and_lighting,
person_and_audio_distance, test_case_id, attempts, passes, failures, measured_metric,
threshold, bench_vs_simulation, safe_fixture, objective_evidence_path, reviewer,
acceptance_state, corrective_action
```

Only measured evidence may transition to `bench_passed` or `assembled_robot_accepted`. Photograph/test fixtures and local records must not expose private credentials, raw personal audio/video without consent or unredacted user data.

## Minimum CI needed to enforce full features

The [existing host workflow](../../.github/workflows/host-verification.yml) already runs Python/head checks, body C++ sanitizer tests and WROOM PlatformIO compiles; it is NOT the complete final CI. Add new dedicated tests alongside implementation for:

1. Sensor fake-bus invalid/NACK/stale/status, fault latch and local USB rearm after safe frames.
2. Proactive camera producer, frame age, dedup, real scene event, suppressed busy and quiet state.
3. Per robot memory provenance, atomic persistence and no cross-robot identity contamination.
4. Utility picker reproducibility, human/stop/fault preemption and no model motor credentials.
5. Single speaker lease and peer digital messaging even during human interruption/disconnection.
6. Actual provider-side cancellation, device FLUSH, delayed audio chunk rejection and model busy until playback finishes.
7. Build/flash task for the real XIAO Sense ESP-IDF target with pinned upstream/toolchain. CI build is not an acoustic acceptance substitute.

**Exit of final robot one** is all A1–A12 measured on final hardware plus E01–E10 experience evidence. Then test each duplicate and fleet goals before saying the project is completed.


## 2026-11-10 ten connected engineering passes, not ten physical trials

The consolidated PR #17 now includes code and tests for these connected paths:
WROOM latched fault to Mac job cancellation; Pololu VL53L0X and OzzMaker
BerryIMU identity verification; native touch to Stackchan OLED reaction;
fail-closed head fault display; per-board Sense AEC reference delay; replay
resistant JPEG completion metadata; correct distinction among own utterances,
heard peers and sensory evidence; continuous operator-enabled but physically
gated exploration; shared real WROOM health verification through grip and
placement; and full five-robot simulated conversation, local private memories
and single moving pet acceptance tests.

All changes target the user's existing **full five-pet feature requirements**.
The new real hardware exploration default is locked until measured swept path
clearance and current floor/IMU calibration, not because exploration was
removed from the product. The real gripper and microphone still need their
specified 8/10 key, 8/10 candy, 19/20 voice interruption, and five unit trials.
Do not stamp these passes green from older runs: check GitHub Actions against
the *final PR #17 head SHA* and retain all physical gates as pending until
independently recorded evidence exists.


## 2026-11-11 docking GPIO sample provenance and realtime model handshake review

**Actual GitHub Actions outcome:** [run 43100939229](https://github.com/hungngodev/desk-robot-remix/actions/runs/43100939229), PR #17 commit `19e0a1a6efa2f971dbb667443c6ac8f025ebe5d8`. All four jobs (Python/head, C++ host, WROOM PlatformIO, Sense ESP-IDF) concluded **failure**, with **zero steps reported** and job log endpoint returning `BlobNotFound`. That means the run has **NO usable test execution evidence**; do not attribute the failure to source without a log. No new passing build or physical trial was observed from this revision. Re-run or perform an actual local build before accepting software.

**Docking readout flaw found:** Three identical cached `/api/aux` results previously counted as "stable three samples" despite no evidence of three new MCP23017 transfers. New firmware `DockPinRaw.sample_seq` increments only after `GPIOA=0x12` completes; WROOM UART reports `dock.seq` and `dock.age_ms` within the existing 1100-byte response. Mac source validation rejects missing/future/outdated or unsequenced samples; independent diagnostic requires three strictly increasing hardware sequence IDs and matching contact / PGOOD / CHG states. Host mock test now simulates MCP23017 success and I2C failure without incrementing sequence. Python tests include repeated, reordered, stale, changed and forged source cases. **Code and tests committed, not run.**

**Bounded UART capacity source audit:** after adding `seq` and `age_ms`, the `BodyControl.cpp` auxiliary format string has 44 conversions. A source-based, intentionally oversized string substitution with 10 digits for every unsigned field and `-2147483648` for every signed field yields a 1073-byte JSON payload, below `kReplyCapacity=1100`. This is a static worst-case inspection, **not** a compiled host formatter test or byte-for-byte serial measurement.

**Upstream audio contract reviewed:** [vLLM Omni realtime-duplex API](https://github.com/vllm-project/vllm-omni/blob/main/docs/serving/realtime_duplex_api.md) documents native session-created capability negotiation, 16kHz input PCM, 24kHz output PCM, output identity and model-owned barge-in. New adapter `verify_native_server` fails closed on wrong model, absent native-duplex capabilities, wrong chunk period or incompatible PCM rates before microphone streaming. A 15-second per-device retry backoff retains a bounded error diagnostic rather than creating one failed WebSocket per incoming audio frame. The official [MiniCPM-o 4.5 recipe](https://github.com/vllm-project/vllm-omni/blob/main/recipes/OpenBMB/MiniCPM-o-4_5.md) requires a supported Linux GPU setup; **macOS M1 Max serving is not established**. Native voice and acoustic interruption remain unverified.

**Reproducible commands for actual verification** from `code/` with dependencies installed and pinned fixtures restored:

```sh
uv run --no-sync pytest -q tests/test_dock_evidence.py tests/test_dock_charge_pins.py tests/test_aux_telemetry.py tests/test_native_omni_xiaozhi.py tests/test_server_bridge.py
uv run --no-sync ruff check laptop/src/desk_robot/aux.py laptop/src/desk_robot/dock_evidence.py laptop/server/overlay/desk_robot_native_omni.py tests/test_dock_evidence.py tests/test_native_omni_xiaozhi.py
cmake -S firmware/body -B /tmp/desk-robot-body-host -DBODY_SANITIZERS=ON -DCMAKE_BUILD_TYPE=Debug
cmake --build /tmp/desk-robot-body-host --parallel 2
ctest --test-dir /tmp/desk-robot-body-host --output-on-failure
uvx --from platformio==6.1.18 pio run -d firmware/body -e esp32_full
```

**Physical acceptance remains zero:** Neither a BQ24074 CHG indication nor three distinct GPIOA reads measure actual charge current; no battery protection, power-path, thermal or connector measurement was conducted. No terminal dock motor command, print fit or voice playback ACK was promoted to `ROBOT_VERIFIED`.


## 2026-11-11 registered five-pet human voice and WROOM dock monitor source inspection

This check was conducted by comparing **current GitHub branch file contents** in the same revision (not by running the robots). All 10 static source-consistency assertions returned true: full `esp32_full` requires dock GPIO, local WROOM validates nonzero sequenced samples newer than 500ms, any seat or PGOOD latches motion stop, C++ tests cover installed/missing/hot-removed cases, the pinned Xiaozhi VAD gate uses current authenticated connections and clears on disconnect, MiniCPM output START and each Opus packet obey that gate, tests cover spoken/start/packet races, all eight selected VL53L0X lanes are represented correctly, PN532 is explicitly not integrated and physical trials remain zero, and source-manifest regression tests cover the same implementation evidence.

**This is a STATIC audit, not `HOST_TESTED` or `FIRMWARE_COMPILED`.** The latest PR #17 workflow run [43110335948](https://github.com/hungngodev/desk-robot-remix/actions/runs/43110335948) finished with four failed jobs. Job step records remain absent and earlier log downloads returned `BlobNotFound`; no passing Python, C++ or ESP32 compile can be asserted. The full read-only expansion bus and actual purchased carrier wiring still need physical testing. The power charger, gripper fit, dock contact and original licensed mesh assembly are not completed by these safety reviews.


## 2026-11-11 Reachy Mini source and contextual initiative review

Source inspection retrieved **official** `pollen-robotics/reachy_mini` agent skills and `pollen-robotics/reachy_mini_conversation_app` including its current `moves.py` owner, local candidate VAD audio ducking, profile and camera tools. Also inspected the community `yaseminozkut/judgy_reachy_no_phone` YOLO detector's trigger confidence and persistence. Research mapping and papers are committed at [Reachy Mini proactive reuse review](../reviews/REACHY_MINI_PROACTIVE_REUSE_2026_11_11.md). This is source research only; no Reachy hardware, package or new runtime was installed.

The Mac `PetController._initiative_evidence` now uses the existing low-cost contextual gate before a spontaneous LLM. It requires source-specific confidence for camera categories, validates sensor event kind and finite confidence, keeps quiet/duplicate/fleet cooldown checks, and refuses a reply if **any** of the five robot VAD sources became active while the LLM was reasoning. The group cooldown now advances only after `Conversation.say_proactive` reports actually transmitted audio. Source tests added for a legitimate CAP1188/siderange event, uncertain visual category, cross-fleet active voice, and voice beginning during a blocked model response.

**Verification evidence:** A source-only cross-file audit checked nine contracts against current GitHub source, all returned true, including the existing pinned XIAO Stackchan idle/touch/speaking HSM. There is **no new passing pytest, macOS playback, local Ollama benchmark or physical robot test** from this review. CI remains blocked by GitHub jobs reporting failed conclusions but no usable execution steps or logs. Hand-coded confidence thresholds are illustrative until measured confusion and annoyance rates are obtained; they are **not** paper-trained or hardware calibrated. Full speech interruption, timing and physical performance claims remain unverified.

## November 12 additional NEC and emergency STOP source verification

The selected OOMWOO final alignment hardware **source path** now exists without authorizing docking. WROOM `lib/TerminalIr/NecBurst.h` requires a complete 34-symbol classic NEC mark/space pattern, correct inverted address/command bytes, a final mark, independent receiver sequences and a shared 200ms recency window with at most 120ms receiver timestamp separation. `TerminalIr.cpp` owns exactly two nonblocking legacy ESP-IDF 4.4 RMT channels on reserved WROOM GPIO36/39. It polls only after critical WROOM cliff and mandatory independent MCP23017 dock GPIOA, with all signals read only. `BodyControl` publishes new read-only UART command `ir` and never arms or energizes contacts from that observation. The XIAO authenticated `GET /api/ir` validates the JSON and the Mac `HttpHead.ir_status()` plus `GET /v1/robots/{id}/dock/ir` verify provenance and return the same explicit false physical authority flags.

**Actual observed evidence:** a separately compiled local mirror of the portable NEC logic passed `g++ -std=c++11 -Wall -Wextra -Wpedantic -Werror -fsanitize=address,undefined` and executed **100 valid distinct frames plus 400 malformed timing/termination vectors**, as well as checksum, rollover and no authority assertions. This is a real isolated compiler and sanitizer smoke, **not** a claim that the complete GitHub header, full WROOM firmware, XIAO bridge or physical receiver compiled or passed. Portable source regression in `terminal_ir_tests.cpp`, `guarded_body_tests.cpp`, `protocol_test.cc`, `test_dock_ir.py` is committed; no passing repository CI has been recorded. No physical 38kHz carrier, NEC transmitter, battery, charger, servo or optical alignment has been powered or measured.

**Cancellation priority:** `Coordinator.stop` and the job cleanup path now dispatch the WROOM STOP before awaiting any canceled camera or model tasks. The host no longer uses `asyncio.wait_for(gather(...))`, which can itself block indefinitely on a cancellation-resistant child; it uses `asyncio.wait(..., timeout=2)` and preserves failure status for unresponsive cleanup. `test_control.py` injects a hanging canceled job to assert physical STOP dispatch first. Still unexecuted on the full repository. The local WROOM watchdog and independently latched cliff/bumper/dock stops remain the last safeguard.

**Repeatable future execution:** `python3 code/scripts/verify_system.py --suite body --report verification-result.json` runs real CMake, C++ sanitizer build and CTest with actual subprocess codes. `--suite all` additionally requests Python, Ruff, all three PlatformIO profiles and actual pinned Sense build. The script creates a machine readable receipt with each stage result and **never** sets `assembly_ready`, `charging_verified`, `print_fit_verified` or `five_robot_acoustics_verified` true. The four GitHub Actions jobs are still failing before recording any step and logs cannot be retrieved through the current connector. No arbitrary number of changes, commits or simulated trials substitutes for real live electrical, mechanical and acoustic evidence.


## November 12 native portable source tests, exact blob identity

**Evidence class: HOST_TESTED for the five standalone portable C++ tests listed here only.** Source and test files were retrieved from the canonical PR #17 head, recreated byte-for-byte in an isolated working directory, and verified with `git hash-object` against the actual GitHub blob SHAs before compilation. Executed using GNU g++ 14.2.0, C++11, `-Wall -Wextra -Wpedantic -Werror -fsanitize=address,undefined -fno-omit-frame-pointer`; five processes returned exit code 0 and printed their PASS markers. These are actual compiled and executed repository test sources, not a simulated interpretation of source code. The isolated directory did not contain the complete firmware tree and was not an authorized real rover or full CMake build.

| Actual source test | Verified Git blobs (header(s); test) | Observed executable result |
| --- | --- | --- |
| `range_scan_tests.cpp` | `RangeScanOrder.h` 79330bae; test e146643e | PASS: five critical channels before each rotating optional direction |
| `terminal_ir_tests.cpp` | `NecBurst.h` 7114aba7; test 93e5b98c | PASS: 100 valid classic NEC frames, 400 corruptions, stale pair invalidation, queue age and wrap |
| `pn532_frames_tests.cpp` | `Pn532Frames.h` 596be478; test e91576a4 | PASS: PN532 bounded framing, ACK and checksum, absent/present/invalid tag |
| `pulse_raw_tests.cpp` | `OpticalRaw.h` c08681c2; test adf93510 | PASS: MAX30102 raw 18-bit parsing and uninitialized sample status |
| `accessory_math_tests.cpp` | `AccessoryReadings.h` eaf15dd3, `Bmp280Math.h` f9778e6e, `GestureDecoder.h` e2bd53a9; test 1141127c | PASS: SHT CRC and conversions, BMP pressure/temperature, INA226/MAX17048, APDS9960 direction and empty state |

The commands followed the same portable target pattern (each exact source path substituted):

```sh
g++ -std=c++11 -Wall -Wextra -Wpedantic -Werror \
  -fsanitize=address,undefined -fno-omit-frame-pointer \
  -I <isolated-git-blob-matched-header-directory> \
  <isolated-git-blob-matched-tests/target.cpp> -o <target>
<target>    # observed exit 0 and PASS
```

**New source change not covered by those five passes:** `dc9fb75` invalidates the cached side/rear ToF diagnostics upon a shared mux or I2C fault, and `999f6f2` adds a regression in `tof_mux_tests.cpp`. The new regression initially assumed incorrect scan order. Independent compilation and execution of a small scanner schedule harness established the actual sequence (critical 0..4, then optional 5/6/7 in rotation), and `5006f24` corrected the new test. **This new `tof_mux_tests` regression was not executed or compiled as part of this portable set.** Next run `cmake -S code/firmware/body -B /tmp/desk-robot-body-host -DBODY_SANITIZERS=ON`, build, then `ctest --test-dir /tmp/desk-robot-body-host --output-on-failure` in a full checked-out branch, including the actual fake Wire implementation and CliffGuard.

**CI environmental blocker persists:** Four Actions jobs for the recent PR heads still finish with zero recorded steps, and requested downloadable job logs return HTTP 404 `BlobNotFound`. Direct terminal `git ls-remote` failed with `Could not resolve host: github.com` in the working execution container. This isolated exact-blob route verifies portable components without suggesting that full Python, PlatformIO or ESP-IDF builds passed.

**Still not physically qualified:** cliff stops, camera/VAD acoustic latency, gripper force and fit, terminal IR GPIO36/39 actual receiver timing, approved protected battery/charger/NTC/load sharing, dock contacts and 1S pack current, dimensionally fitted CAD, real motor outputs, five physically active robots. `assembly_ready=false`, `charging_verified=false`, `print_fit_verified=false`, `five_robot_acoustics_verified=false`. Preserve PR #17 draft and do not turn these portable test passes into acceptance of the complete robot.


## November 12 verification runner and full side ranging fault propagation

**Executed repository pytest, exact Git blob matched files:** `code/scripts/verify_system.py` at blob `514d678a1ff622dc3abcf84ca25b8ab118f995c8`, `code/tests/test_verify_system.py` at blob `cce987cbac96f0de47142cf6b06a9e024354ff38`, both retrieved through the connected GitHub source and byte-for-byte confirmed via `git hash-object` in an isolated directory. Ran `python -m pytest -q -ra tests/test_verify_system.py` from the corresponding `code` directory with Python 3.13.5 and pytest 9.0.2. **Observed `4 passed in 0.05s`, exit code 0.** The existing three cases verify stage selection and failure truthfulness; the new fourth verifies that a timed-out subprocess retains bounded partial stdout/stderr, including invalid UTF8 bytes decoded with replacement, without reporting a pass. Commits `95dd143`, `e3eab4a`, `dd7c412`. This verifies only the isolated runner logic, not the full real source/firmware build.

**End-to-end source gap discovered and addressed:** A newly failing TCA9548A mux or shared I2C bus correctly invalidated optional samples inside `TofBus` (`dc9fb75`) but the separate WROOM `BodyControl` telemetry cache could keep publishing `side_ranges.valid_mask` as healthy for up to 350 ms. `BodyControl::invalidate_side_ranges()` now explicitly clears its three optional validity flags without forging presence or changing local motor authority. The WROOM loop compares `TofBus::errors()` before/after poll and propagates new errors into that cache. Regeneration requires a real later side/rear read. Commits `034b346` (API), `81bb36d` (cache), `84c58b4` (firmware integration), `77064ba` (C++ regression), `aa63924` (regression JSON string escaping), and `c577a24` (existing integration guide). The Mac's existing `SideRangeEvents` already requires valid masks and fresh physical observations and resets invalid lanes; no redundant adapter was added.

**Verification boundary:** The new `tof_mux_tests.cpp`, `guarded_body_tests.cpp` and WROOM loop change are **SOURCE IMPLEMENTED ONLY**, because a full checkout cannot be fetched in this runtime and GitHub Actions jobs are failing before steps. No actual full fake Wire/CliffGuard build, PlatformIO compile, or hardware trial was executed for those changes. The exact standalone range scan test pass recorded above confirms ordering only. The canonical next source gate is native CMake with sanitizers plus complete `ctest`, then actual `esp32_full` firmware compile and physical eight sensor mux fault injection. Do not mark `assembly_ready`, charging, dock, gripper or five robot acoustics as verified.


## November 13: implausible IMU gravity replay, source only

PR #17 source `4a8b5e9` preserves `boot_id` and `sample_ms` when a structurally valid MPU6050 frame has physically implausible gravity, while clearing the relative pose baseline. Regression `dab426a` checks that the same conversion cannot restart calibration after a corrected retransmission and a newer conversion can. **No test executed for these commits**: local `git ls-remote` failed DNS resolution for github.com. The GitHub file update was accepted, but this does not prove pytest, firmware or physical behavior. Execute `tests/test_handling.py` and `tests/test_handling_integration.py` on an exact branch checkout before upgrading verification status.


### November 14 ASR whitespace and requested tool priority: unexecuted

Starting PR #17 head `e3d3837262595b465df1dcd32c9e3bc3d2937f43`. Source commit `cac1ba6db71c33615a4ec83daf3718d1ffa354b6`, regression commit `69ae5f67990c089cc5258955428bd662a4e3c1ef`. Human ASR text now uses the same single-line bounded normalization for request matching and prompt display. Regression adds a multiline/leading-space battery request with competing tool receipts to `code/tests/test_brain_context.py`. **Tests not executed**: local container cannot resolve github.com for repository checkout; connector write/readback is not an executable test. QA command: `cd code && python -m pytest -q tests/test_brain_context.py` on the current integration head. No physical verification, battery/charging approval, measured latency or native spoken tool-result proof.


## November 15 stale VAD end ordering regression awaiting execution

Source aac4b52ed9b704379b013fc3b32a79d4d3d0f302 and regression 9a938d89b7052d644f05cdf9ec6987e00c11a248 on PR #17 reject an older speech_end after a newer authenticated human_voice start, preserving the proactive speech floor until the current end. No repository pytest or hardware run occurred. Local git ls-remote failed to resolve github.com, exit 128. Required executable check: cd code && PYTHONPATH=laptop/src python -m pytest -q tests/test_multimodal.py -k stale_speech_end_does_not_release_newer_human_vad. This is a source level race fix only, not proof of physical XIAO interruption or acoustic ACK.


### November 15 Kokoro consent revocation during /speak: unexecuted

Starting PR #17 head b7bc337b8e9afdab33e64a9f664dece88372f004. Source a68822493 and test e4631c79 plus fixture correction 612de49c add a permission recheck after the awaited /speak bridge call, and a deterministic fake bridge consent revocation test expecting the existing group conversation cleanup to request /interrupt. TEST_NOT_EXECUTED: local git ls-remote https://github.com/hungngodev/desk-robot-remix.git HEAD failed DNS resolution; GitHub connector accepted source and test commits but cannot run pytest. Required: cd code && PYTHONPATH=laptop/src python -m pytest -q tests/test_api_conversation.py -k kokoro_permission_revoked_during_bridge_transmission_stops_head. No physical decoder silence, real acoustic interruption, or charger/motion verification claimed.


### November 15 conversation identity validation

Owner: Robot Code Fixes and Cleanup. Reconciled PR #17 at c1cda3b3dd4a004d4de0ef24103dc424735afcc2, 67 combined discussion entries and no inline review threads. Source d4ce61e032c5d08c2fcdae658250d650c7a6141b rejects unhashable, nonstring, empty or duplicate conversation robot IDs before set construction; regression c4898de9793bc612f4e1ab11b41bb5d2e3fa8f40 adds six invalid cases and two valid fleet limits. Eight source-equivalent isolated cases executed in local Python, exit 0. Repository pytest NOT EXECUTED: git ls-remote failed DNS resolution, exit 128. Required exact repository check: cd code && PYTHONPATH=laptop/src python -m pytest -q tests/test_api_conversation.py -k conversation_turns. No physical qualification. Keep PR draft.


### 2026-11-15 group memory persistence consent regression
Source `53d1c053222ac3309d7db510006d85a6cefb6321`: check group consent after asynchronous `_persist_spoken_turn` before publishing history or transcript. Test `cb1b46622834ade7931e45fd111681ac2b1622d7`: `test_group_consent_revoked_during_memory_persist_never_publishes_turn` blocks the write using `asyncio.Event`, revokes permission, and asserts no peer turn publication and released locks. Test status: NOT EXECUTED. `git ls-remote` failed to resolve github.com, exit 128. No device test or physical safety qualification. This guards future transcript publication, not retraction of speech already transmitted or an already committed own utterance.


### November 15 fleet memory duplicate identity rejection
Owner: Robot Code Fixes and Cleanup. Source commit `438c4bb2f9a49fe8dd9ea8de1b25895540e5dca9` rejects duplicate configured robot IDs before creating any SQLite files, preventing two configured pets from silently sharing a single database identity. Regression `6cf15409342ba42d7d9990144267a8bbf7c44f0d` adds three duplicate identity cases and one valid two pet isolation case in `code/tests/test_memory_duplicate_identity.py`. Repository pytest NOT EXECUTED: `git ls-remote https://github.com/hungngodev/desk-robot-remix.git HEAD` failed DNS resolution, exit 128. Required: `cd code && PYTHONPATH=laptop/src python -m pytest -q tests/test_memory_duplicate_identity.py`. No hardware safety or five device validation. PR stays draft.


### November 15 already invalidated Xiaozhi tool request admission

PR #17 starting head `0353e2948ff82636fe9d5dd91e46cc638a8a8320`. Source `bc9cb8e1234ce8467e91285bd70bff94871698f4` checks the existing per-head cancellation event before creating a Mac HTTP task; test `abae394534f3edb8b0b6cdddd20dae6b76f792de` asserts a pre-cancelled `look` never constructs HTTP and produces a silent obsolete-turn result. This closes the admission gap when a speech interrupt happened before the tool bridge began, without adding a new media owner or modifying physical controls. STATUS: SOURCE_AND_TEST_COMMITTED_NOT_EXECUTED. Actual command `git ls-remote https://github.com/hungngodev/desk-robot-remix.git HEAD` failed DNS resolution of github.com (exit 128); pytest and firmware builds NOT executed. Required next: `cd code && PYTHONPATH=laptop/src python -m pytest -q tests/test_xiaozhi_tool_resilience.py`, then live cancellation and camera timing validation. Physical charging, docking, speaker acoustic STOP and motor safety are NOT qualified.


### November 15 read-only Xiaozhi cancellation exception cleanup
Owner Robot Pending Fixes. Source 736a859602cca579a99ce9a35e97cc4606845277 consumes completed obsolete HTTP task exceptions during cancellation cleanup; regression d964eedfb47f47abb86d007fcda627184e3f654e covers cancellation coinciding with request failure. Source and test committed, NOT EXECUTED. Local git ls-remote failed DNS resolution (exit 128). Run `cd code && PYTHONPATH=laptop/src python -m pytest -q tests/test_xiaozhi_tool_resilience.py`; check concurrency determinism and full suite. No hardware qualification. PR #17 remains draft.


### November 15 pending fixer: completed HTTP versus cancellation event race
Owner: Robot Pending Fixes. Starting authoritative PR #17 head `d647ebf1706ec2a4946bdd112cd579a8509e4f51`; 79 issue comments, zero submitted reviews and zero inline threads. Source `61f4d14920a51fafe03ab1708c96d540085ae102` makes the existing read-only Xiaozhi tool bridge inspect the actual cancellation event after the HTTP wait, not only the separately scheduled event waiter task. This prevents an obsolete successful read-only receipt being accepted when HTTP completion and human cancellation race in the same event-loop turn. Regression `6b0e8ddba36459148db50270cb48c4a052913dcb` deterministically returns the completed HTTP task before the event waiter resumes and asserts silent supersession. STATUS SOURCE_AND_TEST_COMMITTED_NOT_EXECUTED: `git ls-remote https://github.com/hungngodev/desk-robot-remix.git HEAD` failed DNS resolution of github.com, exit 128. Run `cd code && PYTHONPATH=laptop/src python -m pytest -q tests/test_xiaozhi_tool_resilience.py` on exact current head, then the broader async cancellation suite. No physical motion, charging, dock, or acoustic verification. Avoid concurrent edits to `desk_robot_tools.py` without fresh head and blob checks. Keep PR draft.


### November 15 camera stream reconnect fixture, partial local check
Source test commit 22082244160247e27d3afaae885fe50184477065 replaces double-escaped JPEG markers with real binary SOI/EOI bytes in three frames used by test_replaced_mjpeg_stream_cannot_publish_or_clear_new_stream. A standalone Python check asserting startswith(b'\\xff\\xd8') and endswith(b'\\xff\\xd9') for all three corrected fixtures executed and passed, exit 0. This is NOT repository pytest. `git ls-remote https://github.com/hungngodev/desk-robot-remix.git HEAD` failed with DNS resolution error, exit 128. Run `cd code && PYTHONPATH=laptop/src python -m pytest -q tests/test_transport_calibration.py -k replaced_mjpeg_stream` on current PR head. No firmware, hardware, or charging test executed; PR remains draft.


### November 16 shared shutdown deadline concurrency correction
Owner: Robot Code Fixes and Cleanup. Starting head `7b94ae367d2edf7899873f203b340dfe241eb09c`. Source `46dbc3600ebaa3099805824ca4496b33b761d4c4` consolidates sequential 0.5-second waits in `MultimodalOrchestrator.close()` into one 0.5-second wait for stream, camera and other tasks. Regression `7c8455b30109f965a4d862f6f839155e7f844055` starts two cancellation-resistant owners simultaneously, checks bounded elapsed time and retained ownership, then releases both and verifies cleanup. TEST NOT EXECUTED: `git ls-remote https://github.com/hungngodev/desk-robot-remix.git HEAD` failed DNS resolution, exit 128. Run `cd code && PYTHONPATH=laptop/src python -m pytest -q tests/test_multimodal.py -k close_uses_one_deadline_for_stream_and_physical_snapshot`. No physical acoustic, camera, motor, charging or docking qualification. Keep PR #17 draft.


### November 16 pending fixer: CAP1188 failed register write completion
Owner: Robot Pending Fixes. PR #17, branch impl/mac-hardware-safety-preflight-2026-11-10. Starting head ae2b149724adecac9cd5be6db535474630fb1c11. Source commit f4b093c7957d281a7b326d0fe894ce67ef67c182 completes endTransmission(false) even if CAP1188 register write fails. Fake injection commit a61977c28f82ca8384bd6468d942a005fa80e0c7 and deterministic C++ regression commit 17a2ff05a2931f164e7f8bb632c6ed0455dea533 assert transaction completion, no stale sample, and optional mux isolation. Status SOURCE_AND_TEST_COMMITTED_NOT_EXECUTED. Local git ls-remote failed github.com DNS (exit 128); no C++ compiler, sanitizer, PlatformIO, CI or physical hardware execution. Next run exact code/firmware/body/tests/optional_i2c_io_tests.cpp target with ASan/UBSan and WROOM firmware build. The physical motor, cliff, dock, battery, acoustics and charging gates remain open. Source overlap: mux owner should reconcile these commits before further changes. PR remains draft.


### November 17 room USB serial cancellation ownership regression
Owner: Robot Integration Fixes. Starting PR #17 head `27b01a6e9276a918572c539a98dbf94a7111368f`. Source commit `4cde26a5b2a9ff7d366846137b9d03c13a41791c` changes `code/laptop/src/desk_robot/room_station.py` to retain and join the actual `asyncio.to_thread` serial worker on task cancellation, including repeated cancellation, and suppress a read returned after the connection stop signal. Test commit `cadfed877347385f5120aaa4d70e268851eb78a6` adds a deterministic blocked-worker cancellation test in `code/tests/test_room_station.py`. Source/test committed, NOT EXECUTED. Actual command `git ls-remote https://github.com/hungngodev/desk-robot-remix.git refs/heads/impl/mac-hardware-safety-preflight-2026-11-10` failed: DNS could not resolve github.com, exit 128. Required test: `cd code && PYTHONPATH=laptop/src python -m pytest -q tests/test_room_station.py -k cancelled_room_reader`; broader station and runtime tests and physical USB disconnect still unexecuted. No firmware build, charging, CAD or physical motor safety verification. Cancellation waits for serial worker exit; an indefinitely blocked callback still needs device-specific bounded shutdown verification. PR remains draft.


### November 17 AMG8833 high-gain thermal validity and atomic chunk test
Owner: desk robot source integrity iteration on canonical draft PR #17. Manufacturer AMG8833 high gain specifies 0 to 80 C object range (Panasonic https://industry.panasonic.eu/products/components/sensors/ir-thermophile-array-sensor-grid-eye ); prior decoder accepted -40 to 125 C, confusing this part with a different sensor operating span. Source commit `db28a288722790409b1a383ce62067b594456d72` makes outside-spec pixels invalid and stages all eight decoded pixels until the entire read succeeds. Test commit `3f02a817b2d75d7021ae7009e53f31abb0fe48e5` covers 0, 25, 80 C, first-above-range, negatives, I2C failure and last-pixel atomic failure/recovery. Local exact-source standalone C++ run: `g++ -std=c++17 -Wall -Wextra -Werror -fsanitize=address,undefined -fno-omit-frame-pointer -O1 -I. thermal_pixels_tests.cpp -o thermal_pixels_tests && ./thermal_pixels_tests` PASS. Independently checked local `git hash-object` of header and test against GitHub blob `b1c38da57be7db1956d4dafe21d7ed9860433fa8` and `ccd0f47ae6060ad03bb6e1406a75a7be8b29a5f1`. Full repo CI, nRF52840 PlatformIO compilation, sensor electrical output, thermal accuracy and physical five pet testing **NOT EXECUTED**. No hardware purchase approved; PR draft remains.


### 2026-11-17 D15 full DC watchdog profile
Observed head before edit: `9deb1a8584d1fc8ee9564e433823457725e3f8fa`. Source commit `852af1cef1ed67fc5ad35271e7696fe35875beb8` sets `DESK_ROBOT_ENABLE_DC_WATCHDOG=1` in the inherited `esp32_dc_full` PlatformIO profile; regression source commit `8a560c086db5df27c7c25b15451e15b82f59201a` asserts profile inheritance and preserves stepper separation. Exact source and test blobs refetched at head `87ae12fa767a3c729559befb9739e0267dbbaa1d`; checks confirmed files contain the change. **Executed test commands: none. Python test NOT EXECUTED; PlatformIO build NOT EXECUTED; hosted Actions unavailable due to user-confirmed exhausted CI budget.** The source change does not prove external CD74HC123 Q2, DRV8833 nSLEEP, stopped CPU cutoff, supply integrity, or loaded braking. Next: independently run `cd code && PYTHONPATH=laptop/src python -m pytest -q tests/test_integration_contracts.py`, `pio run -d code/firmware/body -e esp32_dc_full` from repository root, then perform motor-disconnected oscilloscope cutoff and actual guarded physical trial. PR remains draft; purchasing not approved.


### November 17 CI recovery pass: real runner execution and exact regression evidence
Owner: live PR #17 repair. Previously zero-step CI failures were superseded by actual GitHub Actions Linux jobs at run `44125804371`. Initial body compile failed `TofBus.cpp:149` unused MPU6050 identifier under Werror; source-only fix `4d953ced19e19c37890598d0093ca052fbf47fad`. Python locked install failed because existing `room` optional group was missing in the lockfile; synchronized only the root package metadata (no new package versions) in `1878bb6d9de3170303b381fc5524f95f05256a5d`. Later CI showed locked Python dependency installation SUCCESS. `code/scripts/procurement_release.py` generated CSV mismatches for INA226 shunt, protected switching and haptic driver; corrected exact diff rows in `30f0614a55dbe5b5707c9f3f39da16ba6f883518`; the next CI generated purchase ledger comparison SUCCESS. CI `44126575676` completed 113/115 dock optical tests; two tests expected `optical center` even for huge unrepresentable numbers correctly rejected as `cx/cy must be finite`. Corrected parametrized expected failure types and concise IDs in `dcd7afff0c41db0ceba465181d56320aa3018cd4`. The following CI `44127098490` reported 115/115 optical camera tests SUCCESS and completed the entire C++ host build. Before ctest, 42 malformed double-escaped quote sequences in body test JSON literals blocked compilation; corrected in `dc17126c9a55e70c19453d54b9182c7d55787e47`. Executed GitHub ctest `44127098490` then passed 34/36 host targets (94%); failures were the IR queue test's asserted 75ms "long" stall against actual configured 100ms limit, and the dock monitor's expected stale GPIO error when a forged asserted CHG line had intentionally latched the higher-priority contact power stop. Tests corrected to validate >100ms stall and retained contact lockout in `90676cec4b6ce19a87138b128d2a1c283459f3e1` and `6114ad4cf623d5db6ba33ca614f5e0a17845dfc6`. The full Python suite `44127098490` failed at collection due to an identical parameter decorator moved onto the wrong test in GitHub's **synthetic PR merge tree**, despite correct original branch source. Commit `bda774d95b449c598200261e837401ab82416a8b` makes each decorator syntactically distinct; independently fetched synthetic merge `e8bf3d525a928f33113d1131393863d19690e6db` and verified the correct decorator ownership. **Do not yet claim current complete CI GREEN**: the later run `44128011501` was still PENDING with no job output at the time of this entry. All individual CI passes above refer to specified prior checkout/run; source test corrections not yet fully reexecuted. PlatformIO WROOM and ESP-IDF XIAO live builds, physical hardware, charger isolation and final procurement release remain unqualified. PR stays draft, buying HOLD.


### November 17 C++11 room soil source and fake ADC test portability
GitHub Actions run `44128421430` compiled the guarded stepper, full eight cheap VL53L0X profile, haptic lab, full DRV8833 DC, standalone watchdog lab, combined DC haptic watchdog, and the room bench profile successfully, but the room `feather_nrf52840_room_full` source compilation failed at `src/soil_sample.h:31`: `SoilSample{true, median}` is not valid in the pinned nRF52 Arduino toolchain's older C++ mode when `SoilSample` contains default member initializers. Commit `b9d4a22d1bed17513d81976833b6cf227e85e71a` retains the three ADC validity bounds and constructs the valid result by explicit assignment. The existing portable fake ADC test also used C++14 aggregate initialization; commit `d9f61621701cff8bb2593110b4e8f11be74de35a` gives it an explicit three-value constructor. Both exact GitHub blobs were reproduced and independently checked using local `git hash-object`: header `04b1c32b7391523a765190fdac0dfe1d3520f107`; test `9ddc1a33016ce01cb76d68f9b070225baf9fbc8b`. The exact pair compiled and ran successfully with `g++ -std=c++11`, `-std=c++14`, and `-std=c++17`, each using `-Wall -Wextra -Werror -fsanitize=address,undefined -fno-omit-frame-pointer -O1`. This is **executed local portable source verification**, not a completed real Feather PlatformIO build or physically measured probe accuracy. No board or full shopping approval implied.


### November 17 exact CI read and live input fairness repairs

GitHub Actions run [44135807561](https://github.com/hungngodev/desk-robot-remix/actions/runs/44135807561)
is a completed historical run for commit `99a41a7a14513760ab90fe6951a55759c97cf90a`.
The job metadata reports **SUCCESS** for body C++ sanitizer tests, XIAO
Sense ESP-IDF firmware compile and WROOM/room firmware compile. The Python
and head host job reports **FAILURE**: its log ended with **90 failed,
2131 passed, one error and four passing subtests**. These outcomes are
specific to that run, not to the subsequent moving integration head.

Source repairs committed afterward on the same draft PR:

* `29e1c9f` and `0ba9cbf`: incomplete speaker carrier names now fail
  closed as an unresolved purchase contract rather than raising a TypeError;
  an explicit malformed-carrier regression was added.
* `85a8ca6` and `6e3843e`: shared room USB context now coalesces into
  one pending event-loop callback, replacing stale environmental snapshots
  instead of letting the lower-priority producer fill the audio event loop.
  Four deterministic source regressions cover a thousand-frame burst,
  latest-only delivery and closed-loop races.
* `f01c60e` and `538b11e`: physical sensor initiative is scoped to the
  originating pet, while duplicate shared visual descriptions remain
  fleet-deduplicated. Two regressions distinguish independent touches
  from repeated camera guesses.
* `b74d36f` and `0a025f1`: Runtime's bounded room-shutdown waiter
  shields the original serial task, so a deadline cannot cancel the tracked
  worker and falsely mark ownership finished. The prior test fixture now
  includes the runtime's new bounded queue state and checks zero reader
  cancellation requests.
* `b3ba0ce` updates the existing multimodal orchestration guide.

**Verification for these new patches:** GitHub source changes and regression
files were accepted by the GitHub connector. Their full pytest execution,
Python lint, original PR merge-head tests and physical hardware behavior
have **NOT** been independently executed in this pass. Local repository
clone failed DNS resolution, and a pending workflow is not a passed test.
Next focused command from a full checkout is
`cd code && PYTHONPATH=laptop/src python -m pytest -q tests/test_room_context_backpressure.py tests/test_runtime_room_shutdown.py tests/test_proactive_fleet_event_identity.py tests/test_procurement_release.py`.
Then run complete host verification and all firmware jobs on the SAME
fixed commit. New claims must be based on the specific resulting run.

The 42 robot and dock parent roles, 7 shared station parent roles and 14
nonadditive linked parts are still a sourcing register, not a purchase
approval. Exact carrier schematics, prices, battery current and pack fit,
loaded ToF cliff stopping, dock and charging trials, real audio interruption
and mechanical clearance remain unqualified. `physical_trial_count=0`,
`prices_complete=false`, full first robot purchase HOLD, PR stays draft.


### November 17 14:19 EST pending defect R3, STOP receipt diagnostic
Owner: Robot Pending Fixes. PR #17 observed head f5a846314373bb3d1a2102a3cbca2d5155774d0a. New review R3 reported that Coordinator.stop() overwrites a failed WROOM physical STOP receipt with an inaccurate "WROOM stop dispatched" message when a cancelled job ignores its timeout. The source fix gates the timeout diagnostic on actual acknowledged stop receipt, preserving the failure text and existing failed state on transport errors. Regression: code/tests/test_stop_transport_failure.py blocks a cancelled job, injects a failed body STOP receipt, and asserts failed state, retained unconfirmed STOP error and revoked permit. STATUS: SOURCE AND REGRESSION COMMITTED IF THIS ENTRY IS PRESENT; regression NOT EXECUTED in this connector environment; no physical motor cutoff evidence. Next: execute PYTHONPATH=laptop/src python -m pytest -q tests/test_stop_transport_failure.py on exact commit, then full host tests, independently prove CD74HC123 Q2 forces DRV8833 nSLEEP low during CPU halt. No GitHub Actions retry requested, no purchase authorization.


### November 17 Integration Fixes: cancelled task must not erase failed STOP receipt
Reviewed head b2a18473c04ba7670ff268300596394fa85ea5bb. Source correction in code/laptop/src/desk_robot/controller.py preserves failed job state after STOP transport failure even when asyncio task cancellation completes before stop() returns. Regression in code/tests/test_stop_transport_failure.py injects a failed receipt after cooperative cancellation. Regression NOT EXECUTED here. No GitHub hosted CI rerun requested due exhausted budget. Physical motor stop and watchdog NOT VERIFIED.
