# Keep the purchased Sense: concrete reuse sources

User reports purchasing the full XIAO ESP32S3 Sense listing, displayed $18.87.
Quantity, delivered receipt, arrival and hardware revision are unconfirmed.
Keep that board as the active head. A replacement has **not** been established
as necessary for voice interruption. The earlier Waveshare work is an optional
fallback, not an additional shopping requirement.

## Recommended reuse combination

| Source | Verified useful implementation | Remaining integration |
| --- | --- | --- |
| [RIO on XIAO Sense](https://github.com/mk14ray/RIO-XIAO-ESP32-S3-Gemini-Live-Voice-Assistant/tree/b911305e48ce6a1b75fe6c07fc02f86ad7bfeb0a) | Explicit MIT license; exact Sense PDM microphone, MAX98357A, SSD1306; actual Espressif AEC calls, software playback-reference delay, 24→16 kHz conversion and `serverContent.interrupted` playback flushing. | Review its task synchronization/reference timeline, port pins and qualify AEC. Its camera is tool-requested still photos, **not continuous video**. No WROOM robot boundary or five-robot scheduler. |
| [Google Live API cookbook](https://github.com/google-gemini/cookbook/blob/main/quickstarts/Get_started_LiveAPI.py) and [robotics streaming](https://ai.google.dev/gemini-api/docs/robotics-streaming) | Official continuous audio/video examples, interruption event handling and camera-frame/heartbeat observation pattern. | Feed Sense frames/audio through a suitable transport; flush both Mac and device playback; preserve turn ownership. Video frames alone do not initiate a reasoning turn. Model/SDK capabilities vary; verify the selected version. |
| [Pipecat Gemini Live video example](https://github.com/pipecat-ai/pipecat/blob/c87446099f88560b861ac0e1c13cce331e3a5770/examples/realtime/realtime-gemini-live-video.py) | BSD-2-Clause server framework, actual audio/video service and 1 FPS camera example. | Suitable Mac-side orchestration reuse. Its [MIT ESP32 client](https://github.com/pipecat-ai/pipecat-esp32/tree/e70e3b1f0576e502af9e390434e1a6e8a5cd0d2e) has other board targets, so Sense needs a peripheral port. It does not remove acoustic calibration. |
| [LiveKit ESP32](https://github.com/livekit/client-sdk-esp32/tree/669ef1382501224fdac93d8d02378fbc5b2cb197) | Apache2 SDK with audio/video/data/RPC, developer-preview alternative. | A larger integration path. Sense capture/render support and reference-based AEC are not supplied merely by selecting this SDK. |

RIO is saved unchanged at the exact revision under ignored
`upstream/rio-sense-reference`. [Reuse source hashes](../../hardware/reuse-sources.json)
record the inspected files. No firmware from this source has been flashed or
integrated, and no cloud session has been opened.

## What actual RIO source says

`aec.cpp` calls `aec_create_from_config`/`aec_process`; this is real cancellation
code, not just an advertised feature or microphone mute. It captures the speaker
reference and has a bring-up sweep. However:

- The default 90 ms reference delay is explicitly **unmeasured**. Measure it in the
  final mic/speaker/enclosure arrangement; do not freeze it as our calibration.
- `aec.h` explicitly explains that poor cancellation makes its gate suppress the
  mic during playback. That loses barge-in and must **fail** our required gate.
- Shared reference state and flush/read concurrency need review. Its comment
  claiming no lock is needed is not independent proof of race-free operation.
- Its speaker pins are BCLK7/LRC8/DIN9 and amplifier SD44. Our current compiled
  Sense target uses 4/7/8 and no SD control. **Do not combine those wiring tables.**
  Preserve camera/PDM/nativeUSB and review debug-UART44 use if adopting SD44.
- It is Arduino-ESP32 3.x code; our current Sense/Xiaozhi target uses pinned
  ESP-IDF 6.1. Integration is not copying a header and relabeling an old binary.
- Camera capture powers the sensor between requested stills and can block for
  seconds. Continuous observation needs an independently scheduled capture path.

## Separate the three requested behaviors

1. **Voice interruption:** echo-clean live input, interrupt detection, cancel the
   obsolete answer, flush queued audio on Mac/device and keep the new utterance.
   [Physical acceptance](../audio-barge-in.md) remains mandatory for robot one.
2. **Proactive pet behavior:** local blink/gaze plus an event/timer scheduler that
   sometimes initiates an observation or speech. Google's proactive-audio option
   controls response selectivity; it is not a complete autonomous pet scheduler.
   Use fresh frame + brief contextual prompt when idle, with cooldowns. Avoid
   injecting prompts while user/model/tool turns are active.
3. **Ongoing camera understanding:** start with recent JPEG frames at about 1 FPS
   per active observation session, matching existing examples. A smooth camera
   preview and an AI processing every video frame are different workloads. Measure
   actual camera/audio/Wi-Fi coexistence before raising cadence. Local edge
   protection never waits for a VLM frame.

OpenDuck/Microduck are useful for gaze, motion timing and expressive behavior.
Their learned locomotion and higher-compute hardware are not this Sense voice/video
client. Reuse the exact audio/video projects above for this layer instead of
replacing the whole robot architecture.

## Integration direction

The [concrete Sense port seam](../sense-aec-port.md) reuses Xiaozhi's existing
audio front end with a Sense-only synchronized mic/playback-reference adapter.
RIO supplies reference-timing/calibration and cancellation patterns; importing
its entire second AEC/VAD/gate chain is unnecessary. This adapter is not yet
implemented, and declaring a reference flag without actual paired samples is
invalid.

```text
Purchased Sense: camera + PDM mic + MAX98357/speaker + OLED
    <-> Wi-Fi audio/frame transport <-> shared Mac session/turn coordinator
                                      <-> optional Gemini Live/Pipecat service
    <-> bounded UART <-> existing WROOM motor/sensor controller
```

The current pinned Xiaozhi server's `GeminiLLM` provider streams text via
`generate_content`; it is **not** Gemini Live audio/video. Keep existing verified
driver/control foundations and add the appropriate live transport/provider layer.
RIO's direct-to-Google client is a reference; it cannot silently bypass the Mac's
operator permits or add unrestricted body tools.

Google Live is a cloud service; model usage is separate from the hardware budget.
Keep keys private and sessions opt-in. No API key is required for offline code/tests,
and none was read or used in this work. The local Mac STT/TTS/LLM route remains
available, but native Live features are not implied for every local provider.

## Immediate work and evidence

Keep Sense as ordered; retain MAX98357/speaker shopping items. Verify a sample
sensor mount before fleet orders. Reuse and test RIO's cancellation/reference
ideas, Google's turn/queue handling and frame heartbeat, then connect that to
the existing guarded robot APIs. Source availability, compilation, mocked tests
and physical audio/navigation acceptance must remain separate claims.
