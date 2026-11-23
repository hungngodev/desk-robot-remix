# Small-component head — paid Sense, inspection pending

Updated 2026-11-23 from the original 2026-11-06 fit study. Reuse the reported
**0.96-inch SSD1306 OLED** after inspecting the actual board and glass. Compare
[Cozmars packaging](../product-definition.md) first for the accepted rounded
retro-TV head; the saved [Sparky v0.1.0](../cad/originals/sparky-head/README.md)
remains an unprinted fallback fit study, not a fitted head. EVA is historical.

One **XIAO ESP32S3 Sense camera/microphone bundle** is confirmed **$13.67 paid**
by a seller order and independent payment receipt on November 3, 2026. The
carrier reported delivery on November 7, but the actual board, camera, PDM
microphone, included accessories, revision and condition remain **uninspected**.
The older **$18.87** displayed listing was not the paid amount, and the earlier
**$21.11 head subtotal** combined historical listing prices before shipping,
tax, mounts, power and the rest of the robot. Neither is a qualified current
checkout total. Consult the [canonical first-unit builder and buying route](one-complete-robot.md)
and the [paid receipt reconciliation](../hardware/bom.json).
Keep the Sense for voice and continuous video. The selected digital playback
uses one MAX98357A I²S amplifier and a separately qualified speaker; the
photographed HiLetgo PAM8403 is an analog spare, not a direct I²S substitute.
See the [parts list](../hardware/parts.md) and historical
[supplier comparison](../research/2026-11-03-head-budget.md).
Inspect the complete actual Sense kit before making mounts or audio connections.

## Reuse drivers, change the board configuration

