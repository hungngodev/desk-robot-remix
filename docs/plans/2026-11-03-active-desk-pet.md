# Active Desk Pet Implementation Plan

Run development commands from the repository’s `code/` folder.

Updated 2026-11-04: reconcile accepted decisions, not rediscover features.
The [canonical product brief](../product-definition.md) takes precedence over
historical BOMs, runtime defaults and earlier research suggestions. The remaining
work is implementation, integration and physical qualification.

> **For implementation:** Use the installed executing-plans workflow, preserve the current checkout and validate each milestone before enabling hardware motion. This file records the implementation sequence. See the progress note below before treating a task as unfinished.

**Goal:** Build one affordable, expressive, camera-equipped desk rover that can
initiate supervised activities, avoid qualified table edges locally, and lift
keys/candy, then repeat its validated core for five distinct characters.

**Architecture:** Owned WROOM handles deterministic steppers, servos and sensor
interlocks; the purchased XIAO ESP32S3 Sense handles camera/PDM audio/OLED; one Mac
handles vision, speech, memory and activity selection. The existing UART/job and
credential boundaries stay in place. A separate operator-enabled pet session allows
multiple bounded activities without giving a model arming authority.

**Tech stack:** ESP32 Arduino body, ESP-IDF/Xiaozhi head, Python coordinator,
VL6180X-down/VL53L0X-front/TCA9548A candidates, SSD1306, ULN2003/28BYJ-48, MG90S; shared Ollama/Qwen3,
SenseVoice, Kokoro and OpenCV/YOLO-World. RoboEyes is a GPL-3.0 integration
candidate, not an already-installed dependency.

## Implementation progress — 2026-11-03

Stepper timing, portable guard policy, local-USB-only recovery and separate
Sense8MB/PDM/SSD1306 target are implemented and compile. Actual sensor I/O and
measured calibration remain missing; the stepper target refuses arming. Pet
scheduler/animation/memory remain unimplemented.
[Evidence and remaining gates](../guides/firmware-foundation.md).

User now reports purchasing at least one Sense kit (displayed $18.87, receipt,
quantity and arrival unconfirmed). Keep it as the active head. The old $40.33
owned-bank/L0X target is historical; the sensor/power revision needs a new quote.
The **$50 delivered cap includes already-spent money**. Ordinary-speech interruption is mandatory in robot one.
RIO software AEC and Google/Pipecat live examples are the reuse direction;
replacement hardware is not yet necessary. The offline Mac turn/frame core is
implemented; live transport, device AEC and physical acceptance are pending.

## Baseline before this implementation and constraints

Read [master plan](../PLAN.md), [inventory](../hardware/fleet-inventory.json),
[parts](../hardware/parts.md), [sensor requirements](../research/2026-11-03-cliff-sensors.md),
[video audit](../research/2026-11-03-video-audit.md) and
[behavior sources](../research/2026-11-03-active-pet-sources.md).

- Existing body implements DC PWM, two positional servos, disarmed boot, 500 ms
  watchdog and 250 ms bounded drive. It cannot yet run ULN2003 steppers or stop at cliffs.
- Before this milestone the head builds were Freenove 16 MB/SH1106/I²S mic and
  CoreS3 references. A separate Sense/SSD1306/PDM/8 MB build now exists. The
  subsequent user-reported Sense order supersedes the earlier no-S3 inventory.
- Existing Mac has one-use 30-second operator permits, bounded pickup jobs,
  stop/cancellation and two-to-five robot digital turn-taking. Pet mode and
  persistent character memory are new work.
- Historical 90 checks, simulations and compilation are not physical acceptance
  or verification of any new design. No hardware is flashed or assembled.
- First prototype now $40.33 conditional target, $50 delivered cap. Missing
  owned quantities and all delivered charges remain gates. No automatic purchases.
- Keep saved originals/upstream clones untouched. Small CAD fixes only. If
  combined stepper/lift/head cannot fit without a major redesign, stop that
  mechanical branch and report the incompatibility before new spending.

