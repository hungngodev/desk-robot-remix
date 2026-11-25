> **November 16 current source correction:** The selected cheap sensor is VL53L0X GY-530 with pinned Pololu vl53l0x-arduino v1.3.1 in full WROOM safety firmware. Older dated audits discussing VL53L4CD below are historical and do NOT authorize a premium sensor purchase. CAP1188 firmware now probes the common 0x29 and strapped 0x28 addresses only behind verified mux isolation. A project cited in this source map is a design reference unless docs/ATTRIBUTION.md and actual code show a copied/installed dependency. OOMWOO is still in hardware development and not a completed docking module to install.**

# Source-to-feature register

Updated 2026-11-04. Canonical index of supplied projects/videos, their intended
contribution, and the actual reuse boundary. This is a source map, not a claim
that all components have been integrated. The product requirements remain in
[product-definition.md](product-definition.md); detailed prior evidence stays in
[the video audit](research/2026-11-03-video-audit.md),
[guide audit](research/2026-11-03-guide-audit.md), and
[case audit](research/2026-11-03-rounded-cases.md).

**Complete research preservation:** The [day-zero reuse shortlist](research/2026-11-03-active-pet-sources.md) gives inspected implementation files and compatible integration boundaries. The [200-entry feature register](#original-html-feature-and-sensor-idea-register) records original and historic sensor, game, personality and robotics ideas; [all 131 unique external links from the original 41-section HTML](#complete-original-html-research-link-index) are preserved without claiming every destination was verified. The [linear integration plan](PLAN.md) keeps these visible before buying or printing. Existing source reviews below are retained, not superseded by a small shortlist.

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
| [Xiaozhi](https://github.com/78/xiaozhi-esp32), its S3-CAM / Otto / ESP-Hi / ATK targets | Reuse existing camera/audio/display drivers, AFE/MCP/tool and choreography patterns | Device pin `c435f99a88066029ec2dbd2d758c8cc9d051565b` in `code/upstream-lock.json`; current Sense target compiles; correct reference audio and live integration still required; board targets are not interchangeable |
| [Python server](https://github.com/xinnan-tech/xiaozhi-esp32-server), [Java alternative](https://github.com/joey-zhou/xiaozhi-esp32-server-java), [Go alternative](https://github.com/AnimeAIChat/xiaozhi-server-go), [py-xiaozhi](https://github.com/huangjunsen0406/py-xiaozhi) | Existing protocol/persona/provider work, or alternate implementations | Python foundation pin `d9c2e8c5d92627b670dec57d72a07a4226a410a3` in `code/upstream-lock.json`. Alternatives are not all deeply audited or concurrent dependencies; no claimed 100-bot benchmark transferred to this build |
| [Verdure UART/MCP bridge](https://github.com/maker-community/VerdureBuddyRover/blob/main/docs/xiaozhi-mcp-serial-integration.md) | Existing head/body control boundary | Architectural reference; preserve our bounded stepper/fault controller |
| [Project Emily](https://github.com/broml/Project_Emily) | Multi-controller camera/body architecture lead | Actual topology/reuse must be checked before adopting the pasted description |
| [RoboEyes](https://github.com/FluxGarage/RoboEyes), [esp32-eyes](https://github.com/playfultechnology/esp32-eyes) | Historical procedural blink, gaze, mood and expression references | RoboEyes GPL-3.0 and esp32-eyes mixed GPL/AGPL code remain research only; the selected Sense face instead uses the MIT Stackchan HSM and an original Xiaozhi LVGL overlay |
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
| [Stackchan-agent](https://github.com/botamochi6277/stackchan-agent/tree/bfb98fb8bdb4f8ecc4b7c1c4f9bc90ee5227e613) | Tested hardware-independent behavior controller, touch/person/sound events and adaptive sound monitor | MIT behavior HSM is vendored in `code/firmware/head/overlay/stackchan_behavior.hpp`; the actual Sense `FaceTask` maps its `Action.motion` to a local eye gesture, never a head servo or WROOM motor action. Real OLED expression acceptance remains open |
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


---

## Original HTML feature and sensor idea register

*Original research references, not approved purchases or completed installations.*


**Purpose:** Prevent any behavioral, sensor, accessory, game or research idea from vanishing when the robot is integrated. All 23 HTML sections and their named idea families are represented. This is an inventory of requirements and *research candidates*, **not a claim that every module is owned, electrically compatible, purchased, implemented or physically tested**. Details, citations and original URLs remain in the original 1.1MB HTML and [source map](source-map.md); see [reuse register](research/2026-11-03-active-pet-sources.md), [system contract](product-definition.md) and [all detailed original HTML quantitative research proposals](research/2026-11-03-active-pet-sources.md).

**Status interpretation:** `REQUIRED` is a user-visible hard goal that may not be deferred out of the final product. `RESERVE NOW` means leave physical/software extension accommodation before assembling, not that the module must be purchased. `EXPANSION` means fully recorded, with a planned adapter/test but separate cost/fit approval. `REFERENCE` means concept only. `REJECTED FOR SAFETY` cannot be implemented as described. `EVALUATE` is an upstream or tuning candidate awaiting independent proof. Hybrid statuses reflect a required *behavior* with an optional *sensor implementation*. The $50 hard cap and small body make all listed experimental physical modules simultaneously installed an unproven, almost certainly incompatible configuration; see [decision gate](decision-log.md).

## A. Current HTML project and topic sections with repo requirements

| ID | Idea or requirement | Design status | Day-zero reservation, constraint, or proof required |
| --- | --- | --- | --- |
| `F001` | Complete robot form | REQUIRED | One low tracked 28BYJ SMARS core, fixed expressive Sense head, front two-servo closing lift/gripper, five independent copies with different costumes |
| `F002` | Architecture and original parts | REQUIRED | Body WROOM local safety, Sense camera/mic/OLED/speaker, Mac central AI; count actually owned parts |
| `F003` | Seven stages vs day-zero architecture | REQUIRED | The seven original build tasks remain, but all interfaces/holes/requirements are locked before Stage 1 physical work |
| `F004` | Source and historical status honesty | REQUIRED | Do not call compiled firmware, mock robot or draft HTML a tested build |
| `F005` | Delivered budget | REQUIRED | Full $50 cap including reported Sense purchase; cannot accept unpriced extras or silently swap to unsafe cheap power |
| `F006` | MAX30102 paw heart pad | RESERVE NOW | HTML claims about five purple units; verify actual stock and breakout rails; WROOM bus not Sense PDM41/42; user opt-in and nonmedical |
| `F007` | IP5306 architecture A power | BENCH CANDIDATE | Exact board revision, rated output, 1S chemistry/protection, cell and charger; no assumption that chip limit equals module limit |
| `F008` | Power sequencing S1–S8 and low-voltage ladder | REQUIRED DESIGN | Load priority, stepper/servo starts, sag response, cutoff/restart and explicit safe payload behavior measured under system load |
| `F009` | Bulk and local decoupling | REQUIRED DESIGN | Capacitance values from measurement, short power leads, fuse/connector/wire ratings; not a replacement for sufficient supply |
| `F010` | Stepper phases/ramp and gear truth | REQUIRED | Measured phase order, ratio/travel/backlash, speed/acceleration/coils-off modes; current code effective 160 steps/s |
| `F011` | Servo bank 30-minute grading and grades A–X | REQUIRED METHOD | Count and inspect nominal MG90S, measure range, stall/heat/fit/grip; reject failed units before mounted prints |
| `F012` | Gripper fork as scoop; bow on keys, candy wrappers | REQUIRED | Existing Bluino/SMARS lift + 2 positional servos, key/candy strategies, real 8/10 each trials |
| `F013` | Gripper current signatures and sensing ladder | RESERVE NOW | Optional INA219 shunt, contact switch, FSR, camera verification, stall/force readouts; do not call current signature proven grip |
| `F014` | Eight VL53L0X ToFs on TCA9548A 0x70 | REQUIRED | Four downward corners, one forward guard and three read-only side/rear directions; GY-530 carrier and measured stop geometry still unqualified |
| `F015` | Continuous ToF polling and 40ms proposed scan | MEASURE | Bounded mux selection/status/timestamp, quality and freshness; no unmeasured 40ms guarantee |
| `F016` | Cliff classifier and fail-closed behavior | REQUIRED | No blind reverse, sensor degradation drive or auto-resume, local USB recovery only and operator arming |
| `F017` | Owned head touch + boot calibration | REQUIRED | AT42QT1010 through shell, tap/hold patterns, false activation, touch during motion pauses |
| `F018` | Six-axis motion and handling (MPU6050 preferred, BerryIMU spare) | REQUIRED | Detect real MPU6050 via register 0x75 and six raw axes; tilt, shake, suspected pickup still require mounted calibration, floor fusion and motor vibration rejection |
| `F019` | Optional force/vibration/magnet handling | RESERVE NOW | FSR402, piezo, Hall/reed, SW-18010P and pet/belly accessory interfaces; no assumed stock |
| `F020` | Audio RIO AEC and actual user barge-in | REQUIRED | Software reference calibration, double-talk; 19/20 audible stop ≤500ms and 18/20 new request; echo only 10min zero false |
| `F021` | Erle/latency report targets | MEASURE | HTML's 15–25dB ERLE and 18/20 700ms rates are not accepted proof; record measured metrics without weakening canonical A2 |
| `F022` | Flushing network, Mac queue, ESP DMA | REQUIRED | Epoch/generation IDs, FLUSH through transport and DMA, no obsolete sentence resumed after reconnect |
| `F023` | RoboEyes face choice and 0.96in fit | SOURCE IMPLEMENTED; A1 PHYSICAL HOLD | Selected MIT Stackchan HSM plus original `code/firmware/head/overlay/face_eye_animator.hpp` and `face_eye_display.hpp` now consume `Action.motion` in the real Sense `FaceTask` and draw bounded blink/gaze through Xiaozhi's LVGL display lock; upstream `OledDisplay` retains speaking/listening/status ownership. GPLv3 RoboEyes was not copied. Source/firmware tests do not verify the actual 128×64 overlay alignment, all 20 expressions, or the five-minute Mac-offline OLED and zero-motion trial. A1 and G001 remain open until measured |
| `F024` | Cozmars/Sparky/Fetch style and packaging | REQUIRED DESIGN | Round retro TV + Cozmo/Vector, owned OLED, removable cosmetics, no extra head servo silently |
| `F025` | Three Mac processes, Motion Gateway separation | ARCHITECTURE CANDIDATE | Structural model privilege boundary required; exact number of processes measured, not dogma |
| `F026` | Shared MLX Whisper turbo and circuit breaker | EVALUATE | Proposed Apple Silicon shared model, priority class, fallback to whisper.cpp; never assume measured fleet performance |
| `F027` | Kokoro 82M, voices and sentence streaming | REQUIRED CAPABILITY | Five distinct voices, streaming, first chunk latency under actual Mac contention; fallback provider behind same interface |
| `F028` | Mac LLM/VLM selection and two call shapes | REQUIRED | Fast textual turn and image-grounded scene turn; local-first; vision on fresh event, not each frame |
| `F029` | Speaker lease, event clustering, Mac efuse IDs | REQUIRED + CANDIDATE | Single speaker; dedup five observations; manual IDs currently real, MAC efuse provisioning optional qualified future |
| `F030` | Per-robot memory single writer | REQUIRED | Private persistence, provenance, identity isolation, peer hearsay, corruption and restart tests |
| `F031` | Pipecat workers, MQTT Mosquitto, UDP/WS | EVALUATE | Do not stack simultaneous owners or require new broker without proven benefit; prefer existing server and adapters |
| `F032` | Proactive pushed camera events | REQUIRED | Fresh scene events without a spoken prompt, dedup, semantic confirmation, conditional new speech, camera/mic simultaneity |
| `F033` | Utility activity scorer and personality drives | REQUIRED | Mac deterministic activity owner; hard stop/quiet/speech priorities, small LLM intent only, curiosity/boredom/rest/social |
| `F034` | Ambient sound events and one RGB pixel | RESERVE NOW | Double clap attention, triple clap stop, whistle bands, self-sound filtering, no acoustic event may arm |
| `F035` | Fleet play and ongoing peers | REQUIRED | Distinct persistent characters, digital peer exchange, invitations, ten turns, social play, one speaker initially |
| `F036` | AprilTag localization and world anchors | REQUIRED FIRST-UNIT ANCHORING, PHYSICAL HOLD; generalized localization EXPANSION | First unit requires calibrated AprilTag fiducial family/ID/size/placement, fresh JPEG/pose bracketing, and bounded map->odom anchoring per [docs/product-definition.md](product-definition.md), [Guide 50](plans/spatial-first-unit/50-map-and-spatial-memory.md), [Guide 60](plans/spatial-first-unit/60-object-recall-and-navigation.md), and [Guide 90](plans/spatial-first-unit/90-integration-and-release-evidence.md) (9/10 re-anchors within 20 mm, 8/10 remembered-target returns); broader multi-room generalized localization remains optional EXPANSION |
| `F037` | Self-docking and OOMWOO patterns | REQUIRED FIRST PET AND DOCK, PHYSICAL HOLD; historically EXPANSION | Accepted subsequent complete first-pet requirement supersedes original expansion timing. One passive and electrically qualified dock per pet; OOMWOO remains a design reference, not reused production hardware. Real contact isolation, predock visuals, measured net charge and safety release still pending |
| `F038` | Health freshness ladder | REQUIRED | Treat stale sensor data as fault; health from timestamps, successful reads and model confidence, not a plausible old value |
| `F039` | Research links landing pages and tutorials | PRESERVE | All HTML library sections cross-reference the source map and reuse register; reject conclusions not supported by code |

## B. Proactive experience, conversation, perception, memory and peer play

| ID | Idea or requirement | Design status | Day-zero reservation, constraint, or proof required |
| --- | --- | --- | --- |
| `B001` | Camera noticed person/hand/object independently | REQUIRED | Fresh event without button, prompt or user speech |
| `B002` | Scene change and actual semantic interpretation | REQUIRED | VLM reasons from evidence; label uncertainty and reject stale frame |
| `B003` | Repeated scene suppression and cooldown | REQUIRED | Dedup semantic/fingerprint at robot and fleet levels, enforce speech lease |
| `B004` | Contextually initiated speech | REQUIRED | Comments about a newly observed and relevant event; no generic scheduled greetings as substitute |
| `B005` | Routine independent activity | REQUIRED | Curiosity, inspecting, attention, social invitations, rest and silent stillness as selectable activities |
| `B006` | Periodic activity reconsideration | REQUIRED | Configurable 30–90s initial heuristic; vetoes and false trigger tests |
| `B007` | Group speech cooldown | REQUIRED | Initial at most 1 unsolicited group spoken initiation per 120s |
| `B008` | Live natural speech barge-in and double talk | REQUIRED | People speak over TTS; output flush and correctly captured first words |
| `B009` | No false self hearing | REQUIRED | 10min speech-only validation, motor/ambient noise, playback reference |
| `B010` | Speech-first ownership and quiet mode | REQUIRED | Quiet cancels pending spontaneous output, pauses movement; reply to user allowed |
| `B011` | Individual character, voice and memory | REQUIRED | Five distinct IDs/personas and remembered experiences with direct-vs-peer provenance |
| `B012` | Long-term memories and preference evolution | REQUIRED | Explicit user preferences, recent events, bounded private durable history, no invented facts |
| `B013` | Peer conversations and social games | REQUIRED | Digitally routed events, one audible voice, one movement source initially, coalescing |
| `B014` | Spontaneous peer invitations | REQUIRED | Occasional respectful invitations with distinct moods and turn limits |
| `B015` | Ongoing exploration until paused | REQUIRED | Operator-enabled continuing session, no timed reauthorization after 120/300s; bounded pulse + watchdog |
| `B016` | Person and object reactions via eyes | REQUIRED | Animated gaze toward evidence without needing to talk |
| `B017` | Touch/hold/petting reaction | REQUIRED | Head touch, handling fused, no touch gesture grants motor |
| `B018` | Music and ambient sound awareness | RESERVE NOW | Existing mic plus AEC/noise gate; no additional microphone necessary until directionality requirement |
| `B019` | Contextual observation heartbeat | REQUIRED | Send only fresh image when idle, not during user/model/tool session |
| `B020` | Activity cancellation and memory of interruption | REQUIRED | Generation/epoch cleanup, old completion cannot mark new session idle |
| `B021` | Emotion Lab simulator mapping | REFERENCE ONLY | Use its ideas for moods but do not copy old cliff retreat or fake spatial hearing |
| `B022` | Big Five to PAD affect; WASABI boredom spring | EVALUATE | Proposed personality math from HTML; values are simulated character policy, not measured feelings |
| `B023` | Self-perception confirmation loops | EXPANSION | Check generated beep/vibration with mic/IMU if source quality supports, not physical health diagnosis |
| `B024` | Camera attention motion centroids and stability | REUSE CANDIDATE | From Xiaozhi Desk Robot and Google's camera poller; correct self-motion artifacts |
| `B025` | Object pickup verification | REQUIRED | Vision + physical calibrated choreography; 8/10 real keys and candy separately |
| `B026` | Push-notification speech scheduling | REQUIRED | Events wait when speaker busy, not unsolicited mid-turn collision |
| `B027` | Optional cloud reasoning | OPTIONAL | Opt-in separate keys and cost telemetry; Mac local-first remains default |
| `B028` | Desk-connected contextual input | EXPANSION | User consent: PC activity, coding-agent state, calendar/reminders, weather, MCP tools; don't spy on workstation |
| `B029` | Social continuity and games spanning days | EXPANSION | Persistent pet stories, desk RPG and cross-robot evolving game state with bounded memory |
| `B030` | Independent reaction when Mac offline | REQUIRED | Local face/busy/fault responsiveness; never pretend offline LLM is running |

## C. Sensor ideas explicitly named in the research library

| ID | Idea or requirement | Design status | Day-zero reservation, constraint, or proof required |
| --- | --- | --- | --- |
| `S001` | Four downward VL53L0X GY-530 (historically VL6180X) | REQUIRED ROLE | Obsolete VL6180X is not selected; qualify exact GY-530 carrier and four-corner geometry before motion or bulk purchase |
| `S002` | VL53L0X forward | REQUIRED | Separate obstacle view; 0x29 on mux, no all-side coverage |
| `S003` | VL53L1X alternative | COMPARISON | Different near-range constraints; not universal fix |
| `S004` | VL53L4CD short-range replacement | REJECT PREMIUM PURCHASE | Former alternative only; user selected generic VL53L0X; do not order or resurrect the expensive carrier |
| `S005` | TCA9548A I2C switch | REQUIRED | 0x70 channels 0–3 floor, 4 forward, 5–7 read-only left/right/rear; eight isolated 0x29 devices, separate 0x71 accessories; no two-sensor XSHUT substitution |
| `S006` | TCRT5000 reflectance | ALTERNATIVE EXPERIMENT | ~millimeter height, surface sensitive; no movement authority and no two-sensor replacement for the selected four-corner ToF |
| `S007` | Pololu QTR reflectance | ALTERNATIVE EXPERIMENT | Low-mounted calibrated floor alternative, not automatic replacement |
| `S008` | AT42QT1010 cap touch | REQUIRED | Owned breakout; body GPIO34; check shield/touch through case |
| `S009` | Copper tape capacitive petting | REFERENCE | Use only with known capacitance electronics and ESD handling |
| `S010` | TTP223 touch | ALTERNATIVE | No new purchase if owned AT42QT1010 meets requirement |
| `S011` | MPR121 twelve-zone touch | EXPANSION | I2C 0x5A; zone harness, touch case, code and power budget |
| `S012` | FSR402 force strip | EXPANSION | Force/belly/grip event, analog ADC front end and calibration; not precision force control |
| `S013` | Piezo knock sensor | EXPANSION | Knock recognition; analog protection and motor vibration suppression |
| `S014` | SW-18010P vibration switch | VERIFY STOCK | HTML claims 2, repo has no confident model count; digital contact and debounce |
| `S015` | BerryIMU older multi-sensor | OPTIONAL ALTERNATIVE | Photographed likely V1, actual chip/addresses/rails unverified; retain driver for spare only |
| `S016` | MPU6050 IMU | ACTIVE REQUIRED SENSOR | User says MPU6050 is in use; firmware uses official 0x75 ID and 0x3B 14-byte six-axis read, no proven physical handling calibration |
| `S017` | LSM6DS3TR-C six-axis IMU | CONDITIONAL | Replacement only after owned BerryIMU test fails |
| `S018` | GY-61 accelerometer | OPTIONAL STOCK | Cannot replace gyro-assisted handling fusion by itself |
| `S019` | QMC5883L magnetometer | EXPANSION | Yaw/reference demo, not track odometry |
| `S020` | AS5600 magnetic angle | EXPANSION | Magnetic knob/pose feedback; mount/magnet and bus conflict check |
| `S021` | Hall sensor + magnets/reed switch | EXPANSION | Hats, food, board games, proximity flags; no fabricated precise localization |
| `S022` | RC522 RFID reader | EXPANSION | Identified magnetic accessories/game tokens; SPI interface and power budget |
| `S023` | PN532 NFC | EXPANSION | Alternative token identity, explicit bus and range test |
| `S024` | MAX30102 pulse sensor | OPT-IN EXPANSION | Breakout/logic rails, WROOM I2C not Sense mic, nonmedical heartbeat petting |
| `S025` | BLE heart rate strap | OPT-IN EXPANSION | External opt-in data rather than onboard inference |
| `S026` | MR60BHA1 breathing radar | EXPANSION | Human-aware radar, consent, UART/power and vendor driver |
| `S027` | LD2410 mmWave presence | ACTIVE REQUIRED SHARED STATION ROLE, PHYSICAL HOLD | Selected for the one shared room station as presence-only evidence; 5V supply, 3.3V UART, carrier identity, placement and live power measurements remain unqualified; never person identity or movement authority |
| `S028` | AM312 mini PIR | OPTIONAL STOCK | Human movement detection; no location or reliable stationary detection |
| `S029` | WiFi CSI presence | RESEARCH | Radio firmware/calibration, no guaranteed person distance or direction |
| `S030` | APDS9960 gesture/proximity/color/light | EXPANSION | I2C 0x39; different job from floor ToF and BerryIMU |
| `S031` | BH1750 ambient light | EXPANSION | Existing lighting ideas; I2C 0x23/0x5c chosen address |
| `S032` | TCS34725 dedicated RGB color | EXPANSION | Alternative to APDS color channel |
| `S033` | AS7341 spectral sensor | RESEARCH | Spectral/colour play; bus/device power qualification |
| `S034` | LTR390 UV/light | RESEARCH | UV/ambient story, not an uncalibrated health/UV safety instrument |
| `S035` | Four quadrant light seeker | EXPANSION | Four optical pickups + extra channels and mount; no head servo allocated |
| `S036` | BME280 temperature/humidity/pressure | EXPANSION | I2C 0x76/0x77 check vs BerryIMU pressure sensor |
| `S037` | BMP280 pressure only | OPTIONAL STOCK | Photographed owned; not humidity, not motion |
| `S038` | SHT4x/SHT41 fog the glass | EXPANSION | I2C 0x44 typical, mounted breath aperture, humidity response/condensation protection |
| `S039` | DS18B20 waterproof probe | EXPANSION | Tea Buddy/aquarium, isolated sealed waterproof probe and electrical safety |
| `S040` | MLX90614 noncontact temperature | EXPANSION | Thermal reading at distance, no health diagnosis |
| `S041` | MLX90640 thermal camera | RESEARCH | Power/processing budget and privacy; thermal silhouettes not identities |
| `S042` | AMG8833 Grid-EYE thermal array | CONDITIONAL SHARED STATION OPTION, NOT SELECTED | Remains visible for later opt-in thermal play, but is excluded from the core first-robot and default fleet checkout until explicitly selected and physically qualified |
| `S043` | SCD40 real CO2 | ACTIVE REQUIRED SHARED STATION ROLE, PHYSICAL HOLD | Selected for the one shared room station; exact carrier, airflow, warm-up, power and comparison readings remain unqualified; CO2 is not inferred from a VOC sensor |
| `S044` | SGP30 VOC | EXPANSION | Air-quality game, baseline/calibration and ventilation |
| `S045` | BME688 gas/environment | ACTIVE REQUIRED SHARED STATION ROLE, PHYSICAL HOLD | Selected for the one shared room station; exact carrier, heater load, ventilation and baseline remain unqualified; raw gas resistance is not VOC ppm or a medical/food-safety diagnosis |
| `S046` | ENS160 air quality | EXPANSION | Alternative gas sensor, offset and humidity compensation |
| `S047` | PM2.5 SPS30/PMS5003 | RESEARCH | Bulky fan/air path, power/noise conflict with mini enclosure |
| `S048` | MAX9814 analog mic | OWNED SPARE | Not a speaker amplifier; Sense already includes PDM mic |
| `S049` | Sound event classifier on existing mic | REQUIRED CAPABILITY / OPTIONAL SOUNDS | Post-AEC, clap/whistle/speech/noise events and false positives; no directional inference |
| `S050` | Second mic for direction | EXPANSION | Requires phase/mic geometry, pins/audio reference; one PDM mic cannot localize voice |
| `S051` | Acoustic sonar with speaker/mic | RESEARCH | Echo/range precision not assumed; conflicts with own TTS and acoustic ecology |
| `S052` | VL53L5CX multizone ToF | RESEARCH | More processing/power; not simple replacement for floor coverage |
| `S053` | HuskyLens AI camera | RESEARCH | Duplicate camera hardware unless measurable benefit; price/power/fit |
| `S054` | INA219 current monitor | EXPANSION | Battery/servo sensing; calibrated shunt, rails, rates, not direct force |
| `S055` | HX711 load cell | EXPANSION | Mountable scale/stress game; actual strain gauge required |
| `S056` | GSR / EDA | SENSITIVE OPT-IN | Contact measurement consent/electrical isolation; no mental state diagnosis |
| `S057` | Conductive stretch cord | RESEARCH | Tail/belly position sensing, ADC and repeatability |
| `S058` | IR break-beam pair | EXPANSION | Coin-slot mouth/feed game, aperture and false beam handling |
| `S059` | IR reflective obstacle | OWNED SPARE | Not a replacement for physically qualified cliff ToFs |
| `S060` | VS1838B IR receiver | EXPANSION | Remote game/commands, no bypass of operator motion permissions |
| `S061` | Spill/wet feet detection | RESEARCH | Safe nonmains contact circuit and corrosion, battery water safety |
| `S062` | Capacitive soil moisture | ACTIVE REQUIRED SHARED STATION ROLE, PHYSICAL HOLD | One separate shared room station soil probe is in room_pod.modules and the complete shopping ledger; ROOM_SOIL_FITTED=0 leaves optional source sampling disabled until actual soil probe carrier, isolation, weather sealing, current and calibration are qualified. It is not a sensor installed on every pet |
| `S063` | AS3935 lightning | RESEARCH | Ambient environmental demo; no safety guarantee |
| `S064` | 433MHz RXB6 receiver | SENSITIVE OPT-IN | Legal and privacy concerns, no covert device interception |
| `S065` | Loose mains ghost sense antenna | REJECTED FOR SAFETY | Do not add unprotected mains-coupled antenna or expose accidental voltage |
| `S066` | Geiger counter module | RESEARCH WITH SAFETY REVIEW | High-voltage modules may exist; no unreviewed onboard radioactive/high-voltage experiment |
| `S067` | Weather pod/window sensor | EXPANSION | Explicit remote optional enclosure, not required core footprint |
| `S068` | Coin slot mouth | EXPANSION | Physical break-beam game and separate object geometry, not substitution for key/candy grip |
| `S069` | Magnetic Tic-Tac-Toe Hall grid | EXPANSION | Many inputs or scanned matrix, removable game board |
| `S070` | Four-direction sound/LED system | RESEARCH | Needs more sources/sensors, not a single mic's bearing |
| `S071` | Self-test beep, battery, touch and floor | REQUIRED OBSERVABILITY | Health from measured freshness, faults and explicit source |
| `S072` | Bluetooth phone presence | OPT-IN VIRTUAL SENSE | Signal strength not exact proximity/bearing; user consent |
| `S073` | MCP desktop app activity | OPT-IN VIRTUAL SENSE | AI agent/coding session, reminders and weather with explicit scope and privacy |
| `S074` | ESP-NOW satellite sensors | RESEARCH | Not required for Mac group; radio channel/messaging/security must be qualified |
| `S075` | Environmental audio/music tempo | EXPANSION | Use same mic and speaker processing without extra hardware; do not play copyrighted tracks |

### Reserved sensor compatibility and privacy boundaries

The original sensor register is a reservation ledger, not a firmware enable list.
For every S019–S075 idea, preserve the distinction between selected hardware,
an electrically qualified acquisition path, consent to collect, consent to
expose context, and consent to retain or share it. A qualification flag alone
is not a privacy switch. Never silently promote research or alternative parts
into either canonical shopping list.

| IDs | Compatibility and activation boundary |
| --- | --- |
| S019–S021 | Magnetometer, angle and magnetic contact sources need measured field geometry and isolated bus/address checks; no unqualified yaw, odometry, identity or movement authority. Preserve selected AS5600/reed functions. |
| S022–S023 | RC522 is an alternative, not another default purchase alongside PN532. PN532 on 0x71 lane 5 must preserve the mandatory MCP23017 dock monitor and bounded bus service. Restrict use to explicitly selected toy tokens; never credentials or access control. |
| S024–S026 | Optical paw, BLE heart-rate strap and breathing radar require separate affirmative consent before collecting human physiological signals; keep nonmedical and local, no identity, diagnosis, passive retention or peer fanout. MAX30102 interaction qualification is not an acquisition lock. |
| S027–S029 | Preserve the selected LD2410C shared station role with explicit source and context consent. Optional PIR and Wi-Fi CSI require consent and privacy review; no person identification or exact room position from echoes or movement. |
| S030–S035 | APDS9960 gesture, ambient light, color, spectral, UV and quadrant experiments require measured optical geometry, current and I2C addresses. No new servo, human inference or safety substitution; separate consent for any human-directed optical monitoring. |
| S036–S038 | Climate alternatives must not duplicate the selected SHT41/BMP280 or shared BME688. Preserve units, CRC/identity checks, calibration and enclosure airflow; no health, weather or altitude claim from unqualified data. |
| S039–S042 | DS18B20 liquid probe requires verified sealing and safe isolated low-voltage construction; no immersion of the robot or unattended hot-liquid claims. MLX90614 object-temperature and MLX90640/AMG8833 thermal imaging are not default purchases. Human-directed temperature or thermal collection requires separate explicit consent, no identity/health inference, and no raw thermal-frame retention or sharing. AMG8833 remains deferred. |
| S043–S047 | Preserve selected SCD40 and BME688 shared station roles. SGP30/ENS160 are alternatives, SPS30/PMS5003 remain research pending fan, airflow, noise and power budgets. No air-safety or calibrated pollutant claim without the appropriate calibrated measurement. |
| S048–S053 | Preserve the existing Sense PDM/audio/camera pipeline. Analog spare, additional microphone, acoustic sonar, multizone ToF and second AI camera are not default substitutions; audio/video acquisition and derived human monitoring need appropriate consent. No single-mic bearing or replacement of independent cliff sensing. |
| S054–S058 | Current monitor, HX711/load cell, EDA, stretch cord and break-beam need source-specific electrical/mechanical calibration. HX711 is an object-scale experiment, not a replacement for qualified jaw feedback. Human-contact EDA is sensitive opt-in only with reviewed electrical isolation and no stress or mental-state inference. |
| S059–S063 | Reflective IR, remote IR, wet-contact, soil and lightning experiments cannot grant motion or safety authority. Preserve the separately selected room soil role; keep unfitted ADC disabled. Liquid/contact experiments require protected low-voltage construction. |
| S064–S066 | 433 MHz receiving is sensitive opt-in only for explicitly authorized devices, not covert interception. S065 loose mains sensing remains rejected, not a configurable option. Geiger modules remain research pending specialist electrical/radiation safety review; no unreviewed high-voltage or radioactive experiment. |
| S067–S071 | Remote weather pod, feed slot, magnetic grid and directional sound/LED research require separate fit/power/pin and measurement gates. Preserve mandatory self-test observability and the original grip, safety and audio paths. |
| S072–S075 | Bluetooth RSSI presence and desktop MCP activity require explicit scoped consent; no raw device identity tracking, precise bearing or covert monitoring. ESP-NOW is research pending provenance and link validation. Tempo extraction uses the existing consented audio path; no raw recording or peer sharing by default. |

Source audit at `ccb0d248cc16e62f5aa479902689573ab328bd74` (DRX-491; source evidence, not a test receipt):

* `code/laptop/src/desk_robot/config.py` uses strict extra-field rejection.
  Paw, NFC, ambient, BMP280 and gesture interaction qualification defaults
  are false; room-station source enable and context consent are also false.
  These settings must not be described as global hardware privacy locks.
* `code/firmware/body/src/main.cpp` initializes and polls MAX30102 in the
  full-sensor path even when the Mac paw interaction flag is false.
  `BodyControl.cpp` serializes raw optical and NFC diagnostics in aux.
  `pet.py` gates paw/NFC interaction events but its selected sensory context
  can still expose an NFC event count without the interaction flag.
  Keep sensitive experiments physically disconnected unless specifically
  authorized for a controlled session; a future acquisition/privacy gate
  must also cover diagnostics, model context, retention and revocation.
* `code/firmware/room_station/src/main.cpp` runs AMG8833 recovery and
  thermal sampling when a module responds, despite its deferred purchase
  disposition. The existing `ROOM_SOIL_FITTED=0` pattern is a precedent
  for an explicit fitted/acquisition gate; thermal remains physically
  disconnected pending an equivalent gate and separate thermal consent.
  Station-wide context consent alone does not establish thermal-specific
  consent. Preserve independent climate/radar/soil telemetry and the
  no-motion station architecture when adding such a gate.
* Negative acceptance cases still required: connected sensitive hardware
  with consent absent; consent withdrawal while a sample is in flight;
  old samples after regrant; direct diagnostics and model-context reads;
  attempted persistent or peer retention; unknown experimental config
  keys; and prohibited S065 even with other experiment flags enabled.
  Verify the real acquisition and exposure boundaries, not merely the
  presence of a false default or a source-string assertion.

No new sensor, acquisition authority, hardware qualification, purchase
approval or runtime privacy implementation is established by this register.

## D. Pet toys, personality modes, games and cosmetic additions

| ID | Idea or requirement | Design status | Day-zero reservation, constraint, or proof required |
| --- | --- | --- | --- |
| `G001` | Blink, gaze, 20-expression face and sleepy rest | REQUIRED | OLED face engine; responsive offline eyes and context changes |
| `G002` | Emotion Lab and sensor-to-emotion simulator | REFERENCE | Retain playful mapping, reject unsafe blind retreat and false directional hearing |
| `G003` | Tamagotchi decaying needs | EXPANSION SOFTWARE | Simulated drives with user opt-out/quiet priority |
| `G004` | Memory and spontaneous callbacks | REQUIRED | Truthful per-robot experiences remembered across sessions |
| `G005` | Dreams and next-day storytelling | EXPANSION SOFTWARE | Clearly fictional dreams vs real observed event |
| `G006` | Evolving invented language | EXPANSION SOFTWARE | Peer game with opt-in, never obscure stop commands |
| `G007` | One speaker, six voices/characters | EXPANSION SOFTWARE | Style/personality demo, distinct robot identity remains canonical |
| `G008` | Secret life and Easter eggs | EXPANSION SOFTWARE | Quiet, consent and nonintrusive schedule |
| `G009` | Desk RPG over weeks | EXPANSION SOFTWARE | Saved game state and bounded peer/user turns |
| `G010` | Pomodoro focus buddy, alarm and clock | EXPANSION SOFTWARE | Opt-in timers and true Mac wall time, reminders |
| `G011` | Home Assistant and MCP household control | OPT-IN EXPANSION | Tool credentials isolated; no unsafe robotic arm authority |
| `G012` | PC assistant / desktop activity pet | OPT-IN EXPANSION | User-selected AI job/coding status, clear privacy |
| `G013` | Claude Desktop Buddy / HachimoDock / Tokpet patterns | RESEARCH | Agent task state mapped to emotions without scraping private work |
| `G014` | Music sync, dance and choreography | EXPANSION SOFTWARE | Recorded safe clips, servo/stepper envelope and permission |
| `G015` | Teach-a-move / pose-to-teach | EXPANSION HARDWARE | Need servo positional feedback or external encoder; don't infer from PWM target |
| `G016` | RPS game, mimic/peekaboo, speed tap | EXPANSION SOFTWARE | Camera/touch confidence and cooldown |
| `G017` | Magnetic snacks and cube games | EXPANSION HARDWARE | Hall/NFC/physical tokens, not a replacement for keys/candy acceptance |
| `G018` | Magnetic hats changing personality | RESERVE NOW | Costume clips and optional reed/Hall identity sensor |
| `G019` | Wagging tail and moving ears | EXPANSION | Need extra actuator, pin, current and mounting; initial two servos are lift and grip |
| `G020` | Pet purr/sound effects | EXPANSION SOFTWARE | Short original/public-domain sounds, speaker arbitration and quiet mode |
| `G021` | Diffused glowing chest heart | RESERVE NOW | One RGB pixel or LED, voltage/logic/standby and notifications |
| `G022` | Squeezable belly | EXPANSION | FSR or contact sensor with printed belly insert |
| `G023` | Twistable nose dial | EXPANSION | AS5600/magnetic encoder or potentiometer, accessible case |
| `G024` | Wobbly antenna | RESERVE NOW | Static safe removable flexible cosmetic, optional input if proven |
| `G025` | Thought bubble rear/e-ink second display | EXPANSION | Separate module, high pin/space cost and rear visibility |
| `G026` | Servo pan/tilt head | EXPANSION HARDWARE VARIANT | Not in two servo allocation; requires third/fourth actuator and confirmed new center of mass |
| `G027` | 4-servo body language / dance | EXPANSION HARDWARE VARIANT | Cannot be "free" on two-servo lift+grip base |
| `G028` | Two pets and five pet interaction | REQUIRED | Digital messages and individual characters; coordinated games |
| `G029` | Self dock / go home | REQUIRED FIRST PET AND DOCK, PHYSICAL HOLD; historically EXPANSION HARDWARE | New accepted first-pet requirement supersedes historical expansion timing. AprilTag predock, terminal alignment, two independent passive seat inputs, contact isolation, charger qualification, bounded retries and explicit safe departure must be proven on the assembled robot |
| `G030` | Remote phone and ESP-NOW control | EXPANSION | Operator-only control path, no motion permission from broadcasts |
| `G031` | Camera see-what-it-sees and AI Eye | REQUIRED | Real fresh image to VLM; scene comments are validated before claims |
| `G032` | Hand/face mimic and personalized gestures | EXPANSION | Do not infer face identity without opt-in data and evaluation |
| `G033` | PIR homecoming and attentive greeting | EXPANSION | Presence source with evidence/cooldown and no generic repeated speech |
| `G034` | Breath fog / tea / aquarium / plant/weather modes | EXPANSION | Physical external sensors/safety and signed readings |
| `G035` | PC agent mirrors and AI coding emotions | EXPANSION SOFTWARE | MCP/status protocols, not scraping or broad credentials |
| `G036` | Dog bark on understanding / playful language | EXPANSION | Dogo pet pattern, sounds prioritized below humans |
| `G037` | Educational games and board game magnets | EXPANSION | Real interactive props and physical scene analysis |
| `G038` | Expression costumes / custom avatar / GIF | EXPANSION SOFTWARE | SSD1306 monochrome limits; no false color/60fps promise |
| `G039` | Peer physical chasing/handoff | RESEARCH HARDWARE | Not within one-front-ToF collision coverage; separate multi-robot safety program |
| `G040` | Social games with robot-robot rivalry | REQUIRED EXPERIENCE | Can be stationary with expressive peer turns before physical group roaming |
| `G041` | Household sounds and custom whistle | EXPANSION SOFTWARE | Post AEC, false positives, no implied sound bearing |
| `G042` | Mood from ambient illumination/temperature | EXPANSION | Real sensor required; simulated mood not a weather instrument |
| `G043` | Handling/lap/cuddle/gentle squeeze | REQUIRED + EXPANSION | IMU/touch required; FSR/piezo optional, immediate motion inhibition |
| `G044` | Self-perception and confidence | REQUIRED | Actual sensor checks, no fabricated emotional states |
| `G045` | Pet remembers user and spontaneous stories | REQUIRED | Truthful per-robot memory provenance and consent |
| `G046` | Multi-robot peer fun with distinct culture | REQUIRED EXPERIENCE | Five identical core units but evolving individual character histories |

## E. Historical research and new-find queues retained, not silently implemented

| ID | Idea or requirement | Design status | Day-zero reservation, constraint, or proof required |
| --- | --- | --- | --- |
| `H001` | Historical Xiaozhi First, Emotion Lab and older forks | REFERENCE | Earlier Xiaozhi packs retained; not substitute for current Sense/WROOM platform |
| `H002` | Historical Xiaozhi mod packs and six week schedule | REFERENCE | Touch/motion/cliff/dance ideas mapped here; old two-TCRT5000 scheme not accepted edge coverage |
| `H003` | Historical sensor leaderboard and brainstorm waves | PRESERVE | Every named sensor family appears in group C, with source/fit/safety flags |
| `H004` | Historical sensors, emotions and 24 idea shortlist | PRESERVE | Mapped to groups B/C/D; no automatic reverse or single-mic voice direction |
| `H005` | Historical finds from Reddit and YouTube | PRESERVE | Source register includes original patterns; a video demo does not equal source license or code |
| `H006` | Historical newly found projects from Nov 7 and Nov 9 | RESEARCH | Claude Desktop Buddy, Tiny Engineer, JARVIS, coding agent pet, Dogo, HachimoDock, Tokpet, Sesame Robot, MoodiMOS, Meta Muse, Tiny Touch DeskBuddy, Duckbert, AI Ball, AI DeskBuddy and others retained as leads |
| `H007` | Historical reference BOM and fork list | PRESERVE | StackChan, MyDeskRobo, AI Pet Robot V2, Sentio, Xiaozhi-Pet, Claude Desktop Buddy remain candidates, not verified source integrations |
| `H008` | Eilik/EMO/Cozmo/Vector/Mochi/Fetch comparisons | INSPIRATION | Character and appearance pattern, not copying closed commercial personality engines |
| `H009` | Projects with no confirmed source/license | REVIEW | Do not copy copyrighted binary, STL or code from partial videos simply because public URL exists |
| `H010` | New external sources and model/library claims | SOURCE CHECK | Verify per pinned release/license/readme/actual code; never turn user's unverified market/pricing/model benchmark into repo truth |

## Explicit status preservation for historically conflicting details

The original HTML's GPIO41/42 MAX30102 wiring, auto-reverse upon cliff, unsafe fault-degraded retreat, proposed relaxed audio A2 gate, 700 half-steps/s treated as implemented, `CAMERA_GRAB_LATEST` treated as proven, current RoboEyes integration, 40ms five-sensor scan, invented STT/TTS contention results, unmeasured 1.85A peaks, misleading $38.44 basket and $34 IP5306 selection are **not final instructions**. Preserve them as research in the original artifact. Refer to [engineering audit](research/2026-11-09-html-verification.md) and [full gate](decision-log.md) for safe resolutions.

## Requirement vs idea vs evidence

Every feature must eventually have `feature_id`, named origin or URL, code/physical owner, power/pins/location, licensed upstream SHA, chosen software adapter, permission/data sensitivity, declared cost, acceptance test, `not_attempted | source_reviewed | simulated | software_passed | bench_passed | accepted` state, and evidence link. This register does **not** mark feature delivery. Add new user research ideas as new IDs, never erase previous IDs; mark superseded and link the successor. Safety-related `REJECTED` items remain visible in history to prevent reintroduction.

A full URL list from the uploaded HTML was not embedded in this Markdown file; its live HTML has many repeated/unique links, some in historical sections. The curated and previously inspected official links live in [source map](source-map.md) and [reuse register](research/2026-11-03-active-pet-sources.md). Do not claim every external URL was visited or every creator video was watched just because its idea is traceable here.


---

## Complete original HTML research link index

*Original research references, not approved purchases or completed installations.*


**Provenance:** The user-supplied `ESP32 Deskpet Ideas.html` (1,074,994 bytes) was statically inspected on 2026-11-09. Its 567 anchor occurrences contain **256 external HTTP(S) references, 131 distinct external URLs, and 311 in-document anchors**. This file preserves every distinct external URL **exactly as authored**, including duplicates that existed in other research lists and historical shopping/research links. These are **links found in the HTML, not evidence that each target still exists or that every video/article was opened, read, licensed or validated**. Links may be broken, paywalled, outside safety scope, stale, or unsafe to follow. Treat code licensing and claims as unverified until examined individually.

This index is not a shopping list or authorization to install all parts. See [feature register](source-map.md) for concepts, [reuse decisions](research/2026-11-03-active-pet-sources.md) for inspected candidates, [prebuild decisions](decision-log.md) for constraints, and [source map](source-map.md) for earlier twelve-video evidence. Do not silently remove an older source because it is not selected.

| ID | Original URL |
| --- | --- |
| `L001` | <https://atomic14.com/2026/03/15/cheap-heart-rate-monitor> |
| `L002` | <https://benchrobotics.com/esp-32/esp32-robot-with-odometry-and-waypoint-navigation/> |
| `L003` | <https://bitcoinversus.tech/2026/10/10/pamk-robot-replaces-sticky-notes/> |
| `L004` | <https://blog.mgbeets.com/portable-as3935-lightning-detector-xiao-esp32c3/> |
| `L005` | <https://circuitdigest.com/microcontroller-projects/esp32-air-quality-monitor> |
| `L006` | <https://circuitdigest.com/microcontroller-projects/sentio-a-cute-companion-robot-esp32-s3-box-3> |
| `L007` | <https://community.element14.com/challenges-projects/design-challenges/light-up-your-life/b/projects/posts/auraalert---lighting-up-every-sound> |
| `L008` | <https://community.home-assistant.io/t/project-xiaozhi-specball-v2-esp32-s3-as-a-desktop-diabetes-monitor-voice-assistant/988264> |
| `L009` | <https://community.home-assistant.io/t/smartdisplay-repurposing-the-1-28-esp32-s3-circular-box-into-a-100-local-notification-display-tts-speaker-esphome-lvgl-8/1029751> |
| `L010` | <https://components.espressif.com/components/espp/vl53l/versions/1.3.9/readme> |
| `L011` | <https://components.espressif.com/components/espressif/ble_services/versions/0.1.0/examples/ble_services/ble_hrs?language=en> |
| `L012` | <https://components.espressif.com/components?page=17&sort_by=name&sort_dir=asc&q=target%3Aesp32h2> |
| `L013` | <https://copyprogramming.com/howto/need-some-help-on-a-beam-break-sensor-code-for-arduino> |
| `L014` | <https://cyberconnect.shop/shop/product/yxa178-mfrc-522-rc522-rfid-card-module-sensor-452> |
| `L015` | <https://deepwiki.com/danielbernalb/AireCiudadano/2.1-hardware-components> |
| `L016` | <https://deepwiki.com/hpy666666/xiaozhi-esp32-pet> |
| `L017` | <https://deepwiki.com/nopnop2002/esp-idf-mpr121> |
| `L018` | <https://deepwiki.com/nopnop2002/esp-idf-mpr121/1.1-getting-started> |
| `L019` | <https://docs.cirkitdesigner.com/component/a0c4bb9b-ec48-41ee-a613-32a78c56b8e0/mlx90640> |
| `L020` | <https://docs.sunfounder.com/projects/summary-of-fun-projects/en/latest/arduino/light_tracing.html> |
| `L021` | <https://esp32engine.com/projects/esp32-water-leak-detector.html> |
| `L022` | <https://esp32io.com/tutorials/esp32-joystick> |
| `L023` | <https://esp32io.com/tutorials/esp32-water-leak-detector> |
| `L024` | <https://espeasy.readthedocs.io/en/latest/Plugin/P142.html> |
| `L025` | <https://evn.coresg.tech/examples/> |
| `L026` | <https://forum.arduino.cc/t/help-with-hall-sensor-and-resistor-wiring/614958> |
| `L027` | <https://forum.seeedstudio.com/t/xiao-esp32s3-feetech-servo-communication-issue-can-send-commands-but-cannot-receive-feedback-servo-unresponsive/294715> |
| `L028` | <https://github.com/AngeloMontesano/MyDeskRobo> |
| `L029` | <https://github.com/DirkzeSoft/weather_station_esphome/blob/HEAD/CLAUDE.md> |
| `L030` | <https://github.com/EARTKEY/LF_Alpha> |
| `L031` | <https://github.com/Martvixtor/APDS9960> |
| `L032` | <https://github.com/RealDeco/xiaozhi-esphome> |
| `L033` | <https://github.com/TechTalkies/YouTube/tree/main/95_Chatbot_on_wheels> |
| `L034` | <https://github.com/YizhengWw/HachimoDock> |
| `L035` | <https://github.com/anthropics/claude-desktop-buddy> |
| `L036` | <https://github.com/bmellink/GeigerCounter> |
| `L037` | <https://github.com/collabray/wisense> |
| `L038` | <https://github.com/dorianborian/sesame-robot> |
| `L039` | <https://github.com/dreamhunter02/jarvis-desk-bot> |
| `L040` | <https://github.com/espressif/esp-who> |
| `L041` | <https://github.com/facebookincubator/muse-gadget-sdk> |
| `L042` | <https://github.com/ferrolho/vl53l5cx-bno08x-viewer/blob/HEAD/README.md> |
| `L043` | <https://github.com/francescopace/espectre> |
| `L044` | <https://github.com/grpcer/tokpet> |
| `L045` | <https://github.com/homeautomatorza/esphome-modules/blob/HEAD/recipes/projects/room_sense/presence/README.md> |
| `L046` | <https://github.com/innocircuitslab/esp32-s3-offline-voice-control/blob/HEAD/ESP32-S3-Offline-Voice-Control/README.md> |
| `L047` | <https://github.com/iotdevicesdev/GGreg20_V3-ESP32-HomeAssistant-ESPHome> |
| `L048` | <https://github.com/jamro/tiny-engineer> |
| `L049` | <https://github.com/kiryl-bahdanovich/esp32s3-ai-audio> |
| `L050` | <https://github.com/mzhnk/ai-pet-robot/blob/HEAD/README.md> |
| `L051` | <https://github.com/oliviazzzu/minimal-embodiment/blob/main/BUILD_GUIDE.md> |
| `L052` | <https://github.com/phamhungtien/esp32-s3-health-monitor/blob/HEAD/README.md> |
| `L053` | <https://github.com/puha-dev/claude-usage-meter> |
| `L054` | <https://github.com/shahdgamal-3/iot-project/blob/HEAD/SENSOR_REFERENCE_TABLE.md> |
| `L055` | <https://github.com/shredermann-hash/MoodiMOS> |
| `L056` | <https://github.com/tny-robotics/tny-360/blob/HEAD/README.md> |
| `L057` | <https://github.com/user-attachments/files/28183272/SatiLoop_Design_Spec_v1_2.1.pdf> |
| `L058` | <https://github.com/xinnan-tech/xiaozhi-esp32-server> |
| `L059` | <https://hubble.com/community/guides/how-to-build-a-ble-asset-tracker-with-esp32/> |
| `L060` | <https://learn.adafruit.com/adafruit-mpr121-12-key-capacitive-touch-sensor-breakout-tutorial?view=all> |
| `L061` | <https://learn.adafruit.com/face-tracking-robot-with-memento/upload-code> |
| `L062` | <https://leroyd.com/> |
| `L063` | <https://lonelybinary.com/blogs/tutorial/ir-receiver> |
| `L064` | <https://make-it.ai/blog/sensor-project-ideas-for-industrial-design-students> |
| `L065` | <https://makerworld.bblmw.com/makerworld/model/US711915b126693d/design/fb2e5666b38d10ea.pdf> |
| `L066` | <https://makerworld.com/en/models/2109424-compagnon-309-build-your-expressive-robot> |
| `L067` | <https://makezine.com/projects/discover-smart-servos-with-the-oxocard-connect/> |
| `L068` | <https://medium.com/@compodenin/idea-to-build-an-esp32-motion-desk-buddy-with-eyes-that-follow-your-t-c793ea240ed4> |
| `L069` | <https://mia-cat.com/en/pet-robot/stackchan-review/> |
| `L070` | <https://mokxi.com/parts> |
| `L071` | <https://moxd.io/files/2026/05/petersen2026capcrown.pdf> |
| `L072` | <https://opencircuit.shop/list/biometry-modules> |
| `L073` | <https://openelab.io/products/fsr402-film-press-sensor> |
| `L074` | <https://orca.cardiff.ac.uk/id/eprint/188629/1/compass26-28.pdf> |
| `L075` | <https://orobot.io/o/program/BROKER-2/stack-chan> |
| `L076` | <https://pmc.ncbi.nlm.nih.gov/articles/PMC9041184/> |
| `L077` | <https://randomnerdtutorials.com/esp32-max30102-oximeter-heart-rate-sensor/> |
| `L078` | <https://randomnerdtutorials.com/esp32-sht41-temperature-humidity-arduino/> |
| `L079` | <https://registry.platformio.org/libraries/herobrine-pixel/AudioCompass> |
| `L080` | <https://robosap.in/product-category/sensors-and-modules/page/9/> |
| `L081` | <https://shillehtek.com/blogs/news/esp32-c3-oled-mpu6050-reactive-desk-pet> |
| `L082` | <https://simcap.parc.land/docs/docs/design/revisiting-simcap.html> |
| `L083` | <https://store.roboticsbd.com/imugyrocompass/3277-gy-271-qmc5883l-3-axis-compass-magnetometer-sensor-module-robotics-bangladesh.html> |
| `L084` | <https://store.roboticsbd.com/sensors/3911-as7341-11-channel-multispectral-sensor-module-color-light-spectrum-detection-robotics-bangladesh.html> |
| `L085` | <https://vineethkalluru.com/blog/jarvis-desk-bot/> |
| `L086` | <https://wiki.seeedstudio.com/xiao_esp32s3_keyword_spotting/> |
| `L087` | <https://www.academia.edu/37461494/Deep_Room_Recognition_Using_Inaudible_Echos> |
| `L088` | <https://www.amazon.com/Gy-521-MPU-6050-MPU6050-Sensors-Accelerometer/dp/B008BOPN40> |
| `L089` | <https://www.amazon.com/dp/B07GGSM8SP/ref=cm_sw_r_cp_api_i_Q.OyEb8A6NAG7> |
| `L090` | <https://www.amazon.com/dp/B0DHPCFXCK/ref=pd_ybh_a_d_sccl_1> |
| `L091` | <https://www.amazon.com/dp/B0DP6893DS/ref=cm_sw_r_cso_cp_apin_dp_BV6YZ9XS400MGMCAECTH> |
| `L092` | <https://www.amazon.com/dp/B0FX7FXQGB> |
| `L093` | <https://www.amazon.com/gp/product/B081RPJ44L> |
| `L094` | <https://www.atomic14.com/esp32/sensors/> |
| `L095` | <https://www.cnx-software.com/2026/05/16/anthropics-open-source-claude-desktop-buddy-turns-esp32-s3-devices-into-interactive-ai-desk-companions/?amp=1> |
| `L096` | <https://www.componentindex.net/> |
| `L097` | <https://www.componentindex.net/components/mpr121/> |
| `L098` | <https://www.doriantodd.com/sesame/> |
| `L099` | <https://www.electromaker.io/project/view/seeed-mr60bha1-presence-breathing-and-heartbeat-sensing> |
| `L100` | <https://www.espboards.dev/sensors/category/environment/> |
| `L101` | <https://www.espboards.dev/sensors/ky-003/> |
| `L102` | <https://www.facebook.com/reel/1527477492402185/> |
| `L103` | <https://www.hackster.io/news/a-companion-robot-that-roams-your-desk-until-you-pet-it-15d35ca26459> |
| `L104` | <https://www.hackster.io/news/lilygo-refreshes-the-circular-t-rgb-with-a-new-more-compact-t-display-s3-amoled-variant-84063ab6ea6c.amp> |
| `L105` | <https://www.hackster.io/openelab/claude-desktop-buddy-tutorial-sticks3-cardputer-48f922> |
| `L106` | <https://www.hackster.io/techtalkies1/esp32-desk-companion-robot-with-wheels-98466c> |
| `L107` | <https://www.instagram.com/p/DfKCQaNDPlQ/> |
| `L108` | <https://www.instagram.com/reel/DaIBVk0OZhW/> |
| `L109` | <https://www.kevsrobots.com/blog/bus-servos.html> |
| `L110` | <https://www.makerguides.com/apds-9960-gesture-and-color-sensor-with-arduino/> |
| `L111` | <https://www.mdpi.com/2673-4591/163/1/2> |
| `L112` | <https://www.pcbway.com/project/shareproject/TempGun_Pro_bfc4ac00.html> |
| `L113` | <https://www.roboatticlab.com/blogs/how-to-build-a-desktop-companion-robot-esp32-s3> |
| `L114` | <https://www.schematik.io/projects/desk-ai-buddy-robot-gbmg> |
| `L115` | <https://www.schematik.io/projects/tiny-touch-deskbuddy-fff6> |
| `L116` | <https://www.teachmemicro.com/esp32-time-of-flight-sensor-vl53l0x/> |
| `L117` | <https://www.teachmemicro.com/using-the-esp32-internal-temperature-sensor-with-arduino/> |
| `L118` | <https://www.teachmemicro.com/voice-command-recognition-with-esp32-and-tinyml-using-edge-impulse/> |
| `L119` | <https://www.xda-developers.com/this-3d-printable-esp32-robot-acts-as-a-physical-body-for-your-ai-agent-thinking-and-typing-alongside-it/> |
| `L120` | <https://www.xloge.site/2026/10/esp32-s3-tinyml-in-2026-edge-impulse-vs.html> |
| `L121` | <https://www.youtube.com/watch?v=2zrfYM4R5U4> |
| `L122` | <https://www.youtube.com/watch?v=62CkepeV6gw> |
| `L123` | <https://www.youtube.com/watch?v=6Js7CPe7Dwo> |
| `L124` | <https://www.youtube.com/watch?v=Hn9TY7mLAIE> |
| `L125` | <https://www.youtube.com/watch?v=NcO8YR63iRU> |
| `L126` | <https://www.youtube.com/watch?v=PMwH1sBMu3I> |
| `L127` | <https://www.youtube.com/watch?v=aDaSp6zaqWM> |
| `L128` | <https://www.youtube.com/watch?v=f1vbvW01v2A> |
| `L129` | <https://www.youtube.com/watch?v=mZHZoPKBkwg> |
| `L130` | <https://xiaozhi.dev/en/blog/xiaozhi-esp32-v2-5-release-notes/> |
| `L131` | <https://yana.vutam.link/wheelbot-en.html> |

**Research tracking:** For each source opened in future work record `LID / feature_id / date / claimed behavior / inspected original source / actual code or diagram / license / specific compatible hardware / deviations / test`. No project or supplier claim becomes a purchase or safety instruction from this URL list alone.


---

## Original HTML DOM section crosswalk, verified 2026-11-09

**Exact source fingerprints:** Uploaded `ESP32 Deskpet Ideas.html`: 1,074,994 bytes, SHA256 `12a0068f3bcec7daa6065cc180478294ccc1d0cc5e439250774684f3b2008b5d`. Uploaded additional engineering audit text: 51,993 bytes, SHA256 `5f934f13ded7cd6764c974456ee15fa79a4733c4059376ee72686e93c60f0414`. These hashes identify the review inputs; the original files are **not committed to this repository**, so the 131 URLs and 41 section IDs are preserved in canonical Markdown instead. A later user upload with a different hash must be diffed before revising this map.

This table is extracted from the **actual uploaded HTML structure**, rather than the previous inaccurate description of the file as 23 numbered sections. The original contains **41 section elements (24 with `class=group`), 44 `h2` headings, 316 `h3` headings and 231 `<details>` research blocks**. The page has 567 link occurrences: 256 external occurrences representing 131 unique URLs and 311 in-page anchors. The original section ID sequence is preserved below; the 200 idea register groups related ideas and should not be mistaken for a one-to-one HTML section count.

| Order | Actual `section` ID in HTML | What the section owns | Interpretation | Canonical existing file |
| --- | --- | --- | --- | --- |
| 1 | `project-overview` | What we are building | Current | [View](product-definition.md) |
| 2 | `project-architecture` | Three compute owners | Current | [View](product-definition.md) |
| 3 | `project-build-order` | Original seven stage summary | Current | [View](PLAN.md) |
| 4 | `project-status` | Current evidence and gaps | Current | [View](records/verification.md) |
| 5 | `project-parts` | Owned versus quoted parts | Current | [View](hardware/parts.md) |
| 6 | `max30102-add` | Proposed heartbeat paw | Optional, not electrically qualified | [View](hardware/wiring.md) |
| 7 | `project-rules` | Safety and build constraints | Current | [View](product-definition.md) |
| 8 | `project-roadmap` | Topics and original navigation | Current | [View](PLAN.md) |
| 9 | `topic6-power` | Power topology and sequencing | Proposed, qualification open | [View](hardware/wiring.md) |
| 10 | `topic4-drive-gripper` | Steppers, lift, grip and trials | Required, physical tests open | [View](PLAN.md) |
| 11 | `topic1-cliff` | Four floor and front ToF | Required roles, VL53L0X selected; physical carrier and geometry unqualified | [View](hardware/wiring.md) |
| 12 | `topic2-touch` | Owned touch and IMU plus experiments | Required reactions and optional parts | [View](hardware/interaction-sensors.md) |
| 13 | `topic3-audio` | Full duplex speech and interruption | Required, physical AEC open | [View](guides/audio-barge-in.md) |
| 14 | `topic5-head-face` | Head geometry and expression | Required, physical fit open | [View](product-definition.md) |
| 15 | `topic7-mac-brain` | Local AI, voices, identity and fleet | Required, live integration open | [View](guides/live-conversation.md) |
| 16 | `topic8-proactive` | Contextual self initiation and agency | Required, implementation open | [View](product-definition.md) |
| 17 | `project-research-map` | Live topics to older sources | Source map | [View](source-map.md) |
| 18 | `research-library` | Historical research intro | Archive | [View](source-map.md) |
| 19 | `start-here` | Xiaozhi baseline and Emotion Lab | Historical | [View](source-map.md) |
| 20 | `paths` | Older Xiaozhi first route | Superseded architecture | [View](decision-log.md) |
| 21 | `build-plan` | Older Xiaozhi mod pack plan | Historical | [View](source-map.md) |
| 22 | `modpack1` | Touch, movement and fall pack | Historical, unsafe parts rejected | [View](source-map.md) |
| 23 | `modpack2` | Dance and tricks pack | Historical | [View](source-map.md) |
| 24 | `schedule` | Older six week plan | Historical | [View](source-map.md) |
| 25 | `top-picks` | Shortlists and leaderboards | Research only | [View](source-map.md) |
| 26 | `brainstorm-sensors` | Unselected sensor candidates | Experimental | [View](source-map.md) |
| 27 | `specs` | Older Xiaozhi specifications | Historical, pinmaps not active | [View](source-map.md) |
| 28 | `spec-pack` | Five cheaper sensor examples | Experimental, old wiring not active | [View](source-map.md) |
| 29 | `sensor-menu` | Broad sensor idea waves | Experimental | [View](source-map.md) |
| 30 | `finds` | Reddit and video research | Research only | [View](source-map.md) |
| 31 | `reddit-youtube` | Creator build reviews | Research only | [View](research/2026-11-03-video-audit.md) |
| 32 | `steal` | Behavior ideas from other pets | Idea reuse only | [View](research/2026-11-03-active-pet-sources.md) |
| 33 | `popular` | Common ESP32 build patterns | Research only | [View](source-map.md) |
| 34 | `tweaks` | Nine physical accessory ideas | Experimental | [View](source-map.md) |
| 35 | `sensors` | Sensor to emotion map and simulator | Historical, no blind retreat | [View](source-map.md) |
| 36 | `ideas` | Twenty four original concepts | Experimental or required by actual product | [View](source-map.md) |
| 37 | `new-finds-2026-11-07` | New desk agent finds | Research only | [View](source-map.md) |
| 38 | `new-finds-2026-11-09` | Later robot and code finds | Research only | [View](source-map.md) |
| 39 | `reference` | Historical parts and BOM | Historical estimates only | [View](hardware/archive/budget-audit.md) |
| 40 | `diy-shopping-list` | Nested DIY shopping block | Historical, not purchase ready | [View](hardware/archive/budget-audit.md) |
| 41 | `repos` | Older open source starter projects | Research only | [View](source-map.md) |

**Important:** Section IDs and link set are source provenance. The table does **not** imply each external article has been visited, that an old wiring example is safe, or that every speculative sensor fits the current chassis and $50 cap. Use the full 131 URL list and feature IDs for deeper source inspection. Do not reinstate deprecated Xiaozhi era pinouts or the interactive simulator's cliff reversal.


## Ten detailed integration reviews of the full five-robot product, November 10, 2026

This is an engineering audit of the **complete requested system**, not a
reduced beginner robot. See the same consolidated draft PR #17 for executable
changes. Reviewed first-party source boundaries were compared before code reuse:

1. The already existing WROOM local cliff fault and Mac one-use permit had
   independent stop handlers. Connected the Mac pet status fault transition to
   the existing Coordinator stop/cancel path so an in-flight pickup/exploration
   job cannot carry on after the WROOM disarms locally.
2. Rechecked Pololu's [VL53L4CD Arduino ULD-derived source](https://github.com/pololu/vl53l4cd-arduino/blob/master/src/VL53L4CD.cpp).
   Confirmed the active-low GPIO status, raw range status 9, nonzero SPAD and
   checked interrupt clear. At that historical November 10 checkpoint the
   VL53L4CD and mux adapter were retained; the November 16 selection superseded
   that choice with VL53L0X. Do not use this historical driver as buying or wiring guidance. Rechecked the paired identity detection in
   [OzzMaker's BerryIMU Arduino source](https://github.com/ozzmaker/BerryIMU/blob/master/arduino-BerryIMU/IMU.cpp).
   Refuse ambiguous WHO_AM_I combinations and unsupported LSM6DSV320X.
3. Compared the actual vendored MIT
   [Stackchan-agent Behavior.hpp](https://github.com/botamochi6277/stackchan-agent/blob/bfb98fb8bdb4f8ecc4b7c1c4aed39bb7d84bdefe613/include/Behavior.hpp)
   with our Sense face task. Connected the real WROOM body UART touch count
   to its existing HSM `kTouched` event and OLED expression without another
   motor controller or invented pan/tilt servo.
4. Reused the same HSM for fail-closed face response when the WROOM is offline
   or reports a fault. Updated OLED only on transitions instead of repeating
   the same display write continuously; restore idle state after recovery.
5. Compared real Sense MR 16 kHz microphone/reference AFE contract with
   [Espressif ESP-SR AFE](https://docs.espressif.com/projects/esp-sr/en/latest/esp32/audio_front_end/README.html)
   and the owned-board-compatible
   [RIO source](https://github.com/mk14ray/RIO-XIAO-ESP32-S3-Gemini-Live-Voice-Assistant).
   Retained existing Xiaozhi I2S, device AEC and ring resampler. Exposed
   reference delay (default 90ms, 0..250ms private per-board build setting)
   instead of falsely assuming room acoustics calibrated.
6. Connected the existing Sense `SnapshotJpeg` camera endpoint and Mac
   `HttpHead` with a boot nonce, per-boot capture sequence and head-side
   JPEG completion timestamp, serializing camera capture per physical head
   without blocking WROOM keepalive. This **is not** a true sensor exposure
   timestamp and does not synchronize device clocks; an actual stale or
   replayed completion is rejected before it drives proactive or pickup logic.
7. Reconciled five independent SQLite memory and peer dialogue semantics:
   a robot's own spoken line now says `I said`; another robot's line says
   `I heard robot-N say`; only real witnessed sensor events use `I witnessed`.
   Conversation and proactive prompts share this provenance distinction.
8. Compared
   [Reachy Mini's weighted idle policy](https://github.com/pollen-robotics/reachy_mini_conversation_app/blob/e90192559149d6281d782c1c4aed39bb7d84bdef/src/reachy_mini_conversation_app/idle_policy.py)
   and [Microduck's proposed 16-state autonomous design](https://github.com/pollen-robotics/microduck/blob/54e0789635ae28120be9ea0dd51750a494ab50ac/docs/ideas/autonomous_behavior.md).
   Reachy dispatches registered local idle tools with weighted stillness;
   Microduck's document is a *proposal* and not a finished motor navigation
   stack. Used the existing Coordinator one job / WROOM motion authority to
   implement persistent operator-enabled exploration with 100ms bounded
   pulses and fresh optical/IMU checks. Full swept turns and autonomous route
   decisions still require mechanical and sensor qualification.
9. Refactored the same sensor-health readout into pickup and exploration.
   Rechecks actual WROOM armed state, 5 ToF channels, IMU and touch between
   100ms approach pulses and lift, hold, release, withdrawal and verification.
   No user trust in simulation images as physical 10mm lift evidence.
10. Added a single five-robot integration simulation with five independent
   stores, 10 sequential digital conversation turns, per-peer memory/source
   separation, persistent one-pet movement, stop and no other pet movement.
   This is an executable software test of wiring, not five assembled robots.

**Not yet accepted:** attached sensor pullups and supply, identified board
revisions, physically calibrated tilt/handling, final CAD/gripper fit, delivered
price, motor slip and swept turn margins, 19/20 natural interruption latency,
8/10 real key and candy pickups, and five actual head + body trials. None of
these original user requirements was removed, and CI cannot substitute for
real mechanical or acoustic evidence.


## Extra-sensor integration priority and source distinction, November 10

The full historical 75-sensor idea list remains intact. The latest user hardware
selection is MPU6050, identified with the actual InvenSense register 0x75 and
0x3B..0x48 14-byte raw sample, sharing WROOM I2C with the eight VL53L0X range
channels on mux 0x70 (five guarded, three read-only). BerryIMU remains a
photographed optional spare, not a second required purchase. The already owned
AT42QT1010 momentary pad is the required petting input. The full WROOM profiles
require the direct normally closed bumper (GPIO35) and enable magnetic reed
closure on MCP23017 GPIOB0 (active LOW). Optional PIR infrared activity uses
GPIOB1 (active HIGH) on the same expander, address 0x20, accessory mux 0x71 lane
5, and is enabled only in `esp32_full_interaction_lab`. GPIO36/39 are reserved
for separate terminal IR receivers, not reed/PIR wiring. C++ edge counters
connect to Mac private eyewitness memories; only the bumper invokes immediate
local stop plus Mac job cancellation. PIR reports infrared activity, not person
identity, location, count, stationary presence, or movement permission. The
SW-18010P vibration switch and piezo knock sensor remain reserved expansion
ideas, not implemented GPIOB inputs; short switch pulses require measured
capture/debounce, and a piezo requires a protected analog front end. None of
these source paths establishes physical qualification.

The user-photographed BMP280 is **pressure and temperature, not humidity**.
Bosch's datasheet specifies I2C 0x76/0x77 and register 0xD0 ID 0x58. It is
reserved for isolated TCA9548A lane 5 to avoid possible 0x77 Berry pressure
conflicts; no BMP driver or claimed reading is enabled before the physical
board and a vendor-compatible compensated driver are verified. Optional MAX30102
heartbeat requires user consent and a physically qualified 1.8V chip/breakout,
never the Sense GPIO41/42 already assigned to its PDM microphone. Optional
light/camera gestures and environmental sensors occupy the remaining mux lanes
only after exact model, power, pullup and cost review, not as blind wired bags.

Primary sources: [InvenSense MPU6050 register map](https://invensense.tdk.com/wp-content/uploads/2015/02/MPU-6000-Register-Map.pdf), [Bosch BMP280 datasheet](https://www.bosch-sensortec.com/media/boschsensortec/downloads/datasheets/bst-bmp280-ds001.pdf), [Adafruit AT42QT1010 product](https://www.adafruit.com/product/1374) and [Espressif ESP32 GPIO reference](https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/peripherals/gpio.html).


## November 10 full original HTML followup

The uploaded 1,074,994-byte original HTML was directly found and inspected again, with matching SHA256 `12a0068f3bcec7daa6065cc180478294ccc1d0cc5e439250774684f3b2008b5d`. The file contains 131 unique external links. This file's L001..L131 index matches its URL count, aggregate URL-length checksum 8,786, and character-code checksum 821,563, including identical first and last URL. The source map also retains the 39 F, 30 B, 75 S, 46 G and 10 H entries, with no numeric gaps, for **200** categorised ideas. Source preservation is not verification of every link's contents.

**Correction:** Original HTML explicitly approved and reportedly owned about five MAX30102 fingerprint heartbeat boards for an onboard pet paw pad. The photo audit did not independently establish their presence, so it is **reported unverified**, not a buy. Preserve it on WROOM I2C via the optional mux, not on Sense GPIO41/42 because of PDM audio. Other original research ideas such as piezo knock, coin mouth, tea probe, a second screen, compass and servo tail remain catalogued but not secretly declared physically built. [Review findings](research/2026-11-10-original-html-link-and-hardware-audit.md).
