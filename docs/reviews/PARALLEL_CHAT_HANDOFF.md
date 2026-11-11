# Desk Robot Remix: parallel chat engineering handoff

**Consolidated on 2026-11-11.** This is the shared context for independent GitHub reviewers working from different chats. It describes **requested complete behavior, source ownership, implementation evidence, unresolved blockers and the next verification cycles**. Do not treat a requirement, a proposed integration or a checked-in test as a physically working robot.

**Actual prior PR patch audit:** [November 11 closed PR reconciliation](CLOSED_PR_RECONCILIATION.md) checks all implementation PR #3 through #16 and #18 against current source and records intentionally replaced files. Do not claim all closed PRs were merged.

**One current repository and PR:** [hungngodev/desk-robot-remix](https://github.com/hungngodev/desk-robot-remix), [draft PR #17](https://github.com/hungngodev/desk-robot-remix/pull/17), `impl/mac-hardware-safety-preflight-2026-11-10`. The PR head changes as reviewers commit. Compare to actual current head, not a historical ChatGPT response.

## November 11 followup: preserve human VAD through long speech and camera failures

The current canonical branch adds four small source/test/documentation iterations after the Reachy Mini initiative gate. The risk was in the real Mac media coordinator, not a missing AI framework:

* `CameraFrameHub.notify("human_voice")` previously guessed an end after seven seconds despite the server now emitting actual authenticated `speech_end`. It now keeps the human voice floor active until a real end or explicit disconnect/reset. This avoids reopening proactive speech during a long utterance. A missing end fails quiet rather than guessing silence.
* Failed XIAO camera capture previously called the full `hub.clear`, which also erased human voice state. New `discard_video` invalidates stale JPEGs and in-flight generations without clearing the independent live VAD evidence. Background speech-frame sampling continues at the existing approximate 1 FPS for up to 60 opportunities per utterance, not indefinitely on a missing end.
* `PetController.start` and `pause` now use the same video-only invalidation instead of clearing the Xiaozhi voice floor. Changing autonomous camera mode cannot tell the speech arbiter that a user stopped talking.
* Added offline regression tests in the existing `code/tests/test_multimodal.py` and `code/tests/test_pet.py` for speech longer than seven seconds, camera failure while speaking and autonomous pause during a live user turn. The implementation and tests are committed to PR #17 but **not confirmed passing**. The latest GitHub Actions jobs finish failed with no published steps, so no source-test diagnosis or acoustic acceptance claim is justified.

This is a small compatible reuse of the existing Xiaozhi VAD, LiveKit-inspired frame hub and PetController state owners, not a second media stack. The real XIAO microphone/speaker, live model speed, final printer assembly, grasp calibration, docking and protected charger remain unqualified.

## The user's cross-chat constraints, all retained

1. **One complete robot, then four identical functional copies.** Five different personalities and removable costumes, not five different incomplete hardware architectures. Day zero design includes the entire desired core; physical bringup may still be staged for safe testing.
2. Do not substitute an easier starter robot, camera-only demo, passive chatbot, fake robot simulation, a different controller, or a new scratch-built chassis. Existing open-source designs, datasheets, guides, drivers and algorithms must be researched first, then adapted to the saved source models and controllers. Custom glue is justified only where an actual compatibility gap exists and must be disclosed.
3. The finished experience is proactive and multimodal: real camera observation without prompts, selected camera frames after changes or touch, multiple sensor triggers, vision grounded contextual speech, persistent private memory with honest firsthand/peer provenance, spontaneous activity, real interruption/double-talk while speaking, quiet and pause, reactive expressions, exploration and independent five-pet social sessions. Match the *interaction quality target* of Gemini Live / ChatGPT Live, not a claim of identical proprietary model support.
4. Small actions must actually connect end to end: signal/electricity → WROOM or XIAO driver → UART/Opus/HTTP → Mac policy and memory → physical result → failure/recovery evidence. Don't add a driver without its physical pins, model-specific calibration, telemetry, runtime consumer and test.
5. Require an actual key and wrapped-candy lift, force-aware grasp, place/release and safe retry/failure. The robot must be able to find and dock itself safely and recharge from verified rated electronics. Camera docking observations and PGOOD pins alone do not prove it.
6. Finished delivery should minimize the human's tasks to **buy, print, assemble and limited real calibration**. Coding, harness planning, schematics, BOM, parameterized printable source, flashing guidance and automated tests belong in repo. Measurements of unknown modules and physical experiments cannot be invented or performed by software.
7. User wants **exactly two purchase lists**: previously owned/reported/ordered and still to buy, with images where feasible. Preserve uncertain quantities (e.g. MG90S ~10) instead of treating a remembered count as inspected stock. Prefer widely used generic modules; avoid recommending new Adafruit-specific purchases. Respect the user's first prototype **$50 delivered cap** including money already spent; report conflicts honestly rather than downgrading core features silently.
8. Review each existing PR and all relevant original sources, including useful closed-PR code, but **commit only in canonical PR #17**. Avoid creating 17 more branches/PRs or resetting decisions because a later conversation was opened. Use small review, reuse, integration, test and verification loops and update this shared context with durable new decisions.
9. No external tool installation, Cognee/Mem0/Obsidian/Notion integration or account data sink is required to make progress. **GitHub is the source of truth**. The agent can use available read/search/build tools to improve confidence but must not condition work on local MCP tools or data stores unavailable in its session.
10. Never claim green CI, tested acoustics, qualified battery charging, printed mechanical fit, validated robot docking, calibrated grip or completed five-robot trials without recorded tool output and measured evidence.

## Provenance and historical review reconciliation

The original 1,074,994-byte `ESP32 Deskpet Ideas.html` and the independent November 9 `desk_robot_research_verification_plan.md` are historical source artifacts. The canonical repository captures their **200** feature/idea categories and **131** unique URLs in `docs/source-map.md` and corresponding test. **Active HTML sections 1 to 16** govern current project decisions; **sections 17 to 23** are a historical Xiaozhi research library, not a pinout or bill of materials.

**PR lineage** (18 known pull requests as of the reconciliation):

| Earlier PR | Original topic | How to treat it |
| --- | --- | --- |
| 1 and 2 | Design audit and one complete day-zero plan | Superseded; planning and source maps live in current docs |
| 3 through 6 | Memory, proactive camera runtime, five-personality arbitration | Closed; check source and tests currently consolidated in 17, do not reopen competing runtime |
| 7 and 8 | Authenticated speech abort, ESP-SR/physical speaker flush and echo path | Closed; current Sense/Xiaozhi source in 17 is the owner |
| 9 through 11 | Legacy/final ranging drivers and fail-closed WROOM safety | Closed; latest **VL53L4CD**, **not** old VL53L0X/VL6180X mux mapping, wins |
| 12 through 16 | Physical touch, motor interlock, tap/hold events, grasp placement and read-only ranges | Closed; inspect current WROOM/Head/Pet/Grasp integration in 17 |
| 17 | Full unified WROOM, Sense, Mac, multimodal and five-pet implementation | **Sole active draft integration PR** |
| 18 | Owned BerryIMU optional diagnostics | Closed; new preferred prototype IMU is MPU6050, optional BerryIMU is version-sensitive |

These are historical *topic* summaries. A closed PR is not proof all its commits are present and passing. Use GitHub file-to-file comparison when recovering something that appears lost.

## Current hardware and state ownership

| Function / physical source | True owner | Current implementation anchors | Known reality |
| --- | --- | --- | --- |
| Four downward cliffs, front obstacle, three lateral/rear read-only ranges | WROOM + TCA9548A 0x70 and **eight VL53L4CD** | `code/firmware/body/lib/TofBus/`, `CliffGuard/`, `code/laptop/src/desk_robot/side_ranging.py` | Code for 8 in `esp32_full`; physical distance, placement and stopping trials outstanding |
| Body IMU, motion and handling | WROOM GPIO21/22 I2C + MPU6050; BerryIMU optional | `BerryImu/`, body telemetry, `code/laptop/src/desk_robot/handling.py`, `pet.py`, `docs/guides/imu-handling.md` | Source includes read-only stationary-reference tilt and gyro/acceleration shake events gated off until an actual mounted MPU6050 is qualified; no physical rotation/bias/threshold measurements |
| Skin, pat, tap, double tap, hold, gestures, proximity and squeeze | Owned AT42 head touch, CAP1188, APDS9960, FSR/ADS1115 | `ExpansionTouch/`, `AccessorySensors/`, `pet.py` | Verify the exact circuit and runtime consumer and never infer touch/gesture from an image |
| Optional angle and environmental sensors | WROOM expansion mux 0x71 | `AccessorySensors/`, `PulsePad/`, `aux.py` | Source includes multiple bounded readings but every individual module needs source, address, pullup, driver and user behavior verification. Proposed PN532 and others are not automatically integrated |
| Camera + OLED + PDM mic + I2S speaker | XIAO ESP32S3 Sense | `code/firmware/head/`, pinned Xiaozhi server `code/laptop/server/` | Original Sense camera, pin sharing and actual AEC reference mandatory. No acoustic board trial yet |
| Human realtime voice and 5-pet floor | Xiaozhi + Mac | `desk_robot_bridge.py`, `desk_robot_native_omni.py`, `conversation.py`, `runtime.py` | Normal and group interruption software exists. New MiniCPM duplex route is opt-in with unqualified real-head acoustic delivery and no physical I2S playback ACK |
| Proactive multimodal frames and history | Mac | `multimodal.py`, `vision.py`, `pet.py`, `memory.py` | Source-aware camera hub and tool exist; no guaranteed image exposure sync or 5-robot visual latency trial |
| Lift, jaw and key/candy feedback | WROOM + Mac | `grasp_feedback.py`, `controller.py`, force ADC telemetry, jaw calibration tests | Fresh force sequence checks in code; no physically measured servo force/geometry and no 8/10 object trial |
| AprilTag dock pose and approach | XIAO camera + Mac; WROOM safety owns motor permits | `dock_vision.py`, `dock_runtime.py`, `dock_evidence.py` | Read-only pose and dock pin evidence, no approved terminal contact movement |
| Battery protection, regulator, charger and dock contacts | Real power PCB/modules independent of model | `docs/hardware/charging-design-and-validation.md`, `code/scripts/power_preflight.py` | No selected qualified current-rated and thermally verified powertrain, no safe live dock charging test |
| Chassis, tracks, gripper, head, mounts and dock | Original licensed STLs + Fusion fitting | `docs/cad/originals/`, `docs/cad/remixes/`, `FUSION_ONE_ROBOT_ASSEMBLY.md` | Original parts and printable fit gauges exist; **not** one final assembled STL/F3D package |

## Critical electrical and mechanical truth

The currently selected full eight-channel sensor plan is **four floor cliff VL53L4CD, one front obstacle VL53L4CD, and left, right, rear VL53L4CD** on dedicated 0x70 mux lanes. A separate 0x71 mux supports expansion. Floor safety cannot wait for Mac, AI or WiFi; front, side, rear readings cannot silently grant permission to back off an edge. MPU6050 preferred, photographed BerryIMU spare. XIAO's PDM microphone uses its fixed GPIO41/42 and speaker is digital MAX98357A. Two 28BYJ48 motors/ULN2003 boards, two MG90S lift/grip servos, 0.96-inch SSD1306 and XIAO Sense camera form the existing mechanical/electronic core. No full robot is assembled. **Current `AGENTS.md` has been corrected so it no longer suggests old sensor families or absent firmware I/O.**

Original SMARS motor chassis/tracks, forklift, Bluino SMARS rack/pinion gripper, Sparky v0.1.0 or more rounded licensed head assets are the source geometries. The rounded style should keep the center face, OLED/camera view and the full key/candy gripper. Mechanical dimensions must come from actual purchased modules and Fusion assembly interference analysis. Keep STL source license terms, especially any noncommercial/share-alike material.

Battery architecture remains electrically unqualified, with a potential 1.5 A charger/load-sharing bottleneck; never connect an unprotected live dock or imply a charger status GPIO measures pack current. No safe automated last-centimeter docking just because AprilTag PnP is valid.

## Detailed acceptance gates to be demonstrated, not asserted

| Gate | Minimum proof | Status at this checkpoint |
| --- | --- | --- |
| Build source | Python targeted tests, body C++ host tests, WROOM firmware and Sense ESP-IDF build against pinned code | GitHub jobs reported failure without available execution steps/logs; investigate; do not mark passing |
| Ordinary speech interruption | At least 19/20 audible TTS stop reactions inside 500ms, at least 18/20 new intents preserved, 10 minutes robot-only speech without self-interrupt | Not physically run |
| Proactive vision | Real XIAO camera 1 FPS speech sampling, event selection, 10 objects under varied light, chronological two-frame changes, false-trigger controls and recorded first-answer latency | Software only |
| Five peers | Five distinct active authenticated devices, memories, personality and source identity, speech floor, no cross-robot images or token leaks, 30+ minutes stable interaction | Software tests / plans only |
| WROOM motion | Measured cliff and rear sweep coverage, fail-closed stops, touch/bump/IMU status, low battery and timeout behavior with realistic surfaces | No bench measurements |
| Gripper | Actual MG90S/FSR pocket dimensions, jaw force and object position data, 8/10 key and 8/10 wrapped candy pickups plus safe release | Code only, no tests on physical objects |
| Autonomous docking | Qualified camera intrinsics, AprilTag detection, protective bumper/funnel, motor-locked contact order, reproducible safe charging current and thermal/fault tests | Pose and statuses only |
| Complete CAD | Actual measured source geometry and part envelopes, printable licensed complete assembly + mating dock, support/clearance check, no collisions in Fusion | Fit gauges only |
| Power | Actual components and datasheets, 1S chemistry/protection, current peak, regulator thermal behavior, safe load sharing, isolated/fused dock and transport safety | No final verified choice |
| Procurement | Exactly two reported-owned/buy lists with correct per-pet quantities, user-approved common generic modules and realistic delivered price including past spend | Lists in repo; cost conflict unresolved |

## Reachy Mini proactive interaction and published research

Read [the official Reachy Mini source/paper reuse review](REACHY_MINI_PROACTIVE_REUSE_2026_11_11.md) before changing audio, conversational initiative or expressions. This pass adapts Reachy's single-output-owner/idle behavior and the LlamaPIE cheap-contextual-when vs LLM-what boundary. It commits source-level first-pass confidence/known-event gating plus a **second fleet voice check immediately before speaking** after a slow LLM. Existing per-robot memories, Xiaozhi transport, hardware WROOM stop and five-pet shared speaker remain owners. No new hardware, package install, custom second agent, or Reachy joint motors were introduced. The current expression renderer/physical audio evidence is still open.

## Original HTML docking requirement recovered on November 11

The original audited `ESP32 Deskpet Ideas.html` still has a close-range **OOMWOO IR beacon** concept (two TSOP38238 receivers, NEC modulation, normally dead charging contacts, maximum three attempts) in the active design references. The present branch includes AprilTag pose and guarded predock movement, **NOT** IR burst decoding, physically validated final alignment, a safe isolated contact supply, verified pack current or a safe terminal-docking retry state machine. [OOMWOO dock-cycle source](https://github.com/makerspet/oomwoo/blob/main/contributions/dock-cycle/README.md) and [Vishay TSOP38238 data](https://www.vishay.com/docs/82491/tsop382.pdf) are the reuse foundation. Do not blindly port the ROS2 stack or assign IR receive pins to the slow 12 ms MCP23017 poll; a compatible interrupt capable pin plan, real carrier breakout, license and power design are missing. Do not infer true charging from a ten-second battery voltage rise or BQ24074 CHG/PGOOD alone. See [the precise recovered gap](../hardware/charging-design-and-validation.md#reuse-original-oomwoo-dock-design-rather-than-inventing-a-final-approach).

## Source reuse shortlist for next coding passes

**Existing sources and algorithms must be read before proposing fresh replacements:**

| Topic | Proven upstream/reference | Current integration |
| --- | --- | --- |
| Live XIAO audio, device AEC and access | [Xiaozhi ESP32](https://github.com/78/xiaozhi-esp32), [xinnan Xiaozhi server](https://github.com/xinnan-tech/xiaozhi-esp32-server), [RIO XIAO Sense AEC](https://github.com/mk14ray/RIO-XIAO-ESP32-S3-Gemini-Live-Voice-Assistant), [Espressif ESP-SR](https://github.com/espressif/esp-sr) | Pinned overlays and playback reference, software timing unqualified |
| Native simultaneous audio and video | [OpenBMB MiniCPM-o](https://github.com/OpenBMB/MiniCPM-V), [vLLM Omni](https://github.com/vllm-project/vllm-omni), [LiveKit Agents](https://github.com/livekit/agents), [Pipecat](https://github.com/pipecat-ai/pipecat) | Native opt-in route plus local model wire, no real device or model acceptance |
| Motion-first frame filtering | [Frigate](https://github.com/blakeblackshear/frigate), OpenCV | Selective VLM scene gate and temporal pair, no physical frame rate proof |
| Safety distance | [Pololu VL53L4CD](https://github.com/pololu/vl53l4cd-arduino), ST ULD | Pinned WROOM 8-lane driver and guard; carrier/electrical test missing |
| Dock visual pose | [OpenCV ArUco](https://docs.opencv.org/4.x/d5/dae/tutorial_aruco_detection.html) | AprilTag read-only detector, terminal docking still missing |
| Servo rack and tracked body | Original SMARS stepper, Bluino gripper, SMARS lift with saved license | Original meshes and parametric adapters; final fit not solved |
| Calibration | Real WROOM ADC/USB logs, `code/scripts/power_preflight.py`, jaw coupons | Source algorithms and forms, no physical measurements |

Avoid unreviewed npm/Python wrappers and license-incompatible firmware transplants merely because they match a keyword. First verify pinned API shapes, electrical voltage, source license and integration target.

## November 11 live five-pet voice and dock interlock loops

**Voice floor source and native model reuse:** The existing pinned Xiaozhi server now derives a short global human-speaking lease only from a *currently registered physical head* that passes genuine server VAD. Repeated VAD-positive frames refresh the lease, two quiet frames end it with a short hangover, and disconnect removes the source. The native MiniCPM model reply is blocked before its TTS START and again before every physical 60 ms Opus frame when any human voice is active in the fleet. It invalidates model epochs, requests the existing immediate XIAO speaker flush, schedules remote model cancel, and frees the peer speech owner without an invented hardware playback ACK. No new ASR, microphone or media server. Tests in `test_server_bridge.py` and `test_native_omni_xiaozhi.py` cover spoofed identity, ongoing speech, late reply start, racing VAD, already playing Opus, disconnect and ownership cleanup. These tests have **not** passed CI at this checkpoint; native acoustic quality is still unmeasured.

**Installed dock status fail closed:** WROOM `BodyControl` uses the already selected MCP23017 and its real `dock.sample_seq` plus `dock.at_ms`. Once present, missing/stale/invalid GPIO data for 500 ms locally stops motion and prevents a new arm. Either single seat contact or PGOOD now triggers the *physical* dock lockout instead of requiring both switches and power. An I2C sample loss stops motors **without intentionally dropping MG90S holding PWM**; newly observed complete removal only clears the latch, never automatically resumes driving. `guarded_body_tests.cpp` adds the dry-contact, failure, stale and rearm sequence; bench tests are still essential. The charger remains unselected/untested and `charging_verified` stays false. See [dock charging design](../hardware/charging-design-and-validation.md).

Both changes were made **in the existing owners** and keep the accepted entire five-pet product. Other parallel chats must fetch latest PR #17 head rather than editing stale local copies of the bridge, native adapter or WROOM body.

## How to coordinate the parallel chats without losing anything

All parallel chats start from this file and `AGENTS.md`, the newest PR head, source map, product definition, and the exact changed files. Do **not** assume another chat's state from a vague summary. Each reviewer should choose a nonoverlapping part (e.g. body sensor safety, Sense/native voice, Mac multimodal, charging, grasp, Fusion/CAD), inspect current code and tests, make a narrow source change on the canonical branch, link the commit, and update this file with a dated findings section only if a durable decision or verified status actually changed.

For repeated small loops use a ledger: `requirement → latest accepted source → actual implementation → upstream reused and license → electrical/transport link → tests run → physical status → PR commit → next smallest gap`. Do not fabricate loop counts, passing green status or physical hardware checks, and never duplicate a component another reviewer already finished. An agent that cannot run tests must report `NOT RUN`, not `PASS`.

On November 11, the existing MPU6050 raw WROOM status was connected to Mac `handling_tilt` and `handling_shake` event edges, private witnessed memory, spontaneous speech arbitration and the existing selective camera hub. Config opt-in remains false and physical upright/gyro calibration is unverified; see [IMU handling](../guides/imu-handling.md). The sample identity, body wheel-state gate, hysteresis and source failures are covered by new mock test files, but no new board trial was run.

The immediate order of concern is **actual test execution and CI startup**, native audio protocol and model/head validity, power and docking electrical design, source geometries and printed fit, then measured grasp/sensor acceptance. Documentation and simulation assist but are not substitutes. After each pass choose the next smallest concrete gap; never claim the sprint is complete based solely on the number of commits or PR lines.

**End state**: a full robot with tested battery charging and actual reusable CAD/wiring/software that the builder can buy, print, assemble and minimally calibrate. Until evidence exists, PR #17 remains draft.
