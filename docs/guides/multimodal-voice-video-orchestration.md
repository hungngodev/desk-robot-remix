# Native Xiaozhi + adaptive live video: full desk pet orchestration

Status: November 10 2026. **Code committed, real XIAO mic/camera and physical audiovisual latency NOT QUALIFIED.** This keeps all five full-feature pets, independent episodic memories, WROOM local cliff safety, calibrated grasp plans, RGB/OLED expressions and docking. It does not replace them with a webcam demo or a second robot framework.

## Source comparison and engineering choice

| Actual open-source implementation | Exact reusable mechanism | What was implemented |
| --- | --- | --- |
| [LiveKit Agents video sampler](https://github.com/livekit/agents/blob/main/livekit-agents/livekit/agents/voice/agent_session.py) | VoiceActivityVideoSampler raises capture from 0.3 FPS idle to 1 FPS when human is speaking; frame forwarded into human turn | `CameraFrameHub` 0.30/1.0 FPS cadence plus high-priority voice/physical sensor triggers and bounded 3-frame RAM cache |
| [LiveKit video + realtime model docs](https://docs.livekit.io/agents/multimodality/vision/video/) | Latest frame attached to the actual user turn; Gemini Live or OpenAI Realtime can accept native video, not every model can | `desk_robot_look` asks an installed **image-capable** local Ollama VLM a real camera question in the active Xiaozhi conversation. It is tool-mediated, **not** a native realtime video model |
| [Pipecat frame processor](https://github.com/pipecat-ai/pipecat/blob/main/src/pipecat/processors/frame_processor.py) | Interruptions flush obsolete queued work and user input has priority over background assistant output | Authenticated Xiaozhi VAD stops old TTS, cancels five-pet Mac speech and in-flight background visual inference before a user visual question. No competing Pipecat audio stack |
| [Frigate motion detector](https://github.com/blakeblackshear/frigate/blob/dev/docs/docs/configuration/motion_detection.md) | Cheap motion candidate filter before more expensive object/VLM operations; regional relevance matters | Existing `VisualChangeGate` remains the VLM gate. New brightness-corrected grayscale motion scoring ranks the bounded previous frames and suppresses pure broad lighting shifts from being classified as motion |
| [Frigate snapshot selection](https://github.com/blakeblackshear/frigate/blob/dev/docs/docs/configuration/snapshots.md) | Keep a best representative frame rather than every video frame | One most recent frame for static questions; at most one high-motion prior plus latest for questions about change, movement or what just happened |
| [Xiaozhi firmware and camera MCP](https://github.com/78/xiaozhi-esp32) | Bidirectional Opus, ESP-SR AEC, native ESP32 camera tool, MCP function registry | Keep existing XIAO Sense firmware, authenticated JPEG endpoint, `/events` VAD path, xinnan server overlay and `plugins_func.register`. Add one `desk_robot_look` tool routed to Mac |
| [Ollama Qwen3-VL](https://ollama.com/library/qwen3-vl/tags) | Local image input with 4B and 8B instruction variants | Reuse existing Mac Ollama `/api/chat` image API for current image question answering and two-photo comparison; no new cloud service or another camera |

## Actual data paths

### An actual human asks to see something

1. XIAO Sense PDM microphone feeds the existing Xiaozhi AEC/VAD/Opus server.
2. Pinned Xiaozhi `receiveAudioHandle` now emits a debounced authenticated `speech_start` event from two actual VAD-positive frames while the robot is idle, **not only when the robot is already talking**. If the robot is speaking, the existing AEC double-talk handler emits `normal` or `group` and urgently flushes stale TTS. Both use authenticated `/events`; the idle event never invents AEC or aborts silent speakers. Audio priority is independent of JPEG.
3. The Mac `Runtime._on_voice_interrupt` cancels obsolete peer/pet speech and background Ollama scene inference, **then** synchronously signals the camera hub to schedule nonblocking near-1 FPS JPEG samples while real human speech remains active, capped at 60 frame opportunities per utterance to limit camera load.
4. Xiaozhi's current ASR/LLM conversation calls `desk_robot_look(question)` for a visual question. The tool uses the authenticated robot identity from the **current** Xiaozhi websocket and the existing loopback Mac API. It cannot claim another robot's camera.
5. `MultimodalOrchestrator.look` requires opt-in and a named local vision model, chooses an image received within 600ms or captures a fresh XIAO JPEG, and picks one or two chronological views from the bounded six-second window.
6. `OllamaScene.answer` asks the local VLM to answer the actual spoken question over those photos. Confidence and JSON types are validated. If uncertain, it returns a short inability to see rather than fabricating detail. It can answer questions about objects and visible changes; it does **not** know that the camera recorded video continuously.
7. The model receives the text response with `recent_sensor_events`: actual WROOM touch/gesture/force/other event kinds or authenticated Xiaozhi human VAD with timestamps, not inferred visual facts. Xiaozhi's existing speech pipeline speaks the response to the same robot.
8. The audio session's normal Xiaozhi interruption still applies while the VLM/tool is working. No gesture grants a motor permit.

### No human speaks: proactive camera observation

* The pet's operator-enabled observation loop uses the existing 2-confirmation `VisualChangeGate` and expensive 2-photo VLM scene comparison. Only actual semantic change may become memory or a short spontaneous comment.
* When the hub is attached to hardware, camera sample cadence defaults to about 0.3 FPS idle and speeds up after actual movement/sensor events. A valid CAP1188 pad, touch press, nearby object, APDS9960 wave, magnetic dial or WROOM safety event can request an immediate new frame.
* Only one `_vision_lock` exists across all five robots. Human speech cancels old background inference and gets priority over a queued unsolicited comment. Per-robot voice turn and visual query epochs reject a late image model answer after another human utterance or visual question supersedes it. The Mac's existing cooldown and single speaker lease prevent five overlapping unsolicited audio sessions.
* The hub keeps at most three compressed JPEGs **per robot**, in RAM only. Operator pause and runtime shutdown clear the stored visual context. Source identity, receive time and event provenance are separate. A frame from one robot never gets labeled as another robot's eyewitness memory.
* Sensor and vision comparisons cannot arm motors. WROOM's 500ms watchdog and local physical safety remain independent.

## Enable on the actual Mac

The robot must have a working XIAO ESP32S3 Sense camera and firmware, a configured local Xiaozhi voice connection and a Mac Ollama instance. Run:

```sh
ollama pull qwen3-vl:4b-instruct
ollama list
```

Set the following in a **private** local copy of `code/config/robots.example.toml`:

```toml
mode = "hardware"
vision_model = "qwen3-vl:4b-instruct"
voice_vision_tools_enabled = true
# Keep head_url, each robot's device_id, token_env and fleet selection actual.
# Do not hardcode tokens in committed files.
```

Restart the existing Mac runtime and pinned Xiaozhi server after updating their config. The xinnan server overlay registers `desk_robot_look` via its existing function registry and calls `POST /v1/pet/{id}/look`; the model prompt explicitly instructs tool use only for real human questions. The same `DESK_ROBOT_TOOL_TOKEN` already used by the existing pickup/status tools authenticates this read-only path.

For a local **operator** camera test, with the actual robot connected:

```sh
curl -fsS http://127.0.0.1:8765/v1/pet/robot-01/vision-status \
  -H "Authorization: Bearer $DESK_ROBOT_API_TOKEN"
curl -fsS -X POST http://127.0.0.1:8765/v1/pet/robot-01/look \
  -H "Authorization: Bearer $DESK_ROBOT_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"question":"What am I holding in front of you?"}'
```

If `voice_vision_tools_enabled = false` or no model is installed, spoken camera questions return an explicit error, not a fabricated scene. Neither opt-in nor model selection turns on autonomous locomotion. Opt into proactive camera remarks separately using the existing operator `/v1/pet/{id}/start` endpoint.

## Real physical acceptance still required

* Measured actual source-frame exposure timestamps versus Mac receive time. XIAO currently reports capture completion metadata, which guards against replay but is **not** a synchronized microphone/photo exposure clock.
* At least 20 human trials with speech while the robot is talking: target 19/20 visible or spoken interruptions with speaker silence within 500ms, plus a log of false positives and echo performance.
* “What am I holding?” queries against 10 familiar and novel objects, in varied light/angle; record correct model answer and real first-audio response latency. The `confidence` returned by a VLM is not physical validation.
* “What just moved?” tests with the previous and newest chronological frames, global lighting changes, camera shake, network duplicate/stale JPEGs and loss/reconnect.
* Actual touch/gesture timing and 5 simultaneous pets: one user's voice should preempt all unsolicited audio without causing another robot's memories or images to leak.
* On-device memory/CPU usage, source metadata, WiFi/jitter, XIAO frame rate and Ollama 4B/8B throughput on the Mac. A 45 second vision provider timeout is not a latency promise.
* Full end-to-end realtime **speech-to-speech** Gemini Live/ChatGPT Live quality is still separate from a VAD + STT/LLM/TTS + vision tool pipeline. Moving to Pipecat/LiveKit native video+realtime model would require an actual Opus/PCM transport adapter and provider integration, not a one-line model name. Such an adapter has **not** been shipped or verified.

## Code map

* `code/laptop/src/desk_robot/multimodal.py`: frame cache, adaptive priorities, transient audio/sensor events, voice camera captures, visual question routing.
* `code/laptop/src/desk_robot/vision.py`: existing scene comparator and new local two-frame question answer.
* `code/laptop/src/desk_robot/pet.py`: proactive camera/event scheduling and cancellable background visual inference.
* `code/laptop/src/desk_robot/runtime.py`: wire Xiaozhi VAD to camera after audio cancellation.
* `code/laptop/src/desk_robot/api.py`: authenticated voice-vision status and visual question endpoints.
* `code/laptop/server/overlay/desk_robot_tools.py`: native Xiaozhi `desk_robot_look` tool.
* `code/tests/test_multimodal.py`: offline source, sampling, identity, consent, temporal selection, VLM and no-motion assertions.

All changes above are source implementation and mock tests. No actual XIAO board, Mac GPU inference trace or microphone/speaker was accessible during the coding pass; CI may still fail and must be checked separately.


## November 11 continuation: actual event-loop latency, speech end, and diagnostics

New source changes preserve the same Xiaozhi and Mac owners:

1. **Real VAD end**: the pinned server's existing `receiveAudioHandle` VAD callback now emits an authenticated `speech_end` only after **two consecutive VAD negative frames** following an actual `speech_start`. A brief silence inside a phrase is not treated as the end. The Mac listener validates the source and ordered event; the runtime stops voice-priority camera sampling without cancelling the current human reply or deleting its recent JPEG evidence. `normal` and `group` double talk remain separate events for urgent physical speaker flush.
2. **No Pillow blocking the audio loop**: live authenticated camera captures remain serialized per head, while bounding JPEG downscale/encode work is delegated to `asyncio.to_thread` under a two-worker preprocessing semaphore. Only the Python event-loop owner may publish results to the camera frame hub. A generation token discards a frame if operator pause, reconnect or shutdown occurred while it was being processed.
3. **No obsolete 45-second live scene**: direct image questions now bound actual local VLM inference to 15 seconds, reject a camera answer older than 16 seconds after receipt, and fence a previous question after a new Xiaozhi spoken turn or newer visual query. Failures return explicit no-answer errors rather than a confident old scene description.
4. **Operator timings**: `GET /v1/pet/{robot_id}/vision-status` now includes per-robot read-only `software_timings` with actual camera requests, successful captures, errors, visual questions, model completions, failed answers, last JPEG/capture-processing time and last local VLM inference time in milliseconds. These are measured Mac software timings only; they are NOT synchronized physical camera exposure, network-to-ear, acoustic AEC or audible playback metrics.
5. **Offline regression additions** cover nonblocking Pillow worker, late frame rejection after pause, speaker continuity at VAD end, authenticated speech-start/speech-end order, stale model timeout and per-robot counters.
6. **Long human turns and failed camera safety**: a real authenticated `speech_start` now holds the human voice floor until authenticated `speech_end` or explicit session disconnect/clear. The old seven-second guess could expire during a longer user question. An unavailable XIAO JPEG source discards only stale video evidence and cannot clear an active VAD event. Voice sampling is bounded to 60 one-second opportunities while active; an absent speech end can silence proactive remarks until explicit reset and will not trigger indefinite camera polling. Mock regressions cover the long-turn and camera-fault boundaries. Real acoustic interruption remains unverified.

**Unqualified requirements remain:** actual head PWM and dock hardware, calibrated grasp, complete integrated STL/Fusion model, protected battery charging currents and thermal tests, measured end-to-end voice acoustics, measured real camera/sensor throughput and realtime speech-to-speech backend. The PR remains draft until live hardware trials and CI pass.


### Authenticated idle VAD versus AEC double talk

The same Xiaozhi server produces two distinct event families. An authenticated idle `speech_start` has a matching debounced `speech_end` and now holds human priority without a guessed seven-second cutoff. By contrast, a `normal` or `group` AEC double-talk event is an urgent speaker abort but **does not guarantee a corresponding idle `speech_end`**. Mac `Runtime` now routes these AEC events to `MultimodalOrchestrator.voice_interrupted`, preserving immediate cross-fleet audio cancellation and applying a bounded seven-second camera/voice priority window instead of an endless lock. An independently active explicit VAD turn remains held even if AEC events arrive on top of it. These are scheduling policies, not validated acoustic timings. New regression tests cover both event types and their overlap.


## November 12: source-truthful natural social behavior and active camera triggers

This is one cohesive source path in [PR #17](https://github.com/hungngodev/desk-robot-remix/pull/17), not a new chatbot or second robot framework. [Source reuse versus reference audit](../ATTRIBUTION.md#what-is-actually-reused-versus-locally-implemented-november-12-audit) explicitly distinguishes external upstream from our integration.

### What an actual new event does

1. **Read source:** WROOM local sensor GPIO/I2C and its existing read-only status or optional auxiliary endpoint, or the authenticated XIAO JPEG. A newly sampled MAX30102 paw, CRC checked SHT41 ambient change or new PN532 toy tag must come from its own fresh device acquisition counter. All three now have a matching entry in `multimodal.TRIGGERS`; previously a missing trigger raised an exception before private memory could be stored.
2. **Context immediately, but bounded:** `PetController._notify_sensor` calls the existing `MultimodalOrchestrator.sensor_event`. The hub records source identity, event kind and monotonic Mac receipt time and marks its next JPEG urgent. A new task starts a genuine `HttpHead.snapshot()` **without blocking the sensor polling path**. Bursts coalesce to **one bounded two-frame confirmation task** per 800 ms for each robot. The second photo is taken 450 ms after the first when no live human or direct visual question has priority. This reuses the existing per-head capture lock, shared two-worker JPEG budget, tiny per-robot RAM frames and source checks. Two frames is an upper bound on requests for a burst, **not** measured reaction time. Another pet's event cannot borrow its camera.
3. **Human takes priority:** a genuine Xiaozhi speech start cancels the pending low-priority sensor camera task and uses the existing 1 FPS speech-frame sampler. A direct visual question also preempts the sensor camera task. An immediate end/start voice transition replaces a cancelling speech sampler instead of losing the next utterance. No sensor, head or LLM gets a second microphone or motor authority.
4. **Decide when:** the existing Reachy/LlamaPIE-inspired cheap initiative gate rejects unsupported event kinds, uncertainty, absent authenticated live VAD feed, quiet mode, active conversation, ongoing human speech, repeated event text and fleet speech cooldown. A slow model answer that outlives `max_observation_age` is now discarded rather than turned into a suspiciously late remark.
5. **Decide what:** the local model prompt now distinguishes *physical sensor evidence* from *camera model assessment*, including explicit no-unseen-identity/no-motor instructions and only recent source-qualified per-pet memory. Physical petting and NFC are not described as camera sightings. This is grounding policy, not a guaranteed hallucination-free model.
6. **Optional peer invitation:** after an eligible witnessed key, candy, object, hand-wave, petting or toy tag event, an operator may enable **both** `fleet_text_sharing_enabled=true` and `fleet_social_autonomy_enabled=true` in the Mac hardware config. `fleet_social_min_interval_seconds=300` limits automatic invitations; only another enabled, unmuted pet participates. The selected peer rotates and receives the source event as **reported secondhand**. The existing `Conversation.run` handles **two turns** under the same exclusive speaker/session owner; the peer is instructed not to claim firsthand observation or perform any physical motor action. It uses the same per-robot personas, private SQLite provenance and cancelled Xiaozhi TTS route. Without explicit sharing, no social event is transmitted.
7. **Stop and clean up:** muting or pausing **either** of the two speaking pets cancels the same shared social task. Simultaneous five-pet human interruptions must not repeatedly cancel its urgent device stop cleanup. The same live authenticated VAD snapshot still owns human turn recovery; sensor camera errors cannot clear it.

### Actual visual reasoning and natural interaction correction

Previously `sensor_event` acquired a genuine XIAO JPEG, but the `PetController` semantic observation loop never consumed it. The frame remained useful for explicit voice questions but an actual tap or accessory could fail to provoke visual reasoning. The **same** proactive scene loop now consumes the hub's unseen ordered `sensor` and `proactive` JPEGs, with a per-pet last-received cursor and freshness/generation checks, instead of fetching duplicates. It uses the already present `VisualChangeGate` to demand two local changes before one Ollama VLM comparison. A sensor cue is context, **not proof** that anything visual happened; silent frames never fabricate a scene. Frames captured for a **human speech** or `voice_question` are intentionally excluded from unsolicited semantic analysis. Another robot's frames never enter this pet's history.

The existing Frigate-inspired cheap motion gate already compensated for broad lighting drift, but the separate `VisualChangeGate` still compared raw pixel differences. It now reuses the identical `change_fraction` algorithm, reducing full-room light changes that would otherwise provoke five expensive Ollama calls. Frigate's documentation calls motion a first-stage detector rather than a substitute for actual object understanding: https://docs.frigate.video/configuration/motion_detection/ . This adaptation is algorithmic and original integration source, not imported Frigate NVR or a verified object tracker.

Human interruption remains absolute priority. Separately, an **intentional physical engagement** such as head taps, petting, optical paw contact, hand wave, nose twist or toy tag can respond after a configurable 12-second shared speaker cooldown instead of waiting the ordinary two-minute unsolicited visual-comment cooldown. Repeated text, active VAD, quiet mode, model expiry, consent and one speaker floor still apply. No idle clock alone invents speech or claims to have seen a thing. See also LiveKit's turn-taking separation between interruptions and ordinary endpointing at https://docs.livekit.io/agents/logic/turns/tuning/ . We deliberately retain our existing authenticated Xiaozhi transport rather than adding a competing LiveKit session; the LiveKit video sampling and turn policy are design references.

**New source tests committed, not yet executed:** `test_proactive_frame_gate_reuses_motion_filter_to_ignore_global_exposure`, `test_sensor_capture_burst_is_consumed_by_one_proactive_scene_owner` (both actual changed object and uniform lighting cases), `test_sensor_two_frame_burst_never_blocks_human_speech_priority`, `test_sensor_two_frame_burst_is_bounded_and_camera_serial`, `test_deliberate_touch_can_reply_after_passive_speech_cooldown`, and `test_touch_can_never_override_authenticated_human_vad`. These tests use deterministic mocks, **not real camera, latency, VAD acoustics, or a deployed ESP32**.

### Integration and build knobs

Copy `code/config/fleet.hardware.example.toml` to a local untracked configuration with actual device addresses and private token environment variables. In production, leave `motion_enabled=false`, `dock_motion_qualified=false`, all new sensor `*_qualified=false` and `fleet_social_autonomy_enabled=false` until the real voice, sensing and source privacy tests pass. Enabling social while local source text sharing is disabled is a configuration error. Turning on social is not motor autonomy, changing head firmware or authorizing charging.

Software acceptance (unexecuted while CI runners fail before any job step):

| Source test | Critical property |
| --- | --- |
| `code/tests/test_multimodal.py` | Three new source event kinds can enter the shared trigger hub, independent camera identity, coalesced physical JPEG capture, human VAD preempts slow sensor camera, and immediate VAD end/start has a new video worker |
| `code/tests/test_pet.py` | Local sensor versus camera wording, expired LLM output suppression, consented two-pet auto conversation, secondhand peer memory, cooldown, muted peer cancellation and concurrent human interruption |
| `code/tests/test_live_voice_events.py`, `test_native_omni_xiaozhi.py` | Real server source identity and voice snapshots, model audio generation cancellation and one speaker floor |
| `code/firmware/body/tests/optional_i2c_io_tests.cpp` | Actual mocked I2C PN532, optical, climate and dock input ordering; no optional source holds critical optical guard permission |

**Measured physical acceptance is still mandatory:** gather actual time-stamped camera capture latency, live VAD edge-to-audible-silence latency, false visual motion and false speech interruption rates, sustained five camera memory usage, one speaker exclusivity across 30+ minutes, real sensor exposure versus Mac receipt timestamps, and grounded peer provenance. Run both ESP firmware builds, Linux host C++ sanitizer and full Python suite before enabling. All changes above are committed source and pending regression tests, **not executed CI or a completed autonomous social robot**.


## November 12: voice failure, peer memory scheduling and vendor plugin resilience

A targeted upstream and current branch review found the following integration facts and repairs. These changes refine the **existing** Xiaozhi and Mac owners; no second audio stack, new tool daemon, motion owner or independent PR was created.

| Boundary | Real source behavior | Evidence and remaining limit |
| --- | --- | --- |
| Five robot social context | `Conversation.run` now gathers per-robot SQLite persona history through concurrent `asyncio.to_thread` calls with a five-second deadline. Read errors or cancellation release the exclusive conversation marker. The Mac event loop can therefore process human VAD while slow disk reads are pending | Host tests inject a blocking memory lookup and a failed local database; these tests are committed but CI has not executed them. `MemoryStore._connect` creates and closes its SQLite connection within the worker thread |
| Interrupted/failed group audio | On **any** midstream model, transport or cancellation exception after a robot starts speaking, `Conversation.run` now calls the existing head `speaker.interrupt` path before completing failure cleanup. Proactive TTS similarly requests head abort after any partial transmission failure, not only task cancellation | Host regression cases cover one successful segment followed by an Ollama exception, and a bridge that fails after queuing physical audio. The interrupt command is not a measured I2S DMA completion ACK |
| Xiaozhi tools when Mac is offline | The existing pinned `plugins_func.register` and `Action.REQLLM` registration remain the only voice tool owner. `desk_robot_tools.call` returns bounded, nonsecret, no-retry errors on local Mac HTTP outage, timeout, malformed JSON or unexpected response type; it still resolves robot identity from the registered physical Xiaozhi device | Tests inject `httpx` failures, malicious error content and forged device identity without loading the upstream server in the host test runner. No new MCP server is justified for this private local robot API |
| Code/harness drift | `test_integration_contracts.py` now compares the actual `BodyPins.h` and XIAO Sense `config.h` pin assignments to `full-feature-plan.json`, rather than checking that the JSON alone contains unique pins | Source check only. The XIAO Sense SD J3 cut/isolation, servo/stepper electrical integrity, rated charger and physical fit still require inspection |

**Upstream verified:** [LiveKit VoiceActivityVideoSampler](https://docs.livekit.io/agents/logic/sessions/) uses low idle and elevated speaking cadence; [Pipecat Smart Turn v3](https://github.com/pipecat-ai/smart-turn) adds natural turn completion on local audio. Neither complete framework is linked into this Xiaozhi build; adding either full audio owner would create conflicting VAD, turn state and speaker output. [Xinnan's actual plugin registry](https://github.com/xinnan-tech/xiaozhi-esp32-server/blob/main/main/xiaozhi-server/plugins_func/register.py) already supports the current authenticated Mac tool calls. Research alone does not establish improved live audio.

**Fast camera intent:** local safety and body touch are always higher priority than JPEG and VLM. User VAD preempts unsolicited speech and stale inference. A qualified physical sensor event coalesces requests through the existing per-robot camera hub; image processing is performed away from the audio loop; one global VLM lock avoids multiple expensive model calls. Multi-robot conversations are context-triggered, not random greeting timers. All five still require real microphone, camera, display and measured peak load trials.

**Verification order:** first resolve [the GitHub Actions pre-step failure](../reviews/CI_RUNNER_PRESTEP_TRIAGE_2026_11_11.md), then actually run the host regression suite and pinned builds. After that, instrument real XIAO mic to speaker interruption, VAD recovery, five-robot dialogue scheduling, visual capture-to-model age, dock safety and calibration. Source tests alone cannot certify physical acoustic or charging performance.
