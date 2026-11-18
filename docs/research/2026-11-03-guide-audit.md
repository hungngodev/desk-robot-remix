# Audit of the supplied 2026 desk-pet engineering guide

Reviewed 2026-11-03. User-provided document: *Engineering an Autonomous
Open-Source AI Desk Pet in 2026: The Complete ESP32-S3 and XiaoZhi Robotics Guide*.
This is a research draft, not an established assembly recipe. We checked primary
hardware documentation, actual repository files and the project's pinned source.
The uploaded prose is not treated as evidence that its sample code was compiled
or its hardware tested.

## What changes the project

The user explicitly answered: **voice interruption must work in the first build**.
Ordinary speech over the robot's own playing TTS must stop obsolete playback and
capture the new request. Button interruption cannot satisfy that requirement.
[The audio gate](../guides/audio-barge-in.md) is now required before robot one passes.

**Purchase update supersedes the initial hardware recommendation:** the user has
bought at least one **XIAO ESP32S3 Sense**, with **$18.87 displayed** in the
listing. Exact quantity, receipt, delivered revision and arrival are unconfirmed.
Keep that board active with its included camera/PDM microphone, plus an external
MAX98357A and suitable speaker. A complete Sense package needs no separate camera
or INMP441 purchase. Ordinary-speech interruption remains a required, unpassed gate.

