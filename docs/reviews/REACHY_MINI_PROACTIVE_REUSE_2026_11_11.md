# Reachy Mini and published proactive social robotics: source reuse for Desk Robot Remix

Research checkpoint: 2026-11-11. **This file is shared engineering knowledge, not a new software stack or evidence of hardware completion.** Keep [AGENTS.md](../../AGENTS.md), [parallel chat handoff](PARALLEL_CHAT_HANDOFF.md), and active draft [PR #17](https://github.com/hungngodev/desk-robot-remix/pull/17) authoritative. The user requires five complete tracked desk pets with individual identity, memory, natural voice interruption, multimodal vision, sensors, a grasping arm and genuine safe docking. Do not replace WROOM, XIAO Sense, Mac brain or final CAD with Reachy hardware; do not install an unrelated agent or a second media server merely to imitate a demo.

## The real secret: its *orchestration*, not a magic LLM or one proactive algorithm

[Reachy Mini source](https://github.com/pollen-robotics/reachy_mini) (Apache 2.0 software) offers a documented app ecosystem, Python SDK, daemon, simulation and managed lifecycle. [Official conversation app](https://github.com/pollen-robotics/reachy_mini_conversation_app) (Apache 2.0) is the most relevant source. The app does **not** rely on the model continuously improvising low-level PWM. Its `src/reachy_mini_conversation_app/moves.py` says explicitly:

* One dedicated ~60 Hz control loop and **one actual output writer** for all expressive joints.
* Queue mutually exclusive *primary* behavior (emotion/dance/pose/breathing); blend only compatible *secondary* gaze and speech offsets. Use a monotonic clock and smooth interpolation.
* Idle **breathing** after a delay, overridden by listening and other activity, makes the robot seem present without constant unsolicited dialogue.
* Local Silero VAD gives a low-latency listening signal; server VAD adjudicates the real spoken turn. A suspected interruption first lowers upcoming audio to **25%**, while a confirmed interruption cancels prior generation. The experimental source says actual already-buffered audio latency and echo still need measurement.
* Camera, emotion clips, memory and head tracking are **narrow tools** with explicit profile permissions, not trusted arbitrary motor-control text.
* Per-profile identity, instructions, voice, greeting and tool permissions matter. An `idle_do_nothing` action is as important as the capability to act.
* Reusable expression data is exposed as [Reachy Mini emotions](https://huggingface.co/datasets/pollen-robotics/reachy-mini-emotions-library) and [dances](https://huggingface.co/datasets/pollen-robotics/reachy-mini-dances-library), but the trajectories target Reachy's 6-DOF head, antennas and body rotation and **cannot be loaded as our SMARS stepper, one OLED and two gripper servo trajectories**. Reuse semantic labels, timing and scheduling; only create a display-specific renderer after real XIAO face interface review.

Official build instructions explicitly distinguish real-time `set_target` (single 50–100 Hz owner) from smooth one-shot `goto_target`. See [motion philosophy](https://github.com/pollen-robotics/reachy_mini/blob/main/skills/motion-philosophy.md), [control loops](https://github.com/pollen-robotics/reachy_mini/blob/main/skills/control-loops.md), [AI integration](https://github.com/pollen-robotics/reachy_mini/blob/main/skills/ai-integration.md), [app lifecycle](https://github.com/pollen-robotics/reachy_mini/blob/main/docs/source/SDK/apps.md). We have an even more important priority: **the WROOM controls stop and motor safety independently of every Mac model**.

**Important nuance:** The official Reachy Mini `camera` tool is normally **on-demand** when the assistant calls it. It is **not evidence that the default official conversation app watches forever and autonomously starts a dialogue upon every new scene**. A community [Judgy Reachy No Phone](https://github.com/yaseminozkut/judgy_reachy_no_phone) uses YOLO phone detection, a bounded intervention cooldown and persona-specific speech/expressions as a real example of a proactive visual *event trigger*. That application is context-specific and not a reason to shame users or covertly monitor their desk.

## The important published research and how we should reuse it

1. **LlamaPIE**, Chen et al., ACL Findings 2025, [paper](https://aclanthology.org/2025.findings-acl.710/): a cheap model answers *when should we offer help*, and a larger model creates the concise *what to say*. **Current integration:** existing `PetController._consider_speech` is a cheap first-pass gate before costly Ollama speech. We strengthened it with source-specific confidence cutoffs and a second check after the slower reply. **Do not claim we imported their trained classifier or that our hand-picked confidence thresholds are statistically calibrated.**
2. **ProAct**, Zhang et al., 2026, [paper](https://arxiv.org/abs/2602.14048) and [project](https://proactrobot.github.io/): fast low-latency behavior and a slower deliberative cognitive system, with high-level intentions inserted asynchronously. **Current integration:** WROOM local safety and tactile IMU loops; Mac asynchronous visual comparison, memory and conversational response; existing XIAO face/speaker. **Gap:** no measured continuously composited nonverbal expression linked to TTS progress. Their full streaming neural motion generator is not a drop-in model for our two MG90S (lift and jaw) and cannot be granted motor authority.
3. **ARISE**, Cheng et al., October 2026, [paper](https://arxiv.org/abs/2610.05964): emphasizes the complete loop from social intent through memory to streaming gesture-and-speech expression. **What to adopt:** integrate the eventual real OLED face states with audio events and preserve one output owner, without making up face motion mechanics.
4. **Sensible Agent**, ACM UIST 2025, [paper](https://doi.org/10.1145/3746059.3747748): proactive agent chooses both **what** help and **how disruptive** the delivery is, including unobtrusive visual rather than spoken output. **What to adopt:** a short nonverbal OLED reaction or staying silent is often better than an unsolicited 15-second monologue. No continuous mobile phone monitoring without consent.
5. **ProactiveBench**, Wang et al., 2025, [paper and code](https://github.com/yellow-binary-tree/ProactiveBench), [abstract](https://huggingface.co/papers/2507.09313): evaluates *timing*, not merely correct words. **What to adopt:** log candidate evidence, voice-active suppression, time-to-first-reaction, interruption false starts and missed genuine events by robot.
6. **RoboOmni**, Wang et al., October 2025, [paper](https://arxiv.org/abs/2510.23763): perceiver, thinker, talker, executor, fuses audio and visual cues to infer context from weak rather than explicit instructions. **What to adopt:** source-tagged WROOM touch/IMU/ToF, XIAO JPEG and live Xiaozhi VAD. Its trained action executor **must not** replace WROOM local motion permits.
7. **Proactive Conversational AI: a comprehensive survey**, Deng et al., ACM TOIS 2025, [paper](https://doi.org/10.1145/3715097): evidence for the divide between context understanding, conversation initiative and actual user benefit. Reuse design principles, **not** an untested end-to-end pretrained policy.
8. **EMOTION**, Apple ML Research, January 2025, [paper](https://machinelearning.apple.com/research/emotion-expressive-motion): models semantic expressive gestures from context. Use a semantic expression dictionary and timing, not the original joint trajectories.

## One architecture, not competing agents

```text
[XIAO Sense Mic] real VAD -> server live voice floor (already implemented)
[XIAO Sense Camera] authentic JPEG -> Mac frame gate / selective VLM
[WROOM] touch, CAP, MPU6050, 8 VL53L4CD, dock, force/raw buses
                   -> Mac attributed facts in isolated robot SQLite stores
                   -> cheap initiative decision (source confidence / novelty)
                   -> still needed? fleet voice quiet, cooldown and permissions
                   -> slower Ollama / Xiaozhi or approved realtime model
                   -> SECOND speech permission check after reasoning
                   -> existing single Xiaozhi speaker lease (native and legacy)
[WROOM] cliff / touch / dock / motor owner: never driven by this diagram
```

**Already implemented expression reuse:** the local Sense `FaceTask` uses the pinned Stackchan HSM with real touch and speaking events and owns idle OLED moods; the FaceTask explicitly discards Stackchan motor actions. It is not physically qualified, and the robot cannot reproduce Reachy's head/antenna motion with the two already committed MG90S grip/lift servos.

**In source as of this pass:** `code/laptop/src/desk_robot/pet.py` now has `_initiative_evidence` and `_human_active_in_fleet`. It suppresses low-confidence visual guesses, unknown event kinds, stale/replayed duplicate descriptions, all robots' real VAD during a speech candidate, and human turns beginning during the LLM response. Only an actually transmitted remark advances spontaneous speech cooldown. Generated text that is empty or exceeds 280 original characters is **suppressed, not silently truncated** into a misleading spoken fragment. It preserves low-confidence observational memory as uncertain (does not erase it), and existing qualified CAP1188/side range/touch/IMU event categories remain eligible. The active interruption audio floor in `desk_robot_bridge.py` and `desk_robot_native_omni.py` remains the priority owner. New `test_pet.py` cases cover the gate and cross-robot VAD races. **Source committed, not yet compiled or hardware tested**.

## Concrete next source loops, without pretending finished

1. **Safety and output ownership:** keep WROOM hardware stop independent; actual five-robot group TTS must be interrupted by any authenticated human source, not microphone echo. Measure 19/20 immediate stops under 500ms and >=18/20 intent retention on physical heads.
2. **Expression without new hardware:** the selected `code/firmware/head/sense/desk_robot_sense.cc` already runs a **pinned Stackchan-agent `HsmBehavior`** in one 100ms `FaceTask`. It maps real WROOM touch and CAP edges to `kTouched`, real Xiaozhi speaking state to `kSpeakRequest`/`kSpeechFinished`, and idle Stackchan moods to the existing SSD1306 via `display_->SetEmotion`; body faults override to a sad face. **Do not rebuild a parallel face renderer or assume Reachy's 6DOF movements exist.** Verify physical LVGL/I2C timing and extend that same HSM only for genuinely missing listening/thinking/curious states. No jaw, lift or track animation is permitted.
3. **Why not speak?** record exact suppression reason, confidence, human/quiet state and event source without saving raw JPEG/audio. Personalize opportunity thresholds only after real human judgments, not fabricated training data.
4. **Multimodal context:** preserve truthful temporally matched image and microphone evidence across one human turn. Never promote a text-only peer report into a camera witness or inferred identity.
5. **Physical sign-off:** full CAD imported and aligned, correct PCB and power rails, safe charger+fuse/contact isolation, non-guessy last centimeter docking, force-calibrated grab and placement, real speaker flush. All are still required for buy/print/assemble.

## Acceptance and reproducibility

Run host tests for `test_pet.py`, `test_multimodal.py`, `test_server_bridge.py`, and `test_native_omni_xiaozhi.py`; then run full lint/C++ sanitizer/PlatformIO/Sense overlay compile at the exact current PR commit. Current GitHub Actions runs report failed jobs with unavailable steps/logs: **they do not establish a passing test or a diagnosed failure**. Complete actual temporal trials with WROOM and XIAO on a desk for visual false triggers, chosen thresholds, and 5-pet turn ownership. Nothing about reading a paper proves hardware proactivity or reliable natural conversation.
