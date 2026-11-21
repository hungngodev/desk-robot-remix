# Desk Robot Remix build plan

Build and qualify one robot before making four copies. The
[product definition](product-definition.md) owns appearance, behavior and
acceptance criteria. The [parts list](hardware/parts.md) owns inventory and
shopping. This page owns the original seven physical build stages; the [full day-zero forward-only sequence](#complete-linear-build-and-permanent-verification-stages) owns the complete integrated experience, including proactive conversation, memory, all selected sensors and expansion interfaces. Both descriptions preserve the same final product rather than replacing it mid-build.

## November 12 integration checkpoint

The hardware and experience scope is **unchanged**: one fully featured body first, then four identical bodies with independent names, personas and memory. [PR #17](https://github.com/hungngodev/desk-robot-remix/pull/17) is the only integration PR. The [current document entrypoint](README.md), [actual upstream copy versus inspiration audit](ATTRIBUTION.md), [sensor source/physics matrix](hardware/full-feature-wiring-and-shopping.md#current-sensor-source-and-behavior-closure-matrix), [natural multimodal/social flow](guides/multimodal-voice-video-orchestration.md#november-12-source-truthful-natural-social-behavior-and-active-camera-triggers) and [proof ledger](records/verification.md#2026-11-12-live-source-cross-layer-checks-not-passing-hardware-evidence) own details. Do not create a fresh companion chatbot, independent camera broker or new parallel PR.

**Software source done this review:** required trigger labels, nonblocking sensor JPEG requests, rapid VAD restart protection, source-truthful proactive remarks, stale model deadline, explicitly consented two-pet dialogue with existing exclusive Xiaozhi session, peer quiet/motion-state cancellation, source consent and generation proof, original source attribution, and cross-layer static wiring invariants. **Historical CI context:** Tests added during the November 12 review faced runner failures before recorded test steps at that time. That is not a statement about current CI. For the current PR #17, inspect the [live five-job host verification workflow](https://github.com/hungngodev/desk-robot-remix/actions/workflows/host-verification.yml) at the **exact PR #17 commit SHA** and check each job's success, failure, cancellation, skip or queue status and logs. Do not infer the current result from an older run. Passing software checks do not qualify physical acoustic performance, loaded motion, battery safety or charging; those require [separate physical trial evidence](records/verification.md). The previous committed sensor and firmware drivers are likewise not new hardware qualification.

**Required before calling this an assembly-only product:** restore actual CI and fix real logged code defects; complete and dimensional-check one licensed Fusion/STL assembly for body, gripper, camera/head and docking cradle; finalize and independently current/thermal-test protected 1S pack, regulator and isolated charge contact path; qualify the implemented read-only two-channel NEC RMT reception against physical GPIO36/39 and implement a measured bearing and final contact approach without displacing PIR/reed and WROOM safety GPIO; physically test all sensor bus/carrier timing and XIAO J3 speaker pin isolation; calibrate jaw force and 8/10 key and candy pickup/placement; measure live XIAO Opus/echo cancellation/video and five-pet speaker-floor and latency. The source cannot substitute imaginary measurements; these remain real gates rather than optional extras.

## Build order

| Stage | What to do | Ready when |
| --- | --- | --- |
| **0. Freeze the complete final design** | Reconcile all [200 feature/idea entries](source-map.md), [131 source URLs](source-map.md), functional tests, voice/vision/memory and fleet interfaces, exact wiring/power/fit/expansion budget and [conflicts](decision-log.md). Do **not** make a disposable interim robot. | One realistic fully documented hardware configuration, known source/license boundaries and a complete delivered budget, with no unresolved irreversible choices. |
| **1. Fit and parts** | Check the MG90S in the saved [gripper](guides/first-gripper-test.md) and the 28BYJ-48 in the [stepper chassis](cad/originals/smars-stepper/README.md). Confirm the Sense bundle, select the speaker path and matched rechargeable 1S kit, and check the complete delivered cost. Resolve the stepper remix's source terms before redistribution. | Fit samples clear the mechanism's travel and the complete prototype basket fits the **$50 delivered cap**. |
| **2. Drive and power** | Test the two owned stepper/ULN2003 pairs and two positional MG90S servos on a stand. Measure loaded current, temperature, stability and stop behavior. [Wiring](hardware/wiring.md) | Drive, lift and grip work under load within component ratings. |
| **3. Edge and obstacle sensing** | Bring up the **four downward and one forward low-cost VL53L0X safety/facing channels**, then the **three read-only left, right and rear VL53L0X channels** in the selected full profile through TCA9548A `0x70`. The source driver exists for all eight, but **none is physically qualified**: test exact carrier variant, desk geometry, freshness and stop distance before enabling locomotion. Calibrate on the actual desk and test faults and stops with a tether or catch setup. [Sensor design](research/2026-11-03-cliff-sensors.md) | The WROOM stops locally with measured margin on qualified surfaces and approaches. |
| **4. Head and conversation** | Bring up the Sense camera, onboard mic, OLED, speaker and UART. Test the owned AT42QT1010 through the shell and verify MPU6050 GY521 (BerryIMU superseded / retained as spare). Exercise echo cancellation and turn interruption. [Head setup](guides/modular-head.md) · [Audio gate](guides/audio-barge-in.md) · [Touch and IMU](hardware/interaction-sensors.md) | A person can interrupt ongoing speech by speaking. Touch and handling events pass bench and shell tests. |
| **5. Initiative and exploration** | Integrate **real pushed camera events, contextual unsolicited conversation, per-robot persistent memory, utility activity owner, emotion/quiet/peer arbitration and stationary expressions**. Add supervised, operator-enabled exploration only after local stops pass. Test quiet mode, preemption, pause and link loss. [Implementation tasks](plans/2026-11-03-active-desk-pet.md) | A8/A9 contextual self-initiation, memory provenance, five-feed dedup and A2 interruption are evidenced; the robot yields to the operator and stops safely. |
| **6. Object pickup** | Test real flat keys and wrapped candy with the fitted lifting claw. [Pickup guide](guides/pickup-and-two-robots.md) | At least **8 of 10** attempts per object type lift it 10 mm, hold it for three seconds and place it under control. |
| **7. Duplicate** | Copy the qualified core four times, then assign distinct identities and calibrate each unit. Start group play with serialized speech and one moving robot at a time. [Fleet guide](guides/five-robots.md) | Five distinct robots complete ten coordinated utterances and each passes its own movement checks. |


## Which build order is authoritative?

There are **not two competing build plans**. The original seven stages above are a concise historical summary. For all new implementation work, follow [the complete Stage 0 through Stage 12 protocol](#complete-linear-build-and-permanent-verification-stages) below, in order. The more detailed stages establish final interfaces and all difficult behavioral requirements **before** permanent assembly. The original stage names remain here so instructions and source links written earlier still make sense.

| Original stage | Complete linear stages | What the new sequence changes |
| --- | --- | --- |
| 1. Fit and parts | 0, 1, 2 | First resolve all features, owner boundaries, power/expansion, source licenses, budgets and dimensions, then print only reversible fit coupons |
| 2. Drive and power | 2, 3 | Test the selected physical power path and both actuators on a stand; body motion remains guarded |
| 3. Cliff sensing | 2, 3 | Decide a supported floor sensor before buying; qualify four corner roles and actual stop margin |
| 4. Head and conversation | 4 | First assembled head must already support natural ordinary speech interruption, not require a later replacement |
| 5. Initiative and exploration | 5, 6, 7, 8 | Build true camera-triggered context, per-unit memory and proactive speech **before** roaming; then enable only locally protected motion |
| 6. Pickup | 1, 3, 8 | Reserve and fit the actual lift/claw **from Stage 1**, verify real key/candy pickup when safety and perception are integrated |
| 7. Duplicate | 9, 10, 11 | Qualify the **complete** first unit, then four identical cores with independent memory and a coordinated five-peer experience |
| All original research and future ideas | 0, 12 | Preserve all research from day zero, but swappable experiments receive explicit electrical, cost and safety gates rather than silently changing the qualified core |

**Progression rule:** A stage is not complete until the evidence gate passes; the next stage consumes its fixed interfaces. A failed prebuild measurement can require a design decision before the irreversible build, but no hidden "simple V1 first and replace it" migration is allowed. The $50 delivered cap, the four downward floor roles, real A2 voice interruption, contextual A8/A9 initiative, and key/candy A5 acceptance cannot simply be dropped to advance the schedule.

## Design decisions that affect the build

- **Body.** The WROOM owns motion, sensors and the local stop. The XIAO Sense
  handles camera, audio and face. The Mac handles speech, vision, activity
  selection and memory. See the [interfaces](guides/interfaces.md).
- **Enclosure.** Compare Cozmars head packaging first and keep the saved,
  unprinted Sparky shell as a fallback. Both lift and grip retain their own
  servo. Limit CAD edits to mounts, bezel, clearance, jaw tips and removable
  accessories. See the [product definition](product-definition.md#case-choice-and-allowed-changes)
  and [concept views](cad/concepts/2026-11-03-rounded/README.md).
- **Motion.** Boot disarmed. The body enforces 250 ms drive limits and a 500 ms
  communication watchdog alongside local edge stops. The planned pet session
  stays enabled until paused or stopped. Faults and disconnects cancel it.
  Fault recovery requires a local clear. Resuming movement requires fresh
  operator enable. See the
  [control requirements](product-definition.md#control-and-compute-boundary).

## Current evidence

The Sense and body build profiles and their test targets exist in source, including
the eight VL53L0X full WROOM target and five-pet host simulation. This is not a
claim that the current PR head compiles or passes: recent GitHub Actions jobs fail
before recording any steps, with unavailable logs. The stepper design is intended
to refuse arming without fresh required sensors and calibration, but the real
bench stop margin remains unmeasured. Physical fit, power, speech interruption,
pickup and fleet play are still open.

[Implementation progress](guides/firmware-foundation.md) · [Test evidence](records/verification.md) · [Reuse and licenses](source-map.md)


---

## Complete linear build and permanent verification stages

*Integrated from the user-requested full feature documentation review on 2026-11-09. This section is planning and source evidence only unless a measured result is linked.*


This plan rejects the pattern "make a cheap talking robot first, then replace everything to add autonomy." **All final mandatory feature contracts exist at Stage 0.** Assembly and verification still occur sequentially because motor current, optics, acoustics and gripper fit cannot be established by Markdown. There is no "throwaway V1" alternative head or later foundation migration.

`DONE` is permitted only with named evidence and all exit conditions met. A mock proves integration logic, not physical performance. Experimental features from the HTML are inventoried before any design is frozen, even if their extra board remains unpopulated.

| Stage | Single output and evidence required | Permanent decisions that prevent rebuilds |
| --- | --- | --- |
| 0. Full specification freeze | Source-to-requirement register complete, risks and cost conflicts disclosed, end-state block diagrams signed off | Features, identities, all required sensors, reserve ports/volume, user-visible behavior and tests are in scope now |
| 1. Source and geometry feasibility | Licensed pinned reuse sources, dimensioned CAD envelope, exact servo/motor/camera/battery sample and delivered cart | One reusable SMARS drive + two-servo lift/grip + round Cozmars-inspired head; modular mounts and service windows |
| 2. Electrical/harness and first dock preflight | Real breakout variants, pin/electrical tables, safe rail and protected 1S charging schematics, isolated stand trials, and first assigned dock contact and connector geometry | WROOM/Sense/Mac split, I2C channels, UART, bus recovery, speaker placement, independent charger interlocks, dock electrical isolation and extension points |
| 3. Safety and motor foundation | Both steppers/servos on supported stand, live eight-sensor VL53L0X topology, calibrated stop guard and fault-injection logs | One fail-closed motor API for all future autonomous/manual/pickup/dock actions; no alternative unsafe motor path |
| 4. Exact head and audio | Sense camera/OLED/mic/amp plus reference AEC/ordinary speech interruption and actual device flush | No replacement head, no mic mute fallback, one voice transport and consistent turn generations |
| 5. Perception and memory | Real fresh frames -> typed visual/sensor events -> per-robot durable memories with provenance | No polling-only "Describe the scene" button; event push, stale invalidation, private data and source identity from first iteration |
| 6. Full proactive conversation | Utility activity owner, vision grounded unsolicited speech, suppression/cooldown, quiet/preemption, five-feed dedup | Proactivity is first-class behavior, not a greeting timer or later optional UI |
| 7. Full local robot personality | Deterministic eyes/emotes, sensory reactions, identity/mood/rest, gestures/voice and long-term context | No second personality engine or LLM low-level timing |
| 8. Supervised pet motion, pickup and docking | Operator's ongoing pet session, safe motion arbitration, real key/candy task and supervised terminal dock approach, alignment, seat, departure and recovery trials | No blind roam or model arm; docking uses the same independent WROOM stop, clearance, power and contact interlocks |
| 9. Complete first robot and first dock qualification | A1–A12 plus power, acoustic, observation, memory, gripper, edge, dock seat/contact alignment, protected 1S charging, measured net cell current, safe departure and recovery evidence | **Only after the first assigned dock and robot pass their separate bench and integrated physical gates** label robot one accepted; no simulated charge or purchase release |
| 10. Four additional robots and docks | Reuse the first qualified robot and dock core, unit-specific calibrations/secrets/health and separate acceptance for each of the five assigned docks | Same pins/software/case and per-robot feature set; no watered-down followers or unqualified docking copies |
| 11. Social fleet and shared room station acceptance | Five cameras, five independently qualified docks, one approved shared station, private memories, live speech ownership, independent identities and simultaneous perception | One speaker and initially one moving robot; preserve station consent, per-pet docking and no false synchronized self-interruption |
| 12. Electable research expansions | Nonessential advanced games, alternate experimental docking methods and swappable pre-provisioned accessories pass separate tests | The first dock, five dock fleet target, supervised docking/navigation and protected charging are **already mandatory at stages 2–11**, never optional profiles |

## Stage 0: freeze the *full* product, not an MVP

Deliverables:

1. Read canonical [product requirements](product-definition.md) A1–A12 and this [system contract](product-definition.md). Treat user instructions for active pet mode, ongoing camera awareness, socially meaningful speech, natural interruption and the full five-peer concept as constraints, not a menu. No mandatory capability can move to a later "nice-to-have" release merely because it is hard.
2. Use [feature register](source-map.md) to account for every named sensor, weird idea and software feature in HTML sections 1–23. For each decide `REQUIRED PHYSICAL`, `REQUIRED SOFTWARE`, `RESERVE NOW`, `SWAPPABLE EXPERIMENT`, `REFERENCE ONLY`, `NOT SAFE`, with its owner, bus, power, mechanical aperture, upstream evidence and acceptance. Preserve unselected ideas verbatim in the register; do not silently erase.
3. Choose a single named feature-complete target configuration and matching per-robot bill. Two things cannot silently both be binding if incompatible: a strict **$50 delivered** full prototype and every experimental hardware module physically installed. Use an explicit cost/scope choice before procurement, never a misleading $38.44 partial sum.
4. Publish interface version 1 for head/body UART, typed camera/sensor events, per-robot IDs, observation timestamps, memory writes, speak lease/flush, motion permits and fault state. Reserve required pins and empty expansion channels. Lock the final shell's access/holes and camera-to-claw line of sight on the dimensioned assembly, not a render.
5. Freeze third-party licensing: firmware MIT base, RIO MIT AEC example, Google robotics sample licensing, Reachy Apache-2.0, Stackchan MIT, XiaoZhi desk robot MIT, and separate RoboEyes GPL3/CAD NC-SA obligations. A license review can force choosing a different upstream library **before** integration, not redoing all firmware halfway through.
6. Publish a contradiction sheet with owner, evidence and decision date for all blockers in [prebuild decisions](decision-log.md). Do not print a whole robot or connect the battery while those blockers remain unaddressed.

**Exit:** no unknown *interface or irreversible fit decision*, no false claim that optional parts are owned, and honest budget/cap conflict recorded. Reversibility for a first 3D coupon and bench measurement is a *deliberate test*, not a retroactive architecture change.

## Stage 1: one physical platform chosen from licensed existing geometry

1. Save/pin source hashes for SMARS 28BYJ remix, original SMARS compatible tracks/wheels, Bluino jaw and SMARS forklift; resolve CC BY-NC-SA upstream source-chain constraints. Compare Cozmars V2 editable CAD and V3 head hardware *before* selecting the final head mount; saved Sparky v0.1 (which its author says was not test printed) is only a fallback. Preserve original source files unchanged.
2. Count real MG90S, motor/ULN, WROOM/OLED, AT42QT1010, preferred MPU6050 (and spare BerryIMU) and optional MAX30102/SW-18010P. Verify actual delivered Sense camera revision. Inventory photo is not an electrical test or proof of quantity five.
3. Measure servo case/spline, fixed head camera field, OLED window/PCB and track sweeps, battery shape/mass, four downward sensor optical windows, forward field, touch surface, speaker/mic/acoustic spacing, usb/debug port, power switch/fuse and removable costumes. Reserve swappable expansion positions for proposed gesture/fog/heart/lighting/knock/force/etc without allocating imaginary GPIO.
4. Make minimal coupons: servo pocket, gear/rack, head OLED/camera insert, corner sensor carrier, keyed power holder, track-wheel alignment. Use physical caliper dimensions and printer calibration. Do not print final five shells while an interface is uncertain.
5. Calculate assembled center of gravity, anti-tip footprint, gripper front reach and camera view with raised payload. An attractive assembled PNG does not establish fit.
6. Reconcile order cost delivered; require the actual variant price/quantity/shipping/tax and owned inventory before ordering. Continue only after fixing the cap conflict.

**Exit:** final licensed mechanical assembly fits with small remixes and a *complete priced* prototype. If original combination cannot physically support the requirements, stop before manufacturing rather than build a disposable compromise.

## Stage 2: permanent wiring designed once

1. Draw one explicit schematic for WROOM, Sense, eight VL53L0X channels (four cliff, one forward safety, three informational) on mux 0x70, MPU6050, servos, motors, touch, and the separate 0x71 accessory mux. Preserve GPIO36/39 for terminal IR and MCP23017 GPB0/GPB1 for reed/PIR. Record voltage domains, power-up sequencing, pullup strengths, GPIO strapping, mux reset, grounds, fuse, current, speaker outputs and USB flash access. Confirm actual physical breakout orientation/level shifting; `GPIO41/42` cannot be heartbeat I2C on Sense because the PDM mic owns them.
2. Decide low-mounted floor part only after actual one-module distance/reflectivity test and current manufacturer availability. ST VL6180X is obsolete; cheap generic VL53L0X GY-530 is now selected, but exact carrier voltage, lens geometry and actual optical margins are not qualified. Maintain **four downward optical roles and independent front obstacle** in the final assembly.
3. Qualify an exact cell and charger/protection/5V system, not a chip-name-only IP5306 promise. Measure head/motor/speaker/servo power separately before full connection. Test charging operation separately from powered use. Determine peak and sustained legal overlaps, rail droop, ground bounce, fuse behavior, actuator/logic isolation and low-voltage handling. Do not assume servo PWM can preserve payload during a true brownout.
4. Determine bus topology/address collisions for selected and optional sensors. Treat channel 5–7 mux allocation as reserved space only, not proof of electrical accommodation of every idea. External expansion module needs its own qualified connector/controller choice if three channels are insufficient.
5. Use current limited safe stand setup. Check no unplanned motion at power, flash, reset or reconnection. Avoid running motors directly from laptop GPIO/USB or current-limited DuPont harness.

**Exit:** actual wire-by-wire diagram and BOM match, one harness variant, exact voltages checked, no unresolved battery/processor pin overlap.

## Stage 3: locally safe body, no future controller rewrite

1. Keep current nonblocking StepperDrive and CliffGuard until a reused library is *measurably* better; simply replacing a tested class with AccelStepper creates regression risk. Reuse source-level ToF vendors for checked I2C platform layer, status and timestamp, mux selection and bounded sampling.
2. Implement actual four corner floor readings and front obstacle reading in WROOM, per-surface calibration, sample age, invalid/no return/NACK/timeout and faults. Loss of any essential sensor blocks and latches drive; no auto retreat. Local USB rearm only after healthy fresh samples; it leaves motion disarmed.
3. Verify correct 28BYJ phases, steps per effective revolution (measure, don't hardcode 4096/4076), loaded wheel travel, backlash, slip, ramp, stop distance and slew under worst simultaneous legal load. Existing 160 half-steps/s is baseline; speed changes require measurement.
4. Exercise normal/late/malformed UART, output disable, 250ms drive expiration, 500ms watchdog, fault during stepping/lift, servo holding and active task cancellations. Reject any model or reconnect path that rearms movement.
5. Edge test only over containment/catch with restrained speeds; vary surface, lighting, angle, forward/reverse/pivot, full sensor faults, audio and WiFi contention. Log minimum lead vs actual coast.
6. Add touch, IMU and optional physical safety input adapters to the same event protocol **without** letting an accessory event call raw motors. The eventual social controller consumes the same contract.

**Exit:** supported floor and swept motion envelope qualified. If not, **no physical roaming or pickup approach** despite green software tests.

## Stage 4: first build must already converse naturally

1. Keep the purchased XIAO Sense firmware/peripheral map and Xiaozhi upstream foundation. Bring up camera, OLED, PDM mic, MAX98357A output and UART on the final physical board. Leave SD unused.
2. Port only the necessary existing RIO microphone/playback reference calibration and ESP-SR AEC into the current Xiaozhi ESP-IDF audio engine; do not run two cancelers or claim an AEC flag equals an aligned speaker PCM stream. Check audio ring synchronization, resample, delay drift, playback tail and double talk while camera/steppers run.
3. Connect current `LiveTurns` cancellation core to the actual Mac sound service. Every cancellation must reach decoder, Mac queue, head transport **and I2S/DMA**. Reuse the existing Xiaozhi server/local Ollama/SenseVoice/Kokoro where possible. If Pipecat/MLX is selected, do it **behind** the same provider interfaces and one speech ownership path now, not a later wholesale server replacement.
4. Qualify talking while interrupted by ordinary speech, preserving first words of new request; no special phrase/button. Test at fixed volume and 0.5m plus 1m as distinct test conditions. No false self interrupt from ten minute robot-only TTS.
5. Capture image and mic concurrently under loaded operation, record frame age, drop rates, audio latency, heap/PSRAM, thermal and networking. Set camera buffer count/grab mode only after measured comparison of `WHEN_EMPTY/fb_count=1` vs `LATEST/fb_count=2` on the delivered camera. No unverified automatic mode switch.

**Exit:** A2 audible voice gate passed physically before presenting robot one as conversational. Hardware test also establishes head layout is final enough to close enclosure.

## Stage 5: perception, provenance and durable memory built together

1. Reuse Google robotics camera poller/frame difference/stability routines and typed event patterns. Source camera frames from Sense with true capture timestamps and connection epochs; latest-only processing, stale drop, dedupe and optional on-device cheap person gate.
2. Select one actual local VLM/vision source with licensed code and **verified local model weights**; compare existing YOLO-World for target detection with a VLM for contextual scene description. An object bounding box alone does not mean "understands what changed".
3. Produce real person appeared/left, object appeared/moved, gesture, scene changed and handling/touch events; require debounce and rearm. Do not present camera movement due to tracks as a new user entering the room.
4. Design/store per-robot memories with `observed_by`, `shared_by`, `evidence`, `captured_at`, confidence and bounded expiry. Digital peer messages are hearsay with origin, not direct visual memories. No unconsented raw recordings or secret storage in Git.
5. Integrate restart tests: stale callbacks, corrupted DB, duplicate event IDs, conflicting two writers, two similar scenes from different bots, time offset and silence/quiet mode. If five cameras observe one shared event, store it without forcing five speeches.
6. Provide a deterministic test corpus of prerecorded but consented frames and user scripted interactions. Test false-positive and false initiation rates as well as detection.

**Exit:** A9 first-stage event detection and explicit memory provenance, not just a camera capture API.

## Stage 6: actual independent, contextual, interruptible conversation

1. Reuse Reachy Mini `idle_policy.py`/handler, Stackchan-agent `Behavior.hpp`, Xiaozhi Desk Robot `ambient_behavior`/camera attention and Google's event bus. Pick **one** activity owner and adapt only selected source code with verified license and revision; do not stack three competing state machines. Document selection before the integration.
2. Give each robot an event-driven activity state: novelty, curiosity, rest, social needs, last conversation, observed changes and explicit settings. Utility scoring with a deterministic hard veto layer: fault/stop > explicit user > busy tool/speech > quiet > candidate spontaneous action.
3. Produce a spontaneous **meaningful comment** about a person/object/scene change, as well as nonverbal attention, rest, mood and peer invitations. An LLM provides phrasing, not whether motion is safe. Separate scheduled activity from actual new external observations.
4. Implement the fleet shared speech lease, event coalescer and per-robot cooldown. Initial `>=120 s` between spontaneous group speech initiations is the default; an explicit human request is not throttled. No robot hears its peer's speech as a new user command.
5. Ensure live interruption cancels *spontaneous* TTS exactly like explicit TTS, cleans all queues and accepts the human's new turn. Quiet mode must cancel any spontaneous speech already requested and block new ones; local silent eye behavior may continue.
6. Simulate five robot observations, overlapping events, duplicate scene descriptions, live user speech during an unsolicited comment, model timeouts, listener drop, repeated faces/keys and false detection. Tests must fail if an older callback announces after quiet is enabled.

**Exit:** A8 + A9 + A2 integrated experience observed on robot one and simulated with five independent identities. A timed greeting alone is a failure.

## Stage 7: full local pet expressions and physical interactions

1. Select one licensed 128×64 face engine. Existing stock Xiaozhi UI is an initial diagnostic renderer, **not an accepted final idle character animation**. Evaluate RoboEyes GPL3 or MIT alternative before final code merge; preserve display driver/UI ownership in one task. Test blink/gaze expressions while TTS/network is busy.
2. Add head touch tap/hold through owned AT42QT1010, qualified MPU6050 (GY521 compatible WHO_AM_I 0x68 on 3.3V WROOM path; BerryIMU superseded and retained only as spare) handling/tilt/shake, audio event classifier only after true AEC, optional LED status language and optional knock/FSR/magnetic accessories. Touching a moving pet pauses motion immediately through body policy.
3. Make mood a character state, never misreport emotion as physical temperature, health or battery. Quiet/rest mode and sleep remain visible without talking.
4. Preserve research feature toggles for optional costumes, magnetic identity, heartbeat, breath fog, gesture, temperature and room environment. Their hardware remains individually qualified with an authenticated event source rather than electrically piled onto the first head.

**Exit:** A1, A10, A11 and selected A12 with head enclosure, microphones and motion under load.

## Stage 8: autonomous *intent*, operator-controlled motion and real objects

1. Build a motion arbitration gateway with a strict absent model credential. A human explicitly enables the ongoing pet session; it persists past 300s **until pause/stop** but network loss/fault/reboot cancels it. Short drive pulses/watchdog never cease.
2. When enabled, do stop/look/short bounded drive/observe cycles only inside a cleared patch with qualified sensor coverage. No blind reverse on cliff or unconditional random turns.
3. Reuse existing gripper models and scripted/calibrated movement clips; execute `observe -> align -> lower -> grip -> lift >=10mm -> hold 3s -> visually verify -> place`, with real keys and wrapped candy. Any unobserved slip is not success. Current servo target angles give no real measured force feedback. Optional INA219, limit switch, FSR or gripper ToF can be qualified without changing the lift/grip structure.
4. Record independent 10 trial sets with at least 8 successes for each object, and human help as a failure. Uncertain task/ACK, fault and stop abandon safely.

**Exit:** A3, A4, A5, A6, including actual motion and real object trials.

## Stage 9: freeze qualified robot one

Record all A1–A12 at final normal acoustic volume, maximum supported motion, representative desktop surfaces, loaded power and installed head/gripper/costumes. Publish measured timing, current, temperature, calibration file/hash, source revisions, build/flash hashes, full delivered receipts and failures. Keep raw logs and real attempts. Do not pass from simulation or fabricated bench numbers. **Only then** print/copy four permanent sets.

## Stage 10: identical fleet, not a reduced derivative

Give each a separate physical acceptance sheet, camera perspective/power calibration, link credentials, robot ID and memory. Same functional core and firmware interfaces, different hats/voices/behaviors. Record five concurrently connected streams, one selected speech and one motion owner; test stop/disconnect isolation and tool cleanup. Use digitally delivered peer conversation, not mutual audio transcription. Ensure costumes do not occlude any optical/acoustic/safety port.

## Stage 11: full five-peer continuous experience

Demonstrate all five noticing scenes, one contextual shared event reported once, a different robot privately recalling its own observations, an unsolicited social invitation and a ten-utterance controlled game, user interruption at any point, accurate quiet/stop response, and no unintended motor action. Later simultaneous physical roaming and docking require their own complete localization/obstacle/charging qualification; they are **research ambitions, not implied safe by a ten-turn chat test**.

## Stage 12: experimental feature families with preplanned interfaces

The [feature register](source-map.md) preserves everything in the HTML including advanced multimodal sensing, body-awareness experiments, virtual desktop senses, optical/magnetic games, music, dreams, multiple characters, docking, physical passing and embedded edge AI. Each electable module has `source -> electrical profile -> mounting -> schema -> permission -> test`. If hardware requires a different controller, more current, another microphone, extra servo, a wide-angle sensor or redesigned optics, declare it an **expansion hardware variant** up front and preserve the existing qualified core. Do not quietly install it as if every optional module was part of the $50 core.

## Linear change management rules

* **No hidden substrate swaps.** Model/provider changes use interfaces. Sensor substitutions require measured parity, bus/driver changes, budget delta and explicit review. CAD revisions retain source and versioned adapter only.
* **Every stage produces a permanent artifact.** Source lock + decision record, dimensioned assembly, schematic + bus register, tested body, tested head, actual perception, scheduler + memory, sensor events, motion/pickup acceptance, qualified fleet. All later stages consume these unchanged contracts.
* **No promise of impossible no iteration.** Bench discoveries may invalidate a premature choice. By resolving them with reversible fixtures **before** final assembly, the project avoids avoidable demolition. An engineering gate can block; it must not be bypassed.
* **No lost ideas.** Each addition updates the feature register and its status, exact link, interface and test. Historic source remains attributed even when rejected or physically infeasible.


---

## Concrete code and integration ownership plan

*Integrated from the user-requested full feature documentation review on 2026-11-09. This section is planning and source evidence only unless a measured result is linked.*


This is the actionable engineering map behind [linear stages](PLAN.md). **No code path below is claimed implemented by this document.** Names marked "new" are planned files, not confirmation they exist. Pick one upstream implementation per subsystem, pin/license it and use narrow adapters; keep the existing working stack. The first full-feature robot should be the same base that is duplicated four times, with only calibrated data and cosmetics differing.

## Preserve existing source and the already proven boundary

| Existing code | Keep, extend or test | Do not do |
| --- | --- | --- |
| `code/firmware/body/lib/StepperDrive/{StepperDrive.h,StepperDrive.cpp}` | Tested nonblocking 28BYJ phase generation, bounded speed, injected clock; add calibration/profile data after loaded measurements | Replace with a blocking tutorial sketch, change max pulse or add independent robot motion authority without tests |
| `code/firmware/body/lib/CliffGuard/` | Fault-latched policy with validity/freshness; feed real calibrated sensor frames and test recovery | Rewrite to permit blind sensor-degraded reverse or LLM-initiated rearm |
| `code/firmware/body/src/main.cpp`, `include/BodyPins.h` | Hardware adapter, five-sensor status, touch/IMU and reporting, physical output init, watchdog | Borrow wrong GPIO41/42 Sense PDM pins or use motor pins for optional sensors |
| `code/firmware/head/sense/config.h`, `desk_robot_sense.cc` | Existing compiled XIAO Sense pin map, camera, OLED, audio, UART and authenticated bridge | Port a completely different S3 board's pin layout or disable audio input while speaking |
| `code/firmware/head/install_overlay.py` | Keep pinned Xiaozhi build, exact Sense board augmentation, use reversible narrow AEC/audio feature install | Vendoring incompatible full forks or casually editing original `upstream` tree |
| `code/laptop/src/desk_robot/live_turns.py` | Offline frame pacing, connection/turn epochs, obsolete audio rejection, opt-in observation; attach actual device and provider transport | Treat offline queue clearing as real I2S/DMA audible cancellation |
| `code/laptop/src/desk_robot/runtime.py`, `config.py` | Existing local/simulation provider selection, per-robot IDs and settings; inject one chosen voice/activity/memory owner | Start five independent shared GPU model copies or allow two simultaneous agent activity owners |
| `code/laptop/src/desk_robot/conversation.py` | Preserve bounded digital peer turns and speaker lock; add true live spontaneous turns via single lease | Treat generic turn-limited conversation as continuous social pet runtime |
| `code/laptop/src/desk_robot/controller.py`, `api.py` | Existing authenticated/manual permit, camera/pickup safe jobs and local stop; add pet lease authorization without model credentials | Let a scene description, MCP model or peer message arm, move or clear fault |
| `code/firmware/head/tests`, `code/tests`, `code/firmware/body/tests` | Expand host tests and CI acceptance for all new producers/owners and failures | Mark host tests as physical acceptance or rely only on a full mock demo |

## New interfaces, intended owner and source to remix

| Intended code (new unless existing implementation proves suitable) | Required contract and tested upstream seam | Tests before runtime enabling |
| --- | --- | --- |
| `code/firmware/body/lib/TofBus/` | Small checked I2C/mux platform port around pinned MIT Pololu VL53L0X v1.3.1 startup and the existing bounded nonblocking raw register reader, channel 0–4 selection, status/age, per-surface calibration and error/fault invalidation | Fake bus short read, NACK, timeout, invalid status, reset, mixed channels; actual sampling age under motor load |
| `code/firmware/body/lib/BodyEvents/` | Fixed typed reporting to head for floor fault, touch, IMU, low supply, servo state, completed actions. No model or network in the safety path | Local stop before head event delivery, stale event ID, duplicate input, invalid field payload |
| `code/firmware/head/sense/audio_reference_adapter.*` | Real PDM microphone + reference from currently played I2S PCM, align/resample into Xiaozhi ESP-IDF AFE; reuse RIO algorithms/tests with actual GPIO pins and audio task synchronization | Ring reset races, double-talk, playback tail, 90ms only candidate, no echo gate muting user speech |
| `code/firmware/head/sense/playback_flush.*` | Explicit flush/stop generation, decoder plus DMA output zeroing/clearing, acknowledgement of acoustic stop | Old TTS cannot continue or resume after user speech, quiet, network reconnect or change of robot |
| `code/firmware/head/sense/face_adapter.*` | One licensed 128×64 eyes renderer feeding `idle/listening/thinking/speaking/curious/sleepy/blocked/offline`; compare RoboEyes vs MIT source | Offline blinking, display timing and concurrent live audio camera UART; license and head shell fit |
| `code/laptop/src/desk_robot/perception.py` | Typed event source using Google robotics `camera_poller.py`, frame difference/stability, actual Sense capture timestamp, YOLO World or chosen local VLM; event-gated image calls | Real scene change, person/hand/key/candy labels, stale/false image, camera self-motion and duplicate events |
| `code/laptop/src/desk_robot/events.py` | Event schema v1 includes robot/source, capture and receipt clocks, confidence, scene fingerprint, epoch, privacy, witness vs told_about; one dispatcher for camera/touch/sound/safety/peer | Producer spoofing, out-of-order event, reconnect, TTL, duplicate ID, cross-robot misrouting |
| `code/laptop/src/desk_robot/memory.py` | Per-ID durable private records, append-only history/SQLite where selected, single writer, direct witness provenance, preferences, social and cooldown state; exclude raw recordings by default | Atomic writes, restart/corruption, privacy/retention, two concurrent memories not cross-contaminating |
| `code/laptop/src/desk_robot/pet.py` | One deterministic activity owner, statuses `idle/attentive/interacting/talking/rest/exploring/social`, weighted action/utility scorer and hard veto; adapt selected Reachy/Stackchan/Xiaozhi Desk Robot logic | Same clock/random seed reproducible, no autonomous movement from pet alone, no repeated greeting, quiet and turn preemption |
| `code/laptop/src/desk_robot/observation_runtime.py` | Connect `LiveTurns` latest-frame/heartbeat to true camera/scene event producer and LLM/VLM observation turn, keeping busy through audio completion | Prompts never interrupt humans/tools, old completion never clears newer epoch; avoid two speech loops |
| `code/laptop/src/desk_robot/audio_runtime.py` | One shared provider adapter for local STT, live Kokoro speech streaming, transport, VAD, interrupt cancellation and actual head FLUSH | Acoustic A2 on hardware plus host stale chunk/cancel tests; STT fails closed with no fabricated text |
| `code/laptop/src/desk_robot/fleet_events.py` | Coalesce 2–5 camera event sources, choose actual witness/representative, no duplicate group comments; candidate 3s window and evidence-based confidence | Five cameras one event, different events not merged, stale clusters never spoken |
| `code/laptop/src/desk_robot/speech_floor.py` | Exactly one leased audible speaker with epoch/TTL and closed-state cleanup, human voice preemption and unsolicited group cooldown | Drop stale spontaneous speech, do not ventriloquize a disconnected robot, human interrupts current speaker |
| `code/laptop/src/desk_robot/motion.py` | Operator-only continuing pet enable, bounded move permit, single active body source, local guard status, cancel/recovery; no model motor credentials | >300s persistence, stop/fault/disconnect revocation, no auto resume, watchdog/pulse bounds |
| `code/laptop/src/desk_robot/behavior_actions.py` | Typed limited actions: eyes/look, rest, context speech, invite peer, safe inspect, bounded operator-permitted roam, calibrated pickup | Unknown actions rejected, no arbitrary LLM angles, no source bypass of motor controller |
| `code/laptop/src/desk_robot/optional_sensors.py` (or equivalent adapter registry) | Register *only selected* experimental devices from feature IDs: I2C, touch/analog, virtual desktop, remote environmental pods with privacy and fixed typed events | No connected module -> disabled, no false "sensor healthy", wrong breakout/address/voltage not initialized |
| `code/config/fleet.example.toml`, existing private local config | Robot identity, voice, persona, quiet preference, sensor capability ID, minimum qualified calibration, camera and speech owner, Mac rate limits | Identical core but unique encrypted secrets, private paths, no robot ID collision |

Naming is proposed; consolidate instead of creating a file per adapter if the current source offers a better integration seam. The **interfaces and test responsibility** matter more than a specific Python file count.

## API and message contracts

Keep the WROOM UART commands and authenticated head bridge as recorded in [existing interfaces](guides/interfaces.md). Add versioned read-only sensor/event status without changing the current meaning of `arm`, `rearm`, `stop`, `keepalive`, `drive`, `lift` and `grip`.

Proposed typed app events for a local Mac data model:

```text
CapturedFrame(robot_id, connection_epoch, capture_monotonic, receive_monotonic, jpeg, producer_id)
SensorEvent(robot_id, seq, sample_monotonic, kind, value, validity, confidence, source_id)
ObservedScene(robot_id, scene_id, captured_at, classes, claims, confidence, vision_model_version)
MemoryRecord(robot_id, event_id, observed_by, told_by, witnessed, occurred_at, content, provenance, ttl)
ActivityIntent(robot_id, activity_kind, evidence_refs, created_at, expires_at, veto_snapshot)
SpeakLease(robot_id, generation, owner, issued_at, expires_at, group_cooldown_key)
FlushDirective(robot_id, epoch, reason, cancel_model, cancel_tts, clear_head_dma)
SafetySnapshot(robot_id, timestamp, armed, latched_faults, sensor_freshness, calibration_version)
```

**Authority:** Typed events can be generated by actual sensors, the camera, or a memory/message service, but no event gives motor privileges. Only operator gateway creates a permission token; model processes have no credential or socket that can arm the body. A speech lease does not imply a movement lease. No remembered prior lease can be restored after reboot.

## Exact local Mac benchmark before choosing one provider

Record real resource loads for existing Xiaozhi server + Ollama + Kokoro + local STT first. Compare one shared MLX Whisper large-v3-turbo provider, whisper.cpp fallback and Pipecat/HF alternative only under *the same* one/two/five robot scripted corpus. Compare recorded actual captured acoustic latency, first TTS chunk, VLM scene throughput, memory, thermal and concurrent events. Choose one working adapter before final multi-robot service; do not clone five large models per worker by default. Keep the alternative behind the interface without altering Sense wiring or safety.

## Code and source-license policy

* Never alter ignored original upstream clones or the preserved `docs/cad/originals/` files in place. Record pinned SHA and notice, place small remix patch in a distinct adapter and give source-specific attribution.
* RoboEyes is GPL3; a combined firmware distribution must respect that choice. The original SMARS ancestor and forklift are NC-SA CAD, while Cozmars/Sparky/Tiny Engineer have separate terms. Their license is not inherited from the MIT app just because we linked the file.
* New optical drivers prefer official ST ULD and licensed vendor examples, but every I2C operation must report actual status/quality rather than accepting stale values on errors.
* When replacing an existing source module, write a controlled comparison, allow independent rollback *at source selection time*, choose once before final integration. Avoid manufacturing the wrong hardware and later silently switching to a second system.

## Finishing evidence

The real live robot needs a complete assembled wiring/shell BOM, true body sensor acquisition and guard trials, uninterrupted local face while offline, actual Sense AEC + device flush audible A2, contextual visual A8/A9, persistent separate per-ID memory, one-speaker five-peer social play, pet mode enabled until paused with local safety, and true 8/10 key/candy pickup. All 200 features stay registered, but individual exotic hardware requires a separate approved cost, electrical and sensor test record before calling it installed.

This file is an **implementation checklist**. It does not create those modules or claim their tests were executed.
