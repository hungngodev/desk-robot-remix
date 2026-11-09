# File-by-file implementation plan for the complete robot

This is the actionable engineering map behind [linear stages](linear-build.md). **No code path below is claimed implemented by this document.** Names marked "new" are planned files, not confirmation they exist. Pick one upstream implementation per subsystem, pin/license it and use narrow adapters; keep the existing working stack. The first full-feature robot should be the same base that is duplicated four times, with only calibrated data and cosmetics differing.

## Preserve existing source and the already proven boundary

| Existing code | Keep, extend or test | Do not do |
| --- | --- | --- |
| `code/firmware/body/lib/StepperDrive/{StepperDrive.h,StepperDrive.cpp}` | Tested nonblocking 28BYJ phase generation, bounded speed, injected clock; add calibration/profile data after loaded measurements | Replace with a blocking tutorial sketch, change max pulse or add independent robot motion authority without tests |
| `code/firmware/body/lib/CliffGuard/` | Fault-latched policy with validity/freshness; feed real calibrated sensor frames and test recovery | Rewrite to permit blind sensor-degraded reverse or LLM-initiated rearm |
| `code/firmware/body/src/main.cpp`, `include/BodyPins.h` | Hardware adapter, five-sensor status, touch/IMU and reporting, physical output init, watchdog | Borrow wrong GPIO41/42 Sense PDM pins or use motor pins for optional sensors |
| `code/firmware/head/sense/config.h`, `desk_robot_sense.cc` | Existing compiled XIAO Sense pin map, camera, OLED, audio, UART and authenticated bridge | Port a completely different S3 board's pin layout or disable audio input while speaking |
| `code/firmware/head/install_overlay.py` | Keep pinned Xiaozhi build, exact Sense board augmentation, use reversible narrow AEC/audio feature install | Vendoring incompatible full forks or casually editing original `upstream` tree |
| `code/laptop/src/desk_robot/live_turns.py` | Offline frame pacing, connection/turn epochs, obsolete audio rejection, opt-in observation; attach actual device and provider transport | Treat offline queue clearing as real I2S/DMA audible cancellation |
| `code/laptop/src/desk_robot/runtime.py`, `config.py` | Existing local/simulation provider selection, per-robot IDs and settings; inject one chosen voice/activity/memory owner | Start five independent shared GPU model copies or allow two simultaneous agent activity owners |
| `code/laptop/src/desk_robot/conversation.py` | Preserve bounded digital peer turns and speaker lock; add true live spontaneous turns via single lease | Treat generic turn-limited conversation as continuous social pet runtime |
| `code/laptop/src/desk_robot/controller.py`, `api.py` | Existing authenticated/manual permit, camera/pickup safe jobs and local stop; add pet lease authorization without model credentials | Let a scene description, MCP model or peer message arm, move or clear fault |
| `code/firmware/head/tests`, `code/tests`, `code/firmware/body/tests` | Expand host tests and CI acceptance for all new producers/owners and failures | Mark host tests as physical acceptance or rely only on a full mock demo |

## New interfaces, intended owner and source to remix

