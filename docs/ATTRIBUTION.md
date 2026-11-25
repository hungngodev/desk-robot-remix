# Source attribution and license boundaries

Upstream revisions are recorded in [upstream lock](../code/upstream-lock.json); copies stay in ignored
`code/upstream/`. New integration code uses this repository's MIT license. That does
not change the licenses of models, CAD, dependencies or copied upstream code.

| Source | Reuse | Terms and notices |
| --- | --- | --- |
| [VerdureBuddyRover](https://github.com/maker-community/VerdureBuddyRover) | UART command vocabulary, protocol/PWM approach; our controller adds bounded pulses, strict parsing, servo commands and watchdog | MIT, copyright 2026 创客社区（Hacker space）; full notice in `licenses/VerdureBuddyRover-MIT.txt` |
| [78/xiaozhi-esp32](https://github.com/78/xiaozhi-esp32) | CoreS3 board/audio/camera/display and server/MCP interfaces retained in separate variant | MIT, 2025 Shenzhen Xinzhi Future Technology Co., Ltd. and Project Contributors; `licenses/xiaozhi-esp32-MIT.txt` |
| [Espressif esp32-camera](https://github.com/espressif/esp32-camera) | MJPEG multipart framing and async streaming pattern adapted in the existing authenticated XIAO bridge; camera acquisition stays pinned Xiaozhi | Apache-2.0, Espressif Systems. Official [JPEG HTTP Stream example](https://github.com/espressif/esp32-camera/blob/master/README.md); no separate GStreamer/WebRTC/camera binary installed |
| [Verdure Xiaozhi fork](https://github.com/maker-community/xiaozhi-esp32/tree/verdure-buddy-rover) | Serial integration reference | Retains Xiaozhi MIT notice; source license preserved in its clone |
| [xinnan-tech/xiaozhi-esp32-server](https://github.com/xinnan-tech/xiaozhi-esp32-server) | ASR/LLM/TTS pipeline, device connections, Opus conversion/playback | MIT, 2025 xinnan-tech; `licenses/xiaozhi-esp32-server-MIT.txt` |
| [SMARS](https://www.thingiverse.com/thing:2662828) | Four original screwless chassis/wheel/track STLs and assembly documents, saved unchanged with source/hash register | tristomietitoredeituit; [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/) |
| [SMARS Gripper Arm](https://www.thingiverse.com/thing:4253681) | Three original arm/rack/pinion STLs saved unchanged, with source/hash register | bluino; [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) |
| [Forklift module for SMARS](https://www.thingiverse.com/thing:3027255) | Original lift E/F STLs and assembly PDF, linked by Bluino; saved unchanged with source/hash register | tristomietitoredeituit; [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/) |
| [EVA Robot case](https://www.thingiverse.com/thing:7319190/files) | Unmodified `cad/originals/eva-head/EVA-Robot.3mf` and its embedded preview; component/case layout reference | Ksirailway-Base; [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/); hash, source and dimensions in its `source.json` |

The EVA case, nine mechanism/chassis/wheel/track STLs and original assembly
documents are downloaded without modification. Record all future geometry changes. The
original lift pieces' terms remain separate from Bluino's three bundled pieces.
SMARS derivatives retain the noncommercial/share-alike
requirements; this project is a personal experimental build.

[EVA firmware/server](https://github.com/Ksirailway-base/EVA-Robot) was inspected
at commit `c7ff17718a40d071b352e9894506c264578120c0` as a hardware reference.
Its README declares MIT, but no complete license notice was found in that tree;
no EVA firmware/server code is copied here. The case's explicit CC BY-SA 4.0
grant is separate. The planned module head will reuse licensed Xiaozhi drivers.

Ultralytics/YOLO-World, Qwen3, SenseVoice and Kokoro weights are not redistributed
here. Their code/model licenses and attribution must be preserved when installed
or shared. Generated head build clones retain upstream license files. Do not
publish private configuration or credential-bearing binaries.

## Additional sources collected/reviewed 2026-11-03

- [Sparky v0.1.0](https://github.com/slahiri/sparky/releases/tag/v0.1.0),
  **Sparky by Siddhartha Lahiri**, [CC BY-SA4.0](cad/originals/sparky-head/LICENSE.md):
  unchanged release ZIP, five STLs and source config/license saved under
  `cad/originals/sparky-head/`. The shell is a rounded-head candidate; author
  explicitly labels the design unprinted/estimated. Concept views use it and
  the saved SMARS stepper chassis, with illustrative mechanisms, not print exports.
- [Tiny Engineer](https://github.com/jamro/tiny-engineer/tree/aefc852a894174604a1e350bf9bc04c04f28ec80/3d_models),
  **Krzysztof Jamroz**, hardware **CERN-OHL-S-2.0**: unchanged SG90 Head/Hat STL,
  license, scope and NOTICE saved under `cad/originals/tiny-engineer-head/`.
  Alternative reference only. Software MIT does not relicense this CAD; name/logo
  rights are not adopted. No Tiny Engineer firmware or character assets copied.
- [SMARS 28BYJ-48 remix #2778904](https://www.thingiverse.com/thing:2778904/files),
  unclejeff: two unmodified original STLs now saved in
  `cad/originals/smars-stepper/`, with source hashes. Page displays CC BY4.0;
  recorded original SMARS ancestor is NC-SA4.0. Preserve both attributions and
  resolve that difference before redistribution; no commercial grant inferred.
- [wtlx's sketches](https://github.com/wtlx/smars-28byj-48): no LICENSE found,
  code not copied. Links identify the existing mechanical variant.
- [FluxGarage/RoboEyes](https://github.com/FluxGarage/RoboEyes),
  [Tech Talkies face fork](https://github.com/TechTalkies/Xiaozhi-for-XiaoESP32S3)
  and [chillibasket WALL-E](https://github.com/chillibasket/walle-replica): GPL3;
  research/integration candidates only. No code/assets copied in this update.
  Any future incorporation must preserve source/notices and applicable terms;
  the project MIT file does not relicense these components.
- Qubit README's MIT claim has no matching top-level LICENSE at the checked
  revision; copying permission remains unresolved. Creator binaries, Patreon
  releases and public videos are not assumed open source.
- Dasai Mochi, Living.AI EMO and Disney droids are appearance/interaction
  references only; no proprietary face, sound, shell or character assets copied.

The research files contain original summaries and source links, not complete
video transcripts. See `docs/research/` for evidence and qualification limits.

FETCH by **SECTOR 07 / Austin Dutenhoeffer** is an added appearance and assembly
reference. [Creator's build article](https://projecthub.arduino.cc/sector_07/build-fetch-an-open-source-ai-robot-powered-by-arduino-uno-q-8092d1)
and [video](https://www.youtube.com/watch?v=51q_WmbnJtQ) were reviewed. Page metadata
assigns CC BY-NC 4.0 or later; no Fetch CAD, firmware, face graphics or voice
assets are copied here. [Research and archive audit](research/2026-11-03-fetch-appearance.md).

## Realtime conversation references — 2026-11-03

- [RIO XIAO ESP32-S3 Gemini Live assistant](https://github.com/mk14ray/RIO-XIAO-ESP32-S3-Gemini-Live-Voice-Assistant/tree/b911305e48ce6a1b75fe6c07fc02f86ad7bfeb0a),
  MIT, copyright 2026 Mritunjay Kumar Ray. The playback-reference ring and
  three-tap resampling pattern from pinned `aec.cpp` are adapted in
  [`sense_reference_codec.cc`](../code/firmware/head/sense/sense_reference_codec.cc),
  which retains the upstream MIT notice. The independent RIO AEC/NS/VAD engine,
  residual speech gate and Gemini transport are not incorporated. Xiaozhi's
  existing ESP-SR AFE remains the sole DSP owner. The ignored reference checkout
  is not an installed firmware dependency. [Inspected-file hashes](hardware/reuse-sources.json).
- [Google Gemini cookbook](https://github.com/google-gemini/cookbook) and
  [robotics streaming guidance](https://ai.google.dev/gemini-api/docs/robotics-streaming):
  source references for interruption handling and idle-frame observations. The
  Mac turn-state module is original code, not a copied Google SDK client.
- [Pipecat](https://github.com/pipecat-ai/pipecat), BSD-2-Clause, and its
  [ESP32 client](https://github.com/pipecat-ai/pipecat-esp32), MIT: inspected native
  audio/video integration alternatives, not installed or redistributed here.
- [LiveKit ESP32 client](https://github.com/livekit/client-sdk-esp32), Apache-2.0:
  inspected alternative only. Preserve actual dependency notices if adopted.


## What is actually reused, versus locally implemented (November 12 audit)

**PR creation mechanism:** GitHub connector edits files on branch `impl/mac-hardware-safety-preflight-2026-11-10`, creating commits within the same draft [PR #17](https://github.com/hungngodev/desk-robot-remix/pull/17). This does not automatically run, import or remix every linked GitHub project. An inspected paper, README, or repository is **not** a vendored implementation.

| Reference or dependency | Actual incorporation | Integration and audit boundary |
| --- | --- | --- |
| [Xiaozhi ESP32](https://github.com/78/xiaozhi-esp32) and [xinnan server](https://github.com/xinnan-tech/xiaozhi-esp32-server) | **Pinned external upstream with source overlays** for physical microphone, camera, LCD/OLED and Opus plus group speaker bridge | The shipped Sense and local server revisions must compile together; the Mac does not run a second microphone or fake human VAD source |
| [Pololu VL53L0X](https://github.com/pololu/vl53l0x-arduino) and ST VL53L0X API | **Pinned MIT library reused for initialization; bounded nonblocking register reads adapted for local guard** | Five critical physical guard lanes plus three optional lanes, generic GY-530 carriers not qualified until real 3.3V desk optical and loaded-stop trials |
| [Stackchan-agent](https://github.com/botamochi6277/stackchan-agent) | **Vendored pinned MIT HSM header** `code/firmware/head/overlay/stackchan_behavior.hpp` with license in source, adapted from [Behavior.hpp at bfb98fb8](https://github.com/botamochi6277/stackchan-agent/blob/bfb98fb8bdb4f8ecc4b7c1c4f9bc90ee5227e613/include/Behavior.hpp) | Owns OLED idle/expression decisions, not motors, voice transport or new runtime |
| [Reachy Mini conversation app](https://github.com/pollen-robotics/reachy_mini_conversation_app) | **Design reference only**, not Reachy code, SDK, daemon or joints | Inspired one owner, cheap initiative gate and expressive idles; do not claim the Reachy software was imported |
| [LiveKit Agents](https://github.com/livekit/agents) and [Frigate](https://github.com/blakeblackshear/frigate) | **Algorithmic reference only**, not vendored libraries | Adaptive VAD video cadence, cheap motion gate, priority capture and bounded per-robot RAM buffers are original Mac glue |
| [LlamaPIE paper](https://aclanthology.org/2025.findings-acl.710/), [ProAct](https://arxiv.org/abs/2602.14048) and [ProactiveBench](https://github.com/yellow-binary-tree/ProactiveBench) | **Research references only** | No trained initiative model or benchmark score has been claimed. Current policy uses explicit event evidence, freshness, silence and cooldown |
| [Seeed Studio PN532](https://github.com/Seeed-Studio/PN532/tree/e61296876c1c3e66ef67156562c71324b389f5fa/src) | **Protocol adaptation**, not a linked synchronous driver | `code/firmware/body/lib/AccessorySensors/Pn532Frames.h` and `AccessorySensors.cpp` encode validated frames, asynchronously poll a real separate I2C device and expose cloneable toy tokens only. The direct Seeed blocking wait loops were not copied into WROOM's cliff loop. Preserve [upstream BSD 3 Clause LICENSE.md](https://github.com/Seeed-Studio/PN532/blob/e61296876c1c3e66ef67156562c71324b389f5fa/LICENSE.md) attribution |
| Local `Conversation.run`, `PetController`, `MultimodalOrchestrator` | **Custom glue using already selected components** | Event-triggered two-pet conversation, peer provenance, shared speaker arbitration, priority JPEG, stale answer suppression and cancellation tests are original source in this project, not assertions of vendor integration |
| SMARS, gripper and third-party STL ancestors | **Retained mechanical reference assets under their own licenses** | CC noncommercial or share-alike restrictions remain. Never reinterpret license compatibility or dimensionally fitted assembly from filenames alone |

**Truth rule:** whenever the documentation says *reused*, specify **copied unchanged**, **pinned dependency**, **adapted protocol**, or **design reference**. A GitHub link, an API sketch, a committed mock test or a source-level C++ driver is not proof that the electrical carrier, body shell, voice acoustics, Pogo charger or printed assembly works. CI status is revision-specific: inspect the exact commit's workflow runs and job results. Historical runner failures or successful runs do not qualify a newer head.


## Startup batch distribution rights and accepted prototype source

**Commercial manufacturing is a separate release gate, even when the firmware is MIT.** The current printed robot uses original SMARS chassis/track/wheel and forklift geometry licensed **CC BY-NC-SA 4.0**. That license permits compliant noncommercial remixes, not ordinary commercial production or sale. The separate Bluino SMARS gripper files are reported CC BY 4.0 and can be commercially reused with attribution, but any dependency on NC-licensed geometry must still be assessed. The Sparky/EVA shells and every mixed assembly also retain their own file-specific licenses. The existence of a shared STL or a third-party site's “free download” is not a grant of commercial rights.

Primary license authority: https://creativecommons.org/licenses/by-nc-sa/4.0/ and https://creativecommons.org/faq/. The original SMARS author advertises separate 20-piece and 100-piece commercial manufacture licenses in the original SMARS listing description: https://www.thingiverse.com/thing:2662828 . Author's listed source reference offers, **not verified purchases or blanket approval of altered derivatives**: https://cults3d.com/en/3d-model/gadget/smars-v1-20pcs-license and https://cults3d.com/en/3d-model/gadget/smars-v1-100pcs-license . The separately authored forklift source and any adaptation rights require independent review, not an assumption that the chassis permission covers them.

**Two product paths without deleting requested features:**

1. Keep the presently pinned SMARS/28BYJ48/Fusion sources for **noncommercial functional prototypes**, subject to the actual license terms and purpose of use. Build one complete robot and validate geometry and drive/force/acoustic/charging safety before duplicating hardware. Do not claim a particular startup's internal prototype use is automatically exempt; the CC NonCommercial test depends on the purpose, not the owner's legal form.
2. For **commercial batches**, obtain written authorization covering exact chassis, tracks, stepper remixes and forklift mechanical derivatives with sufficient units, distribution channels, attribution and modifications; alternatively replace ONLY the affected printed chassis/lift source with an independently licensed permissive commercial design after dimension, motor, track and gripper fit validation. Do not relabel an NC derivative as MIT/CC BY simply because a third-party remix page does.

**Release evidence needed:** source file inventory and hashes, each original creator, license URL or signed permission, scope/unit count and expiration, derived-part attribution, permission to reproduce/modify/ship prints, and a design release approved against the finished CAD. No production BOM order or commercial-ready indicator should be marked verified until rights and the independent electrical/mechanical safety qualification are recorded. This is engineering license triage, not a legal opinion.
