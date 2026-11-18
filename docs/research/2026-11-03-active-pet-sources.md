# Active desk-pet sources and remix decisions — 2026-11-03

## Follow-up source inspection — 2026-11-04

This is research evidence, not implemented functionality. Current product choices
and acceptance live in [the product brief](../product-definition.md); later head,
power, sensor and motion-session decisions supersede older recommendations below.

- Reachy Mini conversation app inspected at
  `e90192559149d6281d782c1c4aed39bb7d84bdef`, Apache-2.0. Its
  [idle policy](https://github.com/pollen-robotics/reachy_mini_conversation_app/blob/e90192559149d6281d782c1c4aed39bb7d84bdef/src/reachy_mini_conversation_app/idle_policy.py)
  selects local stillness/dance/emotion/head moves; the
  [conversation handler](https://github.com/pollen-robotics/reachy_mini_conversation_app/blob/e90192559149d6281d782c1c4aed39bb7d84bdef/src/reachy_mini_conversation_app/conversation_handler.py)
  dispatches idle actions without sending a model turn. Its camera tool returns
  a fresh JPEG separately. The movement manager sequences primary moves, blends
  speech motion and suppresses idle movement while listening. Reuse scheduling
  and interruption concepts through our own hardware adapter, not Reachy poses
  or an assumption that its camera tool already supplies our proactive vision.
- [Open Duck's inspected walking path](https://github.com/apirrone/Open_Duck_Mini_Runtime/blob/376de65435c93486347cd601a31aa96951799896/scripts/v2_rl_walk_mujoco.py)
  takes gamepad motion commands into a walking policy. Independent blinking and
  controller-triggered sounds/antenna moves do not establish autonomous social
  or camera-driven activity selection.
- The newer Pollen Microduck's
  [behavior notes](https://github.com/pollen-robotics/microduck/blob/54e0789635ae28120be9ea0dd51750a494ab50ac/docs/ideas/autonomous_behavior.md)
  describe a prior mood/energy/novelty state machine, while explicitly identifying
  the autonomous-brain migration gap in the current daemon. Its old named runtime
  was not retrieved; do not claim independent inspection of that implementation.
- [Cozmo SDK source](https://github.com/anki/cozmo-python-sdk/blob/master/src/cozmo/robot.py)
  activates Freeplay in an existing robot engine. The SDK is not that engine.
  [Vector's subsystem documentation](https://support.anki.bot/article/567-vector-subsystems)
  separates high-level behaviors/mood, animation and cloud voice. These support
  a perception/event/activity/animation split, not a claim we can copy a complete
  commercial personality engine into ESP32 firmware.

Implementation consequence: build fresh camera events, bounded observation
memory, activity selection and speech arbitration around the existing Mac core;
keep eye animation and WROOM reflexes independent. Test camera-triggered reactions
without speech, repeated/stale-event rejection and five-feed speech ownership.
Do not mark source review as completion of those tests or runtime features.

The intended result is five identical, inexpensive tracked robots that initiate
small activities, notice interactions, and pick up keys or wrapped candy. The
sources below inform that behavior and appearance; none establishes that our
combined hardware already works. The [twelve-video audit](2026-11-03-video-audit.md)
separates creator descriptions from inspected code and unverified demonstrations.
No full-video or timestamp-level viewing is claimed here.

## What to reuse

| Reference | Verified published material | Decision for this build |
| --- | --- | --- |
| [chillibasket WALL-E replica](https://github.com/chillibasket/walle-replica) | GPL-3.0 repository. README documents an animation queue, random movement generator, controlled servo velocity, nonblocking serial parsing, and calibration for seven servos. | Reuse the ideas of interruptible choreography and pauses between gestures. The larger seven-servo, Arduino/Pi, 12 V arrangement is not our two-servo arm or a reason to buy a Pi. Any copied implementation must retain its license and attribution. |
| [FluxGarage RoboEyes](https://github.com/FluxGarage/RoboEyes) | GPL-3.0 Arduino graphics library using Adafruit GFX; supports configurable eyes, moods, gaze, blinking, idle motion and one-shot animations. SSD1306 examples are available. | Preferred face-library candidate for the owned 128×64 SSD1306, subject to a small ESP-IDF/Xiaozhi graphics and timing adapter. It is **not MIT** and is not already integrated into our firmware. |
| [Tech Talkies custom-face Xiaozhi](https://github.com/TechTalkies/Xiaozhi-for-XiaoESP32S3) | GPL-3.0 repository for the bare XIAO S3, with an OLED face and separate I²S audio wiring. | Inspect the face-state approach and required changes against our pinned Xiaozhi version. Its board-specific binary and pin map do not qualify the Sense camera/PDM-microphone configuration. |
| [Tech Talkies wheeled buddy](https://github.com/TechTalkies/YouTube/tree/main/95_Chatbot_on_wheels) | The inspected sketch has timed ROAM/PET/ATTN states and touch interruption; see the video audit for the exact source blob. No cliff interlock was found in that behavior path. | Useful concept for attention, cooldowns and petting responses. Do not copy its roaming routine as safe navigation. A repository-wide copying license was not established. |
| [Qubit](https://github.com/0xaiwhisperer/qubit) | Public choreography/dashboard material; README advertises MIT, but its linked LICENSE was absent from the checked top level and metadata reported no recognized license. | Use the architectural idea of calibrated keyframes for `grip`, `lift`, `offer` and `place`. Resolve copying terms before incorporating its source or assets. Its dual-arm hardware exceeds this budget and scope. |

The repository license results above were checked against GitHub repository
metadata on this date. Before incorporation, inspect the actual license and
headers at the selected revision, including separately licensed dependencies and
CAD. GPL components must not be silently presented as MIT-only project code.
No third-party source was copied into runtime code during this research update.

## What the ducks demonstrate

[Open Duck Mini v2](https://github.com/apirrone/Open_Duck_Mini/tree/v2) is an
Apache-2.0 project hub for a biped about 42 cm tall with extended legs. Its README
targets a BOM below $400, links reinforcement-learning policies and a separate
Pi Zero 2 W runtime, and notes incomplete documentation and expression features.
Its mechanics and learned walking stack are not a cheap drop-in replacement for
our WROOM-controlled tracks. Inspect licenses independently in each linked repo.

NVIDIA's [23 October Microduck article](https://developer.nvidia.com/blog/using-ai-agents-to-teach-robots-like-microduck-to-walk-in-simulation/)
distinguishes perception, navigation and locomotion. It describes building a
simulated obstacle course, training/evaluating policies, and preparing deployment.
It shows physical walking, but explicitly leaves detailed hardware deployment
outside its scope. That is useful evidence about the layers involved, not an
off-the-shelf companion personality or an ESP32 firmware recipe.

Disney's [BDX page](https://la.disneyresearch.com/bdx-droids/) explicitly describes
its expressive walking characters as puppeteered. A convincing glance or lively
demonstration does not by itself establish that a robot chooses its own activity.
We can borrow the general rhythm—look, pause, move, react—without reproducing
Disney assets or importing a biped training project.

Three capabilities must remain distinct: **locomotion** moves the hardware;
**navigation** chooses a route using observations; **agency** chooses when and
why to start an activity. A slow wheeled robot can exhibit agency without leg
balancing, reinforcement learning or full SLAM.

## Commercial appearance and interaction references

[Dasai Mochi 3](https://dasai.com.au/pages/mochi3) is a commercial driving companion
with animated expressions, sounds, motion reactivity and interchangeable helmets.
It is a reference for a compact face, playful timing and removable costumes;
its page does not establish a navigating conversational rover or open firmware.
An extra IMU is unnecessary for our first useful behavior set.

[Living.AI EMO](https://living.ai/emo/) advertises independent exploration,
attention, touch responses and personality expressed through motion and eyes.
These are vendor feature claims, not independent validation or published code.
Use the interaction goal—respond promptly, sometimes initiate, sometimes rest—
while creating original face artwork and behavior. Do not promise EMO-equivalent
navigation, recognition or reliability from this inexpensive remix.

## Recommended combination and behavior boundary

Keep the existing stepper-compatible SMARS base, Bluino lift/gripper and saved
EVA head. Aim for a compact WALL-E-like tracked silhouette, an original monochrome
face with Mochi-style playfulness, EMO-inspired initiative, and duck-like gaze
timing. Limit CAD to brackets, an OLED bezel, camera clearance, replaceable jaw
tips and removable hats. Brass rods can be an optional decorative cage; a new
freeform structural chassis, display PCB cutting and new arm are outside scope.

Start with stationary blinking, gaze, short sounds, listening and rest. Add a
deterministic activity scheduler that tracks curiosity, social cooldowns and
recent events. These are simulated character states, not measurements of real
battery charge. The shared Mac can choose occasional higher-level activities,
maintain separate histories, and ask an LLM for an intention when useful; eye
animation and motor reflexes must not wait for an LLM call.

Only after local edge/obstacle qualification should a human enable bounded
roaming. WROOM safety and stop handling override every activity. No blind reverse
or pivot follows a cliff reading. Initially allow one moving robot at a time,
while peers animate and converse with serialized speech and cooldowns. That
provides an active group without pretending simultaneous collision avoidance
already exists. All new scheduling, face adaptation and physical navigation
remain implementation and bench-test work.


---

## Inspected upstream source selection and reuse boundaries

*Checked source candidates and proposed HTML tuning remain distinct from implemented hardware and measured test results.*


This is the **implementation source shortlist**, not a new dependency dump. The [canonical source map](../source-map.md), [full video audit](2026-11-03-video-audit.md), [guide audit](2026-11-03-guide-audit.md) and all creator URLs in the original user HTML remain historical references. Many projects were partially code-inspected, not built or physically tested here. Repo visibility and GitHub stars do **not** prove licensing, audio performance, edge safety or compatibility.

Before writing a new subsystem: search GitHub, official docs and creator guides for an actually working implementation; read README **and executable source**, pin a commit and exact file, check license including generated assets, identify sensor/MCU/OS differences, port through one stable adapter, add targeted automated tests, and log why it could not be reused unchanged. **Never copy an unsafe autonomous driving routine simply because its demo runs.**

## Primary foundations for the full experience

| Layer | Source, exact useful code and current evidence | Reuse action; prevent a later rewrite |
| --- | --- | --- |
| **Sense head** | [Xiaozhi ESP32](https://github.com/78/xiaozhi-esp32), active source previously pinned `c435f99a88066029ec2dbd2d758c8cc9d051565b`; original `Esp32Camera`, `OledDisplay`, `NoAudioCodecSimplexPdm`, ESP-IDF audio and MCP | **Keep, extend narrowly**. Current Sense configuration uses mic 42/41, amplifier 4/7/8, OLED 5/6, UART 2/1, and pinned camera. Do not swap to another robot head to add a feature. MIT notice preserved. |
| **Xiaozhi local speech/server** | [Xinnan Xiaozhi server](https://github.com/xinnan-tech/xiaozhi-esp32-server); project already has server bridge, auth/device identity and Opus speech routing | **Keep baseline**; expose a single turn/session adapter for local speech and vision. Upstream server is not automatically a complete always-on pet brain. |
| **Sense full duplex audio** | [RIO exact Sense voice assistant](https://github.com/mk14ray/RIO-XIAO-ESP32-S3-Gemini-Live-Voice-Assistant/tree/b911305e48ce6a1b75fe6c07fc02f86ad7bfeb0a), `aec.cpp`, `aec.h`, `audio_in.cpp`, `audio_out.cpp` | **Port its software playback-reference timing and AEC calibration**, not a second whole AEC/speech stack. Arduino 3.x and GPIO7/8/9/44 reference differs from active ESP-IDF and 4/7/8. Audio gate needs physical double-talk/flush tests. MIT. |
| **Hardware agnostic camera events** | [Google robotics-samples](https://github.com/google-gemini/robotics-samples/tree/c51cbab6e6efffff8738ecf9ce41ba85034d9654/live-api/agent): `camera_poller.py`, `core/observation.py`, `core/event_bus.py`, `core/decision_making.py` and their tests | **Reuse logic with a Mac local-provider adapter**. Frame difference/stability, queue and typed events exist. Gemini Live model/backend and Spot/other embodiment must not become mandatory paid/cloud dependencies. Apache-2.0. |
| **Behavior HSM** | [Stackchan-agent](https://github.com/botamochi6277/stackchan-agent/tree/bfb98fb8bdb4f8ecc4b7c1c4f9bc90ee5227e613), `include/Behavior.hpp`, `include/SoundMonitor.hpp`, `test/test_behavior.cpp`; only a small reference project | **Adapt pure state machine** for pet modes and events if it proves simpler. Its own `behavior.md` explicitly says camera and LLM events are *defined, not produced*. No claim of end-to-end proactive vision. MIT. |
| **Idle/turn arbitration** | [Reachy Mini conversation app](https://github.com/pollen-robotics/reachy_mini_conversation_app), `src/reachy_mini_conversation_app/idle_policy.py`, `conversation_handler.py` | **Reuse local weighted idle selection, tool management, playback/turn handling**. Existing code selects dance/emote/head/stillness without a model call; camera tool is *pull* and cannot stand in for pushed perception. Apache-2.0. |
| **Closest scene-reactive pet** | [hudrucan Xiaozhi Desk Robot](https://github.com/hudrucan/xiaozhi-desk-robot), `main/robot/behavior/ambient_behavior.cc`, `proactive_events.cc`, `camera_attention_controller.cc`, `sensors/cliff_sensor.cc`; MIT project | **Mine reusable priority, cooldown, motion attention, reaction cancellation and camera motion patterns**. Much closer feature match, but different ESP32-S3-CAM PCB, audio GPIO, L298N DC motors, screen and unsafe auto-recovery possibility. Small project, not an established drop-in or safe firmware. |
| **Generic proactive utterance/group interrupt reference** | [Open LLM VTuber](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber), `src/open_llm_vtuber/conversations/conversation_handler.py`, `websocket_handler.py`, `chat_group.py`, `prompts/utils/proactive_speak_prompt.txt` | **Study** `ai-speak-signal`, group task cancellation, individual histories and interrupt handlers. Default prompt only asks to say something appropriate and is NOT camera-grounded proactivity. Root software license MIT; Live2D sample assets have distinct licensing. Do not port whole UI. |
| **Local-first alternative engine** | [Hugging Face speech-to-speech](https://github.com/huggingface/speech-to-speech/tree/99f03f5f91b7fe148a7494a0a1de3539ca42c503), VLM guide and streaming service | **Compare in a fixed workload before migrating**; pinned candidate offers speech/VLM components, but selecting a text-only default is not video understanding. One chosen provider/transport owner only. Apache-2.0. |
| **Streaming alternative** | [Pipecat](https://github.com/pipecat-ai/pipecat/blob/c87446099f88560b861ac0e1c13cce331e3a5770/examples/realtime/realtime-gemini-live-video.py) and [pipecat ESP32 client](https://github.com/pipecat-ai/pipecat-esp32/tree/e70e3b1f0576e502af9e390434e1a6e8a5cd0d2e) | **Optional tested transport adapter**, not five extra competing Xiaozhi voice loops; sample's camera/voice behavior is not automatic local perception or Sense port. Review BSD-2-Clause/MIT per subproject. |
| **Network AV alternative** | [LiveKit ESP32 SDK](https://github.com/livekit/client-sdk-esp32/tree/669ef1382501224fdac93d8d02378fbc5b2cb197) | Investigate if measured Sense latency/transport demands it; not justified by prose alone. Apache-2.0. |
| **Local models** | [Ollama Qwen3](https://ollama.com/library/qwen3), [Kokoro FastAPI](https://github.com/remsky/Kokoro-FastAPI), [YOLO World Ultralytics](https://docs.ultralytics.com/models/yolo-world/), SenseVoice and optional SmolVLM | Reuse existing providers through one hot, bounded shared Mac backend. Validate Mac M1Max model availability, throughput, memory and licenses/weights, particularly five robot contention. Kokoro FastAPI code Apache-2.0; model weights/licenses independently reviewed. |

**Single-owner rule:** do *not* combine Xiaozhi, Pipecat, HF speech-to-speech, Open LLM VTuber and Reachy as five parallel streaming engines. The desired final robot uses **one** audio owner, **one** activity decision owner, **one** motion gateway, **one** per-robot memory writer and **one** group speaker lease. Reuse selected algorithms behind adapters. A small glue layer is appropriate; a new all-purpose agent framework is not.

## Firmware, sensor and electronics libraries worth copying or comparing

| Subsystem | Source | Correct reuse boundary |
| --- | --- | --- |
| VL53L4CD short range | [ST STSW-IMG026 ULD](https://www.st.com/en/embedded-software/stsw-img026.html), [STSW-IMG049 VL6180X migration](https://www.st.com/en/embedded-software/stsw-img049.html), [Pololu VL53L4CD Arduino](https://github.com/pololu/vl53l4cd-arduino) `src/VL53L4CD.cpp`, `examples/ContinuousWithDetails` | Use a vendor-derived tested driver, correct transport status and optical qualification. Pololu LICENSE.txt identifies a BSD 3-Clause Clear derivative license, not plain MIT. Do not change all sensor constants without wiring and geometry tests. |
| Older VL53L0X | [Pololu VL53L0X Arduino](https://github.com/pololu/vl53l0x-arduino), [STM32duino VL53L0X](https://github.com/stm32duino/VL53L0X/tree/49f877aa99664ac0c4275368235f11c4f0c3faf9) | The existing audit found unchecked Wire transaction/count in STM32duino's platform layer; write a checked adapter, not entire ToF algorithms from scratch. |
| TCA9548A | [Rob Tillaart TCA9548](https://github.com/RobTillaart/TCA9548), `TCA9548` examples | Reuse channel switch/scan and bus reset patterns with checked device-level timing. MIT. |
| Heart pad MAX30102 | [SparkFun MAX3010x](https://github.com/sparkfun/SparkFun_MAX3010x_Sensor_Library), basic reading/presence/heartbeat examples | License.md states MIT for software and CC BY-SA 4 hardware, separate terms. Verify purple breakout regulator/1.8V logic before WROOM bus; not a medical device. |
| IMU handling | [BerryIMU official examples](https://github.com/ozzmaker/BerryIMU), [Adafruit LSM6DS](https://github.com/adafruit/Adafruit_LSM6DS) conditional | Identify actual BerryIMU revision/WHO_AM_I, physical output orientation and powered mount; do not copy V3 mappings onto a V1 board. |
| Stepper controller | Existing `StepperDrive`/test suite; compare [AccelStepper](https://www.airspayce.com/mikem/arduino/AccelStepper/) and [AlashStepper](https://github.com/Alash-electronics/AlashStepper) | Keep tested StepperDrive unless benchmark proves replacement safer, nonblocking and easier. AccelStepper GPL3/commercial constraints; AlashStepper MIT but currently a small/new project, not evidence of field maturity. |
| OLED eyes | [FluxGarage RoboEyes](https://github.com/FluxGarage/RoboEyes), [intellar OLED Eye Display](https://github.com/intellar/oled_eye_display), stock Xiaozhi UI | **Choose before final head**. RoboEyes GPL3 license and Arduino AdafruitGFX need port; Intellar MIT 128x64 eyes candidate; stock Xiaozhi UI alone does not fulfill free-running expressive face goal. |
| AFE/wake | [Espressif ESP-SR](https://github.com/espressif/esp-sr) and Xiaozhi existing AFE | Prefer synchronized playback-reference ESP-SR path already in head; do not duplicate an AEC chain or use an echo gate that blocks new user speech. |
| ESP camera / detection | [Espressif esp32-camera](https://github.com/espressif/esp32-camera), [ESP-WHO](https://github.com/espressif/esp-who), [ESP-DL](https://github.com/espressif/esp-dl) | Reuse camera driver and maybe cheap local event models; actual Sense RAM, format, PDM/audio coexistence must be measured. |
| Sensor events for housing | [Tech Talkies wheeled buddy Part1](https://github.com/TechTalkies/YouTube/tree/main/95_Chatbot_on_wheels), [Stackchan-agent sound monitor](https://github.com/botamochi6277/stackchan-agent/blob/main/include/SoundMonitor.hpp) | Touch/roam/attention logic reference only. Tutorial has no cliff interlock, sound-classifier must operate on real post AEC microphone with false-trigger tests. |
| Remote body contract | [VerdureBuddyRover](https://github.com/maker-community/VerdureBuddyRover/blob/main/docs/xiaozhi-mcp-serial-integration.md) | Existing newline UART vocabulary reused, but current local WROOM watchdog/USB rearm and bounded policy prevail. |
| Sensor utility models | [ST VL53L4CD](https://www.st.com/en/imaging-and-photonics-solutions/vl53l4cd.html), [ST VL6180X obsolete](https://www.st.com/en/imaging-and-photonics-solutions/vl6180x.html), [TI TCA9548A](https://www.ti.com/lit/ds/symlink/tca9548a.pdf), [Seeed Sense pin map](https://wiki.seeedstudio.com/xiao_esp32s3_pin_multiplexing/) | Manufacturer source is necessary but does not qualify a random marketplace breakout. |

## CAD and physical assembly sources (do not redraw needlessly)

| Geometry | Provenance and what actually exists | Reuse limit |
| --- | --- | --- |
| Tracked stepper base | [SMARS 28BYJ remix](https://www.thingiverse.com/thing:2778904), [original SMARS](https://www.thingiverse.com/thing:2662828), [wtlx motor example](https://github.com/wtlx/smars-28byj-48) | Original STL saved with hashes; original SMARS NC-SA ancestor terms despite remix's visible CC BY label. Test two motor shaft fit, track wheel registration and supported stopping. |
| Lift and closing gripper | [Bluino](https://www.thingiverse.com/thing:4253681) + [SMARS forklift](https://www.thingiverse.com/thing:3027255) | Gripper CC BY4, forklift NC-SA4; two servo MG90S parts and actual key/candy reach before assembly. |
| Round head and Cozmo influence | [Cozmars V2 editable model](https://github.com/r-cute/rcute-cozmars-model-v2), [Cozmars V3 hardware](https://github.com/hyansuper/cozmars_v3_hardware), [Sparky v0.1](https://github.com/slahiri/sparky/releases/tag/v0.1.0) | Compare original native Fusion/STEP and electronics cavity. Sparky author says not test-printed; hardware CC BY-SA4. Cozmars hardware is not a drop-in to owned Sense/WROOM/steppers. |
| Additional heads | [Tiny Engineer](https://github.com/jamro/tiny-engineer), [EVA](https://www.thingiverse.com/thing:7319190), [FETCH creator build](https://projecthub.arduino.cc/sector_07/build-fetch-an-open-source-ai-robot-powered-by-arduino-uno-q-8092d1) | Inspiration for face/bezel/ears/service access only; Tiny Engineer hardware CERN-OHL-S2, EVA CC BY-SA, FETCH full mech/electronics different. |
| Choreography | [Qubit](https://github.com/0xaiwhisperer/qubit), [Reachy Mini](https://github.com/pollen-robotics/reachy_mini_conversation_app), [chillibasket WALL E](https://github.com/chillibasket/walle-replica) | Learn keyframe/interrupt patterns; Qubit project license not established by earlier tree review; WALL E GPL3 and much larger 12V/7 servo mech. |
| Parallel gripper alternative | [roboninecom gripper](https://github.com/roboninecom/3D-Printed-Parallel-Gripper-for-Robotics-Arms) | Only if Bluino fit coupon fails; license and fit must be qualified before adoption; don't rebuild robot around a new manipulator. |

## All twelve original tutorial videos remain in scope

See the [original video audit](2026-11-03-video-audit.md) for *description/code evidence, source authors and license caveats*; the table preserves their original order. Do not claim full viewing of every second.

| # | Creator lesson | Video and related source |
| --- | --- | --- |
| 1 | Huy Vector tiny WALL E, Sense mechanics/audio | [Video](https://www.youtube.com/watch?v=5MZ6O6yT73M), [guide](https://www.huyvector.org/robots-kinetic/wall-e-ai) |
| 2 | Kênh Sáng Tạo copper Xiaozhi | [Video](https://www.youtube.com/watch?v=aLbg-b4UZb0), [guide](https://ai.kenhsangtao.com/copper/) |
| 3 | Copper ToF anti-fall followup | [Video](https://www.youtube.com/watch?v=R1E3AkfSaIM) |
| 4 | Tech Talkies mini desk tank | [Video](https://www.youtube.com/watch?v=umeCiPdUtFo), [source](https://github.com/TechTalkies/YouTube/tree/main/112_Desk_tank) |
| 5 | Mo-Chan part 3 face/personality | [Video](https://www.youtube.com/watch?v=2JRqNyq6Epk) |
| 6 | Digit by Naz Louis | [Video](https://www.youtube.com/watch?v=vf1qYoM40aQ) |
| 7 | Tech Talkies custom face buddy | [Video](https://www.youtube.com/watch?v=aDaSp6zaqWM), [source](https://github.com/TechTalkies/Xiaozhi-for-XiaoESP32S3) |
| 8 | Tech Talkies buddy V2 stalled motors | [Video](https://www.youtube.com/watch?v=i05wihSkuD8) |
| 9 | SARAS 2 MCP robot tools | [Video](https://www.youtube.com/watch?v=zrvFgxxDrIU), [source](https://github.com/techwithanant/saras_ai_robot_v2) |
| 10 | SARAS 1 actual drive/power friction | [Video](https://www.youtube.com/watch?v=IT1uBUsOmUY), [source](https://github.com/asharma2040/saras-ai-robot) |
| 11 | Qubit desk robot | [Video](https://www.youtube.com/watch?v=MQBUOHRvMuc), [source](https://github.com/0xaiwhisperer/qubit) |
| 12 | Tech Talkies wheeled desk buddy | [Video](https://www.youtube.com/watch?v=ktWnwJ-e-_w), [source](https://github.com/TechTalkies/YouTube/tree/main/95_Chatbot_on_wheels) |

## Other named research leads remain recorded

The HTML's older library includes [StackChan](https://github.com/m5stack/StackChan), [VerdureLab](https://github.com/maker-community/VerdureLab), [ESP SparkBot](https://github.com/espressif2022/esp_sparkbot), [Open Duck Mini](https://github.com/apirrone/Open_Duck_Mini), [Microduck](https://github.com/pollen-robotics/microduck), [PyCozmo](https://github.com/zayfod/pycozmo), [SO-ARM100](https://github.com/TheRobotStudio/SO-ARM100), [Open LLM VTuber](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber), Yumo Cat, Focus Bot, Huy Vector, FETCH, EMO, Cozmo/Vector, Eilik, Mochi, Dogo, AI DeskBuddy, HachimoDock, Tokpet, Sesame Robot, JARVIS Desk Bot, MyDeskRobo, Sentio, AI Pet Robot V2, Xiaozhi-Pet, MoodiMOS, Tiny Touch DeskBuddy, Duckbert, Meta Muse SDK and other creator tutorials. Those project names and concepts remain in [feature register](../source-map.md) / original HTML. Some source URLs or reuse rights were **not independently verified**; do not invent a Github URL or copy source without a license check.

## Actual reuse decision gates

For each chosen module record:

```text
feature_id, repo_url, upstream_commit_sha, exact_source_path, language/platform,
actual_sensor_and_gpio_map, license_and_asset_terms, tests_or_demo_inspected,
ported_file_or_adapter, final_behavioral_owner, cost_ram_cpu_latency_budget,
missing_dependencies, fail_closed_behavior, test_case_ids, measured_result
```

Candidate selection order:

1. Direct existing subsystem that meets the *real end-to-end acceptance* with minimal safe adaptation.
2. Licensed reference that already implements the important logic, port through a small existing interface.
3. Reuse a well-supported vendor driver or model and write only the necessary glue.
4. Custom implementation only if no suitable source exists or existing source violates safety/contract/licensing, with a documented search.

A single star count is not a quality score: Xiaozhi is a popular full-stack base, while highly relevant code such as Stackchan-agent and hudrucan's desk robot are small and require substantially more verification. **A README's proactive label does not equal actual camera-driven unsolicited conversation**. Judge the code and its tests.


---

## Detailed unverified HTML numerical proposals

*Checked source candidates and proposed HTML tuning remain distinct from implemented hardware and measured test results.*


This is the **lossless decision reminder**, not an approved performance specification. The user's full `ESP32 Deskpet Ideas.html` contains detailed proposed values in the current Power, Drive, Cliff, Touch, Audio, Head, Mac and Proactive topics and the later historical research library. Values below are *transcribed as proposed* so they do not vanish behind a generic "research later" statement. Accept only after the actual code, manufacturer data, source license and physical test support them. The [system contract](../product-definition.md), [existing A1–A12](../product-definition.md#acceptance-before-duplication), [acceptance ledger](../records/verification.md) and WROOM safety policy overrule incompatible proposals.

## HTML topic 8: power, battery, startup and safety states

* Proposed rechargeable architecture A: IP5306 I2C keep-on capable breakout, protected high-discharge 1S 18650 holder/cell, switch/fuse/connectors, split logic/actuator return paths, star grounds, charging support and 5V nominal output. The HTML uses an estimated **>=1.85A peak demand**, **2.1A nominal capacity goal**, **3000mAh capacity** and an estimated **$34 delivered** assembly. None is a completed battery or board qualification. Demand may be worse with stalled servos/steppers or camera/audio coincidence. `3000mAh` is capacity, never a charge current, discharge current or safe runtime proof.
* Sequencing states **S1–S8**: startup and supply health, local motor idle, controlled stepper startup, one-servo-at-a-time ramps, loaded handling, low-cell warnings and shutdown with no auto rearm. Keep as a design checklist and implement in the body **after measured loads**, not as magical current budgeting.
* Candidate smoothing includes bulk caps, local decoupling, optional diode isolation `SS34`, low cell ladder, safe charger mode, brownout resets, standalone supply tests and six bench qualification phases. A capacitor does **not** make an under-rated battery/boost output adequate. Verify cap ripple, polarity, leakage/temperature, fuse and wire sizing.
* Proposed component prices and the HTML's `$19.38` five-part core list are **partial line items**, not a $50 verified cart. Current canonical [BOM](../hardware/bom.json) has unknown `unit_usd:null` for several critical items. Keep total and delivered fees unknown until exact variants quoted.
* Preserve the fault policy conflict: body normally maintains grip servo PWM to avoid dropping the payload, but brownout may make any powered grip unsustainable. The HTML suggestion to detach servos during sag is NOT an unconditional safe response; qualify with a physical payload containment strategy.

## HTML topic 9: 28BYJ motor truth and practical gripper

* HTML proposes effective **4076 or 4075.77 half steps per output revolution** instead of blindly hardcoding 4096, a starting speed of **700 half steps/s** and **1000 half steps/s²** ramp, dual half/full-step modes and measurable millimeter scaling. Real motor gear ratios and drive/slip must be measured; current StepperDrive code instead has a **160 half-steps/s effective speed ceiling** and **320 half-steps/s² acceleration**. None of the proposed faster modes is currently implemented or bench approved.
* Preserve exact direction/phase order, power-off coils when safe, partial step hold, stop margin, load matrix, shaft backlash, current soak and multi-motor sequencing. The existing 250ms pulse/watchdog and local cliff latch may **not** be lengthened by an upstream library example.
* HTML proposes grading approximately ten reported MG90S through a ~**30min** intake/range/current/temp/fit program into grades A–X, selecting two sound matched units for the first robot. Real inventory, horns, spline dimensions, gear play, motor stall and heat still unknown.
* Gripper plan: fork doubles as key scoop, grip key by bow and candy by wrapper caps, individual controlled lift and grip sequences, mechanical compliant jaw pads, camera-visible pickup, staged object-present evidence (visual check, optional INA219, contact switch, limit microswitch, FSR). None of these sensors is a substitute for the canonical actual **8/10 keys + 8/10 wrapped candy, lift >=10mm, hold >=3s, place**.

## HTML topic 10: safety sensor array, sampling, calibration

* Four downward corners plus one independent forward range through **TCA9548A I2C 0x70**, five range sensors typically **0x29** separated by mux channels **0–4**; reserve 5–7 for qualified expansion. Suggested scan **~40ms**, downward threshold **baseline +25mm**, debounce and confidence bands are **bench parameters**, never current tested guarantees.
* ST's VL6180X is obsolete, so choose a supported short-range module only after test at actual sensor height, black/white/glossy/transparent surfaces, LED/ambient light variation, minimum useful range, optical windows, orientation and forward/reverse/pivot swept footprints. Change the source driver and calibration data format with part revision; no five-unit blind bulk buy.
* Local body reading freshness/status is more important than a plausible distance value. Any essential sensor invalid/stale/missing, mux read fault, reset or bus corruption latches motion stop; **do not implement** HTML degraded mode that allows reverse after a front floor sensor died or the old JS simulator's automatic reverse/turn.
* Calculate actual `lead >= speed * (sample_age + decision_latency) + coast_distance + margin` in physical units and all legal travel directions, with catch/tether at first tests. No universal stop threshold transferred from YouTube.

## HTML topic 11: touch, handling and unusual contact

* Use owned Adafruit AT42QT1010 head touch and candidate BerryIMU (likely V1); verify touch through actual housing and IMU chip/voltage/orientation. HTML's `SW18010P x2 owned`, `MAX30102 about five owned`, FSR402, piezo, magnetic reed/Hall and belt/tail feelings are *unverified stock or optional hardware*. Preserve all uses in [feature register](../source-map.md) with real count and cost.
* Petting patterns, holding, tap/hold, squeeze, body vibration and sensed putdown need debounce and motion/floor fusion. **A detected pickup immediately inhibits tracks**; putdown never rearms, and a touch is not a motor permission.
* Candidate MAX30102 paw has I2C `0x57`, not Sense GPIO41/42. Its breakout must be inspected for 1.8V logic plus LED voltage; opt-in, nonmedical novelty, avoid logging personal heart signals by default.

## HTML topic 12: echo cancellation, natural interruption, speaker

* Hardware exact Sense PDM `GPIO42 clock / GPIO41 data`, SSD1306 `5/6`, active speaker amp `4/7/8`, UART TX/RX `2/1`. RIO reference's `7/8/9 + SD44` is **not** an interchangeable wiring table.
* RIO software AEC uses a delayed and synchronized playback reference, its default around **90ms** delay is an **unmeasured starting value**, and cited echo reduction goals around **15–25dB ERLE** are targets, not guaranteed results. If residual echo gate mutes the user during TTS, that is a failed barge-in design.
* HTML's proposed A2-BARGE v1 `>=18/20 at 0.5m, >=17/20 at 1m, median <=700ms, p90 <=1000ms` is a **weaker experiment plan**; it does **not** supersede required **>=19/20 audible stop <=500ms, >=18/20 correct new intent and zero false self interrupt in ten minutes**. Record both reported distributions as diagnostics, but never lower A2.
* End-to-end stop includes Silero/other user-speech detector, model/turn epoch cancel, Mac queue cancel, head decoder cancel, **real DMA/I2S flush**, and proof a stale audio chunk cannot replay after new request/reconnect/quiet. Validate with microphone/speaker/servo/camera final enclosure under actual acoustic load.

## HTML topic 13: head, expression, integration and fit

* RoboEyes GPL3 is HTML's **desired expressive engine**, but only stock Xiaozhi emotion/text UI is currently compiled. Choose one licensed expression adapter before final face build; MIT alternative `intellar/oled_eye_display` is a source candidate. Different graphics driver, refresh performance and license terms must be reviewed; do not mislabel RoboEyes as installed.
* Owned **0.96in 128x64 SSD1306** differs from Sparky's v0.1 **1.3in opening**. Compare Cozmars editable CAD/head packaging *first*, then selectively remix Sparky if needed. Head fixed: no added pan/tilt from the two MG90S already allocated lift and grip. Reserve touch area, camera view, microphone acoustic port, MAX98357A and speaker cavity, USB, antenna, optical windows and hat/accessory mounts.
* Stage expression timing for eyes/gaze/listen/think/speak/blocked/quiet/sleepy, with local idle render when Mac stalls. Record actual I2C frame bandwidth and event latency; 60fps full OLED is not assumed.

## HTML topic 14: one Mac brain and five distinct social identities

* HTML suggests **per-robot Pipecat workers plus deterministic Activity Controller plus separate Motion Gateway** and no LLM networking credentials. Treat the "three processes" and "one shared STT daemon" as an architectural comparison, not confirmed efficient implementation. Prefer current Xiaozhi/local-provider adapters, one trusted owner and no model arm access.
* Proposed shared `WhisperSTTServiceMLX` pinned `large-v3-turbo`, circuit breaker to `whisper.cpp` after **2 failures**, probe every **30s**, switch back after **3 good probes**; frame priority conversational > newly addressed > idle/ambient, with provisional STT quarantined from memory. These values are **candidate tunables**, not known current Pipecat API semantics, full-model fit or tests on this Mac. The report's M4 mlx-whisper vs faster-whisper timing is external evidence, **not a measured M1 Max result**.
* Proposed Kokoro 82M / **54 voices**: begin a token-stream sentence chunk around **15 tokens**; performance study **30 chunks ×5 voices ×20 repeats ×3 chunk policies** under cold, warm, and full STT+LLM+VLM contention. Candidate first chunk **p95 <=450ms**, real-time factor **p95 <=0.5**. Measure and listen for boundary artifacts; Piper optional fallback; no guarantee these targets are met.
* Proposed Ollama Qwen-class **8B Q4** conversation vs grammar-limited activity call, SmolVLM2 **2.2B** event-gated vision, local camera cheap gate. HTML estimates **5 camera feeds at 1fps** would overload one VLM (~0.3–0.7 scenes/s claimed), so one shared event clustering layer performs at most one expensive scene description per confirmed event. All performance figures are *unverified on this Mac*; no silent cloud provider substitution.
* Single speaker lease renewed by TTS chunk, not given to model. Deny spontaneous speech by dropping stale/unwanted invitations, not queueing them to surprise the person later. Old turn epochs must be rejected **at the TTS backend as well as the client**. If speaker disconnects, do not have another robot finish its sentence; keep partial delivery as partial.
* Suggested five-camera event coalescing: **3s sliding window**, compatible event types/zones, different sides treated separately; confirmation via **>=2 witnesses or solo confidence >=0.8 or 3-frame persistence**, **>2.5s age -> memory only, never new speech**. Handle monotonic capture clock and network timestamp mapping; verify false merges and splitting before adopting thresholds.
* Candidate memory layout `robots/<id>/{identity.json,facts.json,mood.json,history.sqlite,calibration.json}`, single writer, `witnessed` vs `told_about`, recency/importance/relevance scoring. No shared "everyone personally saw it" pool and no persisted motion permits. Body eFuse full MAC provisioning, mDNS and MQTT control plane are **options**; current static ID device mapping remains valid and no broker requirement is established.
* Proposed measured fleet load: **~13–16GB** working-set estimate, one/two/five concurrent sessions, 45min soak, 10% activity, second test machine or external replay source, overlapping scenario **robot 1 mid-turn + human addresses robot 3 + robot 2 observes event**, disconnect storm **zero stale delivery**, robot 3 p95 <=2.5s proposed. Reject claim "five local Pipecat robots already proven" until measured.

## HTML topic 15: proactive perception, agency, sound, games and location

* Proposed vision gate frame difference **3 frames confirmation / 12 frames release**, ~1fps latest image, possible ~300KB on-head person model with 3 hits and 5min cooldown. All are candidate design points, not measured deployed pipeline. Current Sense camera `CAMERA_GRAB_WHEN_EMPTY` + `fb_count=1`; `GRAB_LATEST` +2 buffers is a different memory/concurrency tradeoff, not automatic better.
* Activity scoring each **30–90s**, local hard veto `fault/stop > explicit human/manual/pickup > busy tool/speech > quiet > activity > idle`, personal curiosity/social/rest, Big Five->PAD affect, boredom dynamics and fun silent choices. No model owns motion or chooses every tick. The source's "no open-source pet does this" is **a research claim, not proven universal negative**.
* Audible non-speech research: double clap = attention, triple clap = stop activity; one whistle band per robot proposed in **1900–3100Hz**, stable **>=350ms** with Goertzel frequency detection. Suppress clap onset from motor thumps, own TTS and knocks; human ordinary speech retains precedence. RGB status "language" is a swappable add-on, not a new user-visible hard prerequisite.
* Peer play is a real activity category, **not** just robot conversations answering human prompts: emotion exchanges, cooperative games, individual identities, memory and private experiences.
* AprilTag pose concept: proposed **50mm** desk/station tags, **80mm** dock tag, a stopped observation fix every **400mm** or **2 pivots**; no tag -> blocked/qualified scan and request operator rather than unbounded blind pivot. Published `esp-apriltag ~2Hz` in HTML is **unverified**. Cellulo microdot mat is a costly unapproved fallback.
* OOMWOO docking concept: IR **NEC bursts** rather than continuous carrier into `TSOP38238` receiver, contacts unenergized until physically verified dock, proposed **10s** charge signal rise and **3** bounded retries. **Not approved on this robot**; charging power/contact electrical safety and collision/navigation need independent design/acceptance. Returning automatically to a person is **not** demonstrated by AprilTag alone.
* Health states `NORMAL -> DEGRADED -> STOPPED -> RECOVERY`, age/quality rather than unchanged value; HTML proposes 50 fresh reads to regain health and some reverse/pivot allowance when one channel dies. The latter **conflicts with this project's canonical fail-closed guard and is rejected**. Logging can have graded health icons, but **movement remains stopped/latching on any essential channel loss** with local USB recovery and new operator enable only.

## Current proactive topic and historical research library: preserve all ideas, not outdated wiring

The current research integration topic explicitly links camera, exploration, audio, sensor expansion and personalities to the original library. The legacy Xiaozhi First/mod packs, Emotion Lab, 6-week schedule, sensor leaderboard/waves, 24 idea chart, specific 9 one-part hacks, 7 code-only wild ideas, Nov 7/9 new finds, creator tutorials, Reddit ideas, Spec Pack, old BOM and forks still have full coverage in [200-entry feature register](../source-map.md) and [131 exact original URL index](../source-map.md). Those source paragraphs do **not** become product requirements or proof each project/tutorial source was downloaded.

The HTML embedded interactive "sensor-to-emotion map" used older cliff sensor/mic choices and could recommend reverse/turn on cliff. Preserve it as a historical interactive design reference only; never copy it into the real WROOM control.

## On every proposed number

For each numerical threshold, commit its origin, operating hardware, independent data, intended test setup, whether **user requirement** vs **candidate suggestion**, confidence and pass/fail evidence. No report's self-label ("approved", "locked", "possible and easy", "verified") overrides a missing inventory entry, absent connected code, battery rating, exact part variant or source license. Trial thresholds required by A1–A12 cannot be relaxed just to match an appealing published demo.
