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
current baseline available for comparison. The writer owns one stateful 32-to-16
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

**The authenticated Sense `/api/audio.reference` endpoint now exposes
these counters read-only to the Mac `HttpHead.audio_reference_status()`
and the camera contention bench. This is a software integrity diagnostic,
not an acoustic performance metric.** Any nonzero
`integrity_failed` blocks an A2 qualification claim; even a clean
counter does not prove measured ERLE, delay/clock compensation,
cancellation of already buffered TX DMA or preservation of real human
speech during double talk. The operator must still record the actual
audio and hardware timing tests from the mandatory barge-in guide.

With continuous microphone consent flashed, the Sense head reuses the
**same** Xiaozhi listening path after a server audio channel closes even
when WiFi stays associated. It retries only from idle, at most once every
five seconds, and never starts a second microphone or WebSocket owner.
A local BOOT privacy action disables unattended restart for the rest of
that boot. This is software recovery logic, not evidence that network
reconnection, double talk or acoustic STOP passed on real hardware.

## Authenticated one-shot Sense microphone/reference capture

The selected `SenseReferenceCodec` now exposes one *optional* private
four-second PCM calibration window, fed by its own existing
`NoAudioCodecSimplexPdm::Read` callback. The same sample index stores
microphone and digital post-volume speaker reference. No second audio
reader, AEC engine or separate UDP audio path is required. The original
Xiaozhi microphone, AFE, camera, Opus and speaker remain canonical.

**This bench feature is disabled in normal firmware.** For a temporary
operator-authorized lab image only, configure
`CONFIG_DESK_ROBOT_AEC_PCM_CAPTURE_ENABLED=y` and
`CONFIG_DESK_ROBOT_AEC_DELAY_MS=0`. The head build requires delay zero
while capturing absolute acoustic latency, and the firmware rejects
incomplete or invalid microphone/reference windows. Keep the selected
Sense 16 kHz PDM, 32 kHz speaker and device AEC setup. The endpoint
requires the existing per-head bearer token, uses the existing
`/api/audio.capture.start`, `/api/audio.capture.status`, and
`/api/audio.capture.raw` HTTP handlers, and streams one bounded
256000-byte RAM window through an asynchronous worker so HTTP dispatch
can continue serving emergency STOP. Firmware wipes the PSRAM buffer
after transfer, timeout, revocation or failed capture.

The operator must explicitly consent to recording microphone data.
A private firmware build and bearer alone do not grant raw recording.
For EACH trial, mute with BOOT, hold BOOT while already muted until the
long-press event, release, then deliberately tap within 30 seconds to
unmute while connected and idle. This distinct calibration gesture
authorizes exactly one START within the next 30 seconds. Ordinary unmute
does not authorize PCM. BOOT mute, double click, WiFi loss, an observed
audio failure or explicit abort revokes the grant. Failed START after
consumption requires another gesture. Failed WiFi event registration
leaves the recorder unavailable. Playback reset invalidates existing PCM
but does not issue a grant. Repeat the physical gesture for each recording.
Use a private isolated network and disable/reflash the capture setting
after measurements. Do not transmit the bearer token as a command-line
argument, record other people without permission, commit the WAVs or
store them outside the local protected trial directory.

1. With the physical Sense head running and the bench image deliberately
   enabled, set its actual private bearer token in the Mac environment
   variable already configured for this robot. Start the existing audio
   session before capturing; this is a recorder of active codec samples,
   not permission to wake the microphone without consent.
2. Begin the ordinary consented Xiaozhi speaker test stimulus **before**
   starting the four-second capture and keep it playing throughout the
   window. The codec's calibration window rejects a missing speaker
   reference on its first recorded microphone frame, so starting the
   sound afterward produces a failed trial rather than useful WAVs.
   Use a repeatable broadband signal and keep the head's ordinary
   microphone/AFE task active. Do not substitute synthetic reference PCM.