## Milestone 1 — inventory, print source and power feasibility

**Files:** `docs/hardware/fleet-inventory.json`, `docs/hardware/bom.json`,
`docs/hardware/fleet-components.csv`, `docs/hardware/parts.md`,
`docs/cad/originals/smars-stepper/{README.md,source.json}`, future
`docs/records/local/power-and-fit.md`.

1. Count WROOMs, OLEDs, MG90S servos and banks. Do not turn an unknown count into
   five free parts. Confirm five stepper/driver pairs, leaving five pairs to buy
   for the fleet. Select a matched 1S kit and measure its dimensions/weight.
2. Review the saved #2778904 stepper chassis/wheel originals, source URLs,
   author, filenames and hashes; resolve the displayed CC BY remix versus
   recorded NC-SA ancestor terms before redistribution. Do not substitute N20 files. The linked
   GitHub educational sketches are a reference, not an established copying grant.
3. Compare module/servo drawings and actual measurements to the originals.
   Verify the forklift attachment interface on the stepper base and head/arm
   sweep. Print a servo pocket or bracket fit coupon before full sets.
4. Check the selected 1S cell/holder/protection/charger/5 V module and power wiring.
   Measure accessible owned-part loads only with an existing valid test setup;
   estimate remaining head/current needs conservatively. Integrated track/servo/
   Wi-Fi/audio load testing waits until milestones 2 and 4 provide working firmware.
5. Complete delivered quotes, including exact Sense bundle and all vendors'
   delivery/tax. Budget checker must still reject unknown fit/allowances.

**Validation:** `python3 scripts/check_budget.py`; after actual completed quotes,
`python3 scripts/procurement_release.py --require-first-robot --format first-robot-markdown --evidence ACTUAL_RECEIPTS.json`.
The strict release command requires genuine linked receipts, seller quotes, fit, and physical safety signoffs; it will reject invented delivery or tax values. Mechanical
fit/load and sufficient printer/filament stock are separate documented checks.
The purchase checker covers first-prototype quotes, inventory and preliminary
fit/variant checks. Separate `qualification_checks` in the BOM remain false until
real builds/tests; they gate roaming and fleet duplication, not acquisition of the
first sample set. No listing metadata can satisfy physical qualification.

**Exit:** source/attachment availability recorded, drawing/owned-part power and
fit preflight feasible with small parts, cost within cap or explicit conflict.
Actual mechanical fit, loaded current and stopping remain later qualification gates.

## Milestone 2 — portable stepper driver without changing permits

**Create:** `firmware/body/lib/StepperDrive/StepperDrive.h`,
`firmware/body/lib/StepperDrive/StepperDrive.cpp`,
`firmware/body/tests/stepper_tests.cpp`.
**Modify:** `firmware/body/{CMakeLists.txt,platformio.ini}`, `firmware/body/src/main.cpp`,
`firmware/body/include/BodyPins.h`, `firmware/body/lib/BodyControl/BodyControl.{h,cpp}`.

1. Add a pure, clock-injected phase generator. Tests first: correct one/two/half
   step sequence, both directions, bounded speed/ramp, zero command, expiry,
   stop before next phase, clock rollover and no catch-up burst after a stalled loop.
2. Keep the UART drive argument contract as a bounded signed speed request;
   map it to a documented, measured maximum step rate, not PWM or promised mm/s.
   Preserve existing command limits and strict parsing. Add an explicit backend
   identity to status so the host cannot mistake step count for measured travel.
3. Keep pin writes in the hardware adapter. Use the proposed eight outputs only
   after actual phase/polarity verification. No blocking `delay`/multi-second
   step calls that prevent watchdog/sensor checks. Maintain servos independently.
4. Add tests proving malformed frames, keepalive and status queries cannot extend
   drive pulses. Preserve watchdog servo hold and explicit disarm behavior.
5. Build, then test unloaded tracks on a stand: slow start, both directions,
   command timeout and independent stop. Qualify phase hold/coast for current,
   temperature and mechanical stopping; step counts do not imply odometry.

