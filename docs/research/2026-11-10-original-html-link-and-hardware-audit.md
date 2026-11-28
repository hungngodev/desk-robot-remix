# Original HTML direct audit: parts, ideas and linked projects

2026-11-10. This audit uses the user's **actual** `ESP32 Deskpet Ideas.html` in their file library, not an excerpt.

| Check | Verified observation |
| --- | --- |
| Exact file size | 1,074,994 bytes |
| SHA256 | `12a0068f3bcec7daa6065cc180478294ccc1d0cc5e439250774684f3b2008b5d` |
| HTML topic h2 headings | 44 |
| HTML expandable details | 231 |
| Unique external HTTP(S) URLs | 131 |
| URL preservation in `source-map.md` | 131 L001..L131 indexed, no gaps |
| Original and indexed URL string total length | 8,786 each |
| Original and indexed URL character-code checksum | 821,563 each |
| Feature register completeness | 39 F, 30 B, 75 S, 46 G, 10 H: 200 total, no ID gaps |

**This validates archival index completeness, not that all 131 web destinations were individually read, are still working, or have compatible reusable source code.**

## Material missing hardware decision

**MAX30102 heartbeat paw pad.** The HTML explicitly approved a **one-robot** opt-in fingerprint paw pad and claimed roughly five purple GY-MAX30102 boards were owned. The later independent photo audit could not confirm these. The previous full-feature plan incorrectly moved it into the shared room station. Restored its robot role and reserved **WROOM TCA9548A 0x71 channel 0, device address 0x57** with CAP1188 0x28. The original HTML's wiring suggestion **Sense GPIO41/42 is incorrect** because those pins operate the on-board PDM mic. Confirm whether the owned breakout provides sensor core regulation and safe 3.3V I2C pull-ups. No extra purchase until actual stock counted. This is not a medical instrument.

**Other originally requested ideas that are currently research options rather than selected shopping:** piezo tap sensor (S013), magnetic compass QMC5883L (S019), heartbeat radar MR60BHA1 (S026), BH1750 (S031, partly redundant with APDS9960), DS18B20 tea thermometer (S039), infrared breakbeam for coin-mouth (S058), HX711 load cell (S055), magnetic tic-tac-toe grid (S069), thermal imaging, air quality variants, second directional microphone, four-quadrant light seeking, second screen, servo ears/tail, pan/tilt neck, plant pod, Geiger, lightning, WiFi CSI and desktop agent patterns. These are retained in the 200-idea index. They cannot be treated as purchased or driver-integrated simply because they are in an HTML brainstorm.

**The selected CAP1188 eight petting zones are not the same as the historic MPR121 twelve zone option.** The change in channel count requires a real design check before claiming all physical gestures and pads. Both are research candidates; exact generic breakout supply/pinout matters. Do not order an Adafruit-branded board.

**One robot now; later duplication is not this shopping task.** The full WROOM source implements eight generic VL53L0X channels through TCA9548A 0x70: four downward and one front are critical, while left, right and rear remain read-only diagnostics. All eight lanes exist in code; none is physically qualified. The selected GY-530 pilot carrier still requires measured 3.3 V signaling, optics and fit. The budget is not closed. The old 1S IP5306 suggestion was a recommendation awaiting electrical proof; do not buy a generic fixed-shutoff module or unverified battery protections just because the HTML lists it.

## Check of GitHub URLs in the source file

The 131 URLs include **30 distinct GitHub source repository roots**. All 30 were queried for public repository metadata; **28 returned ordinary metadata, one was a 404 and one returned Moved Permanently from the API**. No source-code license conclusion is drawn for repositories with missing license metadata, and no actual physical hardware firmware is claimed validated.

