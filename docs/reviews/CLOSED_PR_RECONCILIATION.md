# November 11: actual closed PR patch inventory reconciled against canonical draft PR #17

**This is a file and functional entrypoint audit, not a merge, build or physical acceptance.** Do not assume a closed PR was merged: GitHub reports PRs #1 to #16 and #18 as `closed` with `merged=false`. The live integration is [draft PR #17](https://github.com/hungngodev/desk-robot-remix/pull/17) against `codex/initial-remix`. A new chat must edit the canonical branch, not resurrect old branches without an explicit missing feature analysis.

I retrieved GitHub's actual per-file patches for **all 15 implementation PRs, #3 through #16 plus #18**, and compared the path list to the current recursive branch tree. **Every changed path exists in #17 except the two obsolete PR #9 files** `code/firmware/body/lib/CliffGuard/TofArray.cpp` and `TofArray.h`. These are earlier discontinued sensor acquisition adapters, superseded by the selected pinned Pololu VL53L4CD `code/firmware/body/lib/TofBus/` driver. Their absence is intentional; never restore the wrong sensor library to satisfy a path-count metric. Existence of a file is not a proof that every old behavior is preserved.

## Patch and current runtime review

| Closed PR | Original feature or branch purpose | Present functional successor in #17 | Evidence and remaining gap |
| --- | --- | --- | --- |
| #1, #2 | Original design verification and complete day-zero scope | `docs/product-definition.md`, `docs/PLAN.md`, `docs/source-map.md`, `AGENTS.md` | Historical changes and 200 ideas/131 URL registry retained. These planning PRs were not a full physical implementation. |
| #3 | Independently persisted witnessed/peer memory | `code/laptop/src/desk_robot/memory.py`, `conversation.py`, `test_fleet.py` | Source exists; private memory and provenance tests need current green CI. |
| #4 | Spontaneous camera observations, peer arbitration, quiet mode | `pet.py`, `multimodal.py`, `runtime.py`, `test_pet.py` | Current PetController replaces older PetRuntime. No real long-duration camera/voice session yet. |
| #5, #6 | Actual active visual observation loop, spontaneous chatter, 5 camera fairness | `pet.py`, `vision.py`, `multimodal.py`, `test_pet.py` | Current observer source and lease exist; no end-to-end five physical cameras measured. |
| #7 | Authentic human VAD interrupt and head decoder flush | `desk_robot_bridge.py`, `desk_robot_native_omni.py`, `test_server_bridge.py` | Native model now sends decoder stop before remote cancellation; acoustic interruption unmeasured. |
| #8 | ESP-SR Sense AEC speaker reference and urgent TTS reset | `sense_reference_codec.cc/.h`, Sense overlay install, `test_sense.py` | Source reference and playback reset exist; no actual I2S played-sample acknowledgement. |
| #9 | Earlier 5-channel USB floor calibration and TofArray | `TofBus/`, `CliffGuard/`, `BodyControl/`, `code/firmware/body/tests/cliff_tests.cpp` successor | Original `TofArray.cpp/.h` intentionally replaced. No actual desk-surface stopping trial. |
| #10 | Combined AEC/voice firmware and proactive Mac | Sense overlay, pinned Xiaozhi server bridge, `pet.py`, `test_server_bridge.py` | Integrated source, not physical audible completion. |
| #11 | Pinned Pololu VL53L4CD physical driver, local guard, fail-closed stale readings | `TofBus/`, `CliffGuard/`, `BodyControl/`, `platformio.ini` | Now includes eight VL53L4CD full-profile directions. Only 5 floor/front channels may affect motor guard. No physical sensor qualification. |
| #12 | Owned AT42 head-touch to private memory | `BodyControl/`, `main.cpp`, `pet.py`, `test_pet.py` | Direct WROOM touch and source edge counters; electrode shell and GPIO electrical test pending. |
| #13 | Pickup **and** supervised place/release after measured hold | `controller.py` `placed_positions`, `placed_visually_verified`, `test_control.py` | Verified symbols from actual latest source: object lift and hold require visual evidence, placement uses two observed positions. Still no real flat key or wrapped candy trial. |
| #14 | Immediate local touch hardware disarms motion | `BodyControl.cpp` `touch_trip` and `sample_touch_input` | Stop happens before gesture debounce; actual local GPIO/servo load trial pending. |
| #15 | Long hold, tap, double tap WROOM event classifier | `BodyControl.cpp`, `pet.py` `_remember_touch`, `test_pet.py` | Typed edges source exists, does not assert human identity. Physical classifier jitter trial pending. |
| #16 | Five real WROOM range diagnostics with source freshness | `CliffGuard.cpp`, `BodyControl.cpp`, `test_side_ranging.py` | Read-only status remains and expanded 3 extra directions. Real detection margins pending. |
| #18 | Version-aware BerryIMU raw six-axis source | `BerryImu/`, `code/firmware/body/tests/berry_imu_tests.cpp`, MPU6050 family 4 | Older unknown BerryIMU retained as spare, preferred real MPU6050 six-axis WROOM source + Mac handling memory/camera edges. Real chip/mount qualification pending. |

## Cross-cutting findings from actual code, not old PR titles

* `controller.py` still includes the PR #13 hold/placement verification terms `placed_positions`, `placed_visually_verified` and the at-least-three-second hold refusal. This protects against accidentally replacing actual object placement with a "picked up" chat summary.
* `BodyControl.cpp` still implements immediate `touch_trip()` and typed `touch_double_taps`, with WROOM as the motor owner. These event paths are not a model suggestion.
* `pet.py` still consumes `touch_double`, `touch_hold` and WROOM physical six-axis events; the newly added `handling.py` handles `handling_tilt` and `handling_shake` only after physical qualification.
* Firmware and Mac now preserve independent `dock.seq` sequence and `age_ms`; repeated cached HTTP status cannot be called independent dock input readings.
* The native vLLM Omni model adapter validates the actual `session.created.capabilities` rather than accepting any server that emits the right event name. An offline model has a bounded reconnect cooldown and diagnostic. Human interruption flushes the hardware output first.

## Next review loops with no false success claims

1. Run the current test suite, host C++ sanitizer tests and both firmware builds on an actual executor. GitHub Actions run #43100939229 failed with **zero recorded job steps and missing log blobs**, so its conclusion cannot locate a source regression; do not treat the tests as green.
2. Trace PR #13 actual one-object pickup, 3-second hold and two-frame placement from real Sense camera through grip force and WROOM, never synthetic detection as a qualified real-world attempt.
3. Wire-by-wire check 1S protected cell, charger/load share, fuse, boost and dock contacts against actual component ratings. In particular, BQ24074 PGOOD/CHG are **status pins**, not current measurement. Keep dock contact power off until bench approval.
4. Qualify CAD from original licensed SMARS chassis, gripper, lift, Sense head and dock source: final geometry and harness clearances, not merely watertight fit gauges. Source dimensions and actual purchased boards must be measured.
5. Validate native voice only on a compatible running model and actual XIAO head. A macOS M1 Max alone does not establish Linux GPU model hosting or physical echo cancellation.
6. For every 200-source idea, distinguish a mandatory user behavior, chosen sensor expansion, optional external station and archived reference. Do not equate the full research library with 200 installed sensors.

Keep [AGENTS.md](../../AGENTS.md), [parallel chat handoff](PARALLEL_CHAT_HANDOFF.md), [product definition](../product-definition.md), [source map](../source-map.md), and the newest PR #17 head together as one reusable source of truth. Do not set up local MCP or external memory applications just to coordinate chats.
