# MiniCPM-o 4.5 as the native realtime audio + video option

Status November 11, 2026: opt-in real Xiaozhi head PCM/Opus server routing, local camera retrieval and the upstream duplex wire implementation exist in source. The hardware speaker, physical echo cancellation and full model backend have **not been bench qualified**. This is not a completed, production-ready live voice system. The original five full-feature desk pets, Xiaozhi hardware, Mac camera event/memory orchestration, eight ToF, force-feedback grasp, docking and power requirements remain unchanged.

## November 11: Xiaozhi real microphone and speaker route committed

This section supersedes the old statements below saying the exclusive audio route and head output are completely unimplemented. **The source adapters are now implemented, but have NOT passed full end-to-end physical tests, and native vLLM model operation on the user's M1 Max is not established.**

The pinned xinnan Xiaozhi server now receives an isolated `desk_robot_native_omni.py` overlay and copies the single shared `realtime_omni_protocol.py` protocol implementation. In an explicitly opted-in robot session, the actual decoded XIAO 16kHz mono PCM (from the same server Opus decoder and VAD) is diverted from legacy ASR into the upstream vLLM-Omni WebSocket. Real native 24kHz PCM16 deltas are converted to 16kHz and encoded in the *same pinned Xiaozhi 60ms Opus framing* for the actual head device websocket. It does not fake WAV/TTS or run another microphone or speaker stack. Device route and model model route are fenced by the real device ID, native response ID and cancellation generation. The existing urgent `tts stop flush:true` signal remains highest priority.

### Explicit opt-in for ONE first pet, keep the complete fleet

Start with a single robot selected for real native streaming validation; the other four retain their configured existing Xiaozhi voice providers. Keep the full physical feature set and five distinct robot IDs in the project.

