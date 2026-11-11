# MiniCPM-o 4.5 as the native realtime audio + video option

Status November 10, 2026: protocol source and isolated backend probe committed. This is a **real model-side protocol implementation**, not a completed device speaker cutover, and not an acoustic qualification. The original five full-feature desk pets, Xiaozhi hardware, Mac camera event/memory orchestration, eight ToF, force-feedback grasp, docking and power requirements remain unchanged.

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

## Exact full cutover architecture still to integrate

```text
XIAO Sense PDM mic + hardware AEC (existing)
  -> ESP32 Opus / pinned Xiaozhi WebSocket (existing)
  -> pinned server decoder: actual mono 16k PCM (existing)
  -> exclusive audio route (NOT YET PATCHED)
       -> MiniCPM omni backend realtime WebSocket
          + camera snapshot from Mac's authenticated per-robot hub
          + one frame on the matching 1s PCM unit
       <- generated PCM16 at 24k and transcript
  -> single XIAO output owner, resample to 16k, Opus 60ms
  -> XIAO I2S speaker DMA
  <- actual sample played feedback (NOT YET IMPLEMENTED)
  -> backend playback.ack with measured cumulative played milliseconds
```

A correct switch has to be exclusive per physical robot and its audio lease: the old Xiaozhi ASR/LLM/Kokoro must not speak concurrently with the model's native full-duplex stream. The native backend must not bypass device AEC, the XIAO speaker decoder, fleet voice priority, or Mac motor permissions. The model-side MiniCPM omni realtime lane is not documented as supporting arbitrary tools; keep private memory, selected sensors and motion decision logic in the Mac, do not claim native model motor tools.

Most important blocker: **playback truth**. The vLLM-Omni protocol requires `playback.ack` to represent actual sound heard. A Mac HTTP response, Opus transmission completion, and an estimated 240ms tail are **not** measurements. We need head firmware tracking decoder-to-I2S played sample count and an authenticated response with sample/turn generation. Only then may the new backend keep a truthful conversational playback ledger. Likewise, barge in needs 19/20 physical trials with audible stop within 500ms, not an API acknowledgement.

The Mac XIAO camera currently gives JPEG capture completion metadata and a freshness check, not true synchronized exposure timestamps. The overlay must preserve headset/mic and camera identity, time alignment, model session replacement and loss/reconnect behavior before swapping the audio path. All five pets require independent backend session identity and one shared unsolicited-speech floor.

## Scope and acceptance

* Native model protocol tests: software integration, not hardware validated.
* Offline realtime server probe: executable if a compatible model server exists, but not yet run against a real server here.
* Xiaozhi speaker cutover, actual audio resampling and DMA playback acknowledgement: NOT IMPLEMENTED.
* End-to-end physical voice interruption, human speech latency, proactive audiovisual correctness and the complete assembled robot: NOT VERIFIED.
* Autonomous docking, protected 1S charger and gripper contact force still require physical measurements, independent of the AI backend.

This route keeps the strongest existing open-source audio/vision systems instead of adding an incompatible second live speaker behind the robot user's back.
