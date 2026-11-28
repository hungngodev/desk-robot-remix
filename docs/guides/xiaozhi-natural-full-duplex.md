# Full duplex natural voice: reuse the real Xiaozhi path

Status: software integration guide and source checked routing decision, November 10, 2026. **Not a physically qualified ChatGPT Live or Gemini Live substitute.** The first robot and the complete five robot fleet remain the product.

## Keep one real audio owner

```
XIAO Sense PDM mic
    -> Espressif ESP-SR AFE (AEC with real I2S speaker reference, VAD)
    -> Xiaozhi ESP32 Opus WebSocket
    -> existing xinnan Xiaozhi server / chosen streaming voice provider
    -> Xiaozhi TTS Opus response
    -> XIAO decoder, I2S amp, speaker
    -> real user speech interrupts currently playing response
    -> server /events delivers authenticated voice preemption
    -> Mac Runtime cancels all proactive pet and peer group speech
```

Do not make a new ESP32 voice stack, replace the XIAO mic or run Pipecat and LiveKit as competing audio owners. The Sense device is the timing and playback authority. The Mac remains the memory, pet intelligence, vision and guarded body coordination authority.

## What current code actually does

* The existing Sense reference codec feeds a playback signal to the ESP-SR AEC. The real VAD path cancels the current device TTS and sends a `tts stop / flush:true` frame. Actual acoustic echo suppression still requires a measured speaker delay and board tests.
* The existing xinnan server overlay has a per-device generation fence around the Mac Kokoro WAV path, so already queued, encoding and in-progress speech is rejected after an interrupt.
* The authenticated `GET /events` feed connects human speech to the Mac proactive and group conversation owners. The November 10 addition now cancels ALL Mac pet audio when one robot detects a human voice, including after missed event batches, server restart and event transport outage. Unknown robot identities cannot invoke fleet cancellation.
* Human native Xiaozhi conversations already travel over a device Opus stream. The example configuration in `code/config/xiaozhi.local.example.yaml` currently selects **local FunASR + OllamaLLM + buffered CustomTTS/Kokoro**. This is still a staged ASR/LLM/TTS pipeline, **not a fully streaming speech-to-speech model**. Mac initiated group and proactive Kokoro speech is also buffered.

## Best open source reuse choices

