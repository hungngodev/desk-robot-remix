# Required first-build voice interruption

Updated 2026-11-03: **voice interruption must work in the first build**. The user
has now bought at least one **XIAO ESP32S3 Sense**, with **$18.87 displayed** in the
listing. Exact order quantity, delivered revision and arrival remain unconfirmed.
Keep that purchased board as the active head; no replacement purchase is required
at this stage. A button remains useful for setup/manual stop, but cannot satisfy
this gate.

## Required experience and proposed acceptance

After a conversation starts, a person can speak naturally while the robot is
playing its own answer. It cancels the obsolete answer, captures the new utterance
and responds to that request. It must not merely mute the microphone, wait for a
button, wait for the whole TTS answer or require a special stop/wake phrase for
each interruption. Model-generated voice must not continually interrupt itself.

Proposed robot-one gate, not an achieved measurement:

1. Record firmware/config, mic/speaker placement, operating volume, room/background
   noise and separate 50 cm and 100 cm speaking distances. Use low/middle/maximum **intended** volume,
   not arbitrary amplifier maximum. Include interruptions near the beginning and
   later in an answer, and during more than one consecutive conversation turn.
2. At each distance, at least 19 of 20 ordinary-speech trials stop audible obsolete TTS within 500 ms
   of human-speech onset. At least 18 of 20 yield the correct new intent, with an
   intelligible transcript that includes the start of the person's utterance.
   A stop without capturing the request fails the conversational part. The
   50 cm and 100 cm sets must pass independently on the same qualified build.
3. Ten minutes of robot-only observation with sustained, audible robot speech
   across the full window has no false self-interruption. Test a second
   person, normal pauses and nearby speech/noise; document the allowed conditions.
4. Repeat with camera capture and Wi-Fi activity, then motors/servos on a stand.
   Log capture/reference alignment, clipping, buffer losses, memory and timings.
5. Aborted audio cannot resume from old queues after a reconnect or new turn.
   Stop/quiet/fault cancel pending spontaneous speech as well as future TTS chunks.
6. Repeat the acoustic gate on every duplicated robot. Hats/costumes must preserve
   mic/speaker paths. For five-peer sessions, grant one conversational floor at a
   time; the current speaker accepts human interruption and the Mac cancels the
   obsolete group turn. Other robots receive peer events digitally.

These thresholds make the requirement reviewable; no physical trial exists yet.

### Executable audio trial record contract

`code/scripts/check_barge_in_trials.py` now rejects incomplete trial
coverage instead of treating an arbitrary set of twenty identical
interruptions as acceptance evidence. The input is JSON Lines containing
twenty `kind: human` records at 50 cm and another twenty at 100 cm,
plus one `kind: robot_only` record and one `kind: quiet` record (42 total).
From the repository root, run `python code/scripts/check_barge_in_trials.py
PATH_TO_PRIVATE_TRIALS.jsonl`. Inspect the JSON `meets_proposed_gate` field;
a zero process exit status alone does not mean the gate passed.
One complete twenty-trial distance set alone can be inspected but **never
passes A2 overall**. Both controls must be observed for at least
600 seconds on the same actual robot, firmware, audio setup and head geometry.

Each human row records a unique `id`, `volume` (`low`, `medium`,
`high`), `interruption_position` (`early` or `late`),
`load_profile` (`voice_only`, `camera_wifi`, or
`motors_servos_stand`), `speaker_id`, a positive
`conversation_turn`, `speaker_distance_cm` within 45 to 55 for the
50 cm set or 95 to 105 for the 100 cm set,
`room_noise_db_a`, `robot_id`, `firmware_commit`, `audio_config_id`,
and `mic_speaker_placement_id`. The twenty rows must actually cover both
positions, all three load profiles and intended speaker volumes, two
human speakers and adjacent conversation turn numbers **in each twenty-trial set**.

Each human trial must also declare `audible_robot_speech_at_onset=true` from
observed robot playback when the person begins speaking. A trial with a silent
robot is not a barge-in attempt and cannot count toward either twenty-trial
population. This declaration remains operator-supplied: acoustic waveform
capture and synchronized device logs are still required for physical proof.

