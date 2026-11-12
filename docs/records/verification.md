# Verification and physical trials

Use the [trial sheet](physical-trials.csv) to record bench results. The
[report archive](reports) contains earlier machine-readable outputs. Entries
in historical reports preserve the commands and paths used at the time.
Earlier firmware artifacts are in the repository’s ignored
`.tools/pre-layout-builds/` folder. Within that folder, `head/` replaces the
old `firmware/head/build/` prefix and `body-platformio/` replaces
`firmware/body/.pio/`.


## 2026-11-12 live source cross-layer checks, not passing hardware evidence

**Canonical PR:** [#17](https://github.com/hungngodev/desk-robot-remix/pull/17). Four GitHub Actions jobs (Python and head, WROOM PlatformIO, Sense ESP-IDF and body C++ sanitizers) still fail before their first recorded step. The connector cannot retrieve the job logs. No new host, firmware or physical trial result is PASS. See the exact [runner diagnosis](../reviews/CI_RUNNER_PRESTEP_TRIAGE_2026_11_11.md) before treating a red status as a compiler error.

| Gate | Added source or regression | Current evidence |
| --- | --- | --- |
| Physical sensor event reaches video | All real initiative event kinds match `TRIGGERS`; `sensor_event` schedules a bounded real JPEG task from existing head, with per-head coalescing and source identity | Source committed, deterministic tests added, **NOT RUN** |
| Live human priority | Genuine VAD preempts a queued sensor camera and already queued model reply; rapid end/start replaces a cancelling speech worker | Source committed, mocked regression added, **NOT RUN** |
| Natural grounded one-pet remarks | Physical sensor and camera model prompts explicitly distinguished; expired local LLM replies cannot speak old event | Source committed, mocked regression added, **NOT RUN** |
| Optional two-pet social play | Explicit local privacy consent, two turns, rotating enabled peer, shared Xiaozhi owner, secondhand peer provenance and concurrent stop cleanup | Source committed, mocked regression added, **NOT RUN** |
| WROOM stop priority | A new actual WROOM fault first attempts to cancel Mac motion permit before optional camera sampling | Source committed, mocked regression added, **NOT RUN** |
| Wiring/source registry | `code/tests/test_integration_contracts.py` checks eight ToF lanes, unique GPIO pins, mux 0x70/0x71 and PN532/MCP23017 lane 5, owner source paths and consent | Source committed, **NOT RUN**, **NOT electrical acceptance** |
| Audio cleanup before lease release | Xiaozhi group speaker requests physical head decoder flush on stream failures or cancellation **inside** the active group lease; proactive TTS also aborts after partial bridge errors | Code and regression cases in `test_streamed_ollama.py` committed, **NOT RUN**, device DMA playback not measured |
| Active five-pet memory context | SQLite reads on worker threads under a five-second deadline with guaranteed owner release if a database fails | Source and `test_api_conversation.py` host cases added, **NOT RUN** |
| Xiaozhi voice tool fail closed | Existing plugin refuses forged device identity, private traceback leakage and automatic retries after Mac HTTP outage | Source and `test_xiaozhi_tool_resilience.py` mock cases added, **NOT RUN** |
| Physical GPIO map versus source | Firmware `BodyPins.h` and XIAO `sense/config.h` pin symbols match machine-readable plan or test fails | Static regression in `test_integration_contracts.py` committed, **NOT RUN**, cannot prove assembled wiring |
| Real optical/audio/power/cad | Five physical pets, real camera/VAD interruption, charge current, final fitted robot/dock and calibrated pickup | **NOT VERIFIED**, still required for assembly-only |

Earlier successfully logged checks remain *historical checks on older commits*, not a certification of this new source. To verify, capture a concrete runner or local terminal command, commit SHA, environment, output, exit code, hardware model, and measured pass/fail before updating this section. Never mark 100 loops or hardware trials done based on source inspections.

## 2026-11-09 independent GitHub Actions host and WROOM evidence

[Host verification run #8](https://github.com/hungngodev/desk-robot-remix/actions/runs/42675991038)
completed successfully against audit commit
`5adb54dd3b54ffa9c511e125099dbf1f5f6f0681`.
The earlier [run #6](https://github.com/hungngodev/desk-robot-remix/actions/runs/42675682437)
had 12 skipped tests because the Xiaozhi device upstream fixture was absent.
The CI workflow now restores the exact pinned upstream and runs those tests.
These are **automatically run on GitHub Ubuntu runners**, rather than copied
from a previous local checklist:

* Python plus head host tests: **116 passed, 0 skipped, 4 subtests passed**.
  The non-failing warning was Starlette's deprecated `httpx` testclient usage.
* Python Ruff lint: **passed** on the specified source directories.
* Body native CTest with address/undefined-behavior sanitizers: **23 of 23 passed**.
* PlatformIO build: **both** the guarded `esp32_stepper` profile and preserved
  `esp32dev` reference profile compiled successfully.

The CI work does **not** restore or compile the actual ESP-IDF Sense head target,
flash a board, supply the missing I2C sensors, or validate microphone AEC,
supply, stopping or gripper performance. The saved Sense firmware artifacts
from 2026-11-03 remain historical evidence, not a new successful head build.

The source document `ESP32 Deskpet Ideas.html` (not checked into Git) was
separately parsed locally on 2026-11-09: JavaScript parsed under Node v22,
567 links and 311 internal anchors were inspected, all internal anchors
resolved and no duplicate HTML element IDs were found. External link
validity, browser runtime behavior and electrical claims were **not** proven
by that static check. See the [engineering research audit](../research/2026-11-09-html-verification.md).

The physical trial CSV still contains zero tested attempts. The robot and
five-unit fleet **remain unverified physically**.

## 2026-11-06 folder reorganization

- From `code/`, `uv run --no-sync pytest -q tests firmware/head/tests` passed
  116 tests and four subtests after a locked dependency install.
- The body’s native CTest suite passed all 23 checks with sanitizers enabled.
  PlatformIO also built the default `esp32_stepper` firmware.
- The Sense overlay installed into a fresh build copy and
  `bash scripts/build_head.sh --board sense --help` loaded the installed
  ESP-IDF and reached the upstream build tool.
- The fleet demo ran a simulated pickup and ten simulated conversation turns.
  The budget and trial checkers read their relocated inputs. The physical trial
  sheet still contains zero attempts.

## Current firmware foundation

Sense8MB/PDM/SSD1306 head target and stepper/DC body profiles now compile.
Portable stepper timing and sensor-fault policy are integrated with local-only
recovery: normal job arm cannot clear a fault. The stepper hardware adapter
provides no sensor I/O or calibration, so it refuses arming. Pet animation,
scheduler, memory and pet-mode motion lease remain unimplemented.

No hardware is flashed, assembled or physically accepted; no geometry changed.
Host tests and compilation do not prove camera/audio, mechanical fit, real sensor
behavior, stopping distance or pickups. See
[firmware progress](../guides/firmware-foundation.md) and
[current evidence](reports/firmware-foundation-2026-11-03.json).

Two stepper originals are saved with hashes; source integrity is not mechanical
qualification. The twelve-video audit covers descriptions/resources and selected
code, not full-frame viewing. The $35.36 target belongs to the earlier basket.
See the [current parts list](../hardware/parts.md) for procurement status.

[Earlier plan-update verification](reports/plan-update-2026-11-03.json) records the prior
documentation-only checkpoint. The historical90 checks below are a separate older
baseline and do not include these new components.

## Product-definition and visual checkpoint — 2026-11-03

User chose a rounder existing head case. [Requirements/acceptance](../product-definition.md)
and [case audit](../research/2026-11-03-rounded-cases.md) now distinguish
requested behavior, current software, measured source geometry and physical gaps.
Sparky v0.1.0 originals and license are saved unchanged; its actual shell measures
about 56×52×54mm, not main/v0.2 dimensions. Source explicitly says not test-printed.

Four [source-based concept views](../cad/concepts/2026-11-03-rounded/README.md)
and an editable native layout were rendered in a separate background Blender 5.2.3
process and visually opened. Head/chassis are actual saved meshes; track/claw/
mount/sensor geometry is illustrative and the bank is not fitted. Originals were
not modified. No print files, fit, manufacturing audit or physical acceptance
result was produced by this visual. No runtime firmware changes in this checkpoint;
earlier software test/build evidence remains dated as above.
[Concept/document checks](reports/product-definition-2026-11-03.json) record source and
preview integrity, local links and the explicit physical-acceptance gap.

## Historical software baseline — 2026-10-30

The plan at that date was five identical cores with removable cosmetics, generic
SG90/N20 actuators, separate camera/OLED/audio modules and existing print files.
**90 checks pass: 60 Python, 20 body C++, 10 head overlay/protocol/snapshot.**
Five-robot mock conversation gives all five IDs two turns. No robot has been
printed, assembled, flashed or physically tested.

The **$36.88 first-prototype parts target** assumes one owned usable power bank
and WROOM. It excludes delivery/tax and includes three allowances; the $50 delivered
cap is not yet established. The $7.11 S3/OV2640 bundle is not qualified against
the compiled Freenove pinout/programming/case. Purchase readiness remains false.
See [ten checks](../hardware/archive/budget-audit.md) and [fleet guide](../guides/five-robots.md).

## Evidence

| Check | Result |
| --- | --- |
| WROOM firmware, PlatformIO 6.1.18/espressif32 6.9.0 | Previously built; exact artifact size/hash in [`build-artifacts.json`](reports/build-artifacts.json); no firmware changes this revision |
| Body portable C++ control tests with address/undefined-behavior sanitizers | 20/20 pass |
| Both head overlays, reversible install/remove/drift, pin/config checks, native protocol/ACK and fresh-JPEG boundary tests | 10/10 pass |
| Active modular S3 head, pinned ESP-IDF release/v6.1 | Build helper exits 0; app 2500528 bytes, merged 8658489 bytes; no flashing |
| Separate CoreS3 head, pinned ESP-IDF release/v6.1 | Build succeeds, app about 2.54 MiB; no flashing |
| Laptop API/control/calibration/transport/conversation/server adapter/budget/trial and head-identity checks | 60/60 pass |
| Earlier upstream Xiaozhi host suite against the CoreS3 build | 143 tests run, 142 pass, one skipped; historical evidence, not rerun for the modular variant |
| Ruff and whitespace checks | Pass |
| Simulation demo | Generated-image pickup logic succeeds; ten total round-robin utterances across five IDs; physical acceptance remains false |
| Budget/trial gates | Reject incomplete quotes and empty physical trial records as intended |
| Source restore | Four pinned upstream revisions verified; source clones unchanged |
| EVA case | Original 300027-byte 3MF saved; four actual meshes, millimeter units, bounds and SHA-256 verified; no geometry edits |
| Gripper/lift sources | Five original STLs saved, binary record lengths/bounds/hashes checked; original-author CC BY 4.0 versus CC BY-NC-SA 4.0 provenance resolved; no slicing/physical checks |
| SMARS sources | Four original matching screwless chassis/wheel/track STLs and original assembly PDF/ZIP saved; structure/bounds/hashes checked; documents not yet reviewed for print quantities |

The modular build is independent of the preserved CoreS3 copy. Its 15 generated
overlay files were compared byte-for-byte with the current overlay sources.
The actual sdkconfig selects 16 MB flash, octal PSRAM, camera SCCB I²C0 with the
new driver, and OLED I²C1. The camera driver's default I²C1 would conflict with
the OLED; explicit Kconfig selection and a compile guard prevent that setting.
Both dependency locks match the pinned project copy. No camera/audio/display
driver was rewritten. Compilation and fake capture/encoding tests do not prove
actual peripheral behavior or case fit.

Case/source records are under `cad/originals/`. All 13 original CAD/document
files matched saved hashes, STL binary lengths and archive/PDF structure checks.
This is source validation, not topology, slicing or physical-fit validation.
The EVA 3MF requires its four objects to be arranged on the print bed.

The skipped upstream host MCP test requires host C++23/cJSON/mbedTLS development
headers absent on this Mac. Firmware MCP code was compiled by the ESP-IDF build.
There is one non-failing Starlette test-client deprecation warning. Host C++
checks use the installed macOS SDK C++ include path described in [the build guide](../guides/build.md).

Firmware hashes and board identities are in [`build-artifacts.json`](reports/build-artifacts.json). Both head
verification configurations have
an **empty bridge token** and disabled wake word; it is a compile artifact, not
personalized local-server firmware. Generate private settings before any flash.
Build output and private settings are excluded from Git.

Useful local checks from the project root:

```sh
uv run --extra dev pytest -q
uv run --extra dev ruff check laptop/src laptop/server/overlay laptop/server/*.py tests scripts firmware/head/*.py
cmake --build .tools/body-host
ctest --test-dir .tools/body-host --output-on-failure
python3 -m unittest discover -s firmware/head/tests -v
bash scripts/build_head.sh --board modular
uv run desk-robot --config config/fleet.simulation.toml demo
python3 scripts/check_budget.py
python3 scripts/check_trials.py
```

Use the C++ include workaround in the build guide if the local compiler cannot
find standard headers. The upstream suite is run from its build copy with the
coordinator Python and the same include-path workaround.

## Five-unit additions verified 2026-10-30

- Two-to-five participants; distinct IDs, bounded dynamic limits (six/six/eight/ten),
  independent histories, every utterance delivered digitally to all peers.
- No overlapping transmissions; all-five mute/session cleanup on completion,
  cancellation, repeated stop, a canceled stop caller, stopped queued speech,
  encoding interruption and disconnected/replaced heads tested.
- API/CLI reject duplicates, oversized groups and invalid turn counts; legacy
  pair limits retained. Hardware fleet examples have motion off and blank real
  device IDs; each duplicate still needs its own measured calibration.
- Missing credentials append without rotation, reject symlinks/duplicate entries,
  retain existing file bytes and use mode 0600. Three new fleet credentials were
  added to ignored local.env; all previous content preserved and no values shown.
- Private head settings resolve the selected fleet's exact credential name.
  Temporary fifth-head fixture verifies ID/token selection, stale-setting removal,
  unchanged public config, restrictive permissions and no token output.
- Named head/power/current readiness gates prevent an allowance-based cheap list
  from being reported as order ready. Original CAD remains unchanged.

Current commands: `.venv/bin/pytest -q` (60 pass), Ruff plus whitespace checks
(pass), `ctest --test-dir .tools/body-host --output-on-failure` (20 pass), head
unittest suite (10 pass, with the documented local SDK C++ include path). No
runtime firmware source changed, so prior head/body builds are preserved rather
than presented as builds for the unqualified cheap camera board.

## Scope and quality review

The final integration keeps the stock camera/audio/display drivers and a unique
board identity, and adds a version-checked reversible overlay. The body has a
strict bounded parser, boot disarm, independent drive deadline and watchdog.
Invalid commands/status polls do not renew control. Watchdog keeps last servo
PWM; explicit disarm detaches. An uncertain ACK is never retried as movement.

The head starts its bridge after Wi-Fi/lwIP initialization; camera capture runs
outside the control HTTP task, and JPEG storage is released before deleting the
FreeRTOS task. Camera snapshots and upstream capture/explain share one lock.
The modular snapshot adapter captures anew before encoding, rejects failed or
unsupported frames and bounds encoded output. The OLED initially shows stock
monochrome emotion glyphs/text; smooth EVA-style eyes remain a later adapter.
Normal voice motion goes through the coordinator; raw head motion tools are
opt-in debugging to avoid competing commands or a stop that later resumes a job.

The coordinator consumes a short, per-robot operator permit, bounds job duration,
cancels on keepalive failure and sends stop on exit. Tests exercise invalid
calibration, wrong ACK/identity, camera/lost-target failures, cancellation,
deadlines and conversation limits. Model credentials cannot enable movement.
The speech adapter checks selected device identities, suppresses acoustic input
while routing digital transcripts and reports transmission rather than measured
playback. These are software checks and source review, not independent hardware
or mechanical certification.

## Still unverified / next actions

- Review original assembly documents for print quantities/orientation; perform
  slicer/topology/fit checks. Source files are collected, not edited or sliced;
  Fusion MCP was unavailable; no geometry changes have been made.
- Measure actual servo fit and flat-key floor clearance, print and bench-test the
  gripper. Perform ten trials per key/candy category before the full build.
- Qualify the cheap head board, actual generic driver package, motor/servo loaded
  currents and existing power bank rating/weight/mount. Finalize speaker mounting and
  delivered charges under $50; $36.88 is a target with allowances, not a cart.
- Confirm exact selected camera sensor/lens, display PCB mount, speaker size and
  head-to-rover bracket/clearance. No component is a measured case drop-in yet.
- Bench-test the compiled modular S3 head and fresh-JPEG adapter on actual
  modules. Confirm OLED address/orientation and camera sensor/byte order. The
  old CoreS3 image cannot be used on the Freenove board.
- Confirm the real WROOM board/USB port. No serial port has been selected and no
  firmware uploaded.
- Verify voltage stability, current/temperature, stopping time, motor polarity,
  camera frames, microphone, speaker and UART on real hardware.
- Install/run Qwen3, SenseVoice, Kokoro and YOLO-World weights/providers. They were
  not downloaded; FFmpeg is currently absent. Full voice/vision inference has not
  been exercised. The base demo uses mock speech and generated images.
- Measure camera geometry and raised-jaw visibility. A planar projection and two
  image detections can misidentify a pickup; human physical trials remain separate.
- Duplicate the validated core four times only after robot one achieves >=8/10
  per category. Test all-five addressing, physical audio timing, disconnects,
  cancellation and cosmetic clearance. Exact owned fleet inventory is unknown.

`physical-trials.csv` is an empty recording template. [`physical-summary.json`](reports/physical-summary.json)
correctly records zero actual attempts and no physical acceptance pass.


---

## Expanded full robot and five peer acceptance cases

*Additional planned verification and unresolved blockers; no new physical trials were conducted.*


No test is a "pass" merely because it appears in this document. Every result is initially **NOT ATTEMPTED** unless the original repo has an explicitly named host-only result. Keep raw measurements, recordings only with consent, commit hashes and per-unit calibration. Do not fabricate attempts or set the existing `docs/records/physical-trials.csv` to passing values.

## Evidence states

| State | Meaning | Cannot assert |
| --- | --- | --- |
| `concept_recorded` | Named idea is present, source/link/proposed value retained | That source is safe, licensed or executable |
| `source_inspected` | Named code/README/datasheet and pin/license checked at specific revision | That the code runs on this board |
| `host_software_passed` | Specified CI job and exact commit green, skipped tests reported | Physical robot safety, audio echo or motor torque |
| `firmware_build_passed` | Correct selected board firmware actually builds at pinned toolchain | That firmware flashed, sensor connected or voice worked |
| `bench_passed` | Real components measured under documented safe stand conditions | Real world operation on any surface/geometry |
| `assembled_robot_accepted` | One final robot passes all mandatory A1–A12 and special gates | Fleet equivalence |
| `fleet_accepted` | Five separately verified units pass identity, speech, social and applicable motion tests | Unrestricted simultaneous roaming, auto docking or all experimental sensors |

## Canonical product tests A1–A12, not negotiable

| ID | Test setup and minimum pass bar | Data to save |
| --- | --- | --- |
| **A1 Face/offline** | Five minutes stationary while Mac is delayed/disconnected. Local blink/gaze/expression stays responsive, no unsolicited physical motion. | Head build SHA, timestamps, FPS/heap, sample animation and no drive pulses |
| **A2 Audio/quiet** | Continuous ordinary speech over robot TTS, no button/phrase. **At least 19/20** trials visibly/audibly stop TTS in **<=500ms** from user speech onset. At least **18/20** recover intelligible *new* request including beginning. 10min echo-only robot speech: **zero false self-interruptions**. Ten-minute quiet mode: no unsolicited speech/motion. Test sustained turns, different users, 0.5m/1m, camera and active WiFi, then motors on a stand. | Speaker acoustic capture/stop latency, VAD/AEC reference logs, first-word transcript, false events, actual DMA/transport flush completion |
| **A3 Control authority** | In simulation operator pet enable stays valid beyond **300s** without reauthorization, until paused/stopped. Fault, stop, reconnect, restart and lost link cancel drive; manual/pickup preempt; no model/reconnect arming; 250ms pulses and 500ms watchdog still enforced; queued canceled activity never runs. | Trace of identity, control owner, permits, status, safe outputs and every denied command |
| **A4 Edge safety** | Every front-left, front-right, rear-left, rear-right and forward sensor invalid/stale/disconnect/mux fault tested. Tether/catch fixture. For all permitted forward/reverse/pivot and supported surfaces, measured detection + decision + coast leave positive margin before any support footprint crosses edge. Recovery **never** automatically reverses or rearms. | Sensor frame timestamps/validity, phase timing, measured wheel coast/sweep, surface/light, lead calculation, fault latch and local recovery |
| **A5 Real manipulation** | **>=8/10 actual flat key** and **>=8/10 actual wrapped candy** *independent* trials. Each real success moves object **>=10mm** up, retains **>=3s**, then places intentionally. Human-assisted or uncertain attempts count as failure. Blocks and magnetic cubes cannot replace required objects. | Object dimensions/mass, calibration, frames, true lift/hold/placement, slip, attempts, failed/assisted flag |
| **A6 Loaded power/mechanics** | Combined tracks/servo/voice/WiFi/camera operate within actual cell, regulator, wiring and module ratings without resets/brownouts, loose mounts, unguarded motion or invalid sensor views. | Voltage at logic/actuator loads, continuous/peak current, temperature, stall response, fuse/switch, camera/gripper occlusion, physical dimensions |
| **A7 Five peers** | Five separately identified physical robots complete 10 total coordinated utterances, exactly one speaker at a time, correct digital peer transcripts, no cross-head command/secret leak, no unpermitted motion; stop and reconnect cleanup. Calibrate and stop-test each unit before its first physical motion. | Per-robot ID/head, microphone state, speaker lease, turn ordering, failed/disconnected unit, secrets isolation |
| **A8 Independent activity** | Within five minutes of stationary non-quiet pet mode at least one attention, curiosity, rest or social activity **starts without a new user prompt**. Fleet spontaneous speech respects initial **>=120s** group cooldown. A local blink alone is not meaningful contextual speech proof. | Chosen candidate, reason, state, vetoes, event/clock, action/audio output, prompt provenance |
| **A9 Pushed visual context** | Person, hand, key, wrapped candy or scene change shown **without speaking/button** produces fresh camera observation and suitable reaction. Repeated stationary sighting not repeatedly announced; stale/disconnected frames cannot trigger scene claim/action. Quiet suppresses unsolicited speech. Concurrent audio/camera measured. Five camera views deduplicate one real event into at most one group announcement. | JPEG capture timestamp (separate from receipt), fresh/old/duplicate frame ID, semantic evidence, language accuracy, cooldown, speaker owner and latency |
| **A10 Head touch** | Real through-case pat/tap/hold detected, false bounce/repetition rejected; touching during exploration locally pauses before reaction; cannot arm/rearm. | Touch traces, shell/hand test, debounce, motion stop time, missed/double events |
| **A11 Tilt/handling** | Actual IMU revision identified; deliberate tilt/shake/suspected pickup and placement distinguish normal motor/servo vibration. Unsafe/held state inhibits tracks. Putdown/reconnect/reboot does not restart canceled motion. | Gyro/accel readings, floor corroboration, thresholds and confusion counts, safe outputs |
| **A12 Optional sounds/light** | If installed, loud sound/clap/whistle/LED behavior does not false-trigger from own speech/drive, has user opt-out and quiet rules, and conforms to pin/current limits. No audible signal itself authorizes movement. | Mic class trace, false positives, LED duty/current, thresholds and privacy state |

The current build has **no A1–A12 physical pass**. Historic host and CI checks test only parts of A3, cancellation state and protocol.

## Full experience scenarios beyond isolated A8 and A9

| ID | End-to-end story required | Must fail if |
| --- | --- | --- |
| `E01` | Robot sees a new key without a spoken command, becomes visually curious, comments accurately, remembers *its* observation and offers a reasonable next activity | Generic timer greeting, stale frame, hallucinated object, secretly armed tracks |
| `E02` | During that unsolicited sentence the human interrupts by ordinary speech. Old TTS stops within A2 gate, first words of human request captured, new turn takes ownership. | Mic muted by residual echo gate; Python queue cleared but ESP speaker continues; new request is lost |
| `E03` | Five camera feeds observe the same moving person. One group representative speaks. Each robot retains exactly its own actual observation provenance; peers receive labelled digital updates. | Five greetings, duplicate event flood, peer memory falsely recorded as personal eyesight |
| `E04` | Human enables quiet while unsolicited response is queued or playing. All pending spontaneous speech invalidated and no deferred continuation; local eyes may continue. | Stale callback later announces, speech queue resumes after reconnect |
| `E05` | Robot has a distinct personality and refers to a previous real encounter with correct robot/person uncertainty and time context | It manufactures a false memory, mixes identities or stores raw private footage by default |
| `E06` | Human manually enables pet exploration for >300s, robot periodically observes, looks, moves in bounded pulses and safely stops on any edge/health fault until operator recovery | LLM obtains motion authority, session silently expires every 120s, fault yields automatic reverse |
| `E07` | Robot can accept touch or handling while moving; tracks stop *locally* before it reacts or speaks, with no auto-resume on putdown | Event is handled only on Mac, robot reverses away from contact without coverage |
| `E08` | Five different robot voices play a cooperative game with ten digital turns, distinct histories and no acoustic self triggering | Duplicate transcript, two simultaneous TTS speakers, peer hears other robot as human |
| `E09` | Robot is asked to pick flat key and candy through existing camera/jaw sequence, reports failure truthfully, never claims grip solely from a servo command | Human assisted motion counted as independent success or object not physically lifted |
| `E10` | Mac/server disconnected: head continues safe local eyes, WROOM stops tracks immediately, no speech/motion retry until explicit recovery | "Offline" reported as working LLM, reconnect autoruns old activity |

## Proactive conversation quality tests, not just "said something"

A spontaneous comment passes *semantic grounding* if the phrase is supported by one fresh visual/sensor event, matches the correct object/person/action and does not assert nonexistent geometry/identity. Record human-rated `correct/relevant/uncertain/false` with representative real scenes and at least five repeated exposures. Compare generic scripted greeting baseline against event-grounded and memory-grounded speech. Define a meaningful false initiation ceiling from observed trial data *before* tuning it to pass; no fictitious threshold without samples. Distinguish `noticed`, `considered`, `silent_acted`, `spoken`, `suppressed` and `rejected` in event logs.

Five peer tests also need fairness: one robot cannot monopolize invitations, a quiet robot cannot be awakened by peer noise, and distinct voices/memories cannot silently leak private context between characters.

## Performance and resource budget tests

| Test | What to measure | Do not assume |
| --- | --- | --- |
| Audio p50/p95/p99 | Ordinary speech onset -> audible stop; first audio chunk; full real-time factor and echo reference drift | RIO ERLE 15–25dB guarantees success in this enclosure |
| Vision pipeline | True source capture time -> event -> local VLM result -> speech; stale rejection; false positives | 1fps means real-time comprehension or CPU can handle five live VLM frames |
| Shared Mac load | One, two and five active robots; STT + Qwen + VLM + Kokoro + video at simultaneous worst plausible demand; memory, thermal, latency | HTML's 13–16GB process estimate or MLX benchmarks are measured on this M1 Max |
| ToF | Optical mount at actual height and surface, read/status/age per channel, whole array worst age, I2C errors, stop margin | A mux makes simultaneous 40ms sample or a prior video threshold transferable |
| Power | Start, idle, speaker peak, two steppers, servo lift/grip, network peak, charge, undervoltage and dropout | IP5306 chip current rating equals a particular cheap breakout's safe 5V output |
| Mechanical | Servo spline, jaw closure, key/candy reach, lift, camera FOV occlusion, costume/tip stability | Printable STL, rendered overlay or successful motor PWM proves fit |
| Storage/memory | Per unit preference persistence, database corruption fallback, atomic write, cross-robot segregation, raw media retention off | Latest LLM reply represents persistent memory |

## Optional sensor expansion gates

Every installed optional device from the feature register must pass five common gates: **identified breakout and voltage**, **mechanical/electrical pin+bus+power and address compatibility**, **licensed known driver**, **bounded typed event with calibration/fault/quality**, and **actual scenario showing benefit without compromising A1–A12**. Specifically:

* Heart MAX30102: measured contact/quality with consent; a valid hardware signal is not a diagnosis. No head mic pin takeover.
* MPR121/APDS9960/SHT4x/BerryIMU/BME/INA219: I2C address and regulator/pullups, read status, aging and independent bus failure.
* Clap/whistle: post-AEC false positives in speech/music/drive, does not stop normal human conversation or arm motors.
* FSR/piezo/reed/Hall/magnets: benign actuator EMI/touch false signals, case fit and no spontaneous motion permission.
* AprilTag/docking: actual mapping error and fiducial uncertainty, safe swept path, charging contact and disconnection policy; none implied by a demo video.
* Thermal/gas/CO2/EDA/radio/Geiger or unusual environment: privacy/safety/licensing/energy reviews before any sensor wiring or claimed measurement.

Keep optional module reports separate from physical core acceptance. No physical expansion can bypass a failing required gate.

## Evidence record contract and template

Use `docs/records/physical-trials.csv` for actual trial rows; do not overwrite its schema. A useful accompanying run manifest records:

```text
run_id, timestamp, commit_sha, robot_id, build_and_tool_versions, board_revisions,
sensor_part_number, circuit_revision, calibration_sha, surface_and_lighting,
person_and_audio_distance, test_case_id, attempts, passes, failures, measured_metric,
threshold, bench_vs_simulation, safe_fixture, objective_evidence_path, reviewer,
acceptance_state, corrective_action
```

Only measured evidence may transition to `bench_passed` or `assembled_robot_accepted`. Photograph/test fixtures and local records must not expose private credentials, raw personal audio/video without consent or unredacted user data.

## Minimum CI needed to enforce full features

The [existing host workflow](../../.github/workflows/host-verification.yml) already runs Python/head checks, body C++ sanitizer tests and WROOM PlatformIO compiles; it is NOT the complete final CI. Add new dedicated tests alongside implementation for:

1. Sensor fake-bus invalid/NACK/stale/status, fault latch and local USB rearm after safe frames.
2. Proactive camera producer, frame age, dedup, real scene event, suppressed busy and quiet state.
3. Per robot memory provenance, atomic persistence and no cross-robot identity contamination.
4. Utility picker reproducibility, human/stop/fault preemption and no model motor credentials.
5. Single speaker lease and peer digital messaging even during human interruption/disconnection.
6. Actual provider-side cancellation, device FLUSH, delayed audio chunk rejection and model busy until playback finishes.
7. Build/flash task for the real XIAO Sense ESP-IDF target with pinned upstream/toolchain. CI build is not an acoustic acceptance substitute.

**Exit of final robot one** is all A1–A12 measured on final hardware plus E01–E10 experience evidence. Then test each duplicate and fleet goals before saying the project is completed.


## 2026-11-10 ten connected engineering passes, not ten physical trials

The consolidated PR #17 now includes code and tests for these connected paths:
WROOM latched fault to Mac job cancellation; Pololu VL53L4CD and OzzMaker
BerryIMU identity verification; native touch to Stackchan OLED reaction;
fail-closed head fault display; per-board Sense AEC reference delay; replay
resistant JPEG completion metadata; correct distinction among own utterances,
heard peers and sensory evidence; continuous operator-enabled but physically
gated exploration; shared real WROOM health verification through grip and
placement; and full five-robot simulated conversation, local private memories
and single moving pet acceptance tests.

All changes target the user's existing **full five-pet feature requirements**.
The new real hardware exploration default is locked until measured swept path
clearance and current floor/IMU calibration, not because exploration was
removed from the product. The real gripper and microphone still need their
specified 8/10 key, 8/10 candy, 19/20 voice interruption, and five unit trials.
Do not stamp these passes green from older runs: check GitHub Actions against
the *final PR #17 head SHA* and retain all physical gates as pending until
independently recorded evidence exists.


## 2026-11-11 docking GPIO sample provenance and realtime model handshake review

**Actual GitHub Actions outcome:** [run 43100939229](https://github.com/hungngodev/desk-robot-remix/actions/runs/43100939229), PR #17 commit `19e0a1a6efa2f971dbb667443c6ac8f025ebe5d8`. All four jobs (Python/head, C++ host, WROOM PlatformIO, Sense ESP-IDF) concluded **failure**, with **zero steps reported** and job log endpoint returning `BlobNotFound`. That means the run has **NO usable test execution evidence**; do not attribute the failure to source without a log. No new passing build or physical trial was observed from this revision. Re-run or perform an actual local build before accepting software.

**Docking readout flaw found:** Three identical cached `/api/aux` results previously counted as "stable three samples" despite no evidence of three new MCP23017 transfers. New firmware `DockPinRaw.sample_seq` increments only after `GPIOA=0x12` completes; WROOM UART reports `dock.seq` and `dock.age_ms` within the existing 1100-byte response. Mac source validation rejects missing/future/outdated or unsequenced samples; independent diagnostic requires three strictly increasing hardware sequence IDs and matching contact / PGOOD / CHG states. Host mock test now simulates MCP23017 success and I2C failure without incrementing sequence. Python tests include repeated, reordered, stale, changed and forged source cases. **Code and tests committed, not run.**

**Bounded UART capacity source audit:** after adding `seq` and `age_ms`, the `BodyControl.cpp` auxiliary format string has 44 conversions. A source-based, intentionally oversized string substitution with 10 digits for every unsigned field and `-2147483648` for every signed field yields a 1073-byte JSON payload, below `kReplyCapacity=1100`. This is a static worst-case inspection, **not** a compiled host formatter test or byte-for-byte serial measurement.

**Upstream audio contract reviewed:** [vLLM Omni realtime-duplex API](https://github.com/vllm-project/vllm-omni/blob/main/docs/serving/realtime_duplex_api.md) documents native session-created capability negotiation, 16kHz input PCM, 24kHz output PCM, output identity and model-owned barge-in. New adapter `verify_native_server` fails closed on wrong model, absent native-duplex capabilities, wrong chunk period or incompatible PCM rates before microphone streaming. A 15-second per-device retry backoff retains a bounded error diagnostic rather than creating one failed WebSocket per incoming audio frame. The official [MiniCPM-o 4.5 recipe](https://github.com/vllm-project/vllm-omni/blob/main/recipes/OpenBMB/MiniCPM-o-4_5.md) requires a supported Linux GPU setup; **macOS M1 Max serving is not established**. Native voice and acoustic interruption remain unverified.

**Reproducible commands for actual verification** from `code/` with dependencies installed and pinned fixtures restored:

```sh
uv run --no-sync pytest -q tests/test_dock_evidence.py tests/test_dock_charge_pins.py tests/test_aux_telemetry.py tests/test_native_omni_xiaozhi.py tests/test_server_bridge.py
uv run --no-sync ruff check laptop/src/desk_robot/aux.py laptop/src/desk_robot/dock_evidence.py laptop/server/overlay/desk_robot_native_omni.py tests/test_dock_evidence.py tests/test_native_omni_xiaozhi.py
cmake -S firmware/body -B /tmp/desk-robot-body-host -DBODY_SANITIZERS=ON -DCMAKE_BUILD_TYPE=Debug
cmake --build /tmp/desk-robot-body-host --parallel 2
ctest --test-dir /tmp/desk-robot-body-host --output-on-failure
uvx --from platformio==6.1.18 pio run -d firmware/body -e esp32_full
```

**Physical acceptance remains zero:** Neither a BQ24074 CHG indication nor three distinct GPIOA reads measure actual charge current; no battery protection, power-path, thermal or connector measurement was conducted. No terminal dock motor command, print fit or voice playback ACK was promoted to `ROBOT_VERIFIED`.


## 2026-11-11 registered five-pet human voice and WROOM dock monitor source inspection

This check was conducted by comparing **current GitHub branch file contents** in the same revision (not by running the robots). All 10 static source-consistency assertions returned true: full `esp32_full` requires dock GPIO, local WROOM validates nonzero sequenced samples newer than 500ms, any seat or PGOOD latches motion stop, C++ tests cover installed/missing/hot-removed cases, the pinned Xiaozhi VAD gate uses current authenticated connections and clears on disconnect, MiniCPM output START and each Opus packet obey that gate, tests cover spoken/start/packet races, all eight selected VL53L4CD lanes are represented correctly, PN532 is explicitly not integrated and physical trials remain zero, and source-manifest regression tests cover the same implementation evidence.

**This is a STATIC audit, not `HOST_TESTED` or `FIRMWARE_COMPILED`.** The latest PR #17 workflow run [43110335948](https://github.com/hungngodev/desk-robot-remix/actions/runs/43110335948) finished with four failed jobs. Job step records remain absent and earlier log downloads returned `BlobNotFound`; no passing Python, C++ or ESP32 compile can be asserted. The full read-only expansion bus and actual purchased carrier wiring still need physical testing. The power charger, gripper fit, dock contact and original licensed mesh assembly are not completed by these safety reviews.


## 2026-11-11 Reachy Mini source and contextual initiative review

Source inspection retrieved **official** `pollen-robotics/reachy_mini` agent skills and `pollen-robotics/reachy_mini_conversation_app` including its current `moves.py` owner, local candidate VAD audio ducking, profile and camera tools. Also inspected the community `yaseminozkut/judgy_reachy_no_phone` YOLO detector's trigger confidence and persistence. Research mapping and papers are committed at [Reachy Mini proactive reuse review](../reviews/REACHY_MINI_PROACTIVE_REUSE_2026_11_11.md). This is source research only; no Reachy hardware, package or new runtime was installed.

The Mac `PetController._initiative_evidence` now uses the existing low-cost contextual gate before a spontaneous LLM. It requires source-specific confidence for camera categories, validates sensor event kind and finite confidence, keeps quiet/duplicate/fleet cooldown checks, and refuses a reply if **any** of the five robot VAD sources became active while the LLM was reasoning. The group cooldown now advances only after `Conversation.say_proactive` reports actually transmitted audio. Source tests added for a legitimate CAP1188/siderange event, uncertain visual category, cross-fleet active voice, and voice beginning during a blocked model response.

**Verification evidence:** A source-only cross-file audit checked nine contracts against current GitHub source, all returned true, including the existing pinned XIAO Stackchan idle/touch/speaking HSM. There is **no new passing pytest, macOS playback, local Ollama benchmark or physical robot test** from this review. CI remains blocked by GitHub jobs reporting failed conclusions but no usable execution steps or logs. Hand-coded confidence thresholds are illustrative until measured confusion and annoyance rates are obtained; they are **not** paper-trained or hardware calibrated. Full speech interruption, timing and physical performance claims remain unverified.
