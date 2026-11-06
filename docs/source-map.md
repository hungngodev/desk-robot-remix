# Source-to-feature register

Updated 2026-11-04. Canonical index of supplied projects/videos, their intended
contribution, and the actual reuse boundary. This is a source map, not a claim
that all components have been integrated. The product requirements remain in
[product-definition.md](product-definition.md); detailed prior evidence stays in
[the video audit](research/2026-11-03-video-audit.md),
[guide audit](research/2026-11-03-guide-audit.md), and
[case audit](research/2026-11-03-rounded-cases.md).

## Requirements that govern reuse

Five identical, inexpensive robots with different removable cosmetics; Fetch
retro-TV plus Cozmo/Vector styling; a screen, camera, natural multi-turn voice
with ordinary-speech interruption in robot one; initiative without a user prompt;
exploration until paused; local edge stops; pickup of flat keys/wrapped candy;
individual identities/memory and peer interaction. Local Mac first; no new Pi,
Pico or Uno required. Prefer existing models and small CAD changes. Reuse owned
hardware when it helps; do not force a substantially different mechanism solely
to consume existing stock. Touch and motion awareness were explicitly added on
2026-11-04. Hardware/physical acceptance and source review are separate states.

## All twelve supplied videos

Descriptions/resources and selected code were reviewed; this does not mean all
videos were watched fully. Canonical links below follow the saved source audit.

