# Project decision log

Updated 2026-11-06. This records durable project decisions and superseded choices,
not a transcript. Earlier items are reconstructed from saved project checkpoints
and user instructions; dates below identify records, not invented message times.
Canonical current requirements: [product-definition.md](product-definition.md).
Sources and reuse boundaries: [source-map.md](source-map.md).

| Record | Decision / reason / supersession |
| --- | --- |
| Historical initial robot brief | Camera, screen, speech and real small-object pickup; reuse existing open designs, with small CAD edits only. Original CoreS3 all-in-one estimate was replaced by budget modular components |
| Saved2026-10-28/30 work | Project folder and preserved upstream/CAD sources, assembly/trial records and dual-controller boundary established. Current work preserves those originals |
| Saved2026-11-03 inventory correction | No spare S3 N8R8 was actually owned. Later Sense purchase is the active camera/mic head; WROOM remains body. Feather/USB-C breakout/continuous servo are spares, not mandatory integration |
| Five-core requirement | All five are equally equipped functional robots with different names/cosmetics; initial one-moving-at-a-time tests stage the full group goal |
| Owned actuator revision |5steppers+5ULN boards and roughly10MG90S prompted stepper-SMARS plus lift/grip. Do not force those parts if compatibility would demand major redesign; report the concrete alternative tradeoff first |
| Manipulation | Actual flat keys and wrapped candy; two servos remain lift+closing grip. A Cozmo cube/fork or extra head tilt cannot silently replace this |
| Voice | Ordinary speech must interrupt ongoing robot TTS in build one. A button, special phrase or muted microphone fails. Source inspection/AEC flag is not acoustic qualification |
| Appearance | Rounder head, then Fetch retro-TV, then Cozmo/Vector cues. Compare actual Cozmars head packaging first; unprinted Sparky remains fallback. AI pictures are not fitted CAD |
| Local compute | Shared M1Max/64GB Mac supplies speech/vision/reasoning; no new Pi/Pico/Uno. Local-first remains active; Google optional cloud is not silently enabled |
| Initiative | Notice camera events and choose activities without a voice prompt. Face/sound reflexes, visual attention, activity memory and task execution need separate timing/ownership |
| Motion session | Enable until user pauses/stops; supersedes recurring120/300s renewal proposal. Short per-drive deadlines/watchdog and fault/disconnect/restart cancellation remain |
| Edge sensing (historical proposal, superseded) | The November 11 proposal for eight costly VL53L4CDs and the still earlier VL6180X layout are **obsolete and not current purchasing selections**. The current source and machine plan select **8 generic VL53L0X GY-530 sensors per robot**: four downward cliff sensors, one forward guarded sensor and three left/right/rear diagnostic sensors, routed through **2 TCA9548A multiplexers** per robot. The exact 3.3 V carrier, range at the chosen mounting height, loaded stopping distance and mechanical fit still require physical qualification. See `docs/product-definition.md` and `docs/hardware/full-feature-plan.json` |
| Power/budget | Matched rechargeable1S kit replaces required consumer-bank direction. Exact cell/charge/protection/5V output remains unselected. $50delivered prototype cap includes money already spent; no updated complete quote |
|2026-11-04 source audit | Preserve full supplied-source mapping, not just six chosen repos. Concrete stronger candidates: Google robotics agent observation/event components, HF local voice/vision engine, Reachy activity arbitration, Stackchan-agent reaction controller. These are reviewed candidates, not integrated features |
|2026-11-04 interaction request | Add head touch and six-axis tilt/shake/handling awareness. TTP223+LSM6DS3TR-C is proposed new baseline; evaluate owned equivalents when simpler. RGB/bumper/Hall/light extras remain optional; no visible laser selected |
|2026-11-04 owned-photo revision |18photos group into ten module types; preserve minimumone per type, not18units. BerryIMU (likely older V1) supersedes new prototype IMU procurement pending identity/readout/fit. LSM6 becomes conditional fallback. MAX9814 is spare analog mic, not speaker output; separate interface-unknown camera stays spare. Reed module supports optional magnet-accessory game; do not force all spares onboard or replace qualified edge sensing with PIR/reflective IR. Four fleet IMU equivalents remain unconfirmed if only one is available. [Evidence](hardware/photo-inventory-2026-11-04.md) |
|2026-11-05 speaker amplifier clarification | User reports a separate HiLetgo board marked `pam 84`, likely PAM8403; exact model/count unverified. A PAM8403 can drive a speaker from analog input. Keep it as a reuse candidate if a suitable DAC is available; MAX98357A remains the one-board I2S baseline. The photographed MAX9814 is microphone input. [Parts](hardware/parts.md) |
| 2026-11-06 new electronics | Adafruit AT42QT1010 #1374 replaces the proposed TTP223 purchase for robot one, pending shell and bench checks. IMG_3902 identifies the earlier HiLetgo board as HW-104 PAM8403. One board is visible and the bag says five. Use a suitable DAC for analog reuse or choose the direct I²S path. DRV8833 and FIT0774 are optional. IMG_3905 matches the earlier reed module type and does not raise its stock count. [Photo follow-up](hardware/photo-inventory-2026-11-04.md#2026-11-06-follow-up) |
| 2026-11-06 project layout | Keep the living handbook in `docs/` and implementation in `code/`. Keep automated tests with the implementation and physical trial sheets and past reports in `docs/records/`. The two [entry points](../README.md) replace the earlier scattered top-level folders. |
| Evidence boundary | No complete robot assembled/flashed/physically accepted. Current runtime foundations compile historically; actual ToF I/O/calibration and many behaviors remain unfinished. New notes do not change those evidence states |

