# Product definition — five active desk pets

Updated 2026-11-04. This is the canonical product and acceptance brief, ahead of final
mounting CAD and assembly instructions. It distinguishes requested behavior from
working software and physically verified hardware. **No complete robot has been
assembled, flashed or tested.**

Accepted requirements are not pending discovery: local Mac first; ordinary-speech
interruption in robot one; camera observations and reactions without a spoken
prompt; proactive activities and exploration until the user pauses/stops them;
five identical functional cores with individual cosmetics and identities.
Touch/petting and motion awareness (tilt, shake and suspected handling) are also
required. Optional diffused lighting adds expression; extra modules are not
forced into the core when their integration would be substantially different.
Source review does not mark a feature implemented. Acceptance cases below define
completion; do not reopen these decisions as missing user requirements.

**Voice requirement revision:** the user explicitly requires ordinary-speech
interruption in the first build and has now purchased **XIAO ESP32S3 Sense**.
Keep it and reuse RIO software AEC/live cancellation plus Google/Pipecat streaming
patterns. A replacement board is not established as necessary. [Required audio gate](guides/audio-barge-in.md)
and [reuse sources](research/2026-11-03-sense-realtime-reuse.md). Order quantity,
arrival and revision remain unconfirmed; no physical test has passed.

**Complete day-zero scope:** The [full-feature system contract](blueprint/system-contract.md), [200 item feature and sensor register](blueprint/feature-register.md), [linear build](blueprint/linear-build.md), [source index](blueprint/original-html-link-index.md) and [acceptance plan](blueprint/acceptance.md) preserve the richer original HTML research without changing A1–A12. Proactive conversation means **fresh unsolicited visual context, meaningful self initiation, per-robot memory, interruption and five-robot speaker arbitration**; generic scheduled greetings are not equivalent. All mandatory interfaces must be planned before final assembly to avoid avoidable rebuilds. Physical experiments and optional add-ons remain separately costed/qualified, not secretly installed or discarded.

## Appearance and shape

The user chose **a rounder existing head case**, replacing the boxy EVA appearance.
Keep the slow tracked body, a face above the body and one front lifting claw.
All five robots use the same functional core; color, removable hats and costumes
give them different characters. Costumes must leave optics, microphone, speaker,
antenna, cooling, USB, switch and moving parts clear.

**Added appearance reference: FETCH by SECTOR 07.** Its inset face, substantial
bezel, soft corners, contrasting side panels and antenna-like ears inform the
next visual study. Combine those cues with our rounder existing head and tracked
base. Optional ears are static/removable; both positional servos stay assigned
to lift + grip. Our existing white monochrome OLED stays. This is inspiration,
not selection of Fetch's much larger shell or additional actuators.
[Video/build review and reuse boundaries](research/2026-11-03-fetch-appearance.md).
Latest styling adds Cozmo/Vector's rounded side panels and compact tracked
silhouette. Keep the fixed head and existing lift/gripper. Styling is not proof
of mechanical fit or selection of a proprietary model.

The longer-term experience remains **five active peers playing together**. The
first acceptance stage serializes movement while all five can animate and
converse; this is a staged fleet bring-up, not a replacement of that group goal.
Simultaneous roaming and physical passing remain additional, unqualified work.

![Rounded-head layout study](cad/concepts/2026-11-03-rounded/proposed-robot.png)

This preview uses the **actual saved stepper chassis and Sparky v0.1.0 shell
meshes**. It is a layout study: tracks, lift/claw, module positions, head mount,
OLED insert and camera lens are illustrative envelopes. They are not new print
files or proof of an assembled mechanism. That historical preview omitted the
then-proposed bank. The current1S kit is also not fitted; its measured envelope
and mass may change the silhouette. [Front](cad/concepts/2026-11-03-rounded/front-layout.png),
[side](cad/concepts/2026-11-03-rounded/side-layout.png) and
[top](cad/concepts/2026-11-03-rounded/top-layout.png) show the same proposal.

