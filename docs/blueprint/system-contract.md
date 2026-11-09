# Frozen system contract before the first permanent build

**Status:** proposed final interface allocation. An assignment is a design decision unless qualified by a named test. Preserve all user-visible hard requirements even if a module is not yet powered or written. Read [feature register](feature-register.md) for every archived idea and [prebuild blockers](decisions-before-hardware.md) before wiring.

## The five-robot end state

Five independent, identical functional cores, with distinct removable costumes, voices, names, memories and evolving behavior profiles. Each has a fixed expressive 128×64 monochrome face, Sense camera/PDM microphone, speaker, head touch, handling awareness, two independent 28BYJ-48/ULN2003 tracks, a front lift and *closing* gripper using two positional MG90S servos, four downward views and separate forward ranging, its own power and credentials. One shared M1 Max Mac performs speech, visual reasoning, LLM decisions and peer coordination; no Pi/Uno/Pico added.

End experience: robots look alive while idle; notice real scene/person/object events on their own; initiate brief context-grounded speech or activity; notice a person talking and **allow ordinary speech to interrupt their own ongoing TTS**; remember *what each observed* and relevant prior conversations; decide when to be curious, social, sleepy, engaged or quiet; respond to touch, shake, sound and being lifted; continue safe operator-enabled desk exploration until paused; pick up flat real keys and wrapped candy; invite each other to games and conversations with one audible speaker at a time. These are **hard product requirements**, not optional upgrades or demo decorations.

## Compute, credentials and interfaces

| Owner | Final responsibility | Forbidden authority |
| --- | --- | --- |
| XIAO ESP32S3 Sense head | Camera capture and timestamp, local OLED animation, PDM microphone and playback-reference AEC, MAX98357A speaker, optional local wake/sound classification, authenticated Mac transport and UART body bridge | No bypass of body cliff guard; never grant local USB recovery or mint motion authorization |
| ESP32-WROOM body | 2 steppers, 2 servos, four downward sensors/forward range, 500ms watchdog, 250ms bounded drive, local fault latch, physical input handling, measured state | No prompt/model driven arming; no continued motion after fault, unknown sensor state or link loss |
| Mac per-robot session | Live media and epochs, VAD/ASR, TTS/LLM/VLM adapters, per robot memory and persona, typed observation source and activity candidate | No direct serial motor drive or rearm rights |
| Mac shared coordinator | Fleet world events, deduplication, one speaker token, one rover motion owner initially, social turns, user pause/quiet and immutable event log | Never invent observations or grant motion from AI recommendations |
| Mac operator gateway | Authenticated human enable, one bounded job or continuing pet permission until paused, hard revocation and audited permits | Never accept LLM/model token as human operator |

A single request/response protocol is preferable to simultaneous independent Pipecat/Xiaozhi/MQTT owners. Keep the current authenticated head API, WROOM UART `115200 8N1`, local server bridge and tested `LiveTurns` epoch logic. Put future provider/transport implementations behind the same session adapter. Avoid two independent speech loops, memory writers or robot body controllers.

**Proposed typed event envelope**, to reserve from day one even before every producer exists:

```text
schema_version; event_id; robot_id; producer; event_type; monotonic_capture_time;
mac_received_time; connection_epoch; turn_epoch; data_quality; confidence;
object_or_person_alias; scene_fingerprint; ttl; cooldown_key; correlation_id;
privacy_class; acknowledged_by; action_owner; safety_snapshot
```

Use explicit types for `person_entered`, `person_left`, `new_object`, `object_moved`, `hand_visible`, `scene_change`, `touch_tap`, `touch_hold`, `handled_suspected`, `shaken`, `placed_down`, `sound_clap`, `whistle`, `speech_started`, `speaker_flush`, `floor_fault`, `peer_invite`, `peer_reply`, `tool_result`, `quiet_on`, `stop` and `activity_complete`. Persist neither raw audio nor raw frames by default. A timestamp must identify **capture**, not merely the later network receipt. Retain producer identity on every delayed callback; stale replies cannot be reidentified as a new turn.

## Natural proactive conversation is a complete pipeline, not an idle timer