| Intended code (new unless existing implementation proves suitable) | Required contract and tested upstream seam | Tests before runtime enabling |
| --- | --- | --- |
| `code/firmware/body/lib/TofBus/` | Small checked I2C/mux platform port around vendor ST/Pololu VL53L4CD or chosen sensor driver, channel 0–4 selection, status/age, per-surface calibration and error/fault invalidation | Fake bus short read, NACK, timeout, invalid status, reset, mixed channels; actual sampling age under motor load |
| `code/firmware/body/lib/BodyEvents/` | Fixed typed reporting to head for floor fault, touch, IMU, low supply, servo state, completed actions. No model or network in the safety path | Local stop before head event delivery, stale event ID, duplicate input, invalid field payload |
| `code/firmware/head/sense/audio_reference_adapter.*` | Real PDM microphone + reference from currently played I2S PCM, align/resample into Xiaozhi ESP-IDF AFE; reuse RIO algorithms/tests with actual GPIO pins and audio task synchronization | Ring reset races, double-talk, playback tail, 90ms only candidate, no echo gate muting user speech |
| `code/firmware/head/sense/playback_flush.*` | Explicit flush/stop generation, decoder plus DMA output zeroing/clearing, acknowledgement of acoustic stop | Old TTS cannot continue or resume after user speech, quiet, network reconnect or change of robot |
| `code/firmware/head/sense/face_adapter.*` | One licensed 128×64 eyes renderer feeding `idle/listening/thinking/speaking/curious/sleepy/blocked/offline`; compare RoboEyes vs MIT source | Offline blinking, display timing and concurrent live audio camera UART; license and head shell fit |
| `code/laptop/src/desk_robot/perception.py` | Typed event source using Google robotics `camera_poller.py`, frame difference/stability, actual Sense capture timestamp, YOLO World or chosen local VLM; event-gated image calls | Real scene change, person/hand/key/candy labels, stale/false image, camera self-motion and duplicate events |
| `code/laptop/src/desk_robot/events.py` | Event schema v1 includes robot/source, capture and receipt clocks, confidence, scene fingerprint, epoch, privacy, witness vs told_about; one dispatcher for camera/touch/sound/safety/peer | Producer spoofing, out-of-order event, reconnect, TTL, duplicate ID, cross-robot misrouting |
| `code/laptop/src/desk_robot/memory.py` | Per-ID durable private records, append-only history/SQLite where selected, single writer, direct witness provenance, preferences, social and cooldown state; exclude raw recordings by default | Atomic writes, restart/corruption, privacy/retention, two concurrent memories not cross-contaminating |
| `code/laptop/src/desk_robot/pet.py` | One deterministic activity owner, statuses `idle/attentive/interacting/talking/rest/exploring/social`, weighted action/utility scorer and hard veto; adapt selected Reachy/Stackchan/Xiaozhi Desk Robot logic | Same clock/random seed reproducible, no autonomous movement from pet alone, no repeated greeting, quiet and turn preemption |
| `code/laptop/src/desk_robot/observation_runtime.py` | Connect `LiveTurns` latest-frame/heartbeat to true camera/scene event producer and LLM/VLM observation turn, keeping busy through audio completion | Prompts never interrupt humans/tools, old completion never clears newer epoch; avoid two speech loops |
| `code/laptop/src/desk_robot/audio_runtime.py` | One shared provider adapter for local STT, live Kokoro speech streaming, transport, VAD, interrupt cancellation and actual head FLUSH | Acoustic A2 on hardware plus host stale chunk/cancel tests; STT fails closed with no fabricated text |
| `code/laptop/src/desk_robot/fleet_events.py` | Coalesce 2–5 camera event sources, choose actual witness/representative, no duplicate group comments; candidate 3s window and evidence-based confidence | Five cameras one event, different events not merged, stale clusters never spoken |
| `code/laptop/src/desk_robot/speech_floor.py` | Exactly one leased audible speaker with epoch/TTL and closed-state cleanup, human voice preemption and unsolicited group cooldown | Drop stale spontaneous speech, do not ventriloquize a disconnected robot, human interrupts current speaker |
| `code/laptop/src/desk_robot/motion.py` | Operator-only continuing pet enable, bounded move permit, single active body source, local guard status, cancel/recovery; no model motor credentials | >300s persistence, stop/fault/disconnect revocation, no auto resume, watchdog/pulse bounds |
| `code/laptop/src/desk_robot/behavior_actions.py` | Typed limited actions: eyes/look, rest, context speech, invite peer, safe inspect, bounded operator-permitted roam, calibrated pickup | Unknown actions rejected, no arbitrary LLM angles, no source bypass of motor controller |
| `code/laptop/src/desk_robot/optional_sensors.py` (or equivalent adapter registry) | Register *only selected* experimental devices from feature IDs: I2C, touch/analog, virtual desktop, remote environmental pods with privacy and fixed typed events | No connected module -> disabled, no false "sensor healthy", wrong breakout/address/voltage not initialized |
| `code/config/fleet.example.toml`, existing private local config | Robot identity, voice, persona, quiet preference, sensor capability ID, minimum qualified calibration, camera and speech owner, Mac rate limits | Identical core but unique encrypted secrets, private paths, no robot ID collision |