1. **Keep** [78/xiaozhi-esp32](https://github.com/78/xiaozhi-esp32), MIT, as the device transport/AFE/OpenAI-style tool entrypoint. Its documented WebSocket protocol supports bidirectional Opus and, on AEC capable boards, realtime conversational models. Upstream version and board profile must stay pinned and compiled in our Sense firmware.
2. **Keep** [xinnan-tech/xiaozhi-esp32-server](https://github.com/xinnan-tech/xiaozhi-esp32-server), MIT, as the single server. It already supports configurable streaming ASR, LLM and TTS providers. Use the upstream provider configuration and test with the actual XIAO. A provider capable of realtime speech-to-speech is only appropriate if that provider implements the Xiaozhi server's actual expected interface. Do not assume naming a provider enables it.
3. **Reuse algorithms** from [pipecat-ai/pipecat](https://github.com/pipecat-ai/pipecat) and [livekit/agents](https://github.com/livekit/agents) for turn-taking, false-interruption policy, latency measurements and metrics. These frameworks do **not** automatically connect to our existing Xiaozhi Opus WebSocket or grant motor control. Do not import entire frameworks unless one server adapter replaces the current speech owner in a measured comparison.
4. **Reuse actual Sense audio reference details** from [RIO-XIAO-ESP32-S3-Gemini-Live-Voice-Assistant](https://github.com/mk14ray/RIO-XIAO-ESP32-S3-Gemini-Live-Voice-Assistant), with its original license. The RIO Arduino code is not a drop-in module for our ESP-IDF app. Keep the existing Sense codec + measurement script.

## Practical rollout without rewriting transport

1. Install the actual XIAO board and speaker. Check the Seeed expansion J3 microSD connections before using GPIO7/8 I2S speaker and GPIO9 optional LED. Leave the on-board PDM microphone untouched.
2. Keep local Xiaozhi mode as a reproducible baseline. Log microphone VAD, reference PCM, speaker playback and measured WAV pair. Use `code/scripts/estimate_aec_delay.py` with actual synchronized recordings, not the 90ms example value.
3. Switch **one provider at a time** to the streaming services documented by the pinned xinnan server. A streaming ASR such as the provider's supported XunfeiStreamASR and a streaming TTS such as its supported HuoshanDoubleStreamTTS require their real SDK/API credentials; these names are examples, NOT working drop-in secrets or free models. Confirm an upstream provider test before promoting a setting into `xiaozhi.local.example.yaml`.
4. Compare the incremental streaming pipeline with the upstream Xiaozhi supported realtime speech model path on one physical robot. Preserve per-robot memory tool, the normal interrupt endpoint, the event cursor fencing and the single operator motion lease.
5. Measure wake-free ordinary speech interruption while the speaker is playing, with motor noise and all five peers present. Record physical double-talk response using `code/scripts/check_barge_in_trials.py`. Require at least 19 of 20 valid interrupted turns with audible stop within 500ms. No simulated test establishes that outcome.
6. Include explicit foreground priority over unsolicited speech, bounded cooldowns, detector false positives and old TTS queue flushing. Keep background object descriptions shorter than real human voice replies.

## Exact unresolved gaps

* Buffered local FunASR/LLM/Kokoro may be perceptibly slower than Gemini Live. True end-to-end speech-to-speech, natural prosody and overlapping speech are provider and acoustic performance questions, not a flag in the prompt.
* We have no real microphone/speaker capture, VAD confusion matrix, AEC delay, head DMA stop acknowledgement, word error rates, actual network jitter or physical five robot room measurements.
* The XIAO Sense hardware speaker and J3 pin isolation, model provider compatibility, long-session reconnection, privacy and physical board power need proof.
* Audio has no permission to energize the dock, arm motors or change physical safety calibrations. Those remain separate local WROOM and operator gates.

Do not call this feature finished until the current branch checks pass AND acoustic acceptance is physically recorded. See `docs/guides/audio-barge-in.md` and `docs/research/2026-11-10-natural-voice-acceptance.md`.


## November 11: actual pinned upstream streaming speech profile

The server pinned at `d9c2e8c5d92627b670dec57d72a07a4226a410a3` already contains `AliyunBLStreamASR` (type `aliyunbl_stream`) and `HuoshanDoubleStreamTTSV2` (type `huoshan_double_stream`, resource `seed-tts-2.0`). These are actual established xinnan source modules, **not** pseudo provider names. The original server includes its own `performance_tester.py` to measure ASR, LLM, VLLM and TTS independently.

The robot's private `code/laptop/server/configure.py` now has `--streaming-profile aliyun-volcengine` for **isolated single-head cloud provider benchmarking only**, not a supported provisioned robot fleet setup. The default remains private local FunASR + Ollama + Kokoro, and the script will refuse to generate a profile when any required credential or activated voice ID is absent. `run_server.py` and `desk_robot_bridge.py` explicitly refuse any non-`CustomTTS` TTS module when mapped fleet devices are configured until a per-robot streaming voice mapping is implemented. The profile uses third-party services with possible charges and audio leaving the Mac. It is **not** an offline mode.

```sh
# Keys are provider-issued; never add them to GitHub or a shell history file.
# Load them from a private environment file or password manager.
export DASHSCOPE_API_KEY="YOUR_PROVIDER_KEY"
export VOLCENGINE_TTS_APPID="YOUR_PROVIDER_APP_ID"
export VOLCENGINE_TTS_ACCESS_TOKEN="YOUR_PROVIDER_TOKEN"
export VOLCENGINE_TTS_SPEAKER="YOUR_ACTIVATED_ENGLISH_VOICE_ID"

# Only for a NEW private .config.yaml. Do not overwrite a working config.
python code/laptop/server/configure.py --server-ip YOUR_MAC_LAN_IPV4 \
  --streaming-profile aliyun-volcengine
```

This selects the existing Xiaozhi streaming adapters and keeps its own Opus/websocket, VAD and tool registry, including `desk_robot_look`. For an existing private `.config.yaml`, preserve/backup it and migrate the documented `selected_module` entries and provider sections manually; the generator deliberately refuses to overwrite that file.

From the overlaid server directory, benchmark `python performance_tester.py` on real credentials, then perform physical double-talk tests while the robot speaks. Record speech-start VAD, final ASR, first LLM token, first audio frame, physical I2S audible onset, 95th-percentile time to silence after interruption, and vision-tool latency, separately. The Mac `vision-status` software counters are NOT microphone-to-ear latency. A cost- or privacy-sensitive owner can stay entirely with local ASR/TTS and still use the new image and VAD orchestration.

**Critical limitation**: Streaming ASR + streaming TTS is still recognition -> LLM -> synthesis. A Gemini Live native realtime speech/video model requires a separate actual provider-backed media transport adapter. This optional profile does not falsely claim that capability or certify an English speaker/acoustic echo quality.