**Validation:**

```sh
cmake -S firmware/body -B ../.tools/body-host -DBODY_SANITIZERS=ON
cmake --build ../.tools/body-host
ctest --test-dir ../.tools/body-host --output-on-failure
../.tools/body-pio-venv/bin/pio run -d firmware/body
```

Use the existing per-terminal macOS compiler workaround in [build.md](../guides/build.md)
if necessary. Do not flash as part of this automated milestone. Keep a separate
legacy DC configuration if useful; do not make one pin map drive both backends.

## Milestone 3 — local cliff interlock and fault reporting

**Create:** `firmware/body/lib/CliffGuard/CliffGuard.{h,cpp}`,
`firmware/body/tests/cliff_tests.cpp`,
`docs/records/cliff-trials.csv` (empty measurement template).
**Modify:** body control/adapter/pins/CMake files above,
`firmware/head/overlay/robot_protocol.h`, `docs/guides/interfaces.md`,
`laptop/src/desk_robot/{transport.py,simulator.py}`,
`tests/test_transport_calibration.py` as the status contract requires.

1. Define per-sensor sample state: channel, role, validity/status and monotonic
   age. Only the four downward sensors have calibrated floor intervals; no-return
   is unknown/fault, never clear floor. The forward sensor uses a separate
   obstacle threshold and verified observation range. An out-of-range/no-return
   forward view is unknown: stop/deny movement rather than assume empty space.
   Test a truly empty forward view explicitly; if valid clear readings cannot be
   obtained, restrict the operating patch or choose a qualified sensing fallback.
   Add status fields without silently breaking the old protocol parser; use an
   explicit version/capability and require it before pet motion.
2. Portable fault-injection tests precede hardware reads: boot, missing calibration,
   all four corner drop cases, invalid result, stale sample, unplug, mux error,
   clock rollover, fault during a phase and fault during a servo ramp. Any failure
   must latch wheel stop and reject every later drive until human rearm.
3. The central output gate checks sensor health for manual, serial, MCP, pickup
   and pet paths. Stop must not drop gripper PWM. Healthy samples do not clear a
   latch. Ordinary job arm must not clear a fault: the implemented recovery is
   local body-USB-only rearm, which leaves motion disarmed. Never automatically reverse.
4. Configure each same-address sensor on one mux channel, verify 3.3 V pullups,
   time-bounded reads, reset behavior and continuous ranging. Do not wait for five
   full sequential measurement cycles inside the motor loop. Bus recovery remains stopped.
5. Store per-unit surface calibration/checksum; missing or incompatible calibration
   prevents arm. A human calibrates on a supported surface; the LLM cannot clear faults.
6. Measure actual freshness and decision latency under maximum voice/Wi-Fi/servo
   load when integrated hardware is available after milestone 4; use stand-mounted
   owned parts earlier. Derive thresholds from final mounting, not the video’s 82 mm value.
7. With tether/catch tray, measure:
   `lead >= speed * (worst_sample_age + decision_latency) + braking_distance + margin`.
   Test forward, reverse and pivot separately; include dark/glossy/transparent
   surfaces, lighting, occlusion, module disconnection and bus timeout. Exclude
   a motion/surface if the lead inequality or swept footprint coverage fails.

**Exit:** host fault cases pass, no loop starvation, documented measured stopping
margin for the allowed surface/motion envelope. Four sensors alone do not certify
all-table operation. One front ToF has no side/rear collision coverage.

## Milestone 4 — Sense head and original face

**Create:** `firmware/head/sense/{config.json,config.h,desk_robot_sense.cc}`,
`firmware/head/sense/README.md`, future `firmware/head/sense/face_adapter.*`.
**Modify:** `firmware/head/{install_overlay.py,private_config.py,BOARD_README.md}`,
`scripts/build_head.sh`, `firmware/head/tests/test_overlay.py`, `docs/guides/modular-head.md`,
`ATTRIBUTION.md` and dependency notices if library code is incorporated.