Each human row also supplies measured monotonic timestamps, in order:
`human_onset_ms`, `vad_arrival_ms`, `abort_dispatch_ms`,
`head_queue_clear_ms`, `i2s_stop_ms`, `audible_stop_ms`. Use one common
monotonic trial clock rebased before numeric conversion; its floating-point
spacing must not exceed 0.001 ms. Reject an audible stop timestamp equal to
speech onset: an interruption must have positive measured elapsed time.
Clock alignment still requires synchronized external evidence. Record
`new_utterance_captured`, `new_intent_correct`,
`utterance_beginning_intelligible`, and
`obsolete_audio_never_resumed` as booleans. A claim of correct new intent
requires actual retained speech at its start. The robot-only row records
`duration_seconds` of at least 600, nonnegative integer
`self_interruptions`, and the exact same `robot_id`, `firmware_commit`,
`audio_config_id`, and `mic_speaker_placement_id` as the twenty human
trials. A control from another robot or mounting configuration is invalid.
The ten-minute `kind: robot_only` control must additionally report
finite `robot_speech_seconds` covering the **first 600 seconds** of the
observation, plus `audible_robot_speech_observed=true`. To exercise the
actual self-echo path throughout this window, the proposed protocol requires
at least **120 cumulative seconds** of audible playback (20% exposure),
a list `robot_speech_seconds_by_minute` of exactly ten finite values
between **5 and 60 seconds** (one value for each successive 60-second
interval), and an aggregate matching `robot_speech_seconds` within
0.01 second. Both the aggregate and the sum of the ten measured intervals
must independently meet 120 seconds; the matching tolerance cannot waive the
minimum exposure. Record `robot_speech_volumes_observed` with all three
intended playback settings, `low`, `medium`, and `high`, during
this control, not merely in the human interruptions. For runs longer than
600 seconds, these metrics describe the first complete ten minutes; later
time cannot rescue an inadequately exercised initial window. The per-minute
distribution prevents a few early utterances from being mistaken for a
ten-minute acoustic stress control. These exposure thresholds are explicit
proposed test coverage criteria, not validated acoustic performance limits.

An otherwise silent or nearly silent robot is not an echo-suppression test.
Measure playback from device logs and synchronized audio capture. The checker
can reject incomplete declarations but cannot authenticate the per-minute
measurements or prove audible energy, volume, microphone exposure, or the
absence of false self-interruption without physical recordings. The separate `kind: quiet` row must
declare `quiet_mode_enabled=true` and record at least 600 actual
seconds with nonnegative integer `unsolicited_speech_events` and
`unsolicited_motion_events`. Both counts must be zero for A2 acceptance,
including silence while the camera and sensors remain operational. The
quiet control must repeat the same `robot_id`, `firmware_commit`,
`audio_config_id`, and `mic_speaker_placement_id` as the interruption
trials. An echo-only control is not a quiet-mode test.
The checker includes these identities in its result so no generic
five-robot qualification can be inferred. The proposed acoustic gate needs **at each distance**
19/20 audible stops within 500 ms, 18/20 correctly retained and understood
intents, zero self-interruptions, no obsolete audio resuming, and no
unsolicited quiet-mode speech or motion.

The checker validates a *declared measurement record*; it does not
independently measure acoustic waveforms, authenticate a second speaker,
or prove the speaker, camera and motor were physically active. Its report
always states that operator evidence is not independently attested.
The final acceptance record must preserve waveform captures, device
logs and real bench evidence outside the repository. A synthetic unit
test passing this checker is never a physical A2 pass.

The `robot_only` record currently scores audible playback exposure and TTS
self-interruptions, not false VAD starts independent of TTS interruption.
The `motors_servos_stand` human trials do not prove rejection of actuator noise
when no person is speaking. Keep the actuator-only false VAD subgate open:
separate real stand observations with actuators active during TTS and without
TTS, and separate false VAD counts, are still needed. A true
`meets_proposed_gate` is not evidence that these observations were made.

## Active hardware and software reuse

Use the purchased **XIAO ESP32S3 Sense**, its onboard PDM microphone and included
camera, and a suitable speaker. The baseline drives a **MAX98357A** over I²S.

The active `code/firmware/head/sense/config.h` pin contract uses onboard PDM
clock GPIO42 and data GPIO41 at 16 kHz; MAX98357A I2S BCLK GPIO4, LRCK GPIO7
and DOUT GPIO8 at 32 kHz. The AFE receives interleaved mic/reference PCM16 at
16 kHz. The initial 24 kHz Opus decoder rate is not the amplifier clock.
No MCU-controlled SD_MODE or switched amplifier supply is wired (`GPIO_NUM_NC`);
an I2S stop is not proof of audible silence. See `code/firmware/head/tests/test_sense.py`.

