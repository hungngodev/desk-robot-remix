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
   noise and a 50 cm speaking distance. Use low/middle/maximum **intended** volume,
   not arbitrary amplifier maximum. Include interruptions near the beginning and
   later in an answer, and during more than one consecutive conversation turn.
2. At least 19 of 20 ordinary-speech trials stop audible obsolete TTS within 500 ms
   of human-speech onset. At least 18 of 20 yield the correct new intent, with an
   intelligible transcript that includes the start of the person's utterance.
   A stop without capturing the request fails the conversational part.
3. Ten minutes of robot-only speech has no false self-interruption. Test a second
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

## Active hardware and software reuse

Use the purchased **XIAO ESP32S3 Sense**, its onboard PDM microphone and included
camera, plus an external **MAX98357A and suitable speaker**. A complete Sense
package does not need a separate camera or INMP441 microphone. Check the delivered
board and sensor before assigning a firmware binary. Keep the owned WROOM body,
steppers, lift+grip servos, SSD1306 and regulated-bank plan. The bank's current
rating and load performance remain unknown.

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
processing chain. The actual paired-sample adapter remains to implement.

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

A Sense software-reference port is technically possible and adds no replacement
board cost. RIO is the closest hardware-matched reference found. Existing Box Lite
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

Existing Sense build success remains historical software evidence. The RIO port,
streamed-frame path and complete interruption chain remain to be implemented and
tested. A compiled head profile establishes software integration only. No hardware
has been flashed by this project and no interruption test has passed.