## 2026-11-09 complete scope / linear integration request

The user explicitly requested a single **day-zero full-feature** plan and a forward-only build rather than first making a reduced talking robot and later rewriting hardware, AI, memory, autonomy or enclosure. This does not mean physically running every sensor simultaneously before testing, nor does it authorize changing the unchanged $50 delivered cap. [Complete scope](README.md#full-final-project-contract-and-scope) maps the 41-section HTML, 200 individually named requirements/ideas and 131 unique external URLs, and records each unresolved conflict before permanent work. Hard requirements are full pushed context-grounded proactive conversations, natural first-build interruption, persistent independent identity/memory, peer social experience, body local safety, real key/candy pickup and operator-enabled continuing activity. Experimental odd sensors, optional games and advanced docking remain traceable and interface-reserved, not claimed installed; their cost, voltage, geometry and source license must be approved separately. Build one fully representative core and duplicate four after acceptance; no throwaway head/body migration.

**2026-11-21 superseding scope decision:** The prior paragraph preserves
the November 9 history that grouped advanced docking with reserved expansions.
The now accepted first complete pet requires physically safe self docking
with **one separate dock per pet**, eventually five docks, and **one shared
room station**. See feature IDs `F037` and `G029` in
[source map](source-map.md) and the [builder release gate](guides/one-complete-robot.md).
This is a scope requirement, **not** charger, printing, motor or battery
purchase approval. Keep contact power disabled until independent seat,
protection, low cell regulation, NTC and measured charge evidence qualifies.

**2026-11-23 owned station allocation supersession:** The November 3
inventory decision called the reported-owned Adafruit Feather nRF52840 a
spare because it was not a pet head or body MCU. The accepted November 21
scope now uses it as a candidate controller for ONE shared read-only room
station serving five pets, not five new station MCUs. The canonical
`room_controller` has `quantity_per_room=1`, `reported_owned_total=1`, and
normal source profiles `feather_nrf52840_room_bench` and
`feather_nrf52840_room_full`. Reuse requires an inspected PCB and measured
3.3 V and 5 V rails, I2C/UART and USB continuity. This is not an authorized
powered station or a reason to purchase another Adafruit board. The older
USB-C breakout and continuous servo remain separate spares.

The selected per-pet IMU is the MPU6050. The photographed old BerryIMU remains
an unqualified spare, superseding its earlier prototype selection without
erasing the photo and research history.


This is a **planning commitment**, not approval of an exact untested IP5306 board, VL53L4CD module, Mac provider or GPL face engine. No physical test status changes.

## Continuing recording rule

Record meaningful decisions, rationale, source/terms and superseded choices in
these canonical GitHub documents and the repository [parallel chat handoff](reviews/PARALLEL_CHAT_HANDOFF.md);
update inventory only from actual reports. GitHub remains the common source
of truth for separate coding agents and chats. External memory systems such as
Cognee, Mem0, Notion or Obsidian are **optional**, never a prerequisite to
reading or updating the project. Do not copy credentials, raw microphone/video
captures or every one-off status update. Verify the GitHub commit and current
source after a write; confirm any optional memory write by retrieval before
claiming it was saved.


---

## Open conflicts requiring decisions before construction

*Additional planned verification and unresolved blockers; no new physical trials were conducted.*


The user requests a **linear path to the complete feature rich robot**, not a quick cheap prototype followed by a controller or chassis rebuild. Therefore settle foundational uncertainty *before* final assembly, using small reusable tests, technical sources and explicit decisions. If a requirement and a cap conflict, disclose the conflict rather than pretending one can be met by a product listing.

For the original HTML's precise power, motor, voice, Mac fleet, camera, AprilTag, docking and timing values, see the [quantitative proposal appendix](research/2026-11-03-active-pet-sources.md). This file is a **decision queue**, not a record that these choices were already approved. Record chosen part, exact upstream commit or supplier variant, data sheet, physical evidence, unit price/shipping/tax, accepted risk and effect on all five robots. Failed gate means pause final assembly, not secretly drop the requirement.

## Red blockers

| ID | What is in conflict / unknown now | Recommendation and evidence required before lock |
| --- | --- | --- |
| D01 **full spec vs $50 delivered** | Reported Sense listing `$18.87` and HTML power estimate `$34` already total **$52.87**, excluding sensors and electronics. HTML core shopping `$19.38` brings naive distinct sum to **$72.25**; check overlap before counting. No complete dated delivered cart, no confirmed quantity/cell/charger. | Fix exact owned items and line items with quantity/variant/currency/delivery. Preserve **hard experience requirements** and **all experimental idea records**. Do not authorize cap increase, change user requirements or buy an unsafe power alternative without an explicit choice. If simultaneous installation of *all* experimental modules is intended, document a separately costed/space-qualified expanded configuration; it is not the $50 base. |
| D02 **Power architecture** | Historical HTML IP5306 Architecture A and the consumer USB power bank are superseded for the current robot; they are not wiring or purchasing alternatives. The [frozen source architecture](hardware/charging-design-and-validation.md#frozen-source-architecture-for-the-first-robot) is a protected 1S pack with real NTC, BQ24075 power-path candidate, and separately qualified 5 V buck-boost. Exact carrier, pack, protection, converter and loaded performance are still unqualified. "3000mAh" says capacity, not allowed discharge. A 1000µF cap does not create a sustained 2A supply. | Keep D02 open for physical qualification, not architecture selection. Require rated datasheets, fuse/switch, safe harness, load overlap, signed pack current, thermal and bench measurements per the [protected power circuit](hardware/2026-11-17-one-pet-protected-power-circuit.md). No purchase release or powered dock connection until qualified. Document brownout effect on servo holding and payload containment. |
| D03 **floor/obstacle ToF carrier & geometry qualification** | Historical VL6180X/VL53L4CD notes are superseded by line 22: source selection is frozen on **8 generic VL53L0X (GY-530, `0x29`) on `0x70` lanes 0–7** (four corner floor roles, one front obstacle, three left/right/rear diagnostics). Physical carrier VIN/pullups, 14 mm aperture geometry, near-floor return and loaded stopping margin remain unqualified. | Preserve the frozen 8× VL53L0X source choice without reopening sensor selection or evaluating VL53L4CD. Physically qualify exact 3.3 V carrier, enclosure optical apertures, floor return and stopping distance before live edge motion. |
| D04 **actual GPIO/I2C allocation & electrical HOLD** | HTML optional MAX30102 claims Sense 41/42 but they belong to its PDM microphone. All eight `0x70` lanes (0–7, including left/right/rear read-only diagnostics on lanes 5–7) and `0x71` accessory lanes 0–7 (`PN532 0x24` + `MCP23017 0x20` on lane 5, `AS5600` on lanes 6–7, `BMP280` on lane 3) are source-allocated in `docs/hardware/full-feature-plan.json`. | Reject Sense 41/42 heartbeat wiring. Verify exact I2C/regulator breakouts, 1.8V/3.3V MAX30102 rails, per-lane pullups and bus current against the allocated `0x70`/`0x71` map before energizing any lane. Physical electrical qualification remains HOLD. |
| D05 **physical geometry** | Original SMARS 28BYJ and Bluino lift/fork require actual mating; Cozmars first comparison and Sparky fallback have different OLED/camera/servo envelopes. Sparky v0.1 explicitly not test-printed; no assembled fit. | Compare native Cozmars CAD with actual possessed Sense, SSD1306, MG90S and battery; print servo/sensor/window coupons. Keep fixed head + 2 servos for lift/grip. Reserve expansion and acoustic/optical access. Full shell/5 copies wait for dimensioned interference check. |
| D06 **real first-build AEC** | Sense Xiaozhi profile currently uses simplex PDM without synchronized playback reference; RIO's correct-hardware AEC code uses different amp pins and Arduino. HTML 18/20, median 700ms is weaker than official A2. | Choose one actual port design to existing ESP-IDF AFE and `LiveTurns`, preserve current GPIO4/7/8, test audio reference and actual audible DMA flush. Required gate 19/20 ≤500ms and 18/20 correct new requests, zero echo-only interruptions 10min. |
| D07 **head face engine and license** | The original HTML claimed RoboEyes selected; that GPLv3 code was not imported. The selected Sense source now combines the vendored MIT Stackchan HSM with original `face_eye_animator.hpp` and `face_eye_display.hpp` inside Xiaozhi's existing `OledDisplay`/LVGL owner. | Source selection is implemented without a second OLED/I2C owner or head servo. A1 physical HOLD remains until five minutes of Mac-offline gaze/blink, actual 128×64 overlay alignment, 20-expression coverage, status priority and no unexpected motor action are observed on the assembled head. |
| D08 **local Mac stack single owner** | HTML proposes per-robot Pipecat processes, shared MLX Whisper, MQTT, SmolVLM2, Qwen, Kokoro sentence streaming; repo actually has Xiaozhi server and Ollama/Kokoro adapters, tested offline `LiveTurns` but no integrated live vision/proactivity. Claimed 13–16GB fleet capacity and subsecond latencies unmeasured. | Benchmark local provider choices on actual M1 Max with one/two/five active robots and contention before implementing a second voice runtime. Pick a **single audio/turn owner** and provider interface up front. Retain ability to switch provider behind interface, not rewire boards or rewrite controller. |
| D09 **true proactive behavior** | Repo has no live pet/memory/motion state machine yet. HTML's detailed utility scoring, 3-confirm/12-release image gate, 5min cooldown, sound whistles and five-feed clustering are proposals, not measured. | Treat A8/A9 as **hard from first feature complete robot**. Reuse Google camera event, Stackchan HSM, Reachy idle arbitration and Xiaozhi Desk Robot reaction code; select one activity owner by tested scenarios and license. No LLM-controlled motor tools or generic greeting substitute. |
| D10 **group identity and memory** | Current static robot-01…05 IDs and in-memory histories are not persistent unique observed memory. HTML eFuse MAC identity/MQTT/SQLite one writer not integrated. | Keep stable configurable robot IDs now; optional efuse provisioning must be shown correct and mapped. Add private per-robot durable storage with direct-vs-peer provenance, speaker lease and identity isolation before five devices. |
| D11 **servo and actual pick-up** | About ten MG90S reported, grades A-X and 30min protocol are unrun; no force sensor/IN219 in physical BOM; 3D jaw tolerance and keys/candy not tested. | Grade/count real units. Measure lift torque, closure, jaw key bow and candy lip geometry, register calibration, run 8/10 true key and 8/10 candy placements. Reserve optional force sensor mounts before final head/chassis assembly but do not require unquoted add-ons. |
| D12 **full source licensing and pin provenance** | Multiple CAD sources carry CC BY-NC-SA 4, Sparky CC BY-SA, Tiny Engineer CERN-OHL-S, RoboEyes GPL3, software projects MIT/Apache/BSD; original reports sometimes infer rights from public visibility. | Select exact sources/commits and preserve source-chain/asset licenses; fork only permitted bits. Avoid copying incompatible code into MIT-only project. Reuse candidate implementation only after passing existing system contracts. |
| D13 **physical independent safety** | No actual sensor sampling driver/calibration in guarded profile, so boot refuses arm. HTML degrades reverse behavior; old JS simulator auto-reverses. | Never weaken current fault latch. Body must have real fresh sensor status and local stop/rearm before any table drive. The obsolete JS sample cannot instruct firmware motion. |
| D14 **five-unit equality vs progressive proof** | User wants five equally functional core units and eventual independent pet interaction; a one-moving-first test is sometimes mistaken for reducing final goal. | Preserve full function/identical core for every eventual robot. Qualify one to avoid five repeats of a defect. Constrain motion to one robot initially only as a **safety staging mode**; higher concurrency requires separate collision and localization proof, not a false done claim. |
| D15 **privacy/safety for ambient sensors** | Experimental MAX30102, EDA, BLE, mmWave, room radio, thermal, sound, camera, Geiger and mains pickup may gather sensitive data or require unsafe circuits. | Opt-in per sensor/event, raw capture retention off by default, consent and actual legal/electrical review. Reject loose mains antenna. No medical, person identity or precise distance claim without qualified evidence. |

## No silent replacement matrix

| Source proposal or historical choice | Selected or current baseline | Rule |
| --- | --- | --- |
| Freenove/CoreS3/Waveshare head alternative | Purchased XIAO Sense, exact Sense build profile | Do not buy replacement head for voice without proving Sense cannot meet A2 |
| N20/TT chassis | Owned 28BYJ/ULN2003 with SMARS stepper remix | Do not switch motors merely because a tutorial does; compare actual fitted torque/power if incompatibility found |
| Servo head tilt | Two MG90S used for **lift + grip**, fixed camera | Extra pan/tilt is a separately approved hardware variant, never steal required closing gripper |
| Five older VL53L0X downward | Four qualified short floor sensors plus forward VL53L0X | Update driver/mount only after near-field proof; never trade four-corner edge coverage for one cheaper IR |
| Historical VL6180X / VL53L4CD proposals (superseded) | **8 generic VL53L0X (GY-530)** per line 22; physical carrier/optical/margin qualification **OPEN** | Former VL6180X/VL53L4CD proposals are historical only; do not reopen part selection or claim physical compatibility without carrier and near-floor qualification |
| Historical IP5306 Architecture A / consumer USB power bank | Protected 1S + real NTC + BQ24075 candidate + separately qualified 5 V buck-boost; physical qualification **open** | Historical reference only; do not reuse guessed wiring, infer rating from charge current or mAh, or substitute an unqualified board |
| RoboEyes claimed active | Superseded by MIT Stackchan HSM plus original local LVGL eye overlay; GPLv3 RoboEyes remains reference only | The implemented source choice does not establish actual OLED appearance or A1 hardware qualification; keep the physical face gate open |
| 700 steps/s and 4076 rev truth | 160 steps/s effective firmware ceiling and no measured scale | HTML values are experiments, not current speed/current sensor results |
| 18/20 interruption within 700ms | A2 >=19/20 audible stop ≤500ms, >=18/20 new request | No lowering hard gate |
| Automatic reverse on cliff or sensor degraded | WROOM fail-closed latch and USB rearm, remain disarmed | Rejected permanently as described |
| Five Pipecat workers, MQTT or Google paid Live | Xiaozhi/local Mac path + adapter reserve | Optional if measured, not an independent competing voice/activity owner |
| Automatic camera latest + 2 frame buffers | Current `GRAB_WHEN_EMPTY`, 1 buffer | Measure and change only if safe for mic/PSRAM under load |
| Owning five MAX30102 or two vibration boards | Claimed in HTML, not verified inventory | No free BOM entry before physical stock/variant evidence |

## Stage 0 final sign-off checklist

* [ ] Every required product goal from A1–A12 appears in the full build and tests.
* [ ] Each of the **200** named features/ideas has an owner/category and no unsafe deprecated wire instruction is active.
* [ ] All **131 distinct external HTML URLs** preserved in source index; selected ones have pinned code/licensing evidence.
* [ ] Actual component inventory counted, board revisions and source geometry measured, battery pack/cell/charger variant identified.
* [ ] Final prototype BOM (including shipping, tax, already paid Sense and wire/fasteners) either meets the unchanged $50 cap **or** records an explicit authorized new cap/scope with no silent feature loss.
* [ ] One final wiring and mechanically viable enclosure drawing with head mic/speaker, OLED/camera, four floor plus forward optics, 2 servos, cell, USB, sensor expansion and costume clearances.
* [ ] One chosen local Mac speech/VLM architecture and stable event, voice, memory and motion interface, no two turn owners or privileged LLM.
* [ ] Actual acceptance scripts designed for ordinary user speech interrupt, pushed visual event, relevant memory, five-persona peer speech and fall protection.
* [ ] Each unresolved safety/compatibility decision has a named reversible bench test and cannot be bypassed for a polished demo.
* [ ] No raw user media, credentials, file or sensor data is inadvertently put in public/Git repository.

**Lock state now:** ALL unresolved physical and purchase gates remain **OPEN**. This documentation is enough to avoid forgetting requirements; it is not enough to order/final-print with certainty. A 'linear build' means eliminate avoidable redesigns by front-loading system decisions, not claiming that physical research never requires correcting a failed assumption.

## 2026-11-23 accepted first-unit spatial retrieval

The user approved **object find, locally mapped remembered-object return, and safe spatial navigation in the first complete pet**, together with its own dock, protected charging and one shared read-only room station. This explicitly supersedes the earlier product-brief sentence that deferred precise map navigation from the first unit. It does **not** select unrestricted SLAM, blind reverse/spins, automatic physical rearm, person following or fleet simultaneous roaming. Existing A1–A12 still apply; the additional guide 60 trial gate is 9/10 reanchors at most 20 mm translation error, 8/10 remembered-object returns from moved starts, and zero false arrival or unsafe movement in the specified negative trials. The initial source path in `code/laptop/src/desk_robot/route_planner.py` produces read-only bounded route proposals only; integrated pose, calibrated map, detector, actual motor execution and physical repeatability remain open with guides [20](plans/spatial-first-unit/20-body-safety-and-odometry.md), [30](plans/spatial-first-unit/30-sense-camera-and-interface.md), [50](plans/spatial-first-unit/50-map-and-spatial-memory.md), [60](plans/spatial-first-unit/60-object-recall-and-navigation.md), [70](plans/spatial-first-unit/70-fit-power-manipulation-and-dock.md) and [90](plans/spatial-first-unit/90-integration-and-release-evidence.md). Hardware plan roles `as5600` and `encoder_magnets` are not proof of measured wheel displacement or a fitted bracket. The unchanged $50 first-unit delivered cap includes the known $13.67 Sense spend, the dock and the shared station. No supplier checkout, automatic charging or physical motor release is claimed.
