# Acceptance, observability and evidence: full target from day zero

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
