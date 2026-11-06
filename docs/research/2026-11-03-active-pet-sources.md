# Active desk-pet sources and remix decisions — 2026-11-03

## Follow-up source inspection — 2026-11-04

This is research evidence, not implemented functionality. Current product choices
and acceptance live in [the product brief](../product-definition.md); later head,
power, sensor and motion-session decisions supersede older recommendations below.

- Reachy Mini conversation app inspected at
  `e90192559149d6281d782c1c4aed39bb7d84bdef`, Apache-2.0. Its
  [idle policy](https://github.com/pollen-robotics/reachy_mini_conversation_app/blob/e90192559149d6281d782c1c4aed39bb7d84bdef/src/reachy_mini_conversation_app/idle_policy.py)
  selects local stillness/dance/emotion/head moves; the
  [conversation handler](https://github.com/pollen-robotics/reachy_mini_conversation_app/blob/e90192559149d6281d782c1c4aed39bb7d84bdef/src/reachy_mini_conversation_app/conversation_handler.py)
  dispatches idle actions without sending a model turn. Its camera tool returns
  a fresh JPEG separately. The movement manager sequences primary moves, blends
  speech motion and suppresses idle movement while listening. Reuse scheduling
  and interruption concepts through our own hardware adapter, not Reachy poses
  or an assumption that its camera tool already supplies our proactive vision.
- [Open Duck's inspected walking path](https://github.com/apirrone/Open_Duck_Mini_Runtime/blob/376de65435c93486347cd601a31aa96951799896/scripts/v2_rl_walk_mujoco.py)
  takes gamepad motion commands into a walking policy. Independent blinking and
  controller-triggered sounds/antenna moves do not establish autonomous social
  or camera-driven activity selection.
- The newer Pollen Microduck's
  [behavior notes](https://github.com/pollen-robotics/microduck/blob/54e0789635ae28120be9ea0dd51750a494ab50ac/docs/ideas/autonomous_behavior.md)
  describe a prior mood/energy/novelty state machine, while explicitly identifying
  the autonomous-brain migration gap in the current daemon. Its old named runtime
  was not retrieved; do not claim independent inspection of that implementation.
- [Cozmo SDK source](https://github.com/anki/cozmo-python-sdk/blob/master/src/cozmo/robot.py)
  activates Freeplay in an existing robot engine. The SDK is not that engine.
  [Vector's subsystem documentation](https://support.anki.bot/article/567-vector-subsystems)
  separates high-level behaviors/mood, animation and cloud voice. These support
  a perception/event/activity/animation split, not a claim we can copy a complete
  commercial personality engine into ESP32 firmware.

Implementation consequence: build fresh camera events, bounded observation
memory, activity selection and speech arbitration around the existing Mac core;
keep eye animation and WROOM reflexes independent. Test camera-triggered reactions
without speech, repeated/stale-event rejection and five-feed speech ownership.
Do not mark source review as completion of those tests or runtime features.

The intended result is five identical, inexpensive tracked robots that initiate
small activities, notice interactions, and pick up keys or wrapped candy. The
sources below inform that behavior and appearance; none establishes that our
combined hardware already works. The [twelve-video audit](2026-11-03-video-audit.md)
separates creator descriptions from inspected code and unverified demonstrations.
No full-video or timestamp-level viewing is claimed here.

## What to reuse

| Reference | Verified published material | Decision for this build |
| --- | --- | --- |
| [chillibasket WALL-E replica](https://github.com/chillibasket/walle-replica) | GPL-3.0 repository. README documents an animation queue, random movement generator, controlled servo velocity, nonblocking serial parsing, and calibration for seven servos. | Reuse the ideas of interruptible choreography and pauses between gestures. The larger seven-servo, Arduino/Pi, 12 V arrangement is not our two-servo arm or a reason to buy a Pi. Any copied implementation must retain its license and attribution. |
| [FluxGarage RoboEyes](https://github.com/FluxGarage/RoboEyes) | GPL-3.0 Arduino graphics library using Adafruit GFX; supports configurable eyes, moods, gaze, blinking, idle motion and one-shot animations. SSD1306 examples are available. | Preferred face-library candidate for the owned 128×64 SSD1306, subject to a small ESP-IDF/Xiaozhi graphics and timing adapter. It is **not MIT** and is not already integrated into our firmware. |
| [Tech Talkies custom-face Xiaozhi](https://github.com/TechTalkies/Xiaozhi-for-XiaoESP32S3) | GPL-3.0 repository for the bare XIAO S3, with an OLED face and separate I²S audio wiring. | Inspect the face-state approach and required changes against our pinned Xiaozhi version. Its board-specific binary and pin map do not qualify the Sense camera/PDM-microphone configuration. |
| [Tech Talkies wheeled buddy](https://github.com/TechTalkies/YouTube/tree/main/95_Chatbot_on_wheels) | The inspected sketch has timed ROAM/PET/ATTN states and touch interruption; see the video audit for the exact source blob. No cliff interlock was found in that behavior path. | Useful concept for attention, cooldowns and petting responses. Do not copy its roaming routine as safe navigation. A repository-wide copying license was not established. |
| [Qubit](https://github.com/0xaiwhisperer/qubit) | Public choreography/dashboard material; README advertises MIT, but its linked LICENSE was absent from the checked top level and metadata reported no recognized license. | Use the architectural idea of calibrated keyframes for `grip`, `lift`, `offer` and `place`. Resolve copying terms before incorporating its source or assets. Its dual-arm hardware exceeds this budget and scope. |

The repository license results above were checked against GitHub repository
metadata on this date. Before incorporation, inspect the actual license and
headers at the selected revision, including separately licensed dependencies and
CAD. GPL components must not be silently presented as MIT-only project code.
No third-party source was copied into runtime code during this research update.

## What the ducks demonstrate

[Open Duck Mini v2](https://github.com/apirrone/Open_Duck_Mini/tree/v2) is an
Apache-2.0 project hub for a biped about 42 cm tall with extended legs. Its README
targets a BOM below $400, links reinforcement-learning policies and a separate
Pi Zero 2 W runtime, and notes incomplete documentation and expression features.
Its mechanics and learned walking stack are not a cheap drop-in replacement for
our WROOM-controlled tracks. Inspect licenses independently in each linked repo.

NVIDIA's [23 October Microduck article](https://developer.nvidia.com/blog/using-ai-agents-to-teach-robots-like-microduck-to-walk-in-simulation/)
distinguishes perception, navigation and locomotion. It describes building a
simulated obstacle course, training/evaluating policies, and preparing deployment.
It shows physical walking, but explicitly leaves detailed hardware deployment
outside its scope. That is useful evidence about the layers involved, not an
off-the-shelf companion personality or an ESP32 firmware recipe.

Disney's [BDX page](https://la.disneyresearch.com/bdx-droids/) explicitly describes
its expressive walking characters as puppeteered. A convincing glance or lively
demonstration does not by itself establish that a robot chooses its own activity.
We can borrow the general rhythm—look, pause, move, react—without reproducing
Disney assets or importing a biped training project.

Three capabilities must remain distinct: **locomotion** moves the hardware;
**navigation** chooses a route using observations; **agency** chooses when and
why to start an activity. A slow wheeled robot can exhibit agency without leg
balancing, reinforcement learning or full SLAM.

## Commercial appearance and interaction references

[Dasai Mochi 3](https://dasai.com.au/pages/mochi3) is a commercial driving companion
with animated expressions, sounds, motion reactivity and interchangeable helmets.
It is a reference for a compact face, playful timing and removable costumes;
its page does not establish a navigating conversational rover or open firmware.
An extra IMU is unnecessary for our first useful behavior set.

[Living.AI EMO](https://living.ai/emo/) advertises independent exploration,
attention, touch responses and personality expressed through motion and eyes.
These are vendor feature claims, not independent validation or published code.
Use the interaction goal—respond promptly, sometimes initiate, sometimes rest—
while creating original face artwork and behavior. Do not promise EMO-equivalent
navigation, recognition or reliability from this inexpensive remix.

## Recommended combination and behavior boundary

Keep the existing stepper-compatible SMARS base, Bluino lift/gripper and saved
EVA head. Aim for a compact WALL-E-like tracked silhouette, an original monochrome
face with Mochi-style playfulness, EMO-inspired initiative, and duck-like gaze
timing. Limit CAD to brackets, an OLED bezel, camera clearance, replaceable jaw
tips and removable hats. Brass rods can be an optional decorative cage; a new
freeform structural chassis, display PCB cutting and new arm are outside scope.

Start with stationary blinking, gaze, short sounds, listening and rest. Add a
deterministic activity scheduler that tracks curiosity, social cooldowns and
recent events. These are simulated character states, not measurements of real
battery charge. The shared Mac can choose occasional higher-level activities,
maintain separate histories, and ask an LLM for an intention when useful; eye
animation and motor reflexes must not wait for an LLM call.

Only after local edge/obstacle qualification should a human enable bounded
roaming. WROOM safety and stop handling override every activity. No blind reverse
or pivot follows a cliff reading. Initially allow one moving robot at a time,
while peers animate and converse with serialized speech and cooldowns. That
provides an active group without pretending simultaneous collision avoidance
already exists. All new scheduling, face adaptation and physical navigation
remain implementation and bench-test work.