The photographed HiLetgo PAM8403 offers an analog path if a suitable DAC is
available. See the [parts list](../hardware/parts.md). Check the delivered
board and sensor before assigning a firmware binary. The rechargeable 1S power
kit and regulated 5 V supply are pending selection. Run the acoustic test with
the selected amplifier, speaker and enclosure.

The closest verified source is
[RIO at revision `b911305e48ce6a1b75fe6c07fc02f86ad7bfeb0a`](https://github.com/mk14ray/RIO-XIAO-ESP32-S3-Gemini-Live-Voice-Assistant/tree/b911305e48ce6a1b75fe6c07fc02f86ad7bfeb0a).
It uses this Sense/PDM + MAX98357A + SSD1306 combination and has an explicit
[MIT license](https://github.com/mk14ray/RIO-XIAO-ESP32-S3-Gemini-Live-Voice-Assistant/blob/b911305e48ce6a1b75fe6c07fc02f86ad7bfeb0a/LICENSE).
Reuse its implementation as a porting reference, preserving attribution; the
repository is not evidence that our acoustics or complete robot have passed.

- Its [AEC implementation](https://github.com/mk14ray/RIO-XIAO-ESP32-S3-Gemini-Live-Voice-Assistant/blob/b911305e48ce6a1b75fe6c07fc02f86ad7bfeb0a/aec.cpp)
  calls Espressif `aec_process` with mic and delayed playback-reference samples.
  It includes stateful 24 kHz-to-16 kHz reference conversion, noise suppression,
  VAD and a residual-echo gate. This is actual software AEC, not only a config flag.
- Its [configuration](https://github.com/mk14ray/RIO-XIAO-ESP32-S3-Gemini-Live-Voice-Assistant/blob/b911305e48ce6a1b75fe6c07fc02f86ad7bfeb0a/config.h)
  enables full duplex, but the 90 ms reference delay is an initial value to
  calibrate. Use its AEC bring-up/delay-sweep approach on the assembled head.
- **Echo-gate fallback is a failure for our requirement.** When cancellation is
  poor, closing the mic gate during playback may prevent self-triggering while
  also removing the person's interruption. It cannot count as ordinary-speech
  barge-in, even if a quiet half-duplex demonstration sounds good.
- Review shared reference-ring ownership and synchronization before transplanting:
  cross-task plain state and clearing a ring while another task reads it need
  explicit handling. Verify alignment, drift, reference reset and double-talk;
  do not copy timing assumptions unchanged.
- RIO's [Live handler](https://github.com/mk14ray/RIO-XIAO-ESP32-S3-Gemini-Live-Voice-Assistant/blob/b911305e48ce6a1b75fe6c07fc02f86ad7bfeb0a/gemini_live.cpp)
  handles `serverContent.interrupted` by requesting a playback flush. Test audible
  cancellation and retention of the new utterance through the complete chain.
- Check GPIO ownership against our head/body UART and debug console. In
  particular, RIO uses GPIO44 for amplifier shutdown; its pin map is not a drop-in
  replacement for our wiring. Never ground a bridge-tied speaker output.

RIO connects directly to Gemini Live and needs a cloud API credential. It does
not provide our WROOM motion guard, cliff sensing, gripper or five-robot scheduler.
Those remain separate local responsibilities. No API request, flash or acoustic
test was performed during this source review.

## Why the current Xiaozhi Sense profile is not already sufficient

The [Sense port design](sense-aec-port.md) identifies an existing ESP-IDF AFE
input for real mic/reference pairs, preserving the purchased board and pin map.
RIO's reference/calibration ideas can be reused without importing a second full
processing chain. The paired microphone and software-reference adapter now exists in
`code/firmware/head/sense/sense_reference_codec.cc` and is compiled as
part of the selected Sense build; real acoustic delay and double-talk
performance are still unmeasured.

Pinned Xiaozhi revision`c435f99a88066029ec2dbd2d758c8cc9d051565b`:

- `AudioCodec` defaults`input_reference_=false`; current Sense uses
  `NoAudioCodecSimplexPdm` with16k capture/24k playback and no reference.
- PDM RX and standard-I²S TX can coexist. `duplex_=false` describes the driver's
  independent-channel arrangement; it is **not** proof that simultaneous input
  and output are impossible. The missing piece is qualified reference/AEC/control.
- [AFE architecture](https://github.com/78/xiaozhi-esp32/blob/c435f99a88066029ec2dbd2d758c8cc9d051565b/main/audio/README.md)
  derives`MR` from mic/reference counts and warns that software reference timing
  and concurrency need validation. Merely setting the reference flag invents
  data; the samples must actually exist and match playback.

The Sense software-reference port is integrated into the selected Xiaozhi
codec and adds no replacement board cost. RIO is the closest hardware-matched reference found. Existing Box Lite
code is another unqualified pattern, with shared buffer state, equal-rate
assumptions and DMA timing concerns. A robust port needs bounded thread-safe
queues, actual post-resampling/post-volume playback samples, alignment/drift
handling, epoch/reset behavior and double-talk tests. Neither source is a
demonstrated drop-in for our firmware and assembled head.

Mac-side SpeexDSP/WebRTC adaptive AEC is another integration route, not currently
installed or implemented. It requires timestamped real PCM references, delay and
clock-drift handling. It is not achieved by changing a VAD threshold.

## The complete interruption chain still needs testing

AEC cleans capture; it does not by itself cancel the old answer. Required path:

```text
mic + actual speaker reference -> AFE/AEC -> real-time uplink -> VAD
 -> cancel obsolete turn/TTS -> stop/flush local playback
 -> retain new human utterance -> ASR/LLM -> fresh response
```

The pinned Python server`d9c2e8c5d92627b670dec57d72a07a4226a410a3` has VAD/TTS
abort handling in`core/handle/receiveAudioHandle.py`. Its experimental spectral
echo suppression in`core/connection.py` is only invoked for timestamped MQTT-gateway
audio, **not the current ordinary direct-WebSocket path**. `features.aec` sets a
flag; it does not create a clean reference or enable that suppression for every
transport. The initial just-woken suppression window also needs early-interruption
tests. The endpoint/UI/config and output queue behavior must work together.

Selecting the pinned server's `GeminiLLM` provider does not enable Gemini Live:
its `core/providers/llm/gemini/gemini.py` uses the traditional text-generation API.
A Live transport is a separate integration choice, not a YAML-only audio upgrade.

## Camera frames and proactive conversation

RIO's camera is **tool-requested still capture, not video streaming**. It powers
the sensor down between captures, so its existence does not prove continuous
vision or simultaneous camera/audio performance.

For the Mac pipeline, reuse Pipecat's
[Gemini Live video example at `c87446099f88560b861ac0e1c13cce331e3a5770`](https://github.com/pipecat-ai/pipecat/blob/c87446099f88560b861ac0e1c13cce331e3a5770/examples/realtime/realtime-gemini-live-video.py)
([BSD-2-Clause license](https://github.com/pipecat-ai/pipecat/blob/c87446099f88560b861ac0e1c13cce331e3a5770/LICENSE))
as a **1 frame/s** camera/screen-input and initial-greeting reference. The example
does not supply Sense capture/transport firmware or solve its acoustic echo.
Google's [robotics streaming guidance](https://ai.google.dev/gemini-api/docs/robotics-streaming)
explains that frames alone do not trigger new reasoning turns: periodic latest
frames plus short text prompts can drive idle observations. New prompts can
interrupt active generation, so the Mac must own cooldowns, speaking turns and
cancellation; do not continuously prompt over human or peer speech. Proactive
audio response settings alone are not an autonomous pet behavior controller.

Start with sampled frames and bounded idle prompts, then measure audio/camera
contention. Higher-rate video is a later measured
capability. Cloud usage charges are separate from hardware and remain unquoted;
no Gemini or other paid API was used for this review.

### Sense camera completion and Mac receipt evidence

The authenticated Sense MJPEG part includes a boot nonce, monotonic frame
sequence, and device-local capture completion counter in microseconds.
The Mac stream parser verifies the source identity and the same-frame ordering,
then keeps a separate Mac monotonic network receipt timestamp. The bounded
`CameraFrameHub` now preserves these original source values in its camera
timeline as `source_boot`, `source_frame_sequence`, and
`source_capture_complete_us`, alongside the normal Mac-receipt `age_ms`.
The device clock has **not** been synchronized to the Mac. Do not subtract
these two clocks, report sensor exposure age from them, or claim an
optical capture-to-speech latency pass. The timeline explicitly retains
`exposure_timestamp_verified=false` and
`source_clock_not_aligned_to_mac=true` for source-tagged streaming frames.
When testing a non-Sense/fake head without device metadata, these source fields
are omitted instead of invented.

For actual A9 acceptance, record the same authenticated source boot, frame
sequence and completion timestamp together with a Mac receive clock,
camera scene event, voice turn and external synchronized visual stimulus.
Measure camera acquisition and network delay with an independent timed
fixture on the final assembled head before claiming source freshness or
synchronized perception. No extra camera capture service is introduced.

## Optional fallback, not a purchase requirement

The initial audit proposed **Waveshare ESP32-S3-CAM-OV5640, SKU33699** before the
Sense purchase was incorporated. That recommendation is superseded by keeping
the purchased Sense active. Waveshare remains an **unqualified alternative** if
the Sense integration fails the acoustic gate and a later purchase is chosen.
It has not passed our interruption tests either.

Historical source check: the selected official option was $19.99, including
OV5640 and a 1217 8Ω/2W speaker; PCB 37×37 mm, hole pitch 32.6 mm.
[Product](https://www.waveshare.com/esp32-s3-cam-ov5640.htm?sku=33699),
[docs](https://docs.waveshare.com/ESP32-S3-CAM-OVxxxx),
[schematic](https://files.waveshare.com/wiki/ESP32-S3-CAM-OVxxxx/ESP32-S3-CAM-OVxxxx_Rev1.1.pdf).
ES8311 DAC OUTP/OUTN feeds ES7210 ADC MIC3 as a physical playback reference;
upstream `BoxAudioCodec` consumes one mic plus that reference, not automatically
dual-mic beamforming. This route would replace the separate MAX98357A/speaker.

Before using it, verify generated device-AEC configuration, exact driver/power
initialization and a separate OLED I²C bus: its OV5640 at 0x3C conflicts with a
default SSD1306. UART43/44 also requires the console on native USB. Its SH1.0/FPC
connectors need matching adapters, and the rounded case has not been fitted.
The earlier conditional Waveshare budget is not the active Sense build total or
a delivered quote; do not order an additional board based on that old comparison.

Source/API references: [Espressif AEC](https://docs.espressif.com/projects/esp-sr/en/latest/esp32s3/acoustic_echo_cancellation/README.html),
[audio hardware guidance](https://docs.espressif.com/projects/esp-faq/en/latest/application-solution/audio-development-framework.html),
[server audio handler](https://github.com/xinnan-tech/xiaozhi-esp32-server/blob/d9c2e8c5d92627b670dec57d72a07a4226a410a3/main/xiaozhi-server/core/handle/receiveAudioHandle.py).

Existing Sense build success remains historical software evidence. The selected Sense reference codec, consented continuous MJPEG stream,
and native Xiaozhi interruption hooks now have source integration and host
regressions. The complete audible interruption chain still needs device
measurement on the assembled head; no 20-trial physical acceptance is claimed. A compiled head profile establishes software integration only. No hardware
has been flashed by this project and no interruption test has passed.


## Authenticated Sense reference integrity while camera and audio run

The existing Sense Xiaozhi codec now exposes **read-only counters** through the
same private, authenticated head bridge as the camera:

`GET http://<sense-lan-ip>:8081/api/audio.reference`

Use this only with the configured head bearer token in a controlled private
bench network. Its fields include `robot_id`,
`reference_underflow_reads`, `reference_overwrite_reads`,
`discarded_stale_writes`, and `reference_integrity_failed`. Both
`speaker_playback_verified` and `aec_physically_qualified` are explicitly
`false`: an accepted I2S write or software reference buffer **cannot** prove
that audio emerged from the speaker or that a human interruption was understood.

The Mac validates these fields and refuses a mismatched robot identity,
noninteger or out-of-range counters, or a claimed physical qualification.
The existing authenticated `code/scripts/bench_head_camera.py --stream`
now attaches these counters to the read-only contention report when the
Sense head is reachable; `aec_reference_probe_error` records any unavailable
route, and `aec_reference_diagnostics` is null when unsupported. It never
opens another PDM reader or stores raw audio. Run the bench with active
operator mic/camera consent and a known speech activity trial, then retain
the actual hardware result. Normal silence can increment some counters;
evaluate changes across measured trials, not a zero counter alone.

Sense codec read/write callbacks and the Sense-only I2S error branches do not
synchronously emit console logs. Poll these authenticated counters outside the
audio tasks instead; a stalled USB or UART log sink must not delay their error
handling. This does not establish a physical DMA or acoustic latency bound.

This telemetry helps diagnose A2 reference integrity. The optional,
authenticated four-second PCM capture path is now implemented and described
below, but a real assembled-head recording, measured acoustic latency,
verified device playback progress, and both twenty-trial human interruption sets plus both controls
are still absent. Source integration never satisfies those physical gates.

## Per-robot playback reference alignment in the pinned Sense build

The ESP-SR AFE input remains two-channel interleaved `MR` at 16 kHz;
`SenseReferenceCodec` converts the accepted 32 kHz MAX98357A speaker
output into a 16 kHz AEC reference and uses the existing Xiaozhi I2S writer.
Xiaozhi's pinned decoder resamples incoming 24 kHz TTS PCM to the supported
32 kHz amplifier clock. The upstream RIO 24 kHz reference described above
is source history, not a safe MAX98357A board clock. The earlier fixed 90 ms
reference alignment is now a Kconfig setting named
`CONFIG_DESK_ROBOT_AEC_DELAY_MS` (0 to 250 ms). That **does not** make the
robot acoustically calibrated. Each actual assembled robot must measure the
reference-to-microphone lag and run the two twenty-trial interruption sets at different
speaker volumes, distances and motor load. The offline
`code/scripts/estimate_aec_delay.py` now accepts a synchronized mono PCM16
speaker recording at the actual 32 kHz I2S rate and a simultaneous 16 kHz
mono microphone recording, with an explicit ten-second limit. Its causal
63-tap Q15 equiripple FIR reproduces the selected Sense codec's reset phase,
nearest-integer rounding (ties away from zero), and PCM16 saturation.
The filter adds 31 input samples (0.969 ms) of group delay. Use actual
post-volume PCM16 output, not arbitrary floating-point or pre-volume TTS data.
This does not replace the zero-delay native capture or prove audible output.
The receipt-checked native capture writes both WAV channels at 16 kHz PCM16,
so its already-decimated reference bypasses the estimator's 32-to-16 kHz FIR.
The external 32 kHz input example below is a different, non-receipt workflow.
The estimator also accepts legacy 24 kHz references for offline diagnostics;
that does not authorize a 24 kHz MAX98357A clock.
Use `python code/scripts/estimate_aec_delay.py --speaker
sense_playback_32k.wav --microphone sense_microphone_16k.wav` with
private real recordings from the SAME assembly and clock alignment.
A 24 kHz decoded TTS file alone is not the actual post-resampler speaker
output and cannot certify echo delay. The command only estimates lag and
drift; it does not capture audio, prove acoustic isolation, or qualify
barge-in without the separate physical trial evidence.
For recordings of four seconds or longer, failed drift validation suppresses
the copyable fixed-delay setting even if global correlation finds a peak.
Long recordings also probe gaps between the four primary drift windows.
Each channel and each candidate overlap must have mean-centered RMS of at
least 0.0001 on the normalized PCM scale (about 3.28 PCM16 counts).
A high correlation in near-silent samples is not usable delay evidence.
This numerical floor is not a measured microphone noise or VAD threshold.
These checks cannot detect every brief timing excursion; retain the physical
AEC and interruption trial requirements.

For a private physical Sense build, pass `--board sense --aec-delay-ms 115`
to the existing `firmware/head/private_config.py` command (without
`--bench-aec-capture`) after measuring a
115 ms reference lag. Use its other required robot ID, config, secrets and LAN
server options as before. The field is written only to the private firmware
configuration, without changing the upstream ESP-SR implementation. A 90 ms
default is retained for a first bench measurement, never as proof of AEC
performance or as an acceptable substitute for retained human utterances.


## Private, actual Sense microphone and reference acquisition

The Sense build now has an explicitly gated, RAM-only four-second stereo
calibration window inside the **existing Xiaozhi PDM plus reference reader**.
It does not instantiate another microphone stack or alter ordinary firmware.
Normal build configuration sets
`CONFIG_DESK_ROBOT_AEC_PCM_CAPTURE_ENABLED=n`. A separate private bench
image needs all of `--board sense --continuous-audio --aec-delay-ms 0
--bench-aec-capture` passed to `code/firmware/head/private_config.py`.
The device must already be assembled, authorized and continuously listening.
Only the optional bench image registers the authenticated
`/api/audio.capture.start`, `/api/audio.capture.abort`,
`/api/audio.capture.status` and `/api/audio.capture.raw` endpoints. The
capture does not begin at boot. For each recording, follow the mandatory
[physical BOOT consent gesture](sense-aec-port.md#authenticated-one-shot-sense-microphonereference-capture):
mute with BOOT, hold BOOT while already muted until the long-press event,
release, then tap within 30 seconds to unmute while connected and idle.
This authorizes one START within the next 30 seconds. Ordinary unmute,
a private image and an authenticated bearer are not recording consent.
Start an audible broadband stimulus before START and sustain it throughout
the four-second recording. An incomplete reference, known short PDM read,
discontinuous source window or playback reset invalidates the trial. The
private capture must never be deployed as a production image.

For a real bench trial, first configure the private image with the robot's
existing unique token and an accessible Mac LAN IPv4 address. Build and flash
only that explicitly approved private image. From the Mac, with the physical
operator's permission and a private output directory, use the installed
`code/scripts/capture_sense_aec.py` tool:

```sh
python code/scripts/capture_sense_aec.py \
  --head-url http://192.168.1.20:8081 \
  --robot-id robot-01 \
  --token-env DESK_ROBOT_HEAD_01_TOKEN \
  --output-dir ./data/private/sense-aec-trial-01 \
  --i-consent-to-private-raw-audio
python code/scripts/estimate_aec_delay.py \
  --speaker ./data/private/sense-aec-trial-01/speaker_reference.wav \
  --microphone ./data/private/sense-aec-trial-01/microphone.wav \
  --capture-report ./data/private/sense-aec-trial-01/capture.json
```

The capture receipt includes SHA-256 digests of both PCM channels. Keep all
three files together: the estimator rejects mismatched or older receipts
without digests when `--capture-report` is supplied. A matching local receipt
is not cryptographic device attestation or physical AEC qualification.

Replace the sample IP, robot ID and token environment name with the actual
local device identity. The capture tool refuses public or proxied addresses,
requires an authenticated matching boot ID, declines partial PCM and writes
private 0700 directory and 0600 files without overwriting existing captures.
Use both WAVs from the same capture directory; do not independently trim,
pad, or substitute one channel. The estimator rejects unequal resampled
sample counts, malformed PCM16 and a dominant negative lag. A positive
candidate is still an offline diagnostic, not proof of shared acquisition
or audible output. Those files contain **real microphone audio**, so do not
commit, share or place them in a synchronized public folder. The device's sample times and
software integrity counters are diagnostics, not proof of audible speaker
output. Reflash the standard build with PCM capture off after calibration.
Keep the true speaker latency, microphone intelligibility, acoustic
isolation and the forty human interruption trials (twenty at each distance),
ten-minute echo-only control and separate ten-minute quiet-mode control open
until recorded on the assembled head.

## Xiaozhi natural realtime VAD and actual acoustic acceptance

The pinned server overlay now uses real realtime listener VAD to preempt ordinary one to one assistant TTS, not only coordinated fleet speech. It requires two consecutive VAD positive frames within 300ms and sends an urgent true decoder/I2S speaker flush while preserving incoming ASR frames. The compiled SenseReferenceCodec already sends real PDM microphone and playback reference channels into ESP SR AEC. These statements concern code integration and tests, not an acoustic calibration on the user's actual head. The companion code/scripts/check_barge_in_trials.py checks real operator measured speaker stop and understanding records. Physical speaker/mic delay is estimated separately by code/scripts/estimate_aec_delay.py. Keep live spoken acceptance false until actual acoustic trials pass.


## Live Xiaozhi voice mode check added to the bridge

The authenticated Mac speech bridge now exposes `GET http://127.0.0.1:8766/voice-readiness?device_id=<xiaozhi-device-id>` using the same private `DESK_ROBOT_SPEECH_TOKEN` Bearer header as speech commands. It reads the **connected** device's current `client_listen_mode`, not a remembered or assumed configuration. Only `realtime` reports the realtime audio path available; `auto`, `manual` or an offline head report false. It also explicitly returns `device_aec_measured=false`, `microphone_double_talk_measured=false`, `audible_flush_measured=false` and `natural_barge_in_certified=false` until real equipment trials. The new host test covers authentication, transitions and disconnects. This is a diagnostic, not a firmware wake word change or a certificate. The previously integrated ESP-SR AFE/Xiaozhi abort path remains the correct approach for natural speech interruption.

## Realtime backend is different from the local three stage pipeline

Official upstream [78/xiaozhi-esp32](https://github.com/78/xiaozhi-esp32) supports **both** a streaming ASR + LLM + TTS server and a realtime end-to-end speech model. Its full-duplex capability also requires AEC-capable actual hardware. The project's current `code/config/xiaozhi.local.example.yaml` selects **SileroVAD, FunASR, OllamaLLM and CustomTTS/Kokoro**, which is the separate three-stage local pipeline, not automatically a Gemini Live / ChatGPT Live equivalent. The `CONFIG_USE_DEVICE_AEC=y` Sense flag and the new `/voice-readiness` endpoint establish a software path; neither proves an end-to-end realtime provider is in use or acoustic echo cancellation on the assembled head.

For genuine open conversation, keep the pinned Xiaozhi firmware, device AFE reference code and server interruption hook. Then connect a supported realtime voice service using its documented provisioning/transport interface, preserving the existing authenticated WROOM motion guard and device identities. Do **not** rename `OllamaLLM` to an unverified realtime module or hardcode a cloud credential. Physical mic/speaker delay, double talk and audible cancel still need the measured two-distance forty-trial procedure and both controls. The control endpoint reports `natural_barge_in_certified=false` until those results are real. See also [Xiaozhi feature guide](https://xiaozhi.dev/en/docs/usage/feature-guide/) and the pinned server bridge config.


## Bounded pinned Xiaozhi TX under urgent flush

The exact pinned [Xiaozhi NoAudioCodec](https://github.com/78/xiaozhi-esp32/blob/c435f99a88066029ec2dbd2d758c8cc9d051565b/main/audio/codecs/no_audio_codec.cc)
uses `i2s_channel_write(..., portMAX_DELAY)` **while holding the
`data_if_mutex_`** in `NoAudioCodec::Write`. Therefore the old
`AudioService::ResetDecoder` followed by `EnableOutput(false)` could
wait indefinitely for a stalled speaker I2S DMA write even though an
urgent speech stop had been received. Cancelling TTS at the Mac layer
alone cannot bound this on-device lock.

Our `code/firmware/head/install_overlay.py` now applies the smallest
Sense-only edit to the exact upstream writer in a disposable pinned
clone. It uses a **120 ms maximum speaker I2S TX wait** and
returns a sample count only for a successful, bounded, whole-frame I2S
write. Driver errors and invalid byte counts become zero accepted frames
rather than fatal `ESP_ERROR_CHECK`. The normal native Xiaozhi
`SenseReferenceCodec` marks short output as an integrity failure and never
promotes uncertain queued PCM into playback or echo reference evidence.
The original upstream checkout, CoreS3, and modular/waveshare board
profiles remain unchanged. `firmware/head/tests/test_overlay.py`
checks pinned patch anchor, callback semantics, the selected Sense
profile and exact revert.

This gives a **bounded codec wait**, not a guaranteed 500 ms
spoken interruption. Even 120 ms I2S timeout plus decoder scheduler, task
wake, VAD/network latency, buffered amplifier output and real
speaker/microphone acoustics can exceed the stated user acceptance
limit. Playback frame length and output DMA queues need a live
oscilloscope/audio recording at the real XIAO board. If they exceed the
20 trial metric, tune bounded queueing and driver cancellation using
the upstream Xiaozhi implementation, not a second fabricated codec.


### DRX-727: separate 120 ms digital playback cutoff target

The trial checker now reports `i2s_stops_within_120ms` and
`max_onset_to_i2s_stop_ms` for each distance, measured from human onset to
I2S stop using the same rebased trial clock. The separate
`meets_120ms_i2s_cutoff` result requires all twenty positive elapsed
cutoffs at each of both covered distances to be no more than 120 ms,
with the full per-distance trial coverage (volumes, positions, loads,
speakers and adjacent conversation turns) required by the checker.
An empty distance has a null maximum and cannot pass. A 120 ms codec
write timeout or WebSocket STOP send is not this measurement. The existing
500 ms audible stop and utterance retention acceptance gate remains
unchanged. Both require physical synchronized measurements; synthetic
records and passing software tests do not qualify the assembled head.