| Area | Product requirement | Existing source / qualification |
| --- | --- | --- |
| Body | Low tracked rover, two independent drive motors | Saved SMARS 28BYJ-48 remix. Chassis about 58×86×42 source units, excluding complete tracks. STL mm interpretation and assembly interfaces remain to qualify. |
| Head | Rounded housing, expressive face, camera/microphone/speaker and concealed head touch | Compare Cozmars head/packaging first; saved Sparky v0.1.0 is an unprinted fallback. Neither is fitted to Sense/SSD1306 and the owned mechanism yet. |
| Manipulation | One front gripper that raises/lowers an object; two positional servos total | Saved Bluino gripper + original SMARS forklift. Actual rack/linkage orientation, MG90S fit, flat-key reach and attachment to stepper chassis remain open. Orange preview is a symbol for this mechanism. |
| Camera pose | Fixed relative to jaws; see the approach area and pickup/placement, including the raised payload | Small camera wedge/spacer or aperture correction allowed. Choose tilt from actual camera field of view, not the lens symbol in this preview. Check occlusion by jaws, payload and head shell. |
| Edge sensing | Four downward optical views plus a separate forward obstacle view | Positions in preview are placeholders. Measure footprints beyond relevant tipping boundaries and all permitted pivot/reverse sweeps. A front beam does not cover every collision direction. |
| Power | Matched rechargeable 1S hobby battery kit, mounted low | Exact cell/holder, charging/protection and regulated 5 V module remain unselected. Check output current, heat, connectors, fit and stability; no runtime promised. |

The head is fixed: there is **no neck pan/tilt servo** in this parts allocation.
Looking around means animated eyes and, when permitted, cautious whole-body turns.
This is a hand-sized remix direction, not a committed overall size. Do not shrink
an entire case or mechanism to make the drawing fit real components.

The latest power direction is a budget rechargeable 1S kit. One 18650 cell
and holder are the candidate; select matched charging, protection and regulated
5 V output, possibly on an integrated board. A current rating must refer to
continuous 5 V output under the selected cell/input conditions, not charging
current or a peak. Use appropriate power wire; DuPont wires are for signals.
The previous bank example and $40.33 owned-bank BOM are historical. The delivered
cap stays $50 including already-spent money; a revised delivered quote is pending.

The [source-to-feature register](source-map.md) records all supplied projects
and videos plus additions found during research. Cozmars head/packaging is the
first comparison for the latest Cozmo/Vector styling; the saved unprinted Sparky
shell remains a fallback, not a fitted final head.

## Case choice and allowed changes

Sparky is a saved **fallback fit-check candidate**, not a qualified replacement shell.
Its v0.1.0 source uses a 1.3-inch OLED opening. Reuse the owned 0.96-inch SSD1306
with a measured bezel. Check a Sense mount, camera opening, microphone path,
speaker retention and removable rover bracket. The original lower front hole is
for an LED; the preview's lens there does not prove a camera module fits behind
it. A new nearby opening may be required.

Keep the shell's main shape and the existing drivetrain/lift. Small plates,
inserts, clips, spacers, sensor mounts, jaw tips and clearance corrections are
allowed. Do not adopt Sparky's power wiring without checking the selected 1S kit
or assume its full magnet set is required. Resolve shell retention within the existing
fastener allowance; add exact items to the BOM if needed.

The [case comparison](research/2026-11-03-rounded-cases.md) records why other
attractive designs are not automatically usable. EVA remains an unchanged
historical reference. Tiny Engineer's saved head is an alternative reference,
not selected: its intended0.91-inch display/servo housing does not establish
camera/audio/Sense or owned 0.96-inch fit.

## What it should do

These are requirements, **not a list of finished features**.

| Situation | Required behavior |
| --- | --- |
| Power on | Start disarmed. Show waking/ready eyes. No automatic track or claw movement. Report missing connection/calibration clearly. |
| Idle | Blink, glance and change between neutral, curious, happy and sleepy faces without waiting for a voice question. Keep animation local so the face remains responsive during Mac/network delay. |
| User speaks | Start a conversational session, show listening/thinking/speaking states and support multiple turns. **Ordinary speech during TTS interrupts playback and captures the new request without a button or special phrase.** Mac performs STT, LLM and TTS; playback-reference AEC and the abort chain must pass the audio gate. |
| A visible person or object appears | With observation enabled, derive a fresh event without a voice prompt/button, coalesce repeats and choose a suitable expression or short comment. Respect quiet mode, speech ownership and recent-event memory. Observation does not authorize movement. Face identity recognition is not required. |
| Pet mode enabled | Choose short curiosity, attention, rest or social activities without needing a new user question each time. Use a state machine, timers and observations; occasional LLM choices supply meaning, not motor timing. |
| Exploration permitted | Stay enabled until the user pauses/stops, without recurring two-minute renewal. Stop/look, make a bounded short movement, then observe again. Fault/disconnect/shutdown cancels the session. Blocked path means stop/wait/report; reverse/turn only in qualified clear swept space. No blind retreat. |
| Asked to pick something up | Observe → approach → align → lower → grip → lift → visually verify → hold → place. Stop/report rather than claim success if the object is absent, slips or cannot be confirmed. Use calibrated sequences, not arbitrary LLM joint angles. |
| Peers interact | Give each robot a unique ID/name, mood and local history. Exchange digital peer events through the Mac, serialize spoken turns, and react with expressions. Begin with five stationary peers and only one moving robot. |
| Quiet mode | No unsolicited speech or movement. Local quiet face animation may continue. User-requested interaction remains available. |
| Mac/Wi-Fi/sensor failure | Cancel activity, stop drive, preserve the current gripper target where powered, show fault/offline state. No automatic motor restart after reconnect or fault recovery. |