3. Within 30 seconds of physical consent, capture the four-second source-tagged device window:

   ```sh
   cd code
   uv run --no-sync python scripts/capture_sense_aec.py \
     --head-url http://<actual_private_Sense_IP>:8081 \
     --robot-id robot-01 --token-env DESK_ROBOT_HEAD_01_TOKEN \
     --output-dir data/private/aec_lab_trial \
     --i-consent-to-private-raw-audio
   ```

   The client checks the head's authenticated reference diagnostics
   before starting. The **flashed firmware**, not just the build command,
   must report integer `aec_delay_config_ms=0` and
   `microphone_privacy_muted=false`. Missing or nonzero configuration
   stops the client before any START request. It also validates the same
   robot identity, boot epoch and the particular capture generation in
   the authenticated START response, subsequent STATUS and raw PCM headers.
   This rejects an old completed recording from the same device after
   a new START. Firmware also discards a PDM callback whose samples began
   before the authorized START, even if that callback completed afterward.
   The Mac checks the final microphone privacy epoch **and capture
   generation** after raw transfer, rejecting a physical BOOT mute or a
   speaker/reference reset that invalidated the samples before WAV saving.
   The client requires exactly 64000 stereo PCM frames and a four-second
   device timestamp span within 80 ms, and rejects truncated/oversized
   replies. It additionally checks that the authenticated codec's PDM read
   counter advanced by at least 64000 frames and that accepted speaker I2S
   frames increased during this capture. The firmware additionally
   latches `speaker_activity_in_window` when the final microphone callback
   completes the private four-second recording. A speaker write occurring
   afterward cannot qualify an otherwise silent recording merely by changing
   the cumulative counters before the Mac's final status request. A silent
   or inactive speaker trial is rejected before WAV persistence. The
   device also refuses a complete, correctly timestamped capture when
   either the 16 kHz digital microphone or speaker-reference channel is
   entirely zero. This checks for missing digital signal only, not adequate
   volume, broadband excitation, physical sound or echo suppression; the
   offline correlation estimator and real assembled-head acoustic trials
   remain mandatory. These receipts are strictly software activity evidence,
   not actual audible playback. Saturated counters require a fresh, safely restarted bench session.
   The Sense buffer also rejects individual microphone callback
   gaps larger than the frame duration plus 40 ms. These conservative
   limits protect software timestamp validity, not physical AEC quality.
   It makes **no automatic retry** of a possibly already-started capture.
   On an interrupted or failed read after an acknowledged START, the
   Mac sends an authenticated **generation scoped ABORT** using the
   same head bearer. The codec invalidates only that capture generation
   and wipes its retained PCM; its asynchronous HTTP worker checks the
   generation before sending the next chunk. A delayed older ABORT
   cannot erase a newer capture. If the Mac crashes or the network
   disappears, the firmware's independent 12-second buffer expiry
   remains the fallback. None of these software receipts certifies
   audible speaker playback or measured AEC quality.
   The output is private mode 0600 `microphone.wav`,
   `speaker_reference.wav`, and `capture.json`, in a mode 0700
   directory with no overwrite.
4. Read these real source frames with the existing offline estimator:

   ```sh
   cd code
   uv run --no-sync python scripts/estimate_aec_delay.py \
     --microphone data/private/aec_lab_trial/microphone.wav \
     --speaker data/private/aec_lab_trial/speaker_reference.wav \
     --capture-report data/private/aec_lab_trial/capture.json
   ```

   Keep the two WAVs and their receipt together. SHA-256 PCM digests detect
   accidental pairing across captures or edited channels; they do not prove
   hardware identity or acoustic playback. Older receipts lacking digests
   must be recaptured for this receipt-checked workflow.

5. Repeat speaker-active broadband bench captures during double talk,
   VAD interruption, WiFi/camera/servo load and head reboot. Also run
   **no-playback and muted-microphone negative controls**: an entirely
   zero-valued digital reference or microphone is expected to fail the
   capture validity check and produce no accepted calibration WAV. Record
   those rejections and authenticated integrity counters separately, not
   as successful acoustic delay estimates. Retain a source-qualified
   local verification receipt with the tested board revision, actual
   output volume, delay estimates, clock drift and rejected/valid runs.
   Securely delete raw WAVs after analysis.

**A source capture is not A2 physical qualification.** The on-device
timestamp reports when PCM samples entered the codec reference window;
it does not prove physical loudspeaker propagation, analog output
drain, zero acoustic echo, or the actual audible silence position after
barge-in. There is no hardware evidence yet for echo suppression, ERLE,
double-talk preservation, interruption timing, temperature drift,
accurate amplifier feedback or five-pet simultaneity. `capture.json`
and `estimate_aec_delay.py` must keep
`aec_physically_qualified=false` until real bench trials are reviewed.
The independent playback acknowledgment thread remains open.

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