The [official Sense guide](https://wiki.seeedstudio.com/xiao_esp32s3_getting_started/)
specifies 8 MB flash / 8 MB PSRAM and a PDM microphone. Current stock may contain
OV3660 or OV5640 AF; verify actual delivered sensor, cable and lens housing. The
camera/microphone stack is about 21 × 17.8 × 15 mm. No new INMP441 is required.

The proposed head reuses pinned Xiaozhi camera, SSD1306, PDM input and I²S output
components. A **separate Sense board target**, pin map and 8 MB partition/asset configuration
are now implemented and compiled. See [actual pins/build](../../code/firmware/head/sense/README.md)
and [verification](firmware-foundation.md). The existing modular build is Freenove 16 MB + SH1106 +
INMP441 I²S; it cannot be flashed to Sense. CoreS3 and WROOM binaries are also
incompatible. The Sense build passes; no physical Sense test has happened.

**Ordinary-speech interruption is required in the first build.** The early
Sense baseline lacked playback reference/AEC; the current pinned
`SenseReferenceCodec` is now integrated and supplies microphone and
playback-reference PCM to the selected ESP-IDF AFE source path. That is software
integration, **not** evidence of fitted-speaker AEC alignment, audible stopping,
or preservation of a human's first words. The exact board, enclosure and
firmware must still pass the [physical audio acceptance](audio-barge-in.md)
at both speaking distances. Reuse the documented
[RIO exact-Sense AEC and cancellation work](../research/2026-11-03-sense-realtime-reuse.md)
and [Sense AEC port procedure](sense-aec-port.md); RIO's speaker pins differ
from ours and its Arduino code is not a drop-in ESP-IDF binary. RIO captured
requested stills, whereas the current Sense uses consented continuous
authenticated MJPEG, with Mac frame selection and stale-frame rejection
described below. Google's and Pipecat's session designs remain research
references, not evidence of a second active voice stack. An echo gate that
mutes the microphone during playback cannot pass the interruption requirement.

Implemented, physically unqualified header budget: OLED2 + amplifier3 + UART2 = seven signals, with
camera/PDM internally connected. The allocation was checked against official documentation and compiled; it is
not physically qualified. OLED5/6, amplifier4/7/8 and UART2/1 preserve nativeUSB,
camera/PDM and PSRAM pins. SD is disabled and CS21 held high; leave its slot empty. Do not copy video GPIO1/2
sensor wiring or the old Freenove UART pin numbers blindly. The body owns all
cliff sensors; the head owns OLED, so no shared two-master bus is required.

The new Sense app is 2,503,664 bytes and passes the 0x2f0000-byte OTA-slot check;
assets fit at 0x600000 in the 8 MB layout. The earlier Freenove merged image is
not a Sense image; never truncate or substitute it. Firmware installation/private/build scripts now accept `--board sense`, using
a separate ignored `xiaozhi-sense` copy.
[Implementation milestone](../plans/2026-11-03-active-desk-pet.md#milestone-4--sense-head-and-original-face).

## Face and interaction

The OLED is monochrome, not a color LCD. The selected Sense firmware
already integrates the **MIT-licensed Stackchan-agent hierarchical behavior
machine**, pinned at `bfb98fb8bdb4f8ecc4b7c1c4f9bc90ee5227e613`,
into `overlay/stackchan_behavior.hpp` and the existing local
`DeskRobotSenseBoard::FaceTask`. Preserve its source license notice.
It handles blink, gaze, listening/speaking transitions, idle/rest and
bounded contextual face cues. Its motion suggestions are **never** sent
to the WROOM motor or gripper. The Mac may request cosmetic mood cues,
but cannot override deterministic body safety; body faults display a
local safety status and neutral face before ordinary idle expressions.
[RoboEyes](https://github.com/FluxGarage/RoboEyes) and the Tech Talkies
face fork remain **GPL-3.0 research options, not integrated dependencies**.
Do not copy their code into this MIT source without a separate license review.

Only the existing local face task owns OLED updates. The WROOM status poll
uses a separate task so an interrupted UART read cannot stall blink timing,
Xiaozhi audio or emergency STOP. The OLED remains available during
continuous listening as well as idle; status and mood owners are separate.
The selected inexpensive generic AT42QT1010 head-touch input needs actual
through-case placement and bounce tests. Reuse any genuinely owned compatible
sensor rather than ordering a new Adafruit module. Head patting does not
locate the user or navigate back to them.

The consented camera is **one authenticated continuous MJPEG producer** on
`/api/camera.mjpg`, not a recurring snapshot request. The Mac
`HttpHead.stream_frames()` verifies each JPEG's per-robot boot, sequence
and device capture-completion receipt and selects the newest frame in
coalesced network reads. It rejects same-boot backlog when
the relative Mac arrival interval exceeds the device capture-completion
interval by more than 500 ms, about two ordinary 4 FPS frame periods.
Delayed frames are not relabeled as fresh simply because the network
reader woke up later. This is a
**relative backlog check**, not clock synchronization or proof of image
exposure latency. Mac and ESP32 clocks cannot be compared absolutely.
A real A9 trial still needs measured camera-to-Mac latency, object freshness,
concurrent voice and consent/offline recovery. A physical camera bench can no
longer pass through legacy snapshot polling. With explicit video consent,
run this read-only test against the actual provisioned head, with its motors
disconnected or safely on a stand:

```sh
cd code
uv run --no-sync python scripts/bench_head_camera.py \
  --config config/local.toml --robot robot-01 --seconds 60 \
  --stream --score-motion --require-audio-activity \
  --report data/private/head_camera_trial.json
```

For this **combined audio and camera** run, begin a consented Xiaozhi
microphone session and ordinary audible speaker test during the camera window.
The additional flag requires microphone and digital speaker reference activity
while MJPEG and WROOM status are being sampled. Without it, the CLI remains a
streaming-only camera and telemetry diagnostic rather than a simultaneous
audio/video trial. The report measures persistent stream interarrival, device
capture-completion deltas, concurrent WROOM status and matched Mac-clock AEC
counter progress. One post-run audio status snapshot does not prove simultaneous
activity; the bench now polls the actual existing audio diagnostics in parallel. It does **not** qualify
true optical exposure timing, image interpretation, gripper reach, audible
playback, motor safety or A9 physical behavior. No motor command or still
snapshot is sent by this bench command.

## Existing case and small changes

The [Sparky v0.1.0 original shell](../cad/originals/sparky-head/README.md) is saved
unchanged under CC BY-SA 4.0, about 56 ×52 ×54mm with rounded corners. The author
explicitly says this release is not test-printed and component sizes are estimates.
Do not mix its STL with v0.2 dimensions. Only the shell is shown in the
[layout study](../cad/concepts/2026-11-03-rounded/README.md); tracks/mechanism/mounts
are illustrative and the bank is not fitted.

The source 1.3-inch window needs an insert for the owned 0.96-inch OLED. Measure
actual PCB/glass and lens position. Expected small remixes: a replaceable
bezel, Sense/camera spacer or wedge, microphone opening, speaker retention and
removable rover bracket. The original LED hole is not proof of camera fit.
Shell retention must be priced; do not adopt the source's raw-LiPo power system
or silently require its full magnet set. EVA's 74mm axis is depth when its 48mm
face points forward; its boxy appearance was declined.
Keep lens, mic, speaker, USB and antenna clear; check full arm sweep and bank
weight/stability. If the combination needs a new shell/chassis, revisit the
choice rather than silently enlarging scope. Do not cut display glass or PCB.

Keep camera pose fixed relative to jaws for calibration. Check actual MG90S
pockets/horns and the stepper chassis lift interface before final head mounting.
No manufacturing geometry edit or physical fit has passed. Fusion tools are exposed for future precision work; verify the live connection
and active design before touching geometry.

## Power/audio and staged bring-up

- Logic stays 3.3 V. Verify amplifier variant/pins and supply per its documentation.
  Speaker connects **SPK+ to SPK−**, neither output to GND. The selected
  Challenge CS20-02P110-04-1X is an **8 Ω, 2 W** rectangular speaker
  candidate, not the superseded 1 W round speaker. Limit output to its
  measured installed acoustic/thermal rating and check enclosure port,
  MAX98357A gain, distortion and cavity fit.
- Use the final **qualified matched rechargeable 1S cell, charger/protection and regulated 5V distribution system**, with separately rated actuator branches. An unidentified owned power bank may only be used for isolated bench testing after verifying its output; it is not the selected permanent power architecture. Do not route
  motor current through head/body regulators or laptop USB.
- On USB with motors absent, verify screen, fresh camera capture, PDM recording,
  speaker/listening transition and head identity before joining UART TX/RX/GND.
- Only after hardware and local body interlock tests should the head command
  bounded motion. Mac handles speech/LLM/vision; no Uno/Pico/Pi needed.

## Preserved historical reference

`firmware/head/modular/` and [build.md](build.md) retain the previously compiled
Freenove N16R8 map: OLED38/39, INMP44142/41/40, amplifier14/21/47, UART2/1;
camera uses Freenove's stock signals, SCCB I²C0 and OLED I²C1. These are **not
Sense wiring instructions**. Native USB, octal PSRAM reservations and exact
module wiring remain board-specific. Preserve the historical build rather than
renaming it Sense or treating its successful compilation as new hardware proof.