Proposed tuning defaults: blink every 3–7seconds, occasional gaze shifts every 6–15
seconds, activity reconsideration every 30–90seconds, and at most one spontaneous
spoken initiation per group every 120seconds. These are configurable personality
timings, not real-time deadlines. Explicit conversation turns use their own
bounded session. Quiet mode and a stop always override timers.

## Control and compute boundary

| Part | Responsibility |
| --- | --- |
| Purchased XIAO ESP32S3 Sense | Camera, onboard PDM mic, owned OLED, external MAX98357/speaker and connection to Mac/body. Reuse software echo-cancellation/reference; board order/revision and physical audio remain to qualify. |
| Owned ESP32-WROOM-32 | Two ULN2003/28BYJ tracks, two MG90S positional servos, sensor/mux acquisition, watchdog and local fault-latched stopping. |
| Shared Mac | Speech recognition/synthesis, LLM, vision, activity selection, peer coordination and per-robot memory. No Uno, Pico or Raspberry Pi is needed. |

The [interaction-sensor specification](hardware/interaction-sensors.md) gives
the touch/IMU/optional-light hardware, behavior, source reuse and acceptance.
The [photo audit](hardware/photo-inventory-2026-11-04.md) makes the owned
BerryIMU the prototype motion-sensor candidate; a new LSM6 purchase is conditional
on that board being unsuitable. Additional photographed modules remain optional.

Local Mac is the default compute route; cloud is optional. Camera capture starts
around one fresh JPEG per second during observation, subject to measured audio/
camera coexistence. Keep only the latest usable frame, reject stale/disconnected
camera data, and derive scene/person/target events before requesting expensive
vision reasoning. An activity controller chooses inspect/react/rest/social
activities without waiting for a user question. Deduplicate group observations
and serialize speech. No raw audio/image archive is required. WROOM retains
immediate local edge protection.

Priority is local stop/fault → explicit stop → manual or pickup task → pet/social
activity → idle animation. Only one motion source owns the body at a time.
Pet motion requires an operator-enabled session continuing until paused/stopped,
without recurring renewal. Models cannot enable it. Preserve short individual
drive deadlines, the body watchdog and existing one-use manual/pickup permits.
Pause/stop, fault, disconnect or shutdown cancels queued activity. Reconnection
and restart do not enable motion. Fault recovery is body-local and leaves motion
disarmed. This supersedes the earlier 120/300-second session proposal.

Use digital peer messages as the authoritative group conversation, not each robot
transcribing the other four speakers. Schedule microphones/audio to avoid
self-triggering. Pair conversations default to six total utterances; five robots
to ten. Initial interaction does not require simultaneous free roaming.

## Compatibility verdict

**The architecture has a coherent pin allocation and builds, but the complete
hardware combination is not yet proven.**

| Subsystem | Evidence now | Still required |
| --- | --- | --- |
| Sense camera/mic/OLED/UART | Baseline8MB/PDM/SSD1306 target compiles; exact-Sense RIO source has real software AEC/cancellation code | Order/revision, actual modules, software-reference timing/concurrency, pin adapter, live provider/frames, capture/playback cancellation and physical barge-in tests. A readme or muted mic is not a pass. |
| WROOM stepper/servo body | Stepper target and portable control tests pass | Actual phase order/direction,3.3V input behavior, loaded motion, current and heat. Open-loop step counts/servo targets are not measured position or force. |
| Five ToFs and mux | Fault-latch/interlock policy tested | Real checked I²C/mux/ToF acquisition and calibration are unfinished. **Current stepper build intentionally refuses arming.** Check3.3V pullups and exact breakout supply/RESET behavior. |
| Supply | Separate power branches/common ground documented | Select the matched 1S kit; check cell/protection/charger/5 V output current, wiring, actuator transients and full-system operation. Capacitors do not establish sufficient power. |
| Mechanics | Original files, dimensions, licenses and hashes saved; source-based visual now exists | Registered assembly, interference/sweep checks, measured parts, balance, slicer review and physical fit samples. |

Use [the current wiring map](hardware/wiring.md),
[head selection/audio guide](guides/modular-head.md) and
[firmware evidence](guides/firmware-foundation.md). The split architecture needs no
additional Uno/Pico. Existing build success does not validate substituted boards,
unmatched binaries, sensor wiring or the new case.

## Acceptance before duplication