1. Verify exact Sense revision, official schematic, camera and microphone pins.
   Allocate OLED2 + amplifier3 + UART2 header signals, reserve native USB and
   internal camera/PDM/PSRAM signals, and explicitly disable SD if sharing pins.
   Do not reuse the Freenove pin map or a video's GPIO1/2 bus allocation.
2. Add a separate `sense` board selector and isolated build copy. Reuse stock
   camera/SSD1306/PDM/I²S output components, selecting the supplied sensor. The
   pinned `main/audio/codecs/no_audio_codec.h` already exposes
   `NoAudioCodecSimplexPdm`; select it rather than the old I²S-microphone codec. Test
   installer drift/remove/private identity isolation for the third target.
3. Use 8 MB partitions/assets that actually fit. The earlier 2,500,528-byte app
   fitting an 8 MB OTA slot is only feasibility evidence; partition check, asset
   sizing and a new successful build are required. Do not just truncate a merged image.
4. Decide face dependency terms before copying: RoboEyes and Tech Talkies face
   source are GPL-3.0. If using RoboEyes, retain source/notices and satisfy the
   resulting head-firmware distribution terms. Do not label combined GPL code
   MIT-only. Otherwise implement original simple graphics without copying those
   sources. The rest of this project keeps its existing licenses.
5. Face adapter receives idle/listening/thinking/speaking/blocked/sleep events,
   owns OLED drawing on one task and yields regularly. Local blink/idle timing
   continues without an LLM; never block voice/UART stop for an animation.
6. Bench-test display, orientation, live camera, PDM recording, speaker volume,
   listen/speak transition and UART separately. Then on a stand with rated power
   branches test loaded track startup/turning, servo lift/grip, Wi-Fi and audio
   together. Record droop/current/temperature, bank auto-off and payload stability.
   Repeat sensor timing/stopping qualification under that combined load.
   Recheck the current rounded-shell OLED insert/camera aperture and retention,
   thermal clearance and full gripper sweep. No eyes-in-render equals fit proof.

**Validation:** existing overlay test command plus new Sense tests,
`uv run pytest firmware/head/tests -q`; only after adding `sense`, run
`bash scripts/build_head.sh --board sense`. The Sense selector and a successful build now exist; physical tests remain.
Hardware flashing remains an explicit device-specific action after successful build.

## Milestone 4.5 — voice interruption and paced camera understanding

**Sources:** [pinned RIO/Google/Pipecat review](../research/2026-11-03-sense-realtime-reuse.md),
[Mac integration contract](../guides/live-conversation.md), [audio acceptance](../guides/audio-barge-in.md).

1. Keep the purchased Sense and the compiled pin map until a reviewed port
   replaces it. Reuse RIO's software playback-reference/calibration approach
   through the [existing ESP-IDF AFE seam](../guides/sense-aec-port.md), adapting task
   synchronization, reference timing and resampling. Avoid a second full AEC chain.
   Measure delay with the final speaker/microphone/enclosure. An echo gate that
   suppresses the user's voice during playback fails this requirement.
2. Connect the offline Mac turn core to local Mac speech/vision transport first;
   cloud providers remain optional.
   Cancel obsolete generation and flush both Mac queues and actual device/DMA
   playback on interruption. Retain the new utterance. Do not stamp delayed old
   audio with a new turn ID. Selecting the pinned Xiaozhi text Gemini provider
   alone does not supply native Live audio/video.
3. Schedule camera capture independently from audio, initially about one JPEG
   frame per second in an active observation session. Reuse the latest fresh
   frame; do not queue seconds of old images or block speech for still capture.
   Camera frames never replace body-local edge sensing.
4. With observation enabled, derive fresh scene/person/target events without a
   spoken prompt; coalesce repeats, remember recent observations and reject stale
   camera events. A brief fresh-frame prompt may run
   only between user/model/tool turns, with cooldowns, quiet mode and five-robot
   speech arbitration. A frame alone and Google's proactive-audio setting do
   not implement the full pet scheduler. No model receives new motion authority.
