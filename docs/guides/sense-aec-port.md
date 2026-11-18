# Sense echo-cancellation port: reuse the existing audio engine

Original source review, 2026-11-03. **Reference PCM adapter is now implemented
and firmware compiled in the selected Sense overlay, but microphone and
speaker acoustics are NOT physically qualified.** Keep the purchased Sense
and its existing pins. Reuse
RIO's playback-reference/delay-calibration approach; let Xiaozhi's existing
ESP-IDF audio front end perform cancellation. Do not stack RIO's entire AEC,
noise suppressor, voice detector and residual gate on top of the existing engine.

References are pinned [Xiaozhi c435f99](https://github.com/78/xiaozhi-esp32/tree/c435f99a88066029ec2dbd2d758c8cc9d051565b)
and [MIT RIO b911305](https://github.com/mk14ray/RIO-XIAO-ESP32-S3-Gemini-Live-Voice-Assistant/tree/b911305e48ce6a1b75fe6c07fc02f86ad7bfeb0a).
Known source paths below refer to those revisions. [Source record](../hardware/reuse-sources.json).

## Existing seams

| File / symbol | Relevant contract |
| --- | --- |
| `main/audio/engines/afe_audio_engine.cc`, `AfeAudioEngine::Initialize` / `Feed` | Existing engine selects `MR` for two input channels with a reference. Input is interleaved signed 16-bit PCM at 16 kHz: mic, reference, mic, reference. Query its actual feed chunk size. |
| `main/audio/audio_service.cc`, `ReadAudioData` / `AudioInputTask` | Requests 160 frames per 10 ms; two channels require 320 sample values. Processed output remains mono. |
| `main/audio/codecs/no_audio_codec.cc`, `NoAudioCodecSimplexPdm::Read` | Current Sense input is mono 16 kHz PDM-demodulated PCM on I²S0. |
| Same file, `NoAudioCodec::Write` | Takes 32 kHz output PCM after XiaoZhi resamples its usual 24 kHz Opus stream, applies squared software volume/clamping, writes 32-bit mono I²S on I²S1. The MAX98357A excludes 24 kHz LRCLK; a tap before this method misses the effective speaker gain/clipping. |
| `firmware/head/sense/desk_robot_sense.cc`, `GetAudioCodec` | Isolated place to select a Sense-only reference codec without changing camera, OLED, UART or amplifier pins. |
| `firmware/head/install_overlay.py`, `planned_files` | Copies Sense board sources. A future opt-in must also extend the upstream device-AEC whitelist narrowly and reversibly. |

## Smallest substantive port

Add a Sense-only codec adapter and bounded playback-reference helper, keeping the
current baseline available for comparison. The writer owns one stateful 24-to-16
kHz converter. Publish the effective post-volume/clamped output samples with
frame indices, timing and a playback generation; do not reconstruct reference
gain independently from an unsynchronized volume variable.

The reader captures half the requested interleaved sample count as mono mic,
fetches the corresponding reference frames, and fills complete MR pairs. Handle
short/error reads explicitly: the existing boolean `InputData` wrapper does not
resize the buffer to a short sample count. Declare two channels/reference only
after this adapter actually supplies them. A flag alone mislabels mono data.

Use short protected copies/publication or a proven single-producer/single-consumer
queue with proper memory ordering. Do not hold a ring lock across blocking I²S,
AFE calls or network work. Reference capacity is bounded; overflow/underflow and
unknown alignment need explicit diagnostics and a failed qualification state.

Reference must follow samples actually accepted/played by the output path,
including partial writes, idle gaps, startup occupancy and audible tails.
Current TX allocation is 6 × 240 frames, nominally 45 ms at 32 kHz; that is not a
measured acoustic delay. Measure capture/output delay and clock drift on the
assembled head. RIO's initial 90 ms is not our calibration.

Coordinate generations with decoder reset, output disable, interruption and
reconnect. Clearing software queues does not cancel a blocking write or flush
TX DMA. Keep reference for any tail that really plays; discard reference for
audio canceled before playback. The Mac [flush contract](live-conversation.md)
must reach this device path and receive actual playback-completion information.

## Reference buffer integrity and observable failure

The selected `SenseReferenceCodec` now reads real mono PDM input and
interleaves it with a bounded 32 kHz to 16 kHz speaker reference before
Xiaozhi's existing ESP-SR AFE. It uses a generation fence on cancellation,
post-volume reference samples and short ring copies under a mutex; actual
blocking I2S reads and writes run outside that mutex. This software path
is implemented, not a simulated microphone or proof of a real acoustic
tail flush.

The codec records saturated lifetime counts of reference underrun
reads, ring-overwrite reads and stale post-cancellation writes. If a
complete ring capacity of reference samples is published between
microphone reads, the newest read does not silently claim a valid
time-aligned history. It substitutes silence, marks A2 reference
integrity failed and warns only for the first occurrence or every 32
new such errors. A sustained 32-read underflow or stale
post-cancellation playback publish also marks integrity failure.
`GetReferenceDiagnostics()` returns these counts and the sticky
`integrity_failed` flag under the codec mutex. `ClearReference()`
resets session indices but **does not erase the lifetime failure**.

**This is an internal device diagnostic, not yet a remote health
endpoint or an acoustic performance metric.** Any nonzero
`integrity_failed` blocks an A2 qualification claim; even a clean
counter does not prove measured ERLE, delay/clock compensation,
cancellation of already buffered TX DMA or preservation of real human
speech during double talk. The operator must still record the actual
audio and hardware timing tests from the mandatory barge-in guide.

## Configuration and verification

Keep locked ESP-SR 2.4.7, S3/PSRAM and the current 8 MB partitions. After adding
real MR data, enable the audio processor/device AEC through a narrowly scoped
Sense opt-in; verify generated configuration, with server AEC disabled. Follow
`EnableDeviceAec` / `ApplyAfeControls`: initialization alone does not enable AEC.
`Application::GetDefaultListeningMode` must select realtime listening so speech
processing continues while the speaker plays.

Verify chunk-boundary conversion, gain, MR order/count, short reads, ring wrap,
idle gaps, concurrent reset and stale generations before a clean Sense build.
Check generated settings, app/asset sizes and 8 MB fit again after the port.
Then measure echo-only suppression and retained human speech during double talk,
including camera/Wi-Fi/servo/track load. A gate that mutes user speech during
playback fails. Pass the [mandatory physical audio trials](audio-barge-in.md),
including audible cancellation and capture of the new request, before claiming
barge-in. The current compiled baseline and offline Mac tests do not pass this gate.