1. Deploy the official [vLLM-Omni realtime MiniCPM server](https://github.com/vllm-project/vllm-omni/blob/main/recipes/OpenBMB/MiniCPM-o-4_5.md) on supported hardware and confirm the official demo really works. The code assumes an actual `/v1/realtime?duplex=1` WebSocket and the upstream 16kHz input/24kHz output contract. A generic Ollama, llama.cpp HTTP or other Realtime-shaped service is **not** a substitute.
2. Install or refresh the pinned Xiaozhi server build with `code/laptop/server/install_overlay.py`. It now includes `desk_robot_native_omni.py` and `desk_robot_omni_wire.py`. This is still the original Xiaozhi backend, not a second gateway. Build must first pass `test_overlay_targets_pinned_server_and_compiles`.
3. Enter the genuine XIAO Sense `device_id`, `head_url`, private bearer tokens and normal five-robot settings. For real video and individual persona retrieval, set `voice_vision_tools_enabled = true` in the private Mac `local.toml`. Set `voice_memory_tools_enabled = true` **only** if you explicitly want prior private memories included in a native model prompt.
4. Ensure `DESK_ROBOT_TOOL_TOKEN` is already in the existing private Mac/server environment (40+ random characters is recommended). The private authenticated `GET /v1/pet/{robot_id}/omni-context` includes that robot's persona and only opted-in past text memories, never motor permits. The private `GET /v1/pet/{robot_id}/omni-frame` returns a fresh source-authenticated JPEG, bounded to 1MB and received no more than 1000ms earlier, with `Cache-Control: no-store`.
5. For **one** native pilot on a loopback model server, add the following values to the private `code/config/local.env` or export in the server's environment:

```sh
DESK_ROBOT_OMNI_ROBOTS=robot-01
DESK_ROBOT_OMNI_URL=ws://127.0.0.1:8099/v1/realtime?duplex=1
DESK_ROBOT_OMNI_MODEL=openbmb/MiniCPM-o-4_5
```

If the model is running on a different machine, the adapter **requires authenticated transport using a properly secured `wss://` endpoint** and the model server should be private. Do not send your microphone stream to a random plaintext `ws://` LAN address. Clear `DESK_ROBOT_OMNI_ROBOTS` to return that robot to the original Xiaozhi provider on restart, without changing or rewriting the base server. When explicitly enabled but unavailable, the adapter fails closed rather than secretly playing from two speech providers.

6. Use the existing `code/laptop/server/run_server.py --config code/config/local.toml` after rebuilding the overlay, and confirm the real device is in Xiaozhi `realtime` listen mode. The backend becomes active when decoded audio frames from that authenticated live device arrive. No synthetic microphone PCM is inserted by the adapter.
7. Use the authenticated loopback `GET http://127.0.0.1:8766/voice-readiness?device_id=YOUR_REAL_DEVICE_ID` with `DESK_ROBOT_SPEECH_TOKEN`. Its `native_omni` status distinguishes an actual connected model from a merely selected configuration. It separately records number of decoded mic frames, video JPEG frames, model PCM deltas and Opus packets transmitted to the head. It **always** reports `head_audio_playback_acknowledged = false` and `audio_video_latency_physically_measured = false` until a real board test establishes them.

### Behavior now in source

* Default off. Both a mapped current Xiaozhi websocket and explicit per-robot native selection are required. Group/peer speech lease and native model speech ownership cannot overlap.
* Mic input uses the pinned server's real Opus decoded PCM and already existing AEC/VAD decisions. A bounded 50-frame queue prevents unbounded input latency and fails closed on overload.
* The 9B model is upstream native inference. Audio and VLM software are not reimplemented. Per 1s model unit, a recent actual JPEG can accompany PCM in the documented `video_frames` wire field. An independent background camera task cannot delay microphone packet delivery; if no timely image arrives, send audio without making up a visual observation.
* Native audio output gets a bounded 40-chunk queue, incremental 24kHz to 16kHz conversion using stateful `audioop.ratecv`, 960-sample Opus frames, paced at 60ms and sent through the original physical device websocket.
* `response.cancel` plus `output_audio_buffer.clear` invalidate the model's old response, and the existing head `tts stop flush:true` requests immediate decoder reset. Stale older response IDs and `response.done` messages cannot stop the newer turn.
* Native replies from different pets share one logical audio floor. One genuine human VAD speech start can request silence from the other native model pets without executing body or battery commands.
* The native backend loads each robot's own voice style from its configured Mac persona, with optional separately authorized short text memories. Untrusted old information is not represented as current camera evidence.

### Important caveats not solved by code alone

The model's `playback.ack` contract must be based on **actual I2S played samples**, not transmitted Opus, so the adapter deliberately sends **no playback ACK**. Until the XIAO firmware provides generation-scoped played-frame counters, the backend may have imperfect listening/speaking state and cannot be called production ready. A physically confirmed 500ms audible barge-in target, proper echo reference, microphone and speaker clocks, long-running 5-robot session recovery and native model low latency remain **unmeasured**.

The host loopback tests in `code/tests/test_native_omni_xiaozhi.py` exercise a real WebSocket handshake, actual PCM-shaped input, native model event responses, Opus-shaped head output, explicit model selection, identity, TLS rules, fleet speaker priority and the fact that no playback ACK is invented. They replace neither the real MiniCPM 9B model nor the ESP32 board. The `test_multimodal_api.py` tests verify the Mac source-authenticated JPEG route requires explicit hardware privacy consent.

The original November 11 GitHub Actions runs failed with **zero visible job steps** and unavailable log blobs. Later runs executed host and firmware jobs; check the exact current commit's five lanes instead of extrapolating either historical failures or successes. Do not promote the PR to ready on software CI alone. Physical docking, charging electronics, fully dimensioned final 3D CAD and calibrated grasp also remain separate unqualified gates.

---


## November 11 upstream protocol verification and operational limitations

The official [vLLM Omni Realtime Duplex API](https://github.com/vllm-project/vllm-omni/blob/main/docs/serving/realtime_duplex_api.md) explicitly negotiates **model-owned duplex capabilities** on `session.created`: `implementation_level=model_native_duplex`, `supports_input_append=true`, `supports_barge_in=true` and `chunk_period_ms=1000` for MiniCPM-o 4.5. Its published `audio.input.sample_rate_hz` is 16000 and `audio.output.format.rate` is 24000. Our native adapter now checks these exact values, the selected model identity and both `pcm16` codec fields **before** it forwards live microphone frames. Any incompatible model, wrong audio clock or fake Realtime server fails closed. This prevents two competing audio implementations or corrupt audio from starting by accident.

When the model server cannot connect or refuses these capabilities, the native session reports the bounded error in `voice-readiness` for the device and imposes a 15-second retry cooldown. Repeated inbound microphone callbacks may not spin up hundreds of competing WebSocket handshakes. The default Xiaozhi pipeline remains the required fallback for a user who has **not** explicitly selected native mode; to disable native, remove that robot from `DESK_ROBOT_OMNI_ROBOTS` and restart the server instead of disabling privacy or speaker guards.

**Mac hardware feasibility matters.** The official [MiniCPM-o 4.5 serving recipe](https://github.com/vllm-project/vllm-omni/blob/main/recipes/OpenBMB/MiniCPM-o-4_5.md#hardware-support) documents Linux and a large-memory GPU, with two GPUs recommended for low-latency continuous batching. That is **not evidence** of a native `vllm-omni` deployment on the user's macOS M1 Max laptop. Do not claim that setting the WebSocket environment variable on macOS starts the model. The existing pinned Xiaozhi FunASR/Ollama/Kokoro staged pipeline remains the usable source foundation pending explicit actual model hosting and physical speaker tests.

**Source validation vs actual proof:** `code/tests/test_native_omni_xiaozhi.py` now includes an upstream-shaped `session.created` mock, explicit rejected capability and codec cases, and a no-retry-flood check. These tests are **committed** but not verified green. GitHub run [43100939229](https://github.com/hungngodev/desk-robot-remix/actions/runs/43100939229) marked all four jobs failed with zero recorded steps and missing log blobs. An inability to fetch logs is not a code test failure diagnosis or a pass.

## The actual open source foundation

* [OpenBMB MiniCPM-o 4.5](https://github.com/OpenBMB/MiniCPM-V/blob/main/docs/minicpm_o4dot5_en.md) is a 9B multimodal model with native simultaneous audio, video and speech generation. This is a more appropriate **model** for the requested live behavior than buffered FunASR + Ollama + Kokoro.
* [vLLM-Omni MiniCPM recipe](https://github.com/vllm-project/vllm-omni/blob/main/recipes/OpenBMB/MiniCPM-o-4_5.md) serves that model via the upstream real `/v1/realtime?duplex=1` endpoint and runs the full model. Do NOT reimplement its model runtime or claim an unrelated model supports that API.
* [vLLM-Omni Realtime Duplex API](https://github.com/vllm-project/vllm-omni/blob/main/docs/serving/realtime_duplex_api.md) documents `session.update`, `input_audio_buffer.append`, camera `video_frames` on the append closing a 1-second model unit, `response.output_audio.delta` with 24kHz PCM16, `response.cancel`, `output_audio_buffer.clear`, and `playback.ack`.
* [Upstream native demo](https://github.com/vllm-project/vllm-omni/blob/main/examples/online_serving/minicpmo/realtime_duplex_demo.py) and [OpenBMB llama.cpp-omni edge guide](https://github.com/OpenBMB/MiniCPM-V/blob/main/docs/minicpm_o4dot5_en.md) are the installation and performance baselines. Start there rather than translating/modeling the audio backend from scratch.
* An [upstream open long-session bug](https://github.com/vllm-project/vllm-omni/issues/7251) reports vision/audio queue drift and response errors for minute-long duplex video streams. We must validate version and duration before asserting continuous all-day operation.

## Actual Mac hardware decision

The user's MacBook Pro is an Apple M1 Max 64GB. OpenBMB's current edge-side published full-duplex guidance lists **M4 Max / 24GB or higher** for native live omni streaming. The vendor's standard PyTorch demo recommends **NVIDIA 28GB VRAM or more**; its specialized `llama.cpp-omni` edge build supports some NVIDIA 12GB setups. These are *different runtimes* with different performance.

No vendor result here establishes that M1 Max 64GB can sustain realtime duplex MiniCPM-o 4.5. M1 Max has sufficient RAM to explore various quantized weights, but RAM size alone is not a speech latency benchmark. Do not buy new hardware merely to guess. Retain the already working Xiaozhi audio flow and benchmark the model in a separate compatible environment first.

## New code already committed

`code/laptop/src/desk_robot/realtime_omni_protocol.py` implements bounded request and response validation for upstream vLLM-Omni:

* Real mono 16 kHz signed PCM chunks with integral 1ms duration, decoded JPEG only from the current authenticated camera adapter, one frame per 1s audio model unit, max 1MB/frame.
* Native session update with `listen_only` overlap and `ack_only` real playback semantics, plus `input_audio_buffer.commit` with native model turn handling.
* 24kHz PCM16 output validation and strict response identity, server epoch, and generation fencing on user interruption; old audio cannot restart while a new human utterance is in progress.
* `playback_ack` accepts a **real external** measured playback progress value and rejects impossible/retrograde progress. It is never called by the current robot, because we do not have an actual speaker audible progress ACK yet.
* No motion commands, no access to battery/dock charging or calibrated gripper operations. The new protocol cannot grant these capabilities.

`code/scripts/omni_duplex_smoke.py` is a real **model-side** WebSocket smoke test using a file-based 16kHz microphone WAV and optional JPEG. It can establish that a vLLM-Omni backend responds with native generated 24kHz speech. It does **not** send speech to an ESP32. Tests live in `code/tests/test_realtime_omni_protocol.py` and `code/tests/test_omni_duplex_smoke.py`.

### Probe an actually running backend

First deploy OpenBMB's **official native server** on compatible hardware and run its official realtime demo. Then from the desk robot project on a machine that can reach that service:

```bash
cd code
uv sync --extra dev --locked
uv run --no-sync python scripts/omni_duplex_smoke.py \
  --url 'ws://127.0.0.1:8099/v1/realtime?duplex=1' \
  --model openbmb/MiniCPM-o-4_5 \
  --input-wav /path/to/real_16khz_mono.wav \
  --frame-jpeg /path/to/real_camera_frame.jpg \
  --output-wav /tmp/desk_omni_probe.wav
```

The probe rejects cleartext nonloopback URLs so audio is not accidentally sent across the LAN. Use `wss://` with a correctly configured private TLS endpoint for remote servers. This is a service compatibility probe, not the final robot setup. Do not use the generated WAV to claim actual robot playback.

## Exclusive audio route in source and remaining playback qualification

```text
XIAO Sense PDM mic + hardware AEC (existing)
  -> ESP32 Opus / pinned Xiaozhi WebSocket (existing)
  -> pinned server decoder: actual mono 16k PCM (existing)
  -> exclusive audio route (implemented, per-robot opt-in)
       -> MiniCPM omni backend realtime WebSocket
          + camera snapshot from Mac's authenticated per-robot hub
          + one frame on the matching 1s PCM unit
       <- generated PCM16 at 24k and transcript
  -> single XIAO output owner, resample to 16k, Opus 60ms
  -> XIAO I2S speaker DMA
  <- generation-scoped digital I2S committed-prefix telemetry (source implemented)
  -> backend playback.ack (not emitted; acoustic playback remains unverified)
```

A correct switch has to be exclusive per physical robot and its audio lease: the old Xiaozhi ASR/LLM/Kokoro must not speak concurrently with the model's native full-duplex stream. The native backend must not bypass device AEC, the XIAO speaker decoder, fleet voice priority, or Mac motor permissions. The model-side MiniCPM omni realtime lane is not documented as supporting arbitrary tools; keep private memory, selected sensors and motion decision logic in the Mac, do not claim native model motor tools.

Most important blocker: **playback truth**. The vLLM-Omni protocol requires `playback.ack` to represent actual sound heard. A Mac HTTP response, Opus transmission completion, and an estimated 240ms tail are **not** measurements. The current adapter accepts a bounded digital I2S committed prefix only from the registered head socket, matching session, playback token, response, generation and turn. It exposes `head_audio_i2s_progress_observed` and `head_audio_i2s_committed_ms`; neither proves that the amplifier or speaker produced sound. `head_audio_playback_acknowledged`, `tool_audio_playback_acknowledged`, `native_context_model_application_verified` and `tool_results_ingested_by_native_duplex_kv` remain false. The completed Mac read-only tool speech route is not evidence that native model KV consumed a tool result. Likewise, barge in needs 19/20 physical trials with audible stop within 500ms, not an API acknowledgement.

The Mac XIAO camera currently gives JPEG capture completion metadata and a freshness check, not true synchronized exposure timestamps. The overlay must preserve headset/mic and camera identity, time alignment, model session replacement and loss/reconnect behavior before swapping the audio path. All five pets require independent backend session identity and one shared unsolicited-speech floor.

## Scope and acceptance

* Native model protocol tests: software integration, not hardware validated.
* Offline realtime server probe: executable if a compatible model server exists, but not yet run against a real server here.
* Xiaozhi speaker cutover and 24kHz-to-16kHz resampling: IMPLEMENTED in opt-in source but NOT hardware or model verified. Generation-scoped digital I2S progress exists in source; audible playback acknowledgement remains unverified and **must not** be invented from either Opus send counters or digital I2S commitment.
* End-to-end physical voice interruption, human speech latency, proactive audiovisual correctness and the complete assembled robot: NOT VERIFIED.
* Autonomous docking, protected 1S charger and gripper contact force still require physical measurements, independent of the AI backend.

This route keeps the strongest existing open-source audio/vision systems instead of adding an incompatible second live speaker behind the robot user's back.