The initial audit proposed **Waveshare ESP32-S3-CAM-OV5640, SKU33699** for its
physical playback-reference path and existing `BoxAudioCodec`. That is now only
an **optional, unqualified fallback**, not a replacement purchase requirement.
The historical official selected option was $19.99, including camera and 1217
8Ω/2W speaker; source drawing: 37×37 mm PCB, 32.6 mm hole pitch.
[Product/package](https://www.waveshare.com/esp32-s3-cam-ov5640.htm?sku=33699),
[documentation](https://docs.waveshare.com/ESP32-S3-CAM-OVxxxx),
[schematic](https://files.waveshare.com/wiki/ESP32-S3-CAM-OVxxxx/ESP32-S3-CAM-OVxxxx_Rev1.1.pdf).
No physical barge-in test establishes either board as qualified.

Keep the owned WROOM, steppers/ULN2003, SSD1306, two lift/grip servos and bank-based
power. No new Uno/Pico/Pi, N20 drivetrain or PCA9685 is added. The rounded head
remains a candidate shell; a smaller PCB envelope is not proof of cable/mic/optical
fit. The newly ordered Sense includes a camera; do not retain the earlier claim
that no camera is ordered. No delivered hardware inspection has occurred.

## Corrections that matter

| Draft claim | Checked correction and project decision |
| --- | --- |
| Sub-$45 Amazon complete Cozmo clone | The listed values total$42.50, but no exact variants, package outlays or delivered quote are supplied. It also changes our owned drivetrain. Do not replace real dated BOM evidence with these estimates. |
| Two servos provide head tilt/lift and useful grabbing | Those two functions leave no closing claw. Our two are **lift + grip**, with fixed head. Adding powered tilt needs a third per robot, fifteen fleet servos rather than the estimated ten, plus pin/power/mechanical review. |
| PCA9685 offloads all independently timed actuation | [NXP](https://www.nxp.com/docs/en/data-sheet/PCA9685.pdf) specifies one shared PWM frequency for all outputs. Servo-rate PWM also constrains DC inputs. It is not a substitute for a timed28BYJ phase sequencer. Keep the WROOM body. |
| Universal S3-CAM pin map/shared GPIO41/42 bus | A board's actual wiring governs. Sense uses41/42 for onboard PDM mic; Waveshare CAM has a different camera/audio map. Do not wire the article's Freenove-style table onto either. [Sense guide](https://wiki.seeedstudio.com/xiao_esp32s3_getting_started/), [Waveshare](https://docs.waveshare.com/ESP32-S3-CAM-OVxxxx). |
| OLED can simply share the new head's camera bus | OV5640, OV3660 and GC2145 use7-bit0x3C, which conflicts with a default SSD1306. OV3660 is **not** a0x30 fix. Use a separate display bus or physically verified0x3D display option. [Espressif sensor address definitions](https://github.com/espressif/esp32-camera/blob/281d951f75b6559adec3cdb8cf076366da103880/driver/include/sensor.h). |
| Any S3 plus mic/MAX98357 gives full-duplex AEC | An S3 can run AEC, but it requires a valid playback reference, acoustics and the right software path. Current Xiaozhi Sense codec has no reference. RIO supplies a hardware-matched software-reference/AEC example, not a passed port. Waveshare has a physical reference but remains an optional, unqualified fallback. Closing a residual-echo gate during playback fails mandatory ordinary-speech interruption if it suppresses the person. |
| AFE includes guaranteed noise suppression | Pinned upstream explicitly disables NS because it does not ship an NSNet model. AEC, VAD, wake recognition, noise suppression and interruption are distinct features. [Pinned audio architecture](https://github.com/78/xiaozhi-esp32/blob/c435f99a88066029ec2dbd2d758c8cc9d051565b/main/audio/README.md). |
| Enable a YAML option and barge-in works | Pinned server direct-WebSocket audio bypasses its experimental MQTT-gateway spectral suppression. `features.aec` sets a flag; VAD/TTS abort still needs echo-clean capture and correct live listening. Multi-turn dialogue is not proof of double-talk interruption. See the audio gate's exact source paths. |
| OV3660 is universally broken, use only OV2640/OV5640 | [Issue1588](https://github.com/78/xiaozhi-esp32/issues/1588) is a closed older2.1.0/IDF5.5.1 report. [PR1695](https://github.com/78/xiaozhi-esp32/pull/1695) added OV3660/OV2640 support for another target. Test the delivered sensor and selected firmware; no global blacklist or guaranteed replacement. |
| Zero-latency cliff sensing, universal65mm threshold | A ranging sensor has finite acquisition time. [ST VL53L1X](https://www.st.com/resource/en/datasheet/vl53l1x.pdf) lists minimum20ms short-mode budget,33ms for all modes. Downward range is not horizontal clearance before a table edge. Derive the stop margin from actual geometry and measured sample age/coast. |
| Automatic300ms reverse is safe escape | Rear space may be unobserved or itself an edge. Keep four downward roles, separate front obstacle sensing, local stop/fault latch and deliberate human recovery. No blind retreat. |
| A20Hz low-priority pet task provides all safety | Separate expression/initiative from body timing and sensor interlocks. All motor paths, including emotes and social reactions, must pass the same bounded authorization and local stop. The draft's100%/5s motor primitives exceed this project's40%/250ms foundation. |
| ESP-NOW requires APSTA | Station or SoftAP can carry it. APSTA is not required. `channel=0` uses the local current channel; same router name/mesh does not prove every peer is on that channel. [Espressif ESP-NOW](https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/api-reference/network/esp_now.html). |
| ESP-NOW guarantees submillisecond/under5ms behavior | Delivery and application processing are not guaranteed. Queue callback work, check initialization/send errors and use measured latency, sequence/ACK/timeout semantics if delivery matters. Existing Mac digital peer coordination remains first. |
| RSSI−42/−45dBm means adjacent and supplies turn direction | RSSI is signal strength, not a measured distance or bearing. The draft gives no calibration/pose method. It cannot authorize approach, nuzzling, passing or collision avoidance. Optional visual badges need calibrated camera detection/pose confidence. |
| Provided swarm packet contains a conversation TTL | The packed struct is35bytes and contains no TTL, session, sequence or authenticated identity. Its fixed payload is not validated as terminated text on receive. Unauthenticated broadcasts cannot authorize movement/recovery. The two pasted `BroadcastEspNowState` declarations also have different signatures. These are snippets, not a complete firmware implementation. |
| MT3608 is a buck/boost for arbitrary battery wiring | [MT3608](https://www.olimex.com/Products/Breadboarding/BB-PWR-3608/resources/MT3608.pdf) is boost-only; [MP2636](https://www.monolithicpower.com/en/mp2636.html) is a single-cell charger/system boost IC. Neither makes a generic2S-to5V buck. Keep the regulated-bank plan. |
|60FPS full-screen OLED animations are automatic | A128×64 monochrome frame is1024bytes. At400kbit/s I²C, payload plus ACK bits alone take about23ms, before commands/addressing; a full-frame60FPS promise is unsupported. Partial updates can differ. Specify responsive blink/gaze, then measure refresh/audio coexistence. |

## New project leads: actual files and terms

| Reference checked | Finding / use |
| --- | --- |
| [Cozmars v2 CAD](https://github.com/r-cute/rcute-cozmars-model-v2/tree/515f980d4ee91f6a279406085f591b882254aad8) | Native Fusion/STEP exists; root README24bytes, no root LICENSE at this revision. [Creator hardware](https://github.com/r-cute/rcute-cozmars-server) uses PiZeroW/OV5647, three9gservos,3V30RPM N20s and L298N. No established stepper/closing-gripper drop-in. SDK MIT does not establish CAD permission. No bulky CAD copied. |
| [playfultechnology/esp32-eyes](https://github.com/playfultechnology/esp32-eyes/tree/2738dbfc1e9876d1e9d9cd04e36669f5b12e9a92) | Real procedural SSD1306 eyes. Root LICENSE says GPL3, but inherited [Face.cpp](https://github.com/playfultechnology/esp32-eyes/blob/2738dbfc1e9876d1e9d9cd04e36669f5b12e9a92/Face.cpp) headers say AGPL3-or-later. Preserve the mixed provenance; do not copy into MIT-only firmware or relabel the complete library as simply GPL3. Arduino/u8g2/hardcoded pins also need adaptation. |
| [Focus Bot](https://github.com/Rayan7717/Focus_Bot_Desktop_Pet_Based_on_esp32C3/tree/cee20a5f2dc945f2488e928906e611751ab305cd) | Actual emotional sketches; MIT badge but no complete license grant found. No usable CAD found. Behavior concepts only until permission is clear: simulated day/night, bond traits and touch reactions. No actual battery state inferred from a mood meter. |
| [Yumo Cat](https://github.com/yumobuilds/Yumo-Cat-Robot-Car-V1/tree/0664862644703bdb2e9117bfec2493eedd143830) | PolyForm Noncommercial1.0. Published STL directory contains only a micro-servo wheel and README, not a full cat enclosure. Four continuous servos, round TFT/two128×32OLEDs and remote are a different build. Useful interaction reference; no code/CAD copied. |
| [RIO, pinned `b911305e48ce6a1b75fe6c07fc02f86ad7bfeb0a`](https://github.com/mk14ray/RIO-XIAO-ESP32-S3-Gemini-Live-Voice-Assistant/tree/b911305e48ce6a1b75fe6c07fc02f86ad7bfeb0a) | Explicit MIT license. Actual Sense/PDM + MAX98357A + SSD1306 source calls Espressif AEC using delayed playback PCM and 24-to-16 kHz conversion; Live interruption requests a playback flush. Reuse as the active audio porting reference. The default delay needs calibration and shared reference-ring state/reset needs concurrency review. Its echo-gate fallback is a failed barge-in condition if it blocks human speech during playback. Camera support is on-demand stills, not streaming. No assembled-robot acoustic proof or body safety controller. |
| [Pipecat Gemini Live video example, pinned `c87446099f88560b861ac0e1c13cce331e3a5770`](https://github.com/pipecat-ai/pipecat/blob/c87446099f88560b861ac0e1c13cce331e3a5770/examples/realtime/realtime-gemini-live-video.py) | BSD-2-Clause source for a Mac/server pipeline with 1 frame/s camera/screen input and an initial greeting. It does not implement Sense capture/transport or microphone echo cancellation. [Google robotics streaming guidance](https://ai.google.dev/gemini-api/docs/robotics-streaming) supplies the latest-frame + periodic text-prompt pattern; frames alone do not initiate reasoning, and prompts can interrupt active generation. Reuse under a bounded idle/turn scheduler. |

## Adopted ideas, without the unverified guarantees

- Keep an event-driven pet state machine with local eyes, simulated rest/curiosity
  and occasional self-initiated speech. Face/emote events never imply motor permission.
- Require natural multi-turn conversation **and first-build ordinary-speech
  interruption**, with real acoustic tests, not only an AEC config bit.
- Keep explicit robot identities, bounded group conversations and digital peer
  events; allow cosmetic recognition badges later. ESP-NOW is optional, not needed
  to make five robots social and not a safety/localization substitute.
- Reuse RIO's software-reference/AEC implementation patterns on the purchased
  Sense first, then run the complete acoustic gate. Keep the optional Waveshare
  alternative unqualified until tested; no additional board purchase is required
  by this research update.
- Use sampled camera frames and bounded idle prompts for proactive observations.
  A camera demo or Live response setting alone does not supply navigation,
  gripping, safe movement or autonomous five-robot behavior. Keep local body
  interlocks independent of remote conversation and vision.

The user's reported Sense purchase is recorded separately from this guide's
claims; arrival and inspection remain open. No completed body sensing, successful
barge-in, sensor stops, pickups, automatic charging or five-robot navigation are
inferred. No hardware was purchased or flashed by this review. Cloud API costs
are separate from hardware and remain unquoted; no paid API was used. Current
build evidence is reported separately.
