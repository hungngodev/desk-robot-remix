# Product definition — five active desk pets

Updated 2026-11-03. This is the product and acceptance brief, ahead of final
mounting CAD and assembly instructions. It distinguishes requested behavior from
working software and physically verified hardware. **No complete robot has been
assembled, flashed or tested.**

**Voice requirement revision:** the user explicitly requires ordinary-speech
interruption in the first build and has now purchased **XIAO ESP32S3 Sense**.
Keep it and reuse RIO software AEC/live cancellation plus Google/Pipecat streaming
patterns. A replacement board is not established as necessary. [Required audio gate](audio-barge-in.md)
and [reuse sources](research/2026-11-03-sense-realtime-reuse.md). Order quantity,
arrival and revision remain unconfirmed; no physical test has passed.

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

The longer-term experience remains **five active peers playing together**. The
first acceptance stage serializes movement while all five can animate and
converse; this is a staged fleet bring-up, not a replacement of that group goal.
Simultaneous roaming and physical passing remain additional, unqualified work.

![Rounded-head layout study](../cad/concepts/2026-11-03-rounded/proposed-robot.png)

This preview uses the **actual saved stepper chassis and Sparky v0.1.0 shell
meshes**. It is a layout study: tracks, lift/claw, module positions, head mount,
OLED insert and camera lens are illustrative envelopes. They are not new print
files or proof of an assembled mechanism. The power bank is omitted explicitly
because its dimensions and mass are unknown. Its eventual fit may change the
silhouette. [Front](../cad/concepts/2026-11-03-rounded/front-layout.png),
[side](../cad/concepts/2026-11-03-rounded/side-layout.png) and
[top](../cad/concepts/2026-11-03-rounded/top-layout.png) show the same proposal.

| Area | Product requirement | Existing source / qualification |
| --- | --- | --- |
| Body | Low tracked rover, two independent drive motors | Saved SMARS 28BYJ-48 remix. Chassis about 58×86×42 source units, excluding complete tracks. STL mm interpretation and assembly interfaces remain to qualify. |
| Head | Rounded housing, one monochrome expressive face, camera, microphone and speaker | Leading candidate: [Sparky v0.1.0](../cad/originals/sparky-head/README.md), CC BY-SA 4. Its saved shell measures about 56×52×54mm, not the larger v0.2 dimensions. Author explicitly says unprinted/estimated. |
| Manipulation | One front gripper that raises/lowers an object; two positional servos total | Saved Bluino gripper + original SMARS forklift. Actual rack/linkage orientation, MG90S fit, flat-key reach and attachment to stepper chassis remain open. Orange preview is a symbol for this mechanism. |
| Camera pose | Fixed relative to jaws; see the approach area and pickup/placement, including the raised payload | Small camera wedge/spacer or aperture correction allowed. Choose tilt from actual camera field of view, not the lens symbol in this preview. Check occlusion by jaws, payload and head shell. |
| Edge sensing | Four downward optical views plus a separate forward obstacle view | Positions in preview are placeholders. Measure footprints beyond relevant tipping boundaries and all permitted pivot/reverse sweeps. A front beam does not cover every collision direction. |
| Power | Owned regulated 5 V USB bank, low and securely retained if it qualifies | Bank size, mass, current, cable drop and auto-off unknown. No miniature battery is silently substituted. No whole-robot dimensions or runtime promised yet. |

The head is fixed: there is **no neck pan/tilt servo** in this parts allocation.
Looking around means animated eyes and, when permitted, cautious whole-body turns.
This is a hand-sized remix direction, not a committed overall size. Do not shrink
an entire case or mechanism to make the drawing fit real components.