5. Keep cloud sessions opt-in with private keys; no account or paid API is used
   by offline tests. Record model availability and usage costs separately from
   hardware costs before live testing.
6. Pass the ordinary-speech, playback-cancellation, speaker-only, camera-load
   and motor-load trials in the audio acceptance sheet before claiming robot one
   supports barge-in. Then repeat per assembled robot; microphone presence and
   compilation are not physical proof.

**Progress:** Mac cancellation/frame/idle-observation state and offline tests
exist. Device AEC, a connected live provider, video transport and physical trials
remain pending. The optional Waveshare adapter does not change this active path.

## Milestone 4.6 — touch, motion and sensor-event reactions

Follow [interaction-sensors.md](../hardware/interaction-sensors.md). Add the
owned AT42QT1010 digital input and a version-matched BerryIMU I²C adapter
(LSM6DS3TR-C conditional fallback only), with bounded bus work and
floor/stop priority. Reuse Stackchan-agent's MIT hardware-independent behavior
controller through a face/audio action adapter; use Focus/Yumo as idea references
within their copying boundaries. Fuse handling evidence rather than infer held
state from IMU alone. Touch during motion pauses locally; putdown cannot rearm.
Test A10/A11 and applicable A12 before duplication; RGB remains optional.

The [source map](../source-map.md) records the stronger Google observation/event
and HF local engine candidates. Prove provider/embodiment adapters and actual
VLM/cancellation before replacing existing server paths. No second competing
voice loop or copied hardware-specific head-motion routine is introduced.

## Milestone 5 — stationary pet behavior and per-robot memory

**Create:** `laptop/src/desk_robot/pet.py`, `laptop/src/desk_robot/memory.py`,
`tests/test_pet.py`, `tests/test_pet_memory.py`.
**Modify:** `laptop/src/desk_robot/{config.py,runtime.py,api.py,cli.py}`, head event
boundary, `config/{fleet.example.toml,fleet.simulation.toml}`, `docs/guides/five-robots.md`.

1. Add disabled-by-default pet configuration. Use injected clock/random source;
   state per robot includes curiosity, social cooldown, rest and recent activity.
   These are personality variables, not inferred charge or physical sensation.
2. Tests first: idle blink/gaze, attention event, pet/button reaction, quiet mode,
   rest, bounded initiation rate, repeated-event coalescing and return to idle.
   Stationary mode must never call the motion transport or acquire a permit.
3. Pick a small action vocabulary: `look`, `react`, `rest`, `invite_chat`,
   `inspect_visible_target`, later `explore_patch` and `pickup_target`. The scheduler
   chooses when, vision supplies observations, and optional LLM chooses a bounded
   intent. Unknown/unseen targets do not become invented coordinates.
4. Default spontaneous speech no more than once fleet-wide per 120 seconds;
   human interactions can reply promptly. These
   are initial tunable product defaults, not hardware timing. Group sessions keep
   existing total-turn/time limits and one audible speaker.
5. Keep small persistent records keyed by robot ID under ignored `data/private/`:
   recent activities, explicitly supplied preferences and peer encounters. Test
   restart/isolation, corrupt-record fallback and bounded retention. No raw audio
   or pictures are retained automatically. Stop/fault/motion sessions are runtime state,
   never persisted as permission to move after restart.

**Exit:** repeatable simulation shows independent, proactive stationary behavior
and memory without LLM-every-tick calls or any hardware movement. Robot/person
recognition reliability remains unqualified; touch does not give user location.

## Milestone 6 — motion arbitration and enable-until-paused pet session

**Create:** `laptop/src/desk_robot/motion.py`, `tests/test_pet_motion.py`.
**Modify:** `laptop/src/desk_robot/{controller.py,runtime.py,config.py,api.py,cli.py}`,
`tests/{test_control.py,test_api_conversation.py,test_fleet.py}`, `docs/guides/interfaces.md`.