| Project | Actual check |
| --- | --- |
| `Martvixtor/APDS9960` | GitHub API 404 now. Old direct code link cannot be relied on |
| `YizhengWw/HachimoDock` | GitHub API redirect; browser page resolves. ESP32-P4 desktop pet source, not our Sense firmware |
| `RealDeco/xiaozhi-esphome` | Accessible, MIT. Alternative integration design |
| `dorianborian/sesame-robot` | Accessible, Apache-2.0. Quadruped choreography, different body |
| `AngeloMontesano/MyDeskRobo` | Accessible, MIT. Face and desktop companion architecture |
| `jamro/tiny-engineer` | Accessible, license metadata unresolved. Physical coding-agent reactions |
| `francescopace/espectre` | Accessible, GPL-3.0. WiFi sensing requires license review before importing |
| `collabray/wisense` | Accessible, MIT. Separate optional WiFi CSI sensing |
| `grpcer/tokpet` | Accessible, Apache-2.0. Desktop agent emotion patterns |
| `mzhnk/ai-pet-robot` | Accessible, MIT. Body/memory reference, not a tested hardware drop-in |
| `xinnan-tech/xiaozhi-esp32-server` | Accessible, MIT. Voice backend reference |
| `anthropics/claude-desktop-buddy` | Accessible, license metadata not a standard SPDX ID. PC Bluetooth pet pattern |

Other roots queried: `DirkzeSoft/weather_station_esphome`, `EARTKEY/LF_Alpha`, `TechTalkies/YouTube`, `bmellink/GeigerCounter`, `dreamhunter02/jarvis-desk-bot`, `espressif/esp-who`, `facebookincubator/muse-gadget-sdk`, `ferrolho/vl53l5cx-bno08x-viewer`, `homeautomatorza/esphome-modules`, `innocircuitslab/esp32-s3-offline-voice-control`, `iotdevicesdev/GGreg20_V3-ESP32-HomeAssistant-ESPHome`, `kiryl-bahdanovich/esp32s3-ai-audio`, `oliviazzzu/minimal-embodiment`, `phamhungtien/esp32-s3-health-monitor`, `puha-dev/claude-usage-meter`, `shahdgamal-3/iot-project`, `shredermann-hash/MoodiMOS`, `tny-robotics/tny-360`.

**Remaining 101 non-GitHub-root links** were preserved in the index but were not individually opened and checked in this pass. Product images, Amazon listings and old tutorials may be stale; each candidate must be validated before purchase/reuse.

## Implementation versus aspiration## New physical board issue found in direct manufacturer crosscheck

Seeed's [Sense microSD documentation](https://wiki.seeedstudio.com/xiao_esp32s3_sense_filesystem/) states its GPIO7/8/9 pin sharing and J3 physical solder link default. The proposed speaker I2S LRCLK/DIN on GPIO7/8 and optional RGB GPIO9 therefore require **actual J3 SD physical isolation**, not only excluding the SD driver from software. This is now recorded in the head and assembly guide. No modification has been performed on the user's board.

The linked XiaoZhi v2.5 upstream note says ESP-IDF 6.0.1+ and recommends release/v6.1; our CI already builds the Sense target with ESP-IDF6.1; upstream tag and local overlay revisions still need compatibility checks. Source: https://xiaozhi.dev/en/blog/xiaozhi-esp32-v2-5-release-notes/.

All 131 original external URLs were attempted for current web reachability or original GitHub repository metadata across this audit. Many targets do not yield readable content via automatic fetch (video pages, paid listings, old tutorials, redirects or blocked URLs). **Only URL provenance and GitHub repo metadata have comprehensive verified coverage.** These failures do not establish that the content was read, reviewed for license or compatible with the physical robot. Do not call 131 projects validated; preserve the 200 idea register and original links separately from actual integrated drivers.



CI compiles both current boards, passes Python tests and simulated native C++ tests on the prior PR commit. No complete physical robot has been assembled. Five critical VL53L0X readings, three read-only side/rear VL53L0X channels, MPU6050 identity/raw samples and basic head touch have code; all eight VL53L0X lanes have driver logic but no real carrier electrical or optical qualification. Most additional pet sensors still require their own physical verification. Full echo-cancelled natural interruption, calibrated cliff stopping, grasp and dock autonomy remain unverified hardware acceptance gates. No claim of project completion.

Supplier-neutral technical references: [Analog Devices MAX30102](https://www.analog.com/en/products/max30102.html), [Microchip CAP1188](https://www.microchip.com/en-us/product/CAP1188), [ST VL53L0X](https://www.st.com/en/imaging-and-photonics-solutions/vl53l0x.html), [TCA9548A data sheet](https://www.ti.com/lit/ds/symlink/tca9548a.pdf).