| ID | Pass condition |
| --- | --- |
| A1 Face/offline | Five-minute stationary test: face animation remains responsive while the Mac is delayed/disconnected; no unintended motion. |
| A2 Voice/quiet | Multi-turn conversation shows listening/thinking/speaking states and passes the required [ordinary-speech interruption gate](guides/audio-barge-in.md), including audible-stop latency, capture of the new request and no false echo-only interruption. No button fallback. Ten-minute quiet-mode test has no unsolicited speech or movement. |
| A3 Control ownership | In simulation, operator enable remains active beyond 300 seconds without renewal. Pause/stop, manual/pickup preemption and link loss cancel active/queued pet motion; individual drive deadlines/watchdog remain effective. Model commands, reconnect and restart cannot enable movement. Initially grant one fleet motion owner; canceled queued movement never resumes automatically. |
| A4 Local edge stop | Test every sensor disconnect, invalid/stale reading, bus fault and relevant edge approach with a tether/catch setup. Log actual detection latency and coast distance; require measured margin before the support footprint crosses an edge. No universal stop distance is assumed. |
| A5 Manipulation | At least 8/10 actual flat-key trials and 8/10 wrapped-candy trials: lift visibly10mm, hold3seconds, then place under control. Record object dimensions/mass, slips and human assistance. Assisted trials fail. Blocks are supplementary, not a substitute for keys. |
| A6 Power/mechanics | Loaded drive/turns and lift/grip with Wi-Fi/audio do not reset the robot, loosen mounts or exceed component ratings. Record peak current/voltage and temperatures. Verify camera/sensor views throughout mechanism travel. |
| A7 Five peers | Five distinct stationary robots complete ten coordinated utterances with one speaker at a time, no unintended motion and clean stop/disconnect cleanup. Repeat calibration/power/stopping checks on each unit before its permitted movement. |
| A8 Initiative | In a five-minute stationary, non-quiet pet-mode trial, at least one attention, curiosity, rest or social activity starts without a new user prompt. Verify the 120-second group cooldown between spontaneous spoken initiations. No movement is needed for this test. |
| A9 Proactive camera | Introduce a visible person/object or scene change without speaking or pressing a button. Require a fresh observation and suitable reaction. Repeated/stationary events must not trigger repeated announcements; quiet mode suppresses unsolicited speech; stale/disconnected frames cannot trigger claims/actions. Run simultaneous audio/camera and record latency. Test five observation feeds for deduplication and one-speaker ownership. |
| A10 Touch | Detect pat/tap/hold through the real shell; reject bounce and repeated events. Touch during exploration pauses locally before expression/voice; no touch gesture rearms motors. |
| A11 Handling | Verify intended tilt/shake/suspected pickup with fused motion/floor/context, rejecting normal motor/servo vibration. Unsafe/held state inhibits tracks; putdown/reconnect/reboot cannot resume canceled motion. |
| A12 Sound/lighting, if enabled | External sound reactions remain responsive while self-speech/motors do not cause repeated startle; optional LED pin/voltage/current/quiet-mode behavior is qualified. |

Initial success excludes SLAM, precise map navigation, returning to a person by
known coordinates, force-controlled grasping, automatic charging, simultaneous
unrestricted roaming/chasing and physical object handoff. Those need additional
localization, coverage and validation. An active personality is achievable through
gaze, pauses, initiative and supervised movement without claiming those features.

## What the eventual print-and-assemble package must contain

1. An assembly drawing with actual parts, overall envelope, mass assumptions,
   source versions, mount/fastener positions and gripper/sensor/camera keep-outs.
2. An exact print manifest: original vs modified file, quantity, orientation,
   supports, material/profile, measured tolerances, license and hash. Fit samples
   first; do not present the concept `.blend` as printable CAD.
3. A delivered BOM under the unchanged $50 prototype cap, including every required
   connector/retainer and already-spent Sense money. Requote the revised sensor
   and 1S power kit; the old $40.33 mix and Amazon comparison are historical.
   Fleet reuse quantities remain incomplete.
4. Finished body sensor driver/calibration, face/initiative/memory/pet-session code,
   affected tests and firmware builds. Existing foundation is not that final code.
5. Illustrated wiring, power checks, exact-board flash steps, mechanical assembly,
   calibration, operation/recovery and fault diagnosis in one ordered guide.
6. Trial sheets for A1–A12. Paper completeness and physical acceptance are separate;
   no document can substitute for measuring the selected power kit, servos and prints.

Next work follows [the implementation plan](plans/2026-11-03-active-desk-pet.md):
implement/verify proactive camera events and pet activities alongside mechanical
fit work. Qualify the shell/interfaces, power and real sensor driver before
enabling physical movement; assemble and accept one unit before duplication.
