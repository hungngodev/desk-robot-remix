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
| [SMARS](https://www.thingiverse.com/thing:2662828) | Planned chassis, wheels and tracks | tristomietitoredeituit / Kevin Thomas; [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/) |
| [SMARS Gripper Arm](https://www.thingiverse.com/thing:4253681) | Planned three bundled arm/rack/pinion pieces | bluino; [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) |

CAD has not been downloaded or modified. Verify originating attribution/license
for the two separately linked lift files before redistributing them. Record all
future geometry changes. SMARS derivatives retain the noncommercial/share-alike
requirements; this project is a personal experimental build.

Ultralytics/YOLO-World, Qwen3, SenseVoice and Kokoro weights are not redistributed
here. Their code/model licenses and attribution must be preserved when installed
or shared. Generated head build clones retain upstream license files. Do not
publish private configuration or credential-bearing binaries.