When asked for a power-bank recommendation, use a **compact 5,000mAh class** as a
mechanical reference, roughly 80×40×25mm and about 100g, with a clearly specified
5 V / 3 A output as a candidate for load testing. The
[Anker Nano A1653 official specifications](https://www.anker.com/products/a1653-usb-c-portable-charger-5000mah)
list about 77×37×25mm,100g and 5 V / 3 A. The checked $26.99 price would increase the
$40.33 reuse-based target to $67.32 before charges, exceeding the unchanged $50 cap.
**Do not add it as a required purchase.** Reuse/test the owned bank first, leave
its carrier replaceable and measure the actual unit before final CAD. A 3 A label
does not qualify transient load, auto-off, stability or runtime; this reference
is not the user's identified bank and is not fitted in the preview.

## Case choice and allowed changes

Sparky is the current **fit-check candidate**, not a qualified replacement shell.
Its v0.1.0 source uses a 1.3-inch OLED opening. Reuse the owned 0.96-inch SSD1306
with a measured bezel. Check a Sense mount, camera opening, microphone path,
speaker retention and removable rover bracket. The original lower front hole is
for an LED; the preview's lens there does not prove a camera module fits behind
it. A new nearby opening may be required.

Keep the shell's main shape and the existing drivetrain/lift. Small plates,
inserts, clips, spacers, sensor mounts, jaw tips and clearance corrections are
allowed. Do not adopt Sparky's separate raw-LiPo power architecture or assume its
full magnet set is required. Resolve shell retention within the existing
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
| A visible person or object appears | Mac can select an observation, change gaze/mood and make a short comment. Observing does not itself authorize motor movement. No face-identity recognition is required. |
| Pet mode enabled | Choose short curiosity, attention, rest or social activities without needing a new user question each time. Use a state machine, timers and observations; occasional LLM choices supply meaning, not motor timing. |
| Exploration permitted | Stop/look, take a bounded short movement, stop and observe again. Blocked path means stop/wait/report. Reverse or turn only within a qualified clear swept area. No blind backing away from a cliff. |
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

Priority is local stop/fault → explicit stop → manual or pickup task → pet/social
activity → idle animation. Only one motion source owns the body at a time.
Proposed pet motion requires a human-granted 120-second lease, capped at 300seconds;
the model cannot grant/renew it. Existing one-use manual/pickup permits remain.
Expiry, fault or disconnect cancels queued activity, rather than pausing it for
later automatic restart. Fault recovery is body-local and leaves motion disarmed.

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
| Supply | Separate power branches/common ground documented | Bank identification/load/auto-off, connectors, actuator transients and whole-system operation. Capacitors cannot establish sufficient power. |
| Mechanics | Original files, dimensions, licenses and hashes saved; source-based visual now exists | Registered assembly, interference/sweep checks, measured parts, balance, slicer review and physical fit samples. |

Use [the current wiring map](../hardware/wiring.md),
[head selection/audio guide](modular-head.md) and
[firmware evidence](firmware-foundation.md). The split architecture needs no
additional Uno/Pico. Existing build success does not validate substituted boards,
unmatched binaries, sensor wiring or the new case.

## Acceptance before duplication

| ID | Pass condition |
| --- | --- |
| A1 Face/offline | Five-minute stationary test: face animation remains responsive while the Mac is delayed/disconnected; no unintended motion. |
| A2 Voice/quiet | Multi-turn conversation shows listening/thinking/speaking states and passes the required [ordinary-speech interruption gate](audio-barge-in.md), including audible-stop latency, capture of the new request and no false echo-only interruption. No button fallback. Ten-minute quiet-mode test has no unsolicited speech or movement. |
| A3 Control ownership | Stop, manual/pickup preemption, lease expiry and link loss cancel active/queued pet motion. Neither a model command nor reconnect can reauthorize it. Concurrent requests from two robot IDs grant at most one fleet motion owner; others wait. Stop/expiry releases ownership without automatic resumption of queued motion. |
| A4 Local edge stop | Test every sensor disconnect, invalid/stale reading, bus fault and relevant edge approach with a tether/catch setup. Log actual detection latency and coast distance; require measured margin before the support footprint crosses an edge. No universal stop distance is assumed. |
| A5 Manipulation | At least 8/10 actual flat-key trials and 8/10 wrapped-candy trials: lift visibly10mm, hold3seconds, then place under control. Record object dimensions/mass, slips and human assistance. Assisted trials fail. Blocks are supplementary, not a substitute for keys. |
| A6 Power/mechanics | Loaded drive/turns and lift/grip with Wi-Fi/audio do not reset the robot, loosen mounts or exceed component ratings. Record peak current/voltage and temperatures. Verify camera/sensor views throughout mechanism travel. |
| A7 Five peers | Five distinct stationary robots complete ten coordinated utterances with one speaker at a time, no unintended motion and clean stop/disconnect cleanup. Repeat calibration/power/stopping checks on each unit before its permitted movement. |
| A8 Initiative | In a five-minute stationary, non-quiet pet-mode trial, at least one attention, curiosity, rest or social activity starts without a new user prompt. Verify the 120-second group cooldown between spontaneous spoken initiations. No movement is needed for this test. |

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
   connector/retainer. Current $40.33 target includes assumed $18.87 Sense purchase
   and $21.46 further parts/allowances before charges; earlier
   Amazon-only option is over cap. Fleet reuse quantities remain incomplete.
4. Finished body sensor driver/calibration, face/initiative/memory/lease code,
   affected tests and firmware builds. Existing foundation is not that final code.
5. Illustrated wiring, power checks, exact-board flash steps, mechanical assembly,
   calibration, operation/recovery and fault diagnosis in one ordered guide.
6. Trial sheets for A1–A8. Paper completeness and physical acceptance are separate;
   no document can substitute for measuring the actual bank, servos and prints.

Next work follows [the implementation plan](plans/2026-11-03-active-desk-pet.md):
qualify the rounded shell/interfaces and finish the real sensor driver before
enabling movement, then implement/verify the pet activities and assemble one unit.