1. **Notice.** Head keeps a fresh image. Reuse Google's camera poller/frame difference and event bus concepts, with bounded queue and observed quality. Proposed ~1 frame/s and 2s freshness from the existing `LiveTurns` state are *starting points*. Source proposals for 3-frame confirmation/12-frame release, on-device person model, spatial tracking, a 5-minute person cooldown and shared scene fingerprints are experiments, **not yet measured policies**.
2. **Interpret.** Mac combines fresh visual observations with touch/motion/sound events. A local object/person model or VLM labels only what the image supports. Uncertain sighting remains uncertain; no invented names, precise distances, positions or memory.
3. **Remember.** Store recent episodic observations per robot ID and provenance, explicit user preferences, previous interactions, peer encounters, and bounded long-term semantic memory. Each robot remembers what it witnessed, not whatever another robot saw. Shared peer messages are tagged second-hand. Single writer, bounded retention, restart recovery and no movement authorization persisted.
4. **Choose.** A deterministic, testable activity owner with scored options and hard vetoes chooses `observe`, `look`, `inspect`, `react`, `rest`, `invite_chat`, `offer_help`, `social_play`, `explore_patch` or supervised `pickup_target`. Curiosity/mood/social drives influence selection; LLM/VLM **suggest content or high-level intent only**. Hard vetoes: stop/fault > human explicit turn or pickup/manual > tool busy > current speech > quiet > pet/social > idle. A future utility scorer is preferred over LLM-chosen actuator commands.
5. **Initiate.** For a true observation change, choose one robot to speak once, with a relevant concise remark grounded in captured context. The initial group spontaneous speech ceiling is one initiation per **120 seconds total**, configurable; reevaluate candidate activities roughly every **30–90 seconds**, without generic timed greetings standing in for camera events. A group event coalescer stops five identical announcements. Silence can be the correct activity.
6. **Yield.** Human speech wins the floor even over spontaneous TTS. Normal speech, without wake phrase/button, interrupts and flushes Mac transport plus ESP32 decoder/I²S DMA while preserving the *new spoken request*. Pauses are not mistaken for a finished conversation. Tool/session activity stays busy until actual device playback completes. Quiet, stop, reconnect and generation changes invalidate stale queued speech.
7. **Interact.** Shared Mac coordinates five different voices, per-robot speaker/mic state, digitally delivered peer transcripts, cooldown and identity. The existing 2–5 robot group chat limits of **6/8/10 utterances** and 5min overall apply to bounded sessions, not an excuse to disable ongoing future pet activity. One audible speaker at first; one moving robot initially; the end-state possibility of simultaneous roaming and object handoff remains a separate qualified research requirement.
8. **Act safely.** Physical motion is a locally guarded outcome of explicit operator enable, never a side effect of a scene description. Without qualified cliff coverage the robot can animate, observe and speak, but **cannot roam**. A sensor fault or lost link cancels movement and does not auto-resume when health returns.

**Do not mislabel reactive eye animation or an LLM greeting as a contextual proactive conversation.** Required test includes appearing in view without speech, fresh semantic observation, relevant self initiation, response to interruption, correct memory provenance, quiet mode and five-camera deduplication. See [acceptance](acceptance.md).

## Board pins and all planned expansion must be frozen before assembly

These are **current compiled software assignments, not a finished tested wiring harness**:

| WROOM body | GPIO | Notes |
| --- | --- | --- |
| Left ULN2003 phases | 13, 14, 25, 26 | 28BYJ track, half step current conservative limits |
| Right ULN2003 phases | 27, 32, 33, 23 | Confirm phase order and track direction on real hardware |
| Lift servo / grip servo | 18 / 19 | Rated independent actuator rail; servo target is not position feedback |
| Body I2C SDA / SCL | 21 / 22 | 3.3V pullups, TCA9548A upstream; bus health and scan time measured |
| TCA9548A reset | 4 | Only if purchased board actually exposes RESET |
| Head touch | 34 input | AT42QT1010 OUT, input-only GPIO |
| UART head link RX / TX | 16 / 17 | Head TX2 / RX1, common logic ground |
| Candidate other signals | 35,36,39 input-only | External pullups if needed, no unqualified extra digital outputs |

| Sense head | GPIO | Notes |
| --- | --- | --- |
| Onboard microphone PDM clock/data | 42 / 41 | **Reserved**. HTML optional MAX30102 wiring to these pins is electrically wrong. |
| SSD1306 I2C SDA/SCL | 5 / 6 | Head I2C1, separate from camera SCCB I2C0 |
| MAX98357A I2S BCLK/LRCK/DOUT | 4 / 7 / 8 | Amplifier speaker terminals differential, not tied to GND |
| Body UART TX/RX | 2 / 1 | Do not copy alternative GPIO43/44 from another head variant |
| Camera | Stock Sense fixed pin allocation | Preserve 8MB flash/8MB PSRAM, native USB19/20, SD disabled/empty |
| SPI SD pins | Shared with audio | Do not insert SD, do not initialize second peripheral |

