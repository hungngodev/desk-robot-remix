# Source attribution and license boundaries

Upstream revisions are recorded in `upstream-lock.json`; copies stay in ignored
`upstream/`. New integration code uses this repository's MIT license. That does
not change the licenses of models, CAD, dependencies or copied upstream code.

| Source | Reuse | Terms and notices |
| --- | --- | --- |
| [VerdureBuddyRover](https://github.com/maker-community/VerdureBuddyRover) | UART command vocabulary, protocol/PWM approach; our controller adds bounded pulses, strict parsing, servo commands and watchdog | MIT, copyright 2026 创客社区（Hacker space）; full notice in `licenses/VerdureBuddyRover-MIT.txt` |
| [78/xiaozhi-esp32](https://github.com/78/xiaozhi-esp32) | CoreS3 board/audio/camera/display and server/MCP interfaces retained in separate variant | MIT, 2025 Shenzhen Xinzhi Future Technology Co., Ltd. and Project Contributors; `licenses/xiaozhi-esp32-MIT.txt` |
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