| Source | Contribution and use | Boundary |
| --- | --- | --- |
| [Huy Vector tiny WALL-E](https://www.youtube.com/watch?v=5MZ6O6yT73M), [build guide](https://www.huyvector.org/robots-kinetic/wall-e-ai) | Sense camera/mic, compact audio/screen packaging and expressive tracked silhouette | Guide/binary is not established reusable source for all firmware; brass structure is not our printed chassis |
| [Kênh Sáng Tạo copper robot](https://www.youtube.com/watch?v=aLbg-b4UZb0), [guide](https://ai.kenhsangtao.com/copper/) | Small OLED/audio packaging and interaction reference | Different S3/pins; a compatible peripheral list is not our complete build |
| [Copper robot ToF follow-up](https://www.youtube.com/watch?v=R1E3AkfSaIM) | Short-range downward VL6180 sensing and calibration idea | One front sensor does not cover rear/pivots; no universal 82/65 mm threshold |
| [Tech Talkies desk tank](https://www.youtube.com/watch?v=umeCiPdUtFo), [112 code/prints](https://github.com/TechTalkies/YouTube/tree/main/112_Desk_tank) | Compact drive assembly, drawings and communication timeout reference | Its AUTO path is not a complete obstacle/cliff-aware navigation controller |
| [Mo-Chan part 3](https://www.youtube.com/watch?v=2JRqNyq6Epk), [creator download](https://drive.google.com/file/d/11oFudRz5YSWumYO1XBSqezHFnrLxhGMc/view) | Small-face proportions, RoboEyes and idle timing | Download availability does not establish copying terms; not our motor controller |
| [Digit by Naz Louis](https://www.youtube.com/watch?v=vf1qYoM40aQ), [creator hub](https://www.patreon.com/cw/NazLouisYT) | Separate reflex and deliberation layers; camera-driven tasks and character timing | Complete public firmware/claimed sensor internals were not established |
| [Tech Talkies custom-face buddy](https://www.youtube.com/watch?v=aDaSp6zaqWM), [source](https://github.com/TechTalkies/Xiaozhi-for-XiaoESP32S3) | Listening/thinking/speaking expression mapping | GPL-3.0; bare XIAO I2S target is not Sense PDM/camera pin-compatible |
| [Tech Talkies buddy V2](https://www.youtube.com/watch?v=i05wihSkuD8) | Motor stall/low-speed torque lesson; test real loaded motion | Description says beta/V2 source not public then; no ready working base inferred |
| [SARAS 2](https://www.youtube.com/watch?v=zrvFgxxDrIU), [source](https://github.com/techwithanant/saras_ai_robot_v2) | MCP tools over a motor-controller boundary and observation/action feedback | Public starter does not include the full demonstrated robot firmware/sensing |
| [SARAS 1](https://www.youtube.com/watch?v=IT1uBUsOmUY), [creator-linked source](https://github.com/asharma2040/saras-ai-robot) | Power distribution and drive-friction lessons | Capacitors do not establish sufficient supply; larger Pi/TT platform is not selected |
| [Qubit](https://www.youtube.com/watch?v=MQBUOHRvMuc), [code](https://github.com/0xaiwhisperer/qubit), [prints](https://makerworld.com/en/models/2448809-qubit-the-desk-robot) | Recorded/calibrated choreography and coordinated expression | Larger dual-arm layout is not adopted; copying terms unresolved in inspected tree |
| [Tech Talkies wheeled buddy](https://www.youtube.com/watch?v=ktWnwJ-e-_w), [95 source](https://github.com/TechTalkies/YouTube/tree/main/95_Chatbot_on_wheels), [prints](https://www.printables.com/model/1631670-companion-robot-with-wheels) | ROAM/PET/ATTN activity states, touch interruption and face timing | Different motors/display; inspected behavior does not supply our cliff interlock |

## Supplied mechanical and electronics projects

| Source/family | How it contributes | Status/boundary |
| --- | --- | --- |
| [Original SMARS #2662828](https://www.thingiverse.com/thing:2662828), [28BYJ remix #2778904](https://www.thingiverse.com/thing:2778904), [stepper build reference](https://github.com/wtlx/smars-28byj-48) | Existing drive chassis matched to owned steppers | Originals saved. Combined fit/print QA pending; NC-SA ancestor versus remix license provenance recorded |
| [Bluino gripper #4253681](https://www.thingiverse.com/thing:4253681), [forklift #3027255](https://www.thingiverse.com/thing:3027255) | Two-servo lift + closing grip | Originals saved; MG90S pocket/horn/ground reach and stepper-base attachment unqualified |
| [Cozmars V1 #4657644](https://www.thingiverse.com/thing:4657644), [V2 #4910801](https://www.thingiverse.com/thing:4910801), [editable V2 CAD](https://github.com/r-cute/rcute-cozmars-model-v2) | Closest supplied Cozmo packaging, native Fusion/STEP, head/track/lift proportions | CAD reviewed; source copying terms need resolution. Pi/N20/three-servo mechanism is not a small swap to owned steppers/closing claw |
| [Cozmars V3 hardware](https://github.com/hyansuper/cozmars_v3_hardware), [head examples](https://github.com/hyansuper/cozmars), [body firmware](https://github.com/hyansuper/cozmars-sub), [#7144853](https://www.thingiverse.com/thing:7144853) | Primary head/packaging comparison; actual STLs, PCB files, assembly resources and MJPEG example | Inspected Nov4. Hardware TAPR OHL; firmware MIT. Custom PCBs/audio/display; body link is I2C, not UART. Head README calls firmware unfinished |
| [BillMerryman Cozmars](https://github.com/BillMerryman/Cozmars), [Emax mods #5924280](https://www.thingiverse.com/thing:5924280), [cube #4657653](https://www.thingiverse.com/thing:4657653) | Wire clearances, servo-pocket/retention ideas and optional standardized game object | Inspected repo has Pi code, not those STLs, no root license found; separate model page access unresolved. Cube is supplementary, not a replacement for keys/candy |
| SMARS rover #5028894 (supplied ID; platform not established), [forklift #1041777](https://www.printables.com/model/1041777), [claw #2840100](https://www.thingiverse.com/thing:2840100), Otto/SMARS hybrid #231568 (platform not established) and camera/display racks | Alternative existing mounts if the selected attachment fails | Leads, not verified interchangeable interfaces; verify exact files/terms before using |
| [robonine parallel gripper](https://github.com/roboninecom/3D-Printed-Parallel-Gripper-for-Robotics-Arms) | Existing alternate jaw mechanism | Lead only; size/actuation/terms not yet qualified; avoid new arm redesign |
| [ESP SparkBot](https://github.com/espressif2022/esp_sparkbot) | Integrated tracked camera/audio hardware reference | Different platform; no whole-stack substitution selected |
| [VerdureLab](https://github.com/maker-community/VerdureLab), [Gitee mirror](https://gitee.com/maker-community/VerdureLab), [EMO #1899485](https://makerworld.com/en/models/1899485), [duck #1625071](https://makerworld.com/en/models/1625071) | Existing expressive shells, accessories and Otto packaging | File-level Sense/tracked-base fit not established; do not claim drop-in shells |
| [StackChan ecosystem](https://github.com/m5stack/StackChan), [print lead #1884272](https://www.printables.com/model/1884272) | Expressive timing, face/person response and head/accessory reference | Its powered pan/tilt is not our fixed-head/two-claw-servo allocation |
| [chillibasket WALL-E](https://github.com/chillibasket/walle-replica) | Interruptible animation queue and expressive pauses | GPL-3.0; larger seven-servo mechanics/12 V hardware not adopted |
| Keyestudio [S3-CAM guide](https://docs.keyestudio.com/projects/KS5028/en/latest/s3cam.html), DFRobot S3 AI Cam, Hiwonder/XiaoR/ThinkRobotics vision-node leads | Alternative camera packaging/wiring references | Not required for purchased Sense. Monocular detections do not establish metric 3D coordinates |
| Espressif [usb_stream](https://github.com/espressif/esp-iot-solution/tree/master/components/usb/usb_stream) | Alternative USB-UVC input route | Not selected; would change peripherals/pins/power. Pasted throughput/coexistence guarantees are unqualified |

## Supplied firmware, behavior and research ideas

| Source | How it contributes | Boundary |
| --- | --- | --- |
| [Xiaozhi](https://github.com/78/xiaozhi-esp32), its S3-CAM / Otto / ESP-Hi / ATK targets | Reuse existing camera/audio/display drivers, AFE/MCP/tool and choreography patterns | Current Sense target compiles; correct reference audio and live integration still required; board targets are not interchangeable |
| [Python server](https://github.com/xinnan-tech/xiaozhi-esp32-server), [Java alternative](https://github.com/joey-zhou/xiaozhi-esp32-server-java), [Go alternative](https://github.com/AnimeAIChat/xiaozhi-server-go), [py-xiaozhi](https://github.com/huangjunsen0406/py-xiaozhi) | Existing protocol/persona/provider work, or alternate implementations | Python foundation exists. Alternatives are not all deeply audited or concurrent dependencies; no claimed 100-bot benchmark transferred to this build |
| [Verdure UART/MCP bridge](https://github.com/maker-community/VerdureBuddyRover/blob/main/docs/xiaozhi-mcp-serial-integration.md) | Existing head/body control boundary | Architectural reference; preserve our bounded stepper/fault controller |
| [Project Emily](https://github.com/broml/Project_Emily) | Multi-controller camera/body architecture lead | Actual topology/reuse must be checked before adopting the pasted description |
| [RoboEyes](https://github.com/FluxGarage/RoboEyes), [esp32-eyes](https://github.com/playfultechnology/esp32-eyes) | Procedural blink, gaze, mood and smooth expression | RoboEyes GPL-3.0 candidate; esp32-eyes has mixed GPL/AGPL provenance. Choose one face adapter rather than both |
| [Focus Bot](https://github.com/Rayan7717/Focus_Bot_Desktop_Pet_Based_on_esp32C3) | Touch patterns, tilt/shake/stillness event vocabulary, simulated mood | Real code inspected; root license missing. Drop enum is not a working drop detector; uptime modulo24 is not real local time |
| [Yumo Cat](https://github.com/yumobuilds/Yumo-Cat-Robot-Car-V1) | Debounced touch, wake/sleep and synchronized reaction ideas | PolyForm Noncommercial; different continuous-servo/screen arrangement, no complete cat enclosure in inspected STL directory |
| [PyCozmo](https://github.com/zayfod/pycozmo), Cozmo Unleashed/acidzebra lead | World/event/face and commercial-robot behavior references | Cozmo-specific hardware control is not our firmware; exact Unleashed source/portability must be established |
| [ESP-SR](https://github.com/espressif/esp-sr), [ESP-WHO](https://github.com/espressif/esp-who), [ESP-DL](https://github.com/espressif/esp-dl) | AFE/wake processing and optional embedded perception | AFE inspected; WHO/DL are not already integrated or established as Digit internals |
| [SO-ARM100](https://github.com/TheRobotStudio/SO-ARM100), [arm print profile](https://makerworld.com/en/models/1287622-lerobot-so-arm-100-control-arm), [LeIsaac](https://github.com/LightwheelAI/leisaac), [LW-BenchHub](https://github.com/LightwheelAI/lw_benchhub), [laundrobot](https://github.com/0xaiwhisperer/laundrobot) | Demonstration/replay and learned-manipulation research | Different arms/training; not dependencies for the two-servo claw |
| [Reachy Mini](https://github.com/pollen-robotics/reachy_mini), [conversation app](https://github.com/pollen-robotics/reachy_mini_conversation_app) | Local idle policy, speech/listening arbitration, memory/tool structure and coordinated expression | Actual app code inspected. Replace hardware actions; camera tool alone is not proactive perception |
| [Open Duck](https://github.com/apirrone/Open_Duck_Mini/tree/v2), [runtime](https://github.com/apirrone/Open_Duck_Mini_Runtime), [Pollen Microduck](https://github.com/pollen-robotics/microduck), [NVIDIA article](https://developer.nvidia.com/blog/using-ai-agents-to-teach-robots-like-microduck-to-walk-in-simulation/) | Gaze/gesture timing and locomotion/navigation/activity separation | Inspected Open Duck walk is gamepad-directed. Microduck docs distinguish prior behavior concepts from unfinished current integration; no biped runtime port |
| [Project Astra](https://deepmind.google/models/project-astra/), [Gemini Live](https://ai.google.dev/gemini-api/docs/live-guide) | User-confirmed experience target: contextual, interruptible multimodal interaction and initiative | Astra capability description is not a downloadable complete robot engine. Gemini is optional cloud; local Mac remains default |
| [Cozmo SDK](https://github.com/anki/cozmo-python-sdk), [Vector architecture](https://support.anki.bot/article/567-vector-subsystems), [EMO](https://living.ai/emo/), [Dasai Mochi](https://dasai.com.au/pages/mochi3), ROLA/EBO references | Ongoing activity, mood/world state, synchronized face/sound/motion, removable costumes | Commercial feature/appearance references, not open copies of their internal personality engines |
| [FETCH](https://projecthub.arduino.cc/sector_07/build-fetch-an-open-source-ai-robot-powered-by-arduino-uno-q-8092d1), [video](https://www.youtube.com/watch?v=51q_WmbnJtQ) | Retro-TV bezel/side panels, accessible assembly and original styling direction | Source archive inspected; UNO Q/larger motors/arms differ; not our whole case |

## Additional sources found during the work

These are additions, not a substitute inventory of the user's sources.

| Source | Concrete reuse proposal | Status |
| --- | --- | --- |
| [RIO Sense](https://github.com/mk14ray/RIO-XIAO-ESP32-S3-Gemini-Live-Voice-Assistant/tree/b911305e48ce6a1b75fe6c07fc02f86ad7bfeb0a) | Software playback reference, calibration and abort patterns for exact Sense hardware | MIT; saved/pinned; not yet ported. Its still capture and echo-gate fallback are not the final streaming/barge-in design |
| [Google robotics agent](https://github.com/google-gemini/robotics-samples/tree/c51cbab6e6efffff8738ecf9ce41ba85034d9654/live-api/agent) | Actual camera poller/difference/stability, latest-frame buffer, typed event bus and guarded heartbeat | Inspected/pinned. Reuse components through device/provider adapters; Google model client is not a local-model client |
| [HF speech-to-speech](https://github.com/huggingface/speech-to-speech/tree/99f03f5f91b7fe148a7494a0a1de3539ca42c503), [VLM guide](https://github.com/huggingface/speech-to-speech/blob/99f03f5f91b7fe148a7494a0a1de3539ca42c503/src/speech_to_speech/LLM/README.md) | Candidate local Apple-Silicon voice/vision backend, streaming/cancellation and image input | Apache-2.0; inspected, not installed/integrated. Enable actual VLM mode; default text configuration is not camera understanding |
| [Stackchan-agent](https://github.com/botamochi6277/stackchan-agent/tree/bfb98fb8bdb4f8ecc4b7c1c4f9bc90ee5227e613) | Tested hardware-independent behavior controller, touch/person/sound events and adaptive sound monitor | MIT; inspected, not yet imported. Map head poses to eyes/sounds; no extra neck servo implied |
| [Pipecat video example](https://github.com/pipecat-ai/pipecat/blob/c87446099f88560b861ac0e1c13cce331e3a5770/examples/realtime/realtime-gemini-live-video.py), [LiveKit ESP32](https://github.com/livekit/client-sdk-esp32) | Alternate realtime transport/cancellation patterns | Not extra simultaneous turn owners; use only if selected transport needs them |
| [Sparky v0.1.0](https://github.com/slahiri/sparky/releases/tag/v0.1.0), [Tiny Engineer](https://github.com/jamro/tiny-engineer), [EVA #7319190](https://www.thingiverse.com/thing:7319190) | Existing head alternatives and small inserts/mounts | Saved candidates; Sparky explicitly unprinted. Compare Cozmars head packaging before treating Sparky as final |
| [Waveshare CAM fallback](https://www.waveshare.com/esp32-s3-cam-ov5640.htm) | Optional audio-reference hardware route | Not a required replacement for the purchased Sense; not physically qualified |

## Reuse-heavy architecture revision to validate

- Preserve Sense/Xiaozhi peripheral work and the WROOM stepper/fault boundary.
- Evaluate HF speech-to-speech as the one local voice/vision engine, replacing
  the need to construct a new STT/TTS streaming engine. Retain existing control,
  identity and fleet code through an adapter; do not run two competing voice loops.
- Adapt Google's actual observation/event/heartbeat components; adapt
  Stackchan-agent's low-level reaction policy and Reachy's activity/arbitration
  patterns. Desk-specific attention, held-state fusion, pickup and fleet adapters
  remain our integration. No percentage of reuse or SOTA ranking is claimed.
- Use Cozmars as the first styling/head-packaging comparison, SMARS for owned
  stepper mounting and Bluino/SMARS for closing grip. A whole Cozmars drivetrain
  adoption is a different mechanism decision, not a cosmetic mount change.
- Compare candidates using recorded person/object/gesture/pickup/interruption/
  peer scenarios: correct events, false initiations, latency, cancellation and
  resource use. A modern model name or demo is not that benchmark.

## Provenance and continuing notes

The four supplied pasted briefs are the research inputs titled 'You don't need
to write a single line...', 'Open-Source ESP32 AI Companion Robots...', the
expanded twelve-video request, and 'Engineering an Autonomous Open-Source AI
Desk Pet in 2026...'. Keep claims from those drafts separate from primary code.
The dual-ESP32 pasted blueprint and specific GitHub issues are also research
leads; the [guide audit](research/2026-11-03-guide-audit.md) records why its pin
maps, sensor placeholders, power advice and timing guarantees are not a recipe.
The earlier [USB keyboard project](https://github.com/KoStard/ESP32S3-USB-Keyboard-To-BLE)
is a separate historical objective, not a robot dependency.
