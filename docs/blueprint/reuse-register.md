# Upstream reuse registry: search, copy, port, test, only then invent

This is the **implementation source shortlist**, not a new dependency dump. The [canonical source map](../source-map.md), [full video audit](../research/2026-11-03-video-audit.md), [guide audit](../research/2026-11-03-guide-audit.md) and all creator URLs in the original user HTML remain historical references. Many projects were partially code-inspected, not built or physically tested here. Repo visibility and GitHub stars do **not** prove licensing, audio performance, edge safety or compatibility.

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

See the [original video audit](../research/2026-11-03-video-audit.md) for *description/code evidence, source authors and license caveats*; the table preserves their original order. Do not claim full viewing of every second.

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

The HTML's older library includes [StackChan](https://github.com/m5stack/StackChan), [VerdureLab](https://github.com/maker-community/VerdureLab), [ESP SparkBot](https://github.com/espressif2022/esp_sparkbot), [Open Duck Mini](https://github.com/apirrone/Open_Duck_Mini), [Microduck](https://github.com/pollen-robotics/microduck), [PyCozmo](https://github.com/zayfod/pycozmo), [SO-ARM100](https://github.com/TheRobotStudio/SO-ARM100), [Open LLM VTuber](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber), Yumo Cat, Focus Bot, Huy Vector, FETCH, EMO, Cozmo/Vector, Eilik, Mochi, Dogo, AI DeskBuddy, HachimoDock, Tokpet, Sesame Robot, JARVIS Desk Bot, MyDeskRobo, Sentio, AI Pet Robot V2, Xiaozhi-Pet, MoodiMOS, Tiny Touch DeskBuddy, Duckbert, Meta Muse SDK and other creator tutorials. Those project names and concepts remain in [feature register](feature-register.md) / original HTML. Some source URLs or reuse rights were **not independently verified**; do not invent a Github URL or copy source without a license check.

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
