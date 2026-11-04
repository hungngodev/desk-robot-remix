# Video and creator-resource audit — 2026-11-03

This audit covers all twelve supplied video links. The official YouTube watch
pages exposed titles, authors, publication metadata and creator descriptions;
those were fetched again on 2026-11-03. This was **not a frame-by-frame viewing**.
Caption-track requests in the earlier research returned empty responses. The
user's timestamp-level hardware and demonstration claims therefore remain
unverified unless corroborated by a linked creator guide or published code.
No complete transcripts or video copies are stored here.

The earlier explicit inventory correction was that no ESP32-S3 was owned.
**Subsequent update:** the user now reports purchasing a XIAO ESP32S3 Sense
bundle. Keep that as the active head; quantity, arrival and revision remain
unconfirmed. See [current reuse research](2026-11-03-sense-realtime-reuse.md)
and [active inventory](../../hardware/fleet-inventory.json).
Repeated N8R8 text in the pasted summary does not override that correction.

## All twelve videos

Dates below are the calendar dates in YouTube's publication metadata. “Description”
means a creator claim, not an independently measured result on our hardware.

| # | Video / creator / published | Evidence found and useful lesson | What cannot be concluded |
| --- | --- | --- | --- |
| 1 | [[Satisfying] Building a Tiny WALL-E Robot from Scratch](https://www.youtube.com/watch?v=5MZ6O6yT73M) — Huy Vector, 2026-07-31 | Description links the creator's [WALL-E guide](https://www.huyvector.org/robots-kinetic/wall-e-ai). Guide names XIAO ESP32S3 Sense **OV3660**, a 1.54-inch display, two 17–68 rpm motors, a wiring diagram, structural template and web firmware installer. Good compactness and expressive tracked-body reference. | The pasted OV2640 identification is not supported by this guide. A downloadable binary is not proof of available firmware source/license. It does not qualify our pin allocation, gripper or edge protection. |
| 2 | [Chế Robot AI Biết Nói Với ESP32-S3 | Xiaozhi AI Robot | Hướng Dẫn Chi Tiết](https://www.youtube.com/watch?v=aLbg-b4UZb0) — Kênh Sáng Tạo .COM, 2026-07-30 | Creator lists N16R8, 0.96-inch I²C OLED, INMP441, MAX98357A, touch input and 60 rpm drive motors. Links [Copper firmware/guide](https://ai.kenhsangtao.com/copper/). Supports the small-display/audio architecture as a build reference. | Exact glass/PCB model, QR-code reliability and every claimed timestamp were not verified. Listed hardware does not validate our existing WROOM as that S3 head. |
| 3 | [Robot AI Xiaozhi Dây Đồng - P2 - Thêm cảm biến chống rơi TOF050C VL6180](https://www.youtube.com/watch?v=R1E3AkfSaIM) — Kênh Sáng Tạo .COM, 2026-08-02 | Description explicitly adds a TOF050C/VL6180 sensor to the preceding build and links the same guide. Useful inspiration for local floor-distance calibration and an interlock. | A front sensor cannot establish protection during reversing, pivots or arbitrary table surfaces. The claimed 82 mm/100%-speed demo was not independently inspected. A downward beam does not measure objects inside our claw. |
| 4 | [How I Built A Tiny Robot Tank With ESP32 | Complete Beginner Guide](https://www.youtube.com/watch?v=umeCiPdUtFo) — Tech Talkies, 2026-07-25 | Creator links [112_Desk_tank](https://github.com/TechTalkies/YouTube/tree/main/112_Desk_tank). It contains Arduino sources, wiring, BOM and a 3D folder. Description specifies C3, DRV8833, SH1106 and N20 drive. Useful packaging and printable drive reference. | The AUTO mode is a forward-cruise aid with human steering, not evidence of obstacle-aware autonomous navigation or cliff protection. Success is not guaranteed by straight-shaft motor shape alone. |
| 5 | [Mo-Chan Robot - Part 3 | Make Mini Arduino Robot [Arduino Code]](https://www.youtube.com/watch?v=2JRqNyq6Epk) — Explore myChai, 2025-11-12 | Creator lists C3, 0.96-inch SSD1306, **TC1508a** dual driver, 16340 cell, N20s and RoboEyes. Links [Arduino download](https://drive.google.com/file/d/11oFudRz5YSWumYO1XBSqezHFnrLxhGMc/view) and [RoboEyes](https://github.com/FluxGarage/RoboEyes). Useful eye timing and miniature visual language. | The pasted DRV8833 identification conflicts with the description. Availability of a Drive sketch does not establish its license or make an Arduino display library a drop-in ESP-IDF/Xiaozhi component. |
| 6 | [My AI Asked For a Body So I Gave it One!](https://www.youtube.com/watch?v=vf1qYoM40aQ) — Naz Louis, 2026-10-20 | Creator description names **Pololu Zumo 2040 + ESP32-S3 + Gemini** and links [Patreon](https://www.patreon.com/cw/NazLouisYT). Useful example of curiosity, expressive motion and high-level vision decisions over local control. | Public firmware, the claimed exact three-sensor array, ESP-SR/ESP-WHO internals and specific peer-handoff behavior were not established from the description. Do not label the whole build open source. |
| 7 | [I Built an AI Desk Buddy with ESP32 (Xiaozhi + Custom Face UI)](https://www.youtube.com/watch?v=aDaSp6zaqWM) — Tech Talkies, 2026-02-14 | The actual code link is [Xiaozhi-for-XiaoESP32S3](https://github.com/TechTalkies/Xiaozhi-for-XiaoESP32S3), not merely the general video index. Creator describes blinking, listening gaze and speaking-mouth animation with a 128×64 OLED and I²S audio. | A supplied binary is board/pin/build-specific. The description's “runs on ESP32 hardware” does not prove all speech understanding or the LLM runs locally. We must inspect source revision/license before integration. |
| 8 | [How I Upgraded My Tiny Desk Robot | Desk Buddy V2 | ESP32 Robot](https://www.youtube.com/watch?v=i05wihSkuD8) — Tech Talkies, 2026-05-08 | Description explicitly calls this a beta, lists XIAO S3, DRV8833, OLED, VL53L0X and right-angle N20s, and says the motors are too weak for reliable motion. A useful warning to test loaded drive torque at low speed. | Creator says V2 code is **not public yet**. This is not a ready-to-remix working code baseline. It does not prove every right-angle gearbox is weak or that our steppers cannot stall. |
| 9 | [What Happens When You Give Claude a Body? (Code Included)](https://www.youtube.com/watch?v=zrvFgxxDrIU) — Tech With Anant, 2026-06-19 | Description links [SARAS v2](https://github.com/techwithanant/saras_ai_robot_v2). Public README supplies a small motor/camera MCP starter and a serial boundary. Useful separation of deliberation from actuator control. | The public starter leaves MCU firmware to the builder and lists sensors, speech and persistent memory as extensions. Its BOM says **VL53L7CX**, not the pasted VL53L5CX. The full video robot is not reproduced by the minimal repo. |
| 10 | [How I Built ChatGPT AI Robot Which Talks & Moves On Its Own | Hardware Build](https://www.youtube.com/watch?v=IT1uBUsOmUY) — Tech With Anant, 2025-08-15 | Creator links [asharma2040/saras-ai-robot](https://github.com/asharma2040/saras-ai-robot), rather than only the pasted owner alias. Its chapters identify power and friction challenges. Useful motivation for actual load tests. | Description alone does not establish capacitor values, a delivered $150 BOM or universal fixes. A capacitor cannot compensate for an undersized power supply; tape changes traction and stopping distance and is not an automatic remedy. |
| 11 | [Building the Ultimate Desk Robot](https://www.youtube.com/watch?v=MQBUOHRvMuc) — The A.I. Whisperer, 2026-03-03 | Description links [Qubit](https://github.com/0xaiwhisperer/qubit) and [MakerWorld model](https://makerworld.com/en/models/2448809-qubit-the-desk-robot). Useful example of expressive staging and record/replay choreography. | It is a dual-arm desktop system, not our low-cost tracked gripper core. README advertises MIT but its linked LICENSE file is absent from the checked top level and repository metadata reports no recognized license. Public visibility alone does not establish copying permission. |
| 12 | [Desk buddy | Companion robot with wheels | Code & 3D included](https://www.youtube.com/watch?v=ktWnwJ-e-_w) — Tech Talkies, 2026-03-07 | Description links [95_Chatbot_on_wheels](https://github.com/TechTalkies/YouTube/tree/main/95_Chatbot_on_wheels) and [Printables shell](https://www.printables.com/model/1631670-companion-robot-with-wheels). Source has ROAM/PET/ATTN timing and an SH1106-specific face renderer. Useful starting concept for initiative, cooldowns and head-pat reactions; our SSD1306 needs its own display adapter. | Its small README is effectively blank; source inspection matters. The inspected behavior has no cliff-sensor logic. Random roaming is not safe navigation, and a capacitive pad cannot infer a user's location or navigate back to them. |

## Published code checked directly

- [Tech Talkies 95 sketch](https://github.com/TechTalkies/YouTube/blob/main/95_Chatbot_on_wheels/Part1/Part1.ino), content blob `639f6d6027fe1b6d03cbf99819832e765931c056`: three timed states, touch stops the motors, roaming picks movements, no inspected cliff/ToF path. The face uses SH1106 support. This is a useful behavior sketch, not the robot's edge-protection layer.
- [Tech Talkies 112 sketch](https://github.com/TechTalkies/YouTube/blob/main/112_Desk_tank/DeskTank/DeskTank.ino), content blob `16f694a00571c28ce05c8b07394e34c42e2925e3`: AUTO retains forward speed while the person steers horizontally; link timeout stops after 400 ms. Its [README](https://github.com/TechTalkies/YouTube/blob/main/112_Desk_tank/Readme.md) agrees. A communications watchdog does not detect a table edge.
- [Tech Talkies custom-face README](https://github.com/TechTalkies/Xiaozhi-for-XiaoESP32S3/blob/main/README.md): separates OLED, I²S input and I²S output wiring for the bare XIAO S3. It supports the face concept but is not a verified Sense-camera pin map.
- [SARAS v2 README](https://github.com/techwithanant/saras_ai_robot_v2/blob/main/README.md): explicitly minimal motor/camera tools and a builder-supplied MCU serial implementation. Do not substitute prompt instructions for a local motor interlock.
- [Qubit repository](https://github.com/0xaiwhisperer/qubit): checked public top-level listing has scripts, assets, emotes, sounds, print files and tutorial but no LICENSE file. Treat its choreography as an architectural reference until copying terms are established.

## Reuse decisions for our robot

Use the small eyes, restrained pauses, attention-seeking rhythm and bounded
choreography as design references. Keep the existing Xiaozhi audio/camera drivers,
WROOM-owned motor/sensor loop and shared Mac; do not stack twelve firmware projects.
A continuous local behavior loop can create initiative without asking an LLM for
every animation or movement. The LLM can choose a high-level activity, but an
independent local interlock must reject unsafe motion even during camera/network
or speech delays.

The Copper guide exposes wiring and a merged 16 MB firmware image; no source
repository link was established from its extracted page. Its GPIO examples must
not be copied blindly: our current head already assigns GPIO1/2 to UART, and
cliff sensors belong to the body controller's bus. A display and a ToF device may
share one compatible I²C bus; two independently controlling MCUs must not simply
be tied onto that bus.

Keep module identities separate: “Mini L298N” is an inconsistent marketplace
label and does not establish an MX1508, TC1508a, DRV8833 or real L298N pinout.
Likewise, an XIAO ESP32S3 **Sense** bundle includes camera/microphone hardware;
the bare XIAO board does not. Exact camera revisions, accessible pins, SD-card
use and flash layout need confirmation before selecting a head.

Retain the user's two physical pickup targets: flat keys and wrapped candy.
None of these videos demonstrates our combined stepper chassis, MG90S lift,
OLED adapter, mounted head and four-direction edge coverage working together.
A small gripper/head bracket is an allowed remix; a new chassis or expensive
bimanual arm is outside this budget build.

## Evidence limits and licensing

The pasted descriptions were treated as research leads, not authority. No
published timestamp claim is labeled observed unless independently inspected.
No binaries were executed, no purchases made and no unrelated designs changed.
This audit saves summaries and links rather than complete creator descriptions.
Before copying any source or CAD, pin the actual revision, inspect its license,
retain attribution and distinguish software from separately licensed print files.