1. Single owner per robot. Fault/operator stop overrides everything; manual and
   pickup preempt roaming, which cannot queue an automatic restart. Keep existing
   bounded-job permits unchanged; they are not reusable wander permission.
2. Add operator-only pet enable until paused/stopped, without recurring renewal.
   Hardware motion stays off unless explicitly configured. Model credentials
   cannot enable/rearm. Keep individual drive deadlines and watchdogs. Disconnect,
   pause/stop, fault and shutdown revoke the session and cancel pending activity;
   reconnect/restart cannot resume movement.
3. Add fault tests before implementation: model cannot enable, stale sensor status
   blocks enable, restart stays off, enable survives beyond 300 seconds without
   renewal, canceled/expired individual jobs never run, active manual
   preempts roam, fault prevents later drive, and stop during LLM/vision wait
   cancels pending intents. No transport retry of uncertain movement ACK.
4. Implement stop/look/short bounded movement only inside a human-cleared region
   with qualified floor sensors. Clamp speed/duration to measured stopping bounds.
   No blind reverse, unrestricted random pivot or guessed camera-only distance.
   Blocked/unknown region means stop and request help.
5. Initially grant only one fleet motion owner at a time. Stationary peers may
   talk/animate. Log denied intents and reasons without exposing credentials.
   One moving unit in a clear reserved area is not simultaneous collision avoidance.

**Validation:** `uv run pytest tests/test_pet.py tests/test_pet_motion.py tests/test_control.py tests/test_fleet.py -q`,
then full `uv run pytest -q` and `uv run ruff check laptop tests scripts`.
Use stand/contained trials only after local interlock qualification.

## Milestone 7 — pickup and social choreography

**Modify:** `laptop/src/desk_robot/controller.py`, activity hooks, existing pickup
and trial guides; add focused keyframe tests if sequences are introduced.

1. Calibrate actual MG90S endpoints and horn geometry unloaded. Learn a short
   interruptible `grip/lift/offer/place` sequence using bounded angles/speeds,
   not a new kinematics engine. Angle bounds are not force feedback or a guarantee
   against stripped gears. Do not copy Qubit code while its terms are unresolved.
2. Validate fresh-camera approach/alignment on a cleared patch. Use the front
   ToF only for its measured field; it cannot prove a grip or see all obstacles.
3. Test ten independent trials each for flat keys and wrapped candy. Require
   visible 10 mm lift, three-second hold and controlled placement, with at least
   eight successes per category. Log slips, failures, manual help and payload mass.
4. Add stationary peer attention and bounded games through the existing digital
   conversation coordinator; five default ten total utterances, pairs six.
   Real object handoff is a later physical experiment requiring verified position,
   free space and both robots' control; a JSON message is not handoff proof.

## Milestone 8 — repeat the validated core and document limits

**Files:** inventory/BOM, per-robot ignored calibration/settings,
`docs/guides/five-robots.md`, `docs/records/verification.md`, physical trial records.

1. Quote missing fleet stock only after prototype success; identical core modules,
   unique tokens/device IDs/addresses/personas and individually measured calibration.
2. Verify all five command/stop/audio routes and fault isolation. Costume changes
   must not block optics/audio/USB/switch/antenna or alter stopping/stability unsafely.
3. Test ten-utterance stationary group sessions, stop mid-speech, head loss and
   coordinator loss. Then one-at-a-time supervised activity with the other four
   stationary. No claim of unconstrained all-five free-roaming play.
4. Save exact firmware hashes, source revisions, test commands, measured speed,
   surfaces, stopping margin, cost and failures. Keep physical acceptance separate
   from synthetic images/mock speech and old test counts.

## Work completed by this planning update

The planning update saved inventory/BOM/source audits. Subsequent implementation
added stepper timing, guard policy/local recovery and a compiled Sense target.
Actual sensor I/O/calibration, face/pet/memory work and all physical qualification
remain. Keep hardware motion disabled while those gates are unresolved.