Naming is proposed; consolidate instead of creating a file per adapter if the current source offers a better integration seam. The **interfaces and test responsibility** matter more than a specific Python file count.

## API and message contracts

Keep the WROOM UART commands and authenticated head bridge as recorded in [existing interfaces](../guides/interfaces.md). Add versioned read-only sensor/event status without changing the current meaning of `arm`, `rearm`, `stop`, `keepalive`, `drive`, `lift` and `grip`.

Proposed typed app events for a local Mac data model:

```text
CapturedFrame(robot_id, connection_epoch, capture_monotonic, receive_monotonic, jpeg, producer_id)
SensorEvent(robot_id, seq, sample_monotonic, kind, value, validity, confidence, source_id)
ObservedScene(robot_id, scene_id, captured_at, classes, claims, confidence, vision_model_version)
MemoryRecord(robot_id, event_id, observed_by, told_by, witnessed, occurred_at, content, provenance, ttl)
ActivityIntent(robot_id, activity_kind, evidence_refs, created_at, expires_at, veto_snapshot)
SpeakLease(robot_id, generation, owner, issued_at, expires_at, group_cooldown_key)
FlushDirective(robot_id, epoch, reason, cancel_model, cancel_tts, clear_head_dma)
SafetySnapshot(robot_id, timestamp, armed, latched_faults, sensor_freshness, calibration_version)
```

**Authority:** Typed events can be generated by actual sensors, the camera, or a memory/message service, but no event gives motor privileges. Only operator gateway creates a permission token; model processes have no credential or socket that can arm the body. A speech lease does not imply a movement lease. No remembered prior lease can be restored after reboot.

## Exact local Mac benchmark before choosing one provider

Record real resource loads for existing Xiaozhi server + Ollama + Kokoro + local STT first. Compare one shared MLX Whisper large-v3-turbo provider, whisper.cpp fallback and Pipecat/HF alternative only under *the same* one/two/five robot scripted corpus. Compare recorded actual captured acoustic latency, first TTS chunk, VLM scene throughput, memory, thermal and concurrent events. Choose one working adapter before final multi-robot service; do not clone five large models per worker by default. Keep the alternative behind the interface without altering Sense wiring or safety.

## Code and source-license policy

* Never alter ignored original upstream clones or the preserved `docs/cad/originals/` files in place. Record pinned SHA and notice, place small remix patch in a distinct adapter and give source-specific attribution.
* RoboEyes is GPL3; a combined firmware distribution must respect that choice. The original SMARS ancestor and forklift are NC-SA CAD, while Cozmars/Sparky/Tiny Engineer have separate terms. Their license is not inherited from the MIT app just because we linked the file.
* New optical drivers prefer official ST ULD and licensed vendor examples, but every I2C operation must report actual status/quality rather than accepting stale values on errors.
* When replacing an existing source module, write a controlled comparison, allow independent rollback *at source selection time*, choose once before final integration. Avoid manufacturing the wrong hardware and later silently switching to a second system.

## Finishing evidence

The real live robot needs a complete assembled wiring/shell BOM, true body sensor acquisition and guard trials, uninterrupted local face while offline, actual Sense AEC + device flush audible A2, contextual visual A8/A9, persistent separate per-ID memory, one-speaker five-peer social play, pet mode enabled until paused with local safety, and true 8/10 key/candy pickup. All 200 features stay registered, but individual exotic hardware requires a separate approved cost, electrical and sensor test record before calling it installed.

This file is an **implementation checklist**. It does not create those modules or claim their tests were executed.