Body mux `0x70` planned channels **0 front-left down, 1 front-right down, 2 rear-left down, 3 rear-right down, 4 front obstacle**, with **5–7 reserved** for qualified expansion. Same-address `0x29` ToFs can be separated per channel; a mux does **not** imply correct level shifting or enough power. The present plan names VL6180X downward, but ST marks it obsolete. Qualify a supported VL53L4CD or another physically verified low-height alternative before fleet purchase, with correct vendor driver and optical field geometry; don't simply rename old L0X constants. Existing current body firmware has **no live sensor acquisition or calibration**, so it correctly cannot arm.

Optional MAX30102 belongs on the **WROOM body** I2C, potentially an unused mux channel; breakout regulator/logic/LED voltage must be checked before assigning. BerryIMU is an owned, likely older revision; validate chip IDs and I2C addresses before adopting. Optional I2C devices (MPR121, APDS9960, SHT4x, INA219, BME688, SCD40, BH1750, thermal and colour modules) need explicit bus topology, power, address collision table and footprint budgets. There is **not** room to wire every experimental module onto existing exposed pins. Design swappable expansion boards or satellite nodes as a separate future variant only if scope/budget approved; optional hardware is not secretly part of the first $50 purchase.

## Power, actuation and mechanical freeze

1. One *selected and electrically rated* rechargeable 1S source plus charger/protection/regulated 5V path, or another explicitly approved matched design; document cell chemistry, continuous load, charging and thermal limits. The HTML's Architecture A IP5306 choice is **proposed**, not bench-certified. `3000mAh` is capacity, not an acceptable charge or discharge rating. Avoid claiming one 1000uF cap prevents brownouts. **Do not revert silently to an unspecified owned USB bank** to make the price look smaller.
2. Reserve accessible, fused/switchable actuator power and a logic rail/reference with suitable common grounds. Measure peak and sustained current with both steppers, WiFi/camera, speaker, lift/grip and worst legal actuator overlaps. Do not assume the charging current rating is the boosted output rating. No automatic motion at power-up or rail recovery.
3. Local WROOM hard stop, fault latch, 250ms maximum drive pulse, 500ms communication watchdog and USB-local `rearm` are retained. Missing/invalid/stale floor data or unknown front clearance fail closed. No automatic blind reverse or degraded retreat; manual recovery must leave drive disarmed. Holding gripper PWM during normal fault is intentional to avoid dropping keys; real undervoltage **may make powered holding impossible**, so test current priority, payload containment and controlled power failure instead of assuming perpetual hold.
4. Open-loop 28BYJ `StepperDrive` currently caps speed at 40% of 400 half-steps/s (160 half-steps/s effective), acceleration around 320 half-steps/s². The HTML's 700 steps/s, 1000 steps/s², 4076 half steps/rev, full/half mode and mm maps are proposed measurements, not current firmware. Qualify torque, slip, gearbox backlash, coast, direction and margins before changing.
5. Reuse SMARS stepper chassis, original compatible track/wheel parts, Bluino/SMARS lift and closing claw, Cozmars head style first and saved Sparky shell as fallback. Use two MG90S for **lift plus grip**, not pan/tilt. Camera remains fixed to jaws, with visual access throughout gripper travel. Do physical servo pocket, shaft, gear, sweep, tipping and payload mass checks **before** a full final print.
6. Design **all needed openings and serviceable expansion volume on day zero**: camera field, mic acoustic port/AEC separation, speaker volume, OLED bezel, head touch, sensor optical windows including rear views, removable costume and magnetic accessories, approved charger connector, fuse/switch, USB access, antenna keepout, airflow and wiring strain relief. A part may be unpopulated initially; the mount interface must not force shell destruction later.

## Exact physical acceptance boundaries

No hardware is certified by host CI. First prototype must prove A1–A12 including **19/20 audible stops within <=500ms, 18/20 correct interrupted new intents, zero self-trigger interruptions in 10min echo-only**, and **8/10 true keys plus 8/10 wrapped candy** with 10mm lift, 3s hold and placement. Cliff trials require measured stop margins on supported surfaces, actual faults and swept turns. Five robots must each qualify independently, keep identities/memory separate and perform clean ten-turn coordinated speech.

The HTML's looser 18/20 at 50cm and 700ms median is **not** an acceptable replacement. See [acceptance ledger](acceptance.md).

## Safety and privacy rules for extra ideas

Never use a deliberately unsafe mains antenna as a casual sensor, direct mains probe, unqualified Geiger/radiation module, unspecified 433MHz interception, thermal camera for sensitive inference, raw Bluetooth identity tracking or unconsented audio/video archiving as implicit baseline. A heartbeat sensor is an *opt-in illustrative interaction* requiring consent and medical caution; no health diagnosis. Eavesdropping, sensitive ambient sensing and home connectivity are opt-in and isolated. Games and pet feelings are simulation or fiction unless a calibrated physical source exists.
