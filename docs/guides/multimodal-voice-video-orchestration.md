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
3. The Mac `Runtime._on_voice_interrupt` cancels obsolete peer/pet speech and background Ollama scene inference, **then** synchronously signals the camera hub to schedule nonblocking near-1 FPS user-speech JPEG samples for about five seconds.
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

**Unqualified requirements remain:** actual head PWM and dock hardware, calibrated grasp, complete integrated STL/Fusion model, protected battery charging currents and thermal tests, measured end-to-end voice acoustics, measured real camera/sensor throughput and realtime speech-to-speech backend. The PR remains draft until live hardware trials and CI pass.
