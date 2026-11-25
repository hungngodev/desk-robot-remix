# Native Xiaozhi + adaptive live video: full desk pet orchestration

## November 12 integrated speech, sensor and camera evidence path

This is a **source implementation checkpoint**, not proof of acoustic latency
or five connected physical robots. The Mac retains one `CameraFrameHub` for
the five registered robot IDs. It now also accepts completed native MiniCPM
audio transcription events as **up to four text-only, per-pet RAM cues**, each
expired from the context after 30 seconds. The existing Xiaozhi server
passes only completed ASR, not unbounded PCM, video or partial hypotheses.
`/v1/pet/{robot_id}/omni-context` separately advertises
`live_transcript_context_enabled` and
`transcript_memory_enabled`. The `omni-heard` endpoint can add an
uncertain transcript to ephemeral conversation context while SQLite writes
remain disabled. This is not an identity-verified utterance, an operator
memory preference or an instruction to move. An explicit hub clear removes
it; camera-only failure does not erase a fresh spoken conversation.

`interaction_timeline()` returns chronological, source-labelled evidence
from authenticated human voice edges, completed uncertain ASR, physical
sensor edges, current XIAO JPEG receipts, completed local visual tool
interpretations and actually transmitted but **playback-unverified** robot
speech. It contains neither raw JPEG nor PCM. The bounded
`compose_brain_context` recognizes uncertain ASR separately from actual
voice activity, and preserves sensor versus model interpretation and
eyewitness versus peer-reported text. It may **summarize or omit** older
transcript chunks under its 400-character live prompt budget. This is
not a lossless transcript archive or a complete native-model state sync.

A sensor burst now records `CameraEvidence.trigger_kind` only when the
existing authenticated sensor event scheduled the two-frame XIAO capture.
The link names the **scheduling cause**, never an inferred object or a
verified camera exposure time. A combined touch/visual prompt can now say
which sensor requested the frame without claiming the touch was visible.
Coalesced later sensor edges remain separate event-history entries, not
additional invented camera triggers. Human VAD still cancels the optional
capture, fresh questions preempt it, and the WROOM still solely decides
movement and dock safety.

**Completed read-only tool receipts now close another gap.** The pinned
Xiaozhi tool adapter marks only its own authenticated Mac calls with a
receipt header. The existing Mac API records concise WROOM status and
latest pickup-job results into the one per-pet `tool_history`, only if
the associated Mac human-turn epoch has not changed during the request.
Normal operator UI status polling does not generate these memories.
`visual_look` expires after 8 seconds; read-only status and job receipts
after 30 seconds. Their labels say "head telemetry" or "Mac job receipt",
never "physical success". They are bounded text only and cannot create an
operator permit. Every new authenticated human VAD clears earlier tool
interpretations, including from another robot; subsequent fresh calls
may refill the correct pet's context.

When **fleet text sharing is explicitly enabled**, the existing
`Conversation.run` group owner can consume each invited pet's **own**
`interaction_timeline()` through the same bounded
`compose_brain_context()` as proactive speech. Its completed ASR,
sensor events, tool receipts and JPEG scheduling causes can inform a
natural response. Without that separate consent, the user can still
request group conversation around the supplied topic, but private live
cues are omitted from those prompts. A peer never inherits these cues
as eyewitness history. One Xiaozhi speaker lease, separate SQLite
memories and the established operator motion permits remain unchanged.
No second microphone, camera, tool executor or agent graph exists.

**Historical group memory consent** is independent of memory retention:
on real hardware, the existing group chat no longer injects private core
facts or retrieved episode text when fleet text sharing is disabled.
One-to-one robot memory stays on its existing separately authorized
path. Source tests cover the consent-off and consent-on group cases.
The native model `status()` now separately reports live ASR delivery
count, whether transient context is enabled, and
`native_tool_calls_supported=false` for this current MiniCPM adapter.
A supported native audio/video session is not a general agent tool
runtime. If tool-capable duplex is desired, investigate a published
backend with negotiated function-call capability and verify it with the
pinned Xiaozhi bridge rather than forging unsupported MiniCPM events.
The [vLLM Omni duplex contract](https://github.com/vllm-project/vllm-omni/blob/main/docs/serving/realtime_duplex_api.md)
distinguishes models with function calls from MiniCPM-o 4.5, which
does not currently advertise them.

**Live priority and recovery:** A direct `desk_robot_look` request
now cancels only the optional in-flight pet scene comparison before
waiting for the shared VLM lock; it never cancels the permanent observer
or emits a motor request. Authenticated Xiaozhi voice stream loss also
invalidates the transient native ASR receipts, which must not silently
survive a head reconnect as if their provenance were continuous.
Repeated ordinary Mac status tool polls replace the prior receipt of
that kind rather than evicting an independent pickup or visual result.
All these source paths have focused tests but no successful full-CI
head pass yet.

**Two source paths remain intentionally distinct:** Legacy Xiaozhi exposes
the real `desk_robot_look`, `desk_robot_situation` and
`desk_robot_memories` tools, using the authenticated Mac runtime. The
optional vLLM Omni MiniCPM realtime duplex backend currently speaks with
PCM and selected JPEGs but **does not have a verified native function-call
contract**. A better Mac context formatter does not magically give it
native tool use or synchronize complete model-internal conversation state.
Do not synthesize unsupported tool packets or run competing TTS owners.

Useful upstream patterns, not copied drop-in code:
[Qwen Live Harness](https://github.com/QwenLM/Qwen-Live-Harness)
separates continuous foreground video, on-demand visual analysis, proactive
monitors, and memory updates with explicit delivery status;
[Pipecat frame documentation](https://github.com/pipecat-ai/docs/blob/main/api-reference/server/frames/overview.mdx)
separates interruptible audio/image/data frames from higher-priority
control/system frames; [LangGraph memory](https://langchain-ai.github.io/langgraph/concepts/memory/)
separates thread-scoped interaction state from long-lived knowledge.
Their architecture motivates our single Mac evidence owner, but the
selected models, sensor transport, device latency and permissions differ.

**Focused verification still required on the exact PR head:**
`python -m pytest code/tests/test_multimodal_api.py
code/tests/test_brain_context.py code/tests/test_native_omni_xiaozhi.py
code/tests/test_multimodal.py code/tests/test_runtime_voice_priority.py -q`.
The code additions and test definitions are committed, but the latest
GitHub Actions run still terminates before any recorded test step.
Run real ESP-IDF/PlatformIO builds and measure synchronized microphone,
JPEG receipt, model and audible output timing before claiming production
multimodal quality.

## November 12 brain consistency fixes and genuinely reusable upstream architecture

**Implemented in the existing runtime, not a new agent framework.** Changes:
`Conversation.run` keeps the completed part of a failed/interrupted
streamed Ollama sentence in only that speaking robot's private memory,
*after* attempting the real head abort. It labels this
`sent, playback unverified` and does **not** copy it to peers as
heard speech. The previous implementation lost every successful segment
when the next stream chunk failed. Tests use successful first transmission,
later model failure, cancellation and peer memory isolation.

`CameraFrameHub.interaction_timeline` now retains the newest voice,
read-only tool, physical sensor, transmitted robot speech and camera cue
under its bound, instead of letting ten background receipts evict the
human's actual interaction. Every limit from 1 to 16 is respected; at very
small limits authenticated human voice and completed tool evidence win.
`compose_brain_context` now collapses repetitive camera receipts and
preserves the distinct source labels within a 400-character transient
prompt budget, with separate 600-character episodic and 500-character
operator-curated core budgets. Losing a camera or Xiaozhi monitoring
stream invalidates stale JPEGs/VLM guesses while retaining the pet's
brief, truly transmitted speech timeline. A full stop/clear still erases
that transient context.

The native Omni opt-in persona endpoint now consumes **the same** pure
`compose_brain_context` labels as proactive Mac speech. The five
robots' private SQLite facts remain separate, operator core facts and
durable history still require separate memory consent, and no speech
prompt may arm motors. This fixes diverging memory interpretations
between native audio and Mac verbal proactivity.

**Research reused as architecture, not copied wholesale:** [Reachy Mini
conversation app](https://github.com/pollen-robotics/reachy_mini_conversation_app)
has one motion/expression scheduler, camera tool and curated tool profile;
[LiveKit Agents](https://docs.livekit.io/agents/logic/turns/) separates
VAD from turn completion, including false interruption handling;
[Pipecat](https://github.com/pipecat-ai/pipecat) separates interruptible
frames from critical control frames; [LangGraph persistence]
(https://github.com/langchain-ai/docs/blob/main/src/oss/langgraph/persistence.mdx)
splits thread checkpoints from long-term stores;
[Letta memory](https://github.com/letta-ai/ai-memory-sdk) distinguishes
small in-context identity from archival history; [LeRobot]
(https://github.com/huggingface/lerobot) separates observations and policy
actions; [Nav2 behavior trees]
(https://github.com/ros-navigation/docs.nav2.org) isolate action
execution and bounded recovery. No architecture above grants the LLM
physical safety authority; WROOM remains the sole body and cliff control.

**Reachy Mini research followup, November 12:** The [current conversation
app](https://github.com/pollen-robotics/reachy_mini_conversation_app)
runs local Silero VAD for immediate physical listening and temporary speaker
ducking, while server VAD still confirms conversational turns and final
interruption. Its audio playback uses paced 20ms chunks and drops obsolete
buffered speech. This is a **two latency budget** pattern, not two competing
conversation owners. Our Mac already fences obsolete answers, but XIAO native
acoustic VAD, device audio duck/flush and actual stop latency remain unmeasured.
Before porting, inspect the pinned Xiaozhi ESP-SR/AEC path and device CPU/I2S
capacity; do not assume desktop Silero can run unmodified on XIAO.

Research behind **when to speak**: [ProAct](https://arxiv.org/abs/2602.14048)
separates a fast interactive behavioral system from slow proactive planning;
[LlamaPIE](https://arxiv.org/abs/2505.04066) uses a small initiative decision
before larger response generation. Existing `PetController._initiative_evidence`
is a conservative nonlearned candidate gate, **not** a reproduction of either
paper or validated human-like engagement. Our next enhancement should measure
false initiations, missed social cues, human interruption to silence, gesture
latency and memory relevance before adding another generative planner.

**Remaining fundamental gaps, not hidden by this patch:** an untested
physical audio playback ACK and AEC double-talk path, missing native
tool calls in the selected MiniCPM-o realtime model, validated visual
exposure timing and cross-modal latency, real bounded head camera and
mic concurrency, motion and docking physical feedback, fitted complete
Fusion assembly, protected charging electronics and five-pet trials.
In particular, MiniCPM audio+video does NOT become a tool-capable live
agent merely because we improved its prompt: preserve the original
Xiaozhi tool-capable server path and adopt a new native backend only
after real model capability negotiation. Source test additions exist,
but the full Python 3.11/ESP-IDF/PlatformIO pipelines are NOT verified
by this update because GitHub Actions still fails before running steps.



## November 12 integrated Mac brain building blocks

This is **one existing robot architecture**, not a new LangGraph/Pipecat
runtime, tool broker or second audio/camera service. Each device retains its
Xiaozhi microphone, AEC, speaker and expression owner; the Mac retains one
`MultimodalOrchestrator` for bounded XIAO JPEG selection and one
`Conversation` speech lease. WROOM alone owns physically safe actuation.

| Stage | Real code owner and evidence |
| --- | --- |
| **Immediate** authenticated speech and barge | `server/overlay/desk_robot_bridge.py` increments `voice_turn_generation` and signals `tool_turn_cancel_event` for that head. `desk_robot_tools.call` races only read-only Mac HTTP against that cancellation signal. Old camera/episodic memory requests are cancelled; actual STOP and permitted jobs keep their independent safety acknowledgments. |
| **Continuous source sampling** | The XIAO camera owns real JPEG capture; Mac `CameraFrameHub` retains at most three processed JPEGs per pet, source receipt timestamps and triggered sensor edges. Idle ~0.3 FPS, human speech ~1 FPS, a bounded two-frame physical sensor confirmation. This is **not** guaranteed hardware frame cadence. |
| **Ephemeral multimodal context** | The SAME `CameraFrameHub` exposes `interaction_timeline()`, sorted by Mac monotonic receipt and limited to 10 entries by default: human VAD, physical sensor edge, JPEG receipt metadata, *completed* local VLM interpretation, and this pet's recent transmitted text. No JPEG/PCM bytes, guessed exposure timestamps or motor permissions. A NEW human turn clears old VLM guesses fleet-wide but preserves the preceding pet remark for a follow-up. Actual speaker playback remains **unverified**. |
| **Relevant episodic recall** | Each `MemoryStore` holds at most 250 text events in that pet's SQLite, marked firsthand or secondhand with confidence. `search()` is a **local lexical** ranked fallback, not a vector model or semantic understanding claim. Xiaozhi `desk_robot_memories` passes a bounded question through the same turn-fenced, opt-in API. No matching text means no claimed recollection. |
| **Stable personality memory** | Separate `core_facts` table holds at most 24 concise operator-curated preferences per robot, with operator-only set/get/delete and explicit per-pet episodic forget. No voice tool or LLM can edit core policy, create hardware permits or read a neighbor's private store. Native Omni gets it only with voice-memory consent. |
| **One prompt composer** | Pure `desk_robot/brain_context.py` composes memories, preferences and ephemeral time-ordered evidence into three small independently capped sections with source labels. `PetController` reuses it rather than building an alternate agent or a hidden parallel LLM. |
| **Playful speech and yield** | Human speech and confirmed tool results take precedence; after a real VAD speech end, unsolicited pet remarks wait **800 milliseconds** in the `spontaneous_floor_busy()` gate, adapted from Qwen Live Harness. Recent *own* utterances suppress repetitive unsolicited lines using a simple similarity check; direct human requests remain unsuppressed. Explicit camera tools still run. This does **not** claim acoustic speaker playback completed. |
| **Response and tool boundary** | Existing local Xiaozhi registered tools can inspect authorized memory/current camera and request guarded jobs. Optional MiniCPM-o native duplex handles bounded audio/video but published capability table does **not** support function calling. Do not claim the two backend paths equivalent or silently synthesize tool events. |

### Independent consent and turn continuity

There are now **two separate, read-only Xiaozhi tools**. The
`desk_robot_situation` tool requires *live vision consent*, returns only this
pet's short-lived timeline and explicitly excludes SQLite; it can answer a
follow-up about what the robot just said or what a sensor reported without
granting persistent memory access. The `desk_robot_memories` tool requires
*durable memory consent*, uses the same authenticated VAD-fenced Mac HTTP
request, and retrieves relevant historical observations and operator-curated
preferences. Both are cancelled on a newer human speech edge; physical STOP
is deliberately excluded from this speculative cancellation. The two
permissions must never be silently coupled.

Native model ASR is uncertain, source-timed evidence, not a command. The
existing Mac route binds accepted ASR in `AttentionLedger` to the *live consent
generation*. The same `CameraFrameHub` carries the original trusted Mac
`source_at` timestamp in its short-lived transcript entry. Both the native
`/interaction-context` tool and proactive `PetController` compare that exact
clock with the current grant start, rather than a rounded display `age_ms`.
Revocation immediately hides the transcript, and an off/on regrant cannot
revive it; a newly accepted transcript can still inform the conversation.
WROOM safety, touch and permitted topic continuity survive independently.
This is transcript prompt isolation, not a playback, identity or acoustic
qualification. Source and regression commits: `a531994b6ffc` and
`bf2da05c6af7`; exact latter-sha Mac suite 1,321 tests passed, with the
Python/head host suite separately blocked by unrelated Ruff lint.

Durable **model-estimated transcript retention** is a separate, stricter
permission: `accepted_at_us` and `audio_committed_at_us` must both be present,
and the original audio commit must postdate both the voice-memory and the
transcript-retention consent grant. Model completion after a grant cannot
retroactively authorize previously captured or chronologically unknown audio.
An older authenticated client may receive HTTP 200 for a nonstored estimate;
`retention_consent_enabled` alone does not mean `stored` or
`episode_persisted`. The route continues to retract in-flight inserts on
consent cancellation and keeps each pet's private SQLite isolated. Regression:
`test_native_durable_asr_requires_real_audio_commit_timestamp` and the
corresponding existing positive storage and revoke fixtures; source commit
`59b6e1265e3b`.

`CameraFrameHub.spoken_history` keeps at most three actual transmitted Mac
pet lines per robot for at most 30 seconds. That is **not** confirmation that
a physical speaker played, that the human heard them, or that a separate
robot spoke them. A new VAD keeps this one limited context type while
discarding obsolete local VLM guesses. The pure context formatter selects
bounded source-aware evidence and rejects a near-duplicate spontaneous
remark if it resembles this pet's own utterance within the preceding hour.
These are experience-quality building blocks, not an autonomous motor policy.

### Example of a grounded playful follow-up

Someone asks Pip where a previously seen key went. The current Xiaozhi
voice turn takes priority, requests relevant memories only from Pip's SQLite,
and may request `desk_robot_look` for a *new* image. Historical memory is
labeled as what Pip saw before, the JPEG's receipt is not mistaken for its
exposure timestamp, and the VLM's answer is labeled as a model
interpretation. A physical pickup requires the separate operator-enabled job,
measured grip evidence and independently authoritative WROOM interlocks.
If the person interrupts while looking, the VAD signal cancels the old
read-only HTTP work and old model answer; a new question starts a new
generation. If a separate robot comments, its own SQLite and speaking identity
remain distinct. No speech may imply that an unmeasured grasp or dock succeeded.

### Why these sources, rather than adding another framework?

* [Qwen Live Harness original injector](https://github.com/QwenLM/Qwen-Live-Harness/blob/main/packages/qwen-live-harness/src/orchestrator/injector.ts) closes result injection while human VAD, model response or host speaker playback is active. We reused its explicit turn cancellation and short post-VAD quiet principle. **Our XIAO still lacks measured physical playback completion**, so an equivalent host receipt cannot yet be claimed.
* [Reachy Mini conversation app](https://github.com/pollen-robotics/reachy_mini_conversation_app) demonstrates one media/speech owner and coordinated expression instead of competing device agents.
* [LangGraph persistence](https://langchain-ai.github.io/langgraph/concepts/persistence/) separates short-lived turn state from durable memory. Our existing per-pet SQLite remains the real durable source.
* [Letta Agent File](https://github.com/letta-ai/agent-file) distinguishes compact editable core personality/user facts from episodic history. Only an explicitly authorized operator may curate such facts here.
* [Pipecat](https://github.com/pipecat-ai/pipecat) propagates interruption as a pipeline signal, avoiding delayed speech after old tool work. The actual implementation remains the pinned Xiaozhi tool bridge plus Mac context owners.
* [vLLM Omni official realtime duplex specification](https://github.com/vllm-project/vllm-omni/blob/main/docs/serving/realtime_duplex_api.md) documents model-specific one-second JPEG/audio append boundaries and capability restrictions.

**Verification:** Exact GitHub `brain_context.py` object
`15fa703a98979b8269a486feb9244970caab0dbd`
was executed in a local isolated Python test with source labels, dedup,
no raw image data and three bounded text budgets: PASS. Exact `memory.py`
object `09907bdb8ae6927a623e0e5472fdd83837c9de37`
was exercised with five private SQLite stores, relevant recall, 250 events,
24 core slots, input validation and local deletion: PASS. Those are scoped
checks, **not** a full FastAPI/Xiaozhi integration run or Python 3.11
lockfile acceptance. Targeted new tests are in `test_brain_*.py`,
`test_multimodal.py`, `test_server_bridge.py` and
`test_xiaozhi_tool_resilience.py`; broad CI still fails before steps.
Physical natural conversation, accurate playback, camera/AEC timing, gripper,
charger and full fitted printable assembly remain unqualified.



## November 12 Qwen Live Harness source comparison, no cloud default

Verified actual official upstream
[QwenLM/Qwen-Live-Harness](https://github.com/QwenLM/Qwen-Live-Harness),
whose v1.0.0 was released September 21, 2026. It is an Apache 2.0
**orchestration** source using the paid Qwen Omni Realtime API, not an
on-device Qwen model to silently deploy onto our XIAO or Mac.
[Proactive media cadence](https://github.com/QwenLM/Qwen-Live-Harness/blob/main/packages/qwen-live-harness/src/proactive/media-cadence.ts)
fixes two video frames in two seconds at one FPS per model monitor chunk;
our separately source-verified sensor trigger burst remains capped at two
frames and a 450 ms interval, while native live PCM attaches up to one
chosen JPEG per one-second audio unit. Do not confuse these cadence policies
or claim 30 FPS raw streaming.

The source
[`orchestrator/injector.ts`](https://github.com/QwenLM/Qwen-Live-Harness/blob/main/packages/qwen-live-harness/src/orchestrator/injector.ts)
is especially instructive: it distinguishes *silent context delivery* from
*spoken notification*, defers injection during user VAD, in-flight model
responses, or incomplete Host playback, then observes an 800 ms quiet
window. It preserves stable task receipts and does not narrate pending
work as success.
Our Mac pet and Xiaozhi tool paths now have authenticated VAD, current socket
and turn generations, background cancellation, a single speaker lock and
successful Mac job receipts. We **do not** yet have physical XIAO playback
progress ACK, so we cannot assert an equivalent Host playback barrier or
automatically speak every result just because bytes were transmitted.
Future improvement must reuse measured firmware playback state and actual
upstream model capabilities, not fabricate playback timestamps.

The official
[`orchestrator/live-session.ts`](https://github.com/QwenLM/Qwen-Live-Harness/blob/main/packages/qwen-live-harness/src/orchestrator/live-session.ts)
also shows generation-fenced turn state, permission brokerage,
proactive monitor and background result routing. Our existing
Mac `Conversation`, `PetController`, `VoiceEventListener` and Xiaozhi
bridge remain the owners. Moving that entire Electron/Node daemon onto
the ESP32 would create a second, unsupported capture and audio pipeline.
The existing local MiniCPM-o vLLM-Omni duplex supports native paired
audio/video but **not** native function calls; the Qwen API's cloud tool
calls are a separate opt-in provider choice, not a feature claim for our
current local model.

## November 12: actual fused microphone, selected camera and context ownership

**One head, not parallel cameras:** XIAO Sense now selects native VGA `PIXFORMAT_JPEG`
using the pinned Xiaozhi `Esp32Camera`; `fb_count=1` and PSRAM allocation are
deliberately conservative for simultaneous AEC and Opus. The existing
`modular_snapshot.inc` validates real JPEG start/end markers and copies the
sensor JPEG under the upstream shared camera lock. Its HTTP bridge runs each
camera request on a separate bounded FreeRTOS task rather than blocking audio
or urgent motor/STOP transport. No ESP32 camera stack was replaced.

**One Mac image owner:** `HttpHead.snapshot()` authenticates camera boot,
sequence and completion, rejecting old capture identities. The
`MultimodalOrchestrator` keeps only three processed JPEGs per robot in RAM,
performs grayscale motion scoring using its existing Pillow worker limits,
and admits one physical camera capture at a time **per head**. Live idle
sampling is about 0.3 FPS; authenticated human speech requests about 1 FPS;
touch/NFC/gesture requests may trigger bounded two-frame confirmations.
`native_frame()` reuses a current VAD JPEG under the same camera lock so
the Mac proactive sampler and native duplex worker do not double-request the
XIAO. A source reception timestamp is not a sensor exposure timestamp.

**One synchronized native duplex owner:** For heads explicitly enabled in
`DESK_ROBOT_OMNI_ROBOTS`, Xiaozhi keeps the existing microphone/Opus/WebSocket
session and forwards actual decoded 16 kHz PCM to the selected locally
configured model-native realtime service. The existing native worker starts
camera selection immediately when authentic VAD becomes positive, obtains a
fresh Mac JPEG over authenticated loopback, and checks identity, age,
JPEG bounds, monotonic receipt and change fraction. It chooses an initial
keyframe, motion of at least 1.5 percent, or a static refresh after 2.5 seconds
and attaches **at most one JPEG per distinct receipt**, only on the model's
one-second audio append boundary. No 30 FPS network stream or fake video
source is claimed. Model audio returns as 24 kHz PCM and is converted to the
**same physical Xiaozhi 16 kHz Opus speaker**, with a single fleet output
lease. Generated/transmitted Opus does not prove audio actually played.

**Exactly one human turn:** The authenticated server's `speech_start`,
`speech_end`, `normal` AEC interruption and `group` AEC interruption
preempt obsolete output before visual work. The native worker advances both
audio and video generations on barge, discards in-flight old JPEGs, and never
replays a selected receipt in a later audio window. The old XIAO socket and
older human speech generation cannot apply a late Mac `desk_robot_look`
tool result. If the authenticated voice event stream fails, the Mac cancels
old visual questions and background images without assuming a silent human;
camera sampling resumes only after an authenticated VAD snapshot and
monitor readiness recover. Failures do not grant any WROOM motion permit.

**Honest tool/model split:** The legacy Xiaozhi ASR/LLM/registered-tool route
has `desk_robot_look`, read-only context, status and guarded pickup job
requests. The published MiniCPM-o model-native duplex route can accept
paired PCM and JPEGs, but **its current upstream duplex model does not
provide native function calling**. The bridge therefore does NOT invent
`response.tool_call` packets, silently duplicate model providers, or claim
the native video model can operate the full tool suite. A future compatible
multimodal tool-capable backend needs an actual published protocol and
recorded end-to-end tool tests. Do not combine both competing audio routes.

**Continuity with separate consent:** Set `pet_autostart_enabled=true`
only with hardware, camera opt-in, a local VLM and real Xiaozhi identities
to begin sensor/idle observation at Mac start. For optional human speech
memory, **both** `voice_memory_tools_enabled` and
`voice_transcript_memory_enabled` must be true. Completed native ASR
transcripts, if the actual backend emits them, use a bounded asynchronous
text-only worker and idempotent per-robot SQLite events labeled
*uncertain machine hearing*. Raw microphone PCM/video is not saved.
Operator quiet and all existing physical permits remain independent.

**Current proof boundary:** Code and new host tests exist, but CI jobs on
the branch still fail before any step is recorded. Actual AEC interruption,
native model integration, speaker acoustics, FPS, PSRAM under load,
five-camera fairness, camera revision and charging remain **unqualified**.
See `docs/records/verification.md` for real evidence rather than assuming
successful source review equals physical acceptance.


Status: November 10 2026. **Code committed, real XIAO mic/camera and physical audiovisual latency NOT QUALIFIED.** This keeps all five full-feature pets, independent episodic memories, WROOM local cliff safety, calibrated grasp plans, RGB/OLED expressions and docking. It does not replace them with a webcam demo or a second robot framework.

## Source comparison and engineering choice

| Actual open-source implementation | Exact reusable mechanism | What was implemented |
| --- | --- | --- |
| [LiveKit Agents video sampler](https://github.com/livekit/agents/blob/main/livekit-agents/livekit/agents/voice/agent_session.py) | VoiceActivityVideoSampler raises capture from 0.3 FPS idle to 1 FPS when human is speaking; frame forwarded into human turn | `CameraFrameHub` 0.30/1.0 FPS cadence plus high-priority voice/physical sensor triggers and bounded 3-frame RAM cache |
| [LiveKit video + realtime model docs](https://docs.livekit.io/agents/multimodality/vision/video/) | Latest frame attached to the actual user turn; Gemini Live or OpenAI Realtime can accept native video, not every model can | `desk_robot_look` asks an installed **image-capable** local Ollama VLM a real camera question in the active Xiaozhi conversation. It is tool-mediated, **not** a native realtime video model |
| [Pipecat frame processor](https://github.com/pipecat-ai/pipecat/blob/main/src/pipecat/processors/frame_processor.py) | Interruptions flush obsolete queued work and user input has priority over background assistant output | Authenticated Xiaozhi VAD stops old TTS, cancels five-pet Mac speech and in-flight background visual inference before a user visual question. No competing Pipecat audio stack |
| [Frigate motion detector](https://github.com/blakeblackshear/frigate/blob/dev/docs/docs/configuration/motion_detection.md) | Cheap motion candidate filter before more expensive object/VLM operations; regional relevance matters | Existing `VisualChangeGate` remains the VLM gate. New brightness-corrected grayscale motion scoring ranks the bounded previous frames and suppresses pure broad lighting shifts from being classified as motion |
| [Frigate snapshot selection](https://github.com/blakeblackshear/frigate/blob/dev/docs/docs/configuration/snapshots.md) | Keep a best representative frame rather than every video frame | One most recent frame for static questions; at most one high-motion prior plus latest for questions about change, movement or what just happened |
| [Xiaozhi firmware and camera MCP](https://github.com/78/xiaozhi-esp32) | Bidirectional Opus, ESP-SR AEC, native ESP32 camera tool, MCP function registry | Keep existing XIAO Sense firmware, authenticated JPEG endpoint, `/events` VAD path, xinnan server overlay and `plugins_func.register`. Add one `desk_robot_look` tool routed to Mac |
| [Ollama Qwen3-VL](https://ollama.com/library/qwen3-vl/tags) | Local image input with 4B and 8B instruction variants | Reuse existing Mac Ollama `/api/chat` image API for current image question answering and two-photo comparison; no new cloud service or another camera |

## Actual data paths

### An actual human asks to see something

1. XIAO Sense PDM microphone feeds the existing Xiaozhi AEC/VAD/Opus server.
2. Pinned Xiaozhi `receiveAudioHandle` now emits a debounced authenticated `speech_start` event from two actual VAD-positive frames while the robot is idle, **not only when the robot is already talking**. If the robot is speaking, the existing AEC double-talk handler emits `normal` or `group` and urgently flushes stale TTS. Both use authenticated `/events`; the idle event never invents AEC or aborts silent speakers. Audio priority is independent of JPEG.
3. The Mac `Runtime._on_voice_interrupt` cancels obsolete peer/pet speech and background Ollama scene inference, **then** synchronously signals the camera hub to schedule nonblocking near-1 FPS JPEG samples while real human speech remains active, capped at 60 frame opportunities per utterance to limit camera load.
4. Xiaozhi's current ASR/LLM conversation calls `desk_robot_look(question)` for a visual question. The tool uses the authenticated robot identity from the **current** Xiaozhi websocket and the existing loopback Mac API. It cannot claim another robot's camera.
5. `MultimodalOrchestrator.look` requires opt-in and a named local vision model, chooses an image received within 600ms or captures a fresh XIAO JPEG, and picks one or two chronological views from the bounded six-second window.
6. `OllamaScene.answer` asks the local VLM to answer the actual spoken question over those photos. Confidence and JSON types are validated. If uncertain, it returns a short inability to see rather than fabricating detail. It can answer questions about objects and visible changes; it does **not** know that the camera recorded video continuously.
7. The model receives the text response with `recent_sensor_events`: actual WROOM touch/gesture/force/other event kinds or authenticated Xiaozhi human VAD with timestamps, not inferred visual facts. Xiaozhi's existing speech pipeline speaks the response to the same robot.
8. The audio session's normal Xiaozhi interruption still applies while the VLM/tool is working. No gesture grants a motor permit.

### No human speaks: proactive camera observation

* The pet's operator-enabled observation loop uses the existing 2-confirmation `VisualChangeGate` and expensive 2-photo VLM scene comparison. Only actual semantic change may become memory or a short spontaneous comment.
* When the hub is attached to hardware, camera sample cadence defaults to about 0.3 FPS idle and speeds up after actual movement/sensor events. A valid CAP1188 pad, touch press, nearby object, APDS9960 wave, magnetic dial or WROOM safety event can request an immediate new frame.
* Only one `_vision_lock` exists across all five robots. Human speech cancels old background inference and gets priority over a queued unsolicited comment. Per-robot voice turn and visual query epochs reject a late image model answer after another human utterance or visual question supersedes it. The Mac's existing cooldown and single speaker lease prevent five overlapping unsolicited audio sessions.
* The hub keeps at most three compressed JPEGs **per robot**, in RAM only. Operator pause and runtime shutdown clear the stored visual context. Source identity, receive time and event provenance are separate. A frame from one robot never gets labeled as another robot's eyewitness memory.
* Sensor and vision comparisons cannot arm motors. WROOM's 500ms watchdog and local physical safety remain independent.

## Enable on the actual Mac

The robot must have a working XIAO ESP32S3 Sense camera and firmware, a configured local Xiaozhi voice connection and a Mac Ollama instance. Run:

```sh
ollama pull qwen3-vl:4b-instruct
ollama list
```

Set the following in a **private** local copy of `code/config/robots.example.toml`:

```toml
mode = "hardware"
vision_model = "qwen3-vl:4b-instruct"
voice_vision_tools_enabled = true
# Keep head_url, each robot's device_id, token_env and fleet selection actual.
# Do not hardcode tokens in committed files.
```

Restart the existing Mac runtime and pinned Xiaozhi server after updating their config. The xinnan server overlay registers `desk_robot_look` via its existing function registry and calls `POST /v1/pet/{id}/look`; the model prompt explicitly instructs tool use only for real human questions. The same `DESK_ROBOT_TOOL_TOKEN` already used by the existing pickup/status tools authenticates this read-only path.

For a local **operator** camera test, with the actual robot connected:

```sh
curl -fsS http://127.0.0.1:8765/v1/pet/robot-01/vision-status \
  -H "Authorization: Bearer $DESK_ROBOT_API_TOKEN"
curl -fsS -X POST http://127.0.0.1:8765/v1/pet/robot-01/look \
  -H "Authorization: Bearer $DESK_ROBOT_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"question":"What am I holding in front of you?"}'
```

If `voice_vision_tools_enabled = false` or no model is installed, spoken camera questions return an explicit error, not a fabricated scene. Neither opt-in nor model selection turns on autonomous locomotion. Opt into proactive camera remarks separately using the existing operator `/v1/pet/{id}/start` endpoint.

## Real physical acceptance still required

* Measured actual source-frame exposure timestamps versus Mac receive time. XIAO currently reports capture completion metadata, which guards against replay but is **not** a synchronized microphone/photo exposure clock.
* At least 20 human trials with speech while the robot is talking: target 19/20 visible or spoken interruptions with speaker silence within 500ms, plus a log of false positives and echo performance.
* “What am I holding?” queries against 10 familiar and novel objects, in varied light/angle; record correct model answer and real first-audio response latency. The `confidence` returned by a VLM is not physical validation.
* “What just moved?” tests with the previous and newest chronological frames, global lighting changes, camera shake, network duplicate/stale JPEGs and loss/reconnect.
* Actual touch/gesture timing and 5 simultaneous pets: one user's voice should preempt all unsolicited audio without causing another robot's memories or images to leak.
* On-device memory/CPU usage, source metadata, WiFi/jitter, XIAO frame rate and Ollama 4B/8B throughput on the Mac. A 45 second vision provider timeout is not a latency promise.
* Full end-to-end realtime **speech-to-speech** Gemini Live/ChatGPT Live quality is still separate from a VAD + STT/LLM/TTS + vision tool pipeline. Moving to Pipecat/LiveKit native video+realtime model would require an actual Opus/PCM transport adapter and provider integration, not a one-line model name. Such an adapter has **not** been shipped or verified.

## Code map

* `code/laptop/src/desk_robot/multimodal.py`: frame cache, adaptive priorities, transient audio/sensor events, voice camera captures, visual question routing.
* `code/laptop/src/desk_robot/vision.py`: existing scene comparator and new local two-frame question answer.
* `code/laptop/src/desk_robot/pet.py`: proactive camera/event scheduling and cancellable background visual inference.
* `code/laptop/src/desk_robot/runtime.py`: wire Xiaozhi VAD to camera after audio cancellation.
* `code/laptop/src/desk_robot/api.py`: authenticated voice-vision status and visual question endpoints.
* `code/laptop/server/overlay/desk_robot_tools.py`: native Xiaozhi `desk_robot_look` tool.
* `code/tests/test_multimodal.py`: offline source, sampling, identity, consent, temporal selection, VLM and no-motion assertions.

All changes above are source implementation and mock tests. No actual XIAO board, Mac GPU inference trace or microphone/speaker was accessible during the coding pass; CI may still fail and must be checked separately.


## November 11 continuation: actual event-loop latency, speech end, and diagnostics

New source changes preserve the same Xiaozhi and Mac owners:

1. **Real VAD end**: the pinned server's existing `receiveAudioHandle` VAD callback now emits an authenticated `speech_end` only after **two consecutive VAD negative frames** following an actual `speech_start`. A brief silence inside a phrase is not treated as the end. The Mac listener validates the source and ordered event; the runtime stops voice-priority camera sampling without cancelling the current human reply or deleting its recent JPEG evidence. `normal` and `group` double talk remain separate events for urgent physical speaker flush.
2. **No Pillow blocking the audio loop**: live authenticated camera captures remain serialized per head, and JPEG downscale/encode now uses a dedicated two-worker native `ThreadPoolExecutor` with a `threading.BoundedSemaphore`. Capacity is released only by the actual native future completion, not by cancellation of an `asyncio` awaiter; at most one low-priority background decode is admitted so human camera questions retain capacity. The Python event-loop owner alone publishes to the camera frame hub. A generation token discards a frame if operator pause, reconnect or shutdown occurred while it was being processed. These are source implementation and regressions, not measured live five-camera throughput.
3. **No obsolete 45-second live scene**: direct image questions bound local VLM inference by the remaining six-second freshness window of the oldest selected JPEG (and the provider timeout), recheck every selected image before publishing an answer, and fence a previous question after a new Xiaozhi spoken turn or newer visual query. Failures return explicit no-answer errors rather than a confident old scene description.
4. **Operator timings**: `GET /v1/pet/{robot_id}/vision-status` now includes per-robot read-only `software_timings` with actual camera requests, successful captures, errors, visual questions, model completions, failed answers, last JPEG/capture-processing time and last local VLM inference time in milliseconds. These are measured Mac software timings only; they are NOT synchronized physical camera exposure, network-to-ear, acoustic AEC or audible playback metrics.
5. **Offline regression additions** cover nonblocking Pillow worker, late frame rejection after pause, speaker continuity at VAD end, authenticated speech-start/speech-end order, stale model timeout and per-robot counters.
6. **Long human turns and failed camera safety**: a real authenticated `speech_start` now holds the human voice floor until authenticated `speech_end` or explicit session disconnect/clear. The old seven-second guess could expire during a longer user question. An unavailable XIAO JPEG source discards only stale video evidence and cannot clear an active VAD event. Voice sampling is bounded to 60 one-second opportunities while active; an absent speech end can silence proactive remarks until explicit reset and will not trigger indefinite camera polling. Mock regressions cover the long-turn and camera-fault boundaries. Real acoustic interruption remains unverified.

**Unqualified requirements remain:** actual head PWM and dock hardware, calibrated grasp, complete integrated STL/Fusion model, protected battery charging currents and thermal tests, measured end-to-end voice acoustics, measured real camera/sensor throughput and realtime speech-to-speech backend. The PR remains draft until live hardware trials and CI pass.


### Authenticated idle VAD versus AEC double talk

The same Xiaozhi server produces two distinct event families. An authenticated idle `speech_start` has a matching debounced `speech_end` and now holds human priority without a guessed seven-second cutoff. By contrast, a `normal` or `group` AEC double-talk event is an urgent speaker abort but **does not guarantee a corresponding idle `speech_end`**. Mac `Runtime` now routes these AEC events to `MultimodalOrchestrator.voice_interrupted`, preserving immediate cross-fleet audio cancellation and applying a bounded seven-second camera/voice priority window instead of an endless lock. An independently active explicit VAD turn remains held even if AEC events arrive on top of it. These are scheduling policies, not validated acoustic timings. New regression tests cover both event types and their overlap.


## November 12: source-truthful natural social behavior and active camera triggers

This is one cohesive source path in [PR #17](https://github.com/hungngodev/desk-robot-remix/pull/17), not a new chatbot or second robot framework. [Source reuse versus reference audit](../ATTRIBUTION.md#what-is-actually-reused-versus-locally-implemented-november-12-audit) explicitly distinguishes external upstream from our integration.

### What an actual new event does

1. **Read source:** WROOM local sensor GPIO/I2C and its existing read-only status or optional auxiliary endpoint, or the authenticated XIAO JPEG. A newly sampled MAX30102 paw, CRC checked SHT41 ambient change or new PN532 toy tag must come from its own fresh device acquisition counter. All three now have a matching entry in `multimodal.TRIGGERS`; previously a missing trigger raised an exception before private memory could be stored.
2. **Context immediately, but bounded:** `PetController._notify_sensor` calls the existing `MultimodalOrchestrator.sensor_event`. The hub records source identity, event kind and monotonic Mac receipt time and marks its next JPEG urgent. A new task starts a genuine `HttpHead.snapshot()` **without blocking the sensor polling path**. Bursts coalesce to **one bounded two-frame confirmation task** per 800 ms for each robot. The second photo is taken 450 ms after the first when no live human or direct visual question has priority. This reuses the existing per-head capture lock, shared two-worker JPEG budget, tiny per-robot RAM frames and source checks. Two frames is an upper bound on requests for a burst, **not** measured reaction time. Another pet's event cannot borrow its camera.
3. **Human takes priority:** a genuine Xiaozhi speech start cancels the pending low-priority sensor camera task and uses the existing 1 FPS speech-frame sampler. A direct visual question also preempts the sensor camera task. An immediate end/start voice transition replaces a cancelling speech sampler instead of losing the next utterance. No sensor, head or LLM gets a second microphone or motor authority.
4. **Decide when:** the existing Reachy/LlamaPIE-inspired cheap initiative gate rejects unsupported event kinds, uncertainty, absent authenticated live VAD feed, quiet mode, active conversation, ongoing human speech, repeated event text and fleet speech cooldown. A slow model answer that outlives `max_observation_age` is now discarded rather than turned into a suspiciously late remark.
5. **Decide what:** the local model prompt now distinguishes *physical sensor evidence* from *camera model assessment*, including explicit no-unseen-identity/no-motor instructions and only recent source-qualified per-pet memory. Physical petting and NFC are not described as camera sightings. This is grounding policy, not a guaranteed hallucination-free model.
6. **Optional peer invitation:** after an eligible witnessed key, candy, object, hand-wave, petting or toy tag event, an operator may enable **both** `fleet_text_sharing_enabled=true` and `fleet_social_autonomy_enabled=true` in the Mac hardware config. `fleet_social_min_interval_seconds=300` limits automatic invitations; only another enabled, unmuted pet participates. The selected peer rotates and receives the source event as **reported secondhand**. The existing `Conversation.run` handles **two turns** under the same exclusive speaker/session owner; the peer is instructed not to claim firsthand observation or perform any physical motor action. It uses the same per-robot personas, private SQLite provenance and cancelled Xiaozhi TTS route. Without explicit sharing, no social event is transmitted.
7. **Stop and clean up:** muting or pausing **either** of the two speaking pets cancels the same shared social task. Simultaneous five-pet human interruptions must not repeatedly cancel its urgent device stop cleanup. The same live authenticated VAD snapshot still owns human turn recovery; sensor camera errors cannot clear it.

### Actual visual reasoning and natural interaction correction

Previously `sensor_event` acquired a genuine XIAO JPEG, but the `PetController` semantic observation loop never consumed it. The frame remained useful for explicit voice questions but an actual tap or accessory could fail to provoke visual reasoning. The **same** proactive scene loop now consumes the hub's unseen ordered `sensor` and `proactive` JPEGs, with a per-pet last-received cursor and freshness/generation checks, instead of fetching duplicates. It uses the already present `VisualChangeGate` to demand two local changes before one Ollama VLM comparison. A sensor cue is context, **not proof** that anything visual happened; silent frames never fabricate a scene. Frames captured for a **human speech** or `voice_question` are intentionally excluded from unsolicited semantic analysis. Another robot's frames never enter this pet's history.

The existing Frigate-inspired cheap motion gate already compensated for broad lighting drift, but the separate `VisualChangeGate` still compared raw pixel differences. It now reuses the identical `change_fraction` algorithm, reducing full-room light changes that would otherwise provoke five expensive Ollama calls. Frigate's documentation calls motion a first-stage detector rather than a substitute for actual object understanding: https://docs.frigate.video/configuration/motion_detection/ . This adaptation is algorithmic and original integration source, not imported Frigate NVR or a verified object tracker.

Human interruption remains absolute priority. Separately, an **intentional physical engagement** such as head taps, petting, optical paw contact, hand wave, nose twist or toy tag can respond after a configurable 12-second shared speaker cooldown instead of waiting the ordinary two-minute unsolicited visual-comment cooldown. Repeated text, active VAD, quiet mode, model expiry, consent and one speaker floor still apply. No idle clock alone invents speech or claims to have seen a thing. See also LiveKit's turn-taking separation between interruptions and ordinary endpointing at https://docs.livekit.io/agents/logic/turns/tuning/ . We deliberately retain our existing authenticated Xiaozhi transport rather than adding a competing LiveKit session; the LiveKit video sampling and turn policy are design references.

**New source tests committed, not yet executed:** `test_proactive_frame_gate_reuses_motion_filter_to_ignore_global_exposure`, `test_sensor_capture_burst_is_consumed_by_one_proactive_scene_owner` (both actual changed object and uniform lighting cases), `test_sensor_two_frame_burst_never_blocks_human_speech_priority`, `test_sensor_two_frame_burst_is_bounded_and_camera_serial`, `test_deliberate_touch_can_reply_after_passive_speech_cooldown`, and `test_touch_can_never_override_authenticated_human_vad`. These tests use deterministic mocks, **not real camera, latency, VAD acoustics, or a deployed ESP32**.

### Five head camera priority and measured software diagnostics

**A concrete cross-pet bug was removed.** Previously `sensor_event` and background camera capture checked only whether the **same** head had active VAD, even though any live human turn should own the fleet's compute and voice priority. `MultimodalOrchestrator._any_human_active` now checks all registered heads. An authenticated Xiaozhi VAD start cancels outstanding sensor camera tasks and active low-priority snapshot requests across all five pets. Its own high-priority speech JPEG sampler and direct visual questions still work; it does **not** stop other heads' local WROOM safety guards or touch polling.

The background camera is a **child HTTP snapshot task** managed by the existing orchestrator. Cancelling it for human speech, a more urgent sensor burst or a direct question releases the existing per-camera capture lock and leaves the permanent `PetController._observe` loop alive. A cancelled snapshot is never promoted to current camera evidence. A later valid turn may resume ordinary observation. All burst requests use the same authenticated head transport; no new global media server is deployed.

For every source ID, `MultimodalOrchestrator.status(robot_id).software_timings` now includes:

| Field | Meaning |
| --- | --- |
| `sensor_triggers` | Real Mac source event notifications, including suppressed observations |
| `sensor_bursts` | Distinct bounded confirmation tasks admitted after coalescing |
| `sensor_coalesced` | Additional events within a pending burst or 800 ms coalescing window |
| `sensor_deferred_human` | Events that did not start camera work while any fleet human spoke |
| `sensor_trigger_to_first_jpeg_last_ms` | Last recorded **Mac event time to Mac JPEG receipt**; no device exposure or network clock synchronization claimed |
| `sensor_followup_frames` | Successfully captured second frames for visual confirmation |
| `proactive_camera_preemptions` | Background HTTP snapshots cancelled before the human question or higher-priority event |
| `camera_latency_last_ms`, `model_latency_last_ms` | Existing Mac software durations, not acoustic latency guarantees |

Regression source now covers simultaneous peer camera cancellation, explicit user look priority, survival of permanent observation after a cancelled JPEG, one genuine two-frame burst, normal exposure drift, and real source-to-visual-memory connection. GitHub runner failure means these **must still be executed** with actual Python and then the five physical heads. Reference mechanisms were inspected in [LiveKit's VoiceActivityVideoSampler](https://github.com/livekit/agents/blob/main/livekit-agents/livekit/agents/voice/agent_session.py), [Frigate's motion-first gating](https://docs.frigate.video/configuration/motion_detection/) and [Xiaozhi's actual bidirectional Opus/JSON transport](https://github.com/78/xiaozhi-esp32/blob/main/docs/websocket.md). They are **design adaptations**, not imported Frigate, LiveKit, or a substitute Xiaozhi server.

### Integration and build knobs

Copy `code/config/fleet.hardware.example.toml` to a local untracked configuration with actual device addresses and private token environment variables. In production, leave `motion_enabled=false`, `dock_motion_qualified=false`, all new sensor `*_qualified=false` and `fleet_social_autonomy_enabled=false` until the real voice, sensing and source privacy tests pass. Enabling social while local source text sharing is disabled is a configuration error. Turning on social is not motor autonomy, changing head firmware or authorizing charging.

Software acceptance (unexecuted while CI runners fail before any job step):

| Source test | Critical property |
| --- | --- |
| `code/tests/test_multimodal.py` | Three new source event kinds can enter the shared trigger hub, independent camera identity, coalesced physical JPEG capture, human VAD preempts slow sensor camera, and immediate VAD end/start has a new video worker |
| `code/tests/test_pet.py` | Local sensor versus camera wording, expired LLM output suppression, consented two-pet auto conversation, secondhand peer memory, cooldown, muted peer cancellation and concurrent human interruption |
| `code/tests/test_live_voice_events.py`, `test_native_omni_xiaozhi.py` | Real server source identity and voice snapshots, model audio generation cancellation and one speaker floor |
| `code/firmware/body/tests/optional_i2c_io_tests.cpp` | Actual mocked I2C PN532, optical, climate and dock input ordering; no optional source holds critical optical guard permission |

**Measured physical acceptance is still mandatory:** gather actual time-stamped camera capture latency, live VAD edge-to-audible-silence latency, false visual motion and false speech interruption rates, sustained five camera memory usage, one speaker exclusivity across 30+ minutes, real sensor exposure versus Mac receipt timestamps, and grounded peer provenance. Run both ESP firmware builds, Linux host C++ sanitizer and full Python suite before enabling. All changes above are committed source and pending regression tests, **not executed CI or a completed autonomous social robot**.


## Fleet wide human voice supersedes old peer visual questions

A real source review on November 12 found that the earlier global priority implementation stopped unsolicited JPEG on all five pets, but left already running explicit `look` tools on other heads alive. Since Ollama can spend many seconds inferring, such a stale answer can be handed back after another robot's user has started speaking. `MultimodalOrchestrator._voice_activity` now cancels and increments a provenance epoch for every peer `look` on authenticated VAD or AEC; an actual visual request cannot start while another head's human turn is active. The speaking head retains its own voice vision tool so camera questions can still be answered naturally. No camera frame, VLM answer or peer message grants motor or charger authority. `test_multimodal.py` now contains deterministic peer cancellation and cross head priority tests. No physical five head microphone/loudspeaker pass is claimed.

## November 12: voice failure, peer memory scheduling and vendor plugin resilience

A targeted upstream and current branch review found the following integration facts and repairs. These changes refine the **existing** Xiaozhi and Mac owners; no second audio stack, new tool daemon, motion owner or independent PR was created.

| Boundary | Real source behavior | Evidence and remaining limit |
| --- | --- | --- |
| Five robot social context | `Conversation.run` now gathers per-robot SQLite persona history through concurrent `asyncio.to_thread` calls with a five-second deadline. Read errors or cancellation release the exclusive conversation marker. The Mac event loop can therefore process human VAD while slow disk reads are pending | Host tests inject a blocking memory lookup and a failed local database; these tests are committed but CI has not executed them. `MemoryStore._connect` creates and closes its SQLite connection within the worker thread |
| Interrupted/failed group audio | On **any** midstream model, transport or cancellation exception after a robot starts speaking, `Conversation.run` now calls the existing head `speaker.interrupt` path before completing failure cleanup. Proactive TTS similarly requests head abort after any partial transmission failure, not only task cancellation | Host regression cases cover one successful segment followed by an Ollama exception, and a bridge that fails after queuing physical audio. The interrupt command is not a measured I2S DMA completion ACK |
| Xiaozhi tools when Mac is offline | The existing pinned `plugins_func.register` and `Action.REQLLM` registration remain the only voice tool owner. `desk_robot_tools.call` returns bounded, nonsecret, no-retry errors on local Mac HTTP outage, timeout, malformed JSON or unexpected response type; it still resolves robot identity from the registered physical Xiaozhi device | Tests inject `httpx` failures, malicious error content and forged device identity without loading the upstream server in the host test runner. No new MCP server is justified for this private local robot API |
| Code/harness drift | `test_integration_contracts.py` now compares the actual `BodyPins.h` and XIAO Sense `config.h` pin assignments to `full-feature-plan.json`, rather than checking that the JSON alone contains unique pins | Source check only. The XIAO Sense SD J3 cut/isolation, servo/stepper electrical integrity, rated charger and physical fit still require inspection |

**Upstream verified:** [LiveKit VoiceActivityVideoSampler](https://docs.livekit.io/agents/logic/sessions/) uses low idle and elevated speaking cadence; [Pipecat Smart Turn v3](https://github.com/pipecat-ai/smart-turn) adds natural turn completion on local audio. Neither complete framework is linked into this Xiaozhi build; adding either full audio owner would create conflicting VAD, turn state and speaker output. [Xinnan's actual plugin registry](https://github.com/xinnan-tech/xiaozhi-esp32-server/blob/main/main/xiaozhi-server/plugins_func/register.py) already supports the current authenticated Mac tool calls. Research alone does not establish improved live audio.

**Fast camera intent:** local safety and body touch are always higher priority than JPEG and VLM. User VAD preempts unsolicited speech and stale inference. A qualified physical sensor event coalesces requests through the existing per-robot camera hub; image processing is performed away from the audio loop; one global VLM lock avoids multiple expensive model calls. Multi-robot conversations are context-triggered, not random greeting timers. All five still require real microphone, camera, display and measured peak load trials.

**Verification order:** first resolve [the GitHub Actions pre-step failure](../reviews/CI_RUNNER_PRESTEP_TRIAGE_2026_11_11.md), then actually run the host regression suite and pinned builds. After that, instrument real XIAO mic to speaker interruption, VAD recovery, five-robot dialogue scheduling, visual capture-to-model age, dock safety and calibration. Source tests alone cannot certify physical acoustic or charging performance.


## November 17 tool fact packing and multimodal priority

Keep Xiaozhi as the one physical microphone, Opus and speaker owner.
Keep the existing Mac MultimodalOrchestrator as the one JPEG stream
consumer, PetController as the initiative scheduler, Conversation as the
speaker allocator, MemoryStore as each pet's opt-in local SQLite, and
WROOM as the motor safety authority. Do not install another realtime
transport, agent framework or media worker just to imitate another product.

### Deterministic priority and provenance

1. A local safety stop and physical interlock outrank everything. Neither
   a model instruction nor any read-only result can grant movement or charge.
2. Authenticated current Xiaozhi human speech and operator consent outrank
   pending TTS, ongoing optional vision inference, peer chatter and pet
   initiative. Clear stale turns before delivering another tool response.
3. A completed source-checked read-only tool result outranks a model guess,
   but is DATA, not a system instruction or a physical acceptance certificate.
   For compound voice questions, preserve the original request order and
   all completed distinct results regardless of completion order.
4. Raw WROOM sensor values, authenticated Mac JPEG receipt timestamps, VLM
   guesses, ASR transcripts, persistent memory and peer hearsay remain
   separate provenance types. No invented camera exposure timestamp, identity
   verification or heard-audio ACK is permitted.
5. An idle desk pet should use bounded sensor and change gates to decide
   whether to be curious, check fresh read-only state, speak once or stay
   silent. Never create low-value periodic commentary or unqualified drive
   commands. Autonomous exploration may start only through the existing
   operator-enabled and physically qualified WROOM motion path.

### Source references and remix status

* [Qwen Live Harness](https://github.com/QwenLM/Qwen-Live-Harness)
  uses a separate fast audio conversation, slower tools and bounded
  announced results after human speech and playback settle. Apache 2.0
  project. Adapt its priority and completed-receipt concepts, not its
  hosted Qwen model or desktop audio runtime.
* [LiveKit Agents](https://docs.livekit.io/agents/logic/turns/)
  documents interruption/turn handling and dynamic pause adaptation.
  Design reference only: Xiaozhi already owns our actual microphone and
  XIAO speaker decoder.
* [Pipecat frame model](https://github.com/pipecat-ai/docs/blob/main/api-reference/server/frames/overview.mdx)
  distinguishes urgent system events from cancellable media and LLM data.
  Design reference only, no second pipeline installed.
* [LangGraph checkpoint/store separation](https://docs.langchain.com/oss/python/langgraph/persistence)
  distinguishes transient sessions from long-term memory. Our existing
  per-pet SQLite and bounded camera hub retain that split without a new DB.
* [Reachy Mini conversation app](https://github.com/pollen-robotics/reachy_mini_conversation_app)
  combines realtime voice, VAD metrics, personality, camera and choreographed
  robot interaction. Reference only: its head pose is not a desk-safe wheel
  trajectory.
* [Gemini Live reference](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/live-api)
  demonstrates affective dialogue, proactive audio, barge-in and interleaved
  16 kHz microphone and 1 FPS video. Capability benchmark, not the deployed
  model. Do not claim MiniCPM has the same native tool-result KV ingestion.

### Implementation change and exact limits

Existing Xiaozhi native tool speech used to slice serialized Mac facts at
an arbitrary 1800 characters. Three completed results could be malformed
or partially omitted before the final text/audio model response.
The shared pure voice intent module now packs one to three receipts in
compact valid JSON. It preserves each requested result, its order, robot
provenance, verified numeric fields and explicit physical-qualification
flags. Only untrusted descriptive text may be excerpted. If the complete
typed facts cannot fit, no model speech is generated and the optional
speaker lease is released. Existing native transport and tool executor
are unchanged. Source regressions are in the current native omni tests.
The isolated helper has passed Python checks, not a full repository suite.

**November 17 live exploration source correction:** The guarded hardware
exploration loop no longer opens its own repeated XIAO `head.snapshot()`
requests while the Mac already holds one continuous MJPEG stream. Runtime
passes its existing MultimodalOrchestrator to Coordinator, which accepts
only a fresh proactive frame from the same three-frame RAM hub, tracks the
last consumed receipt, and requires a NEW frame after each short movement
pulse. No media owner, camera socket or motor authorization is created.
A reconnecting camera worker is NOT a connected MJPEG socket; the
controller now requires the actual head stream connected status as well as
the worker lifetime, and rechecks after awaiting the frame. If the
stream is offline, revoked, stale or no next frame arrives, the
existing exploration job stops under its existing WROOM safety watchdog
and does not start another drive. Simulation retains its synthetic capture
tests. New regressions in code/tests/test_control.py cover missing stream,
one-pulse reuse refusal and stale stream frames. These are committed SOURCE
tests, not yet full pytest or physical loaded exploration qualification.

Physical AEC, speaker STOP and unplayed transcript truncation, live
MiniCPM incorporation of prior tool results, five robot speaker
arbitration, actual camera arrival latency, and complete desk/dock
acceptance remain OPEN. The native adapter has a bounded same-model
text/audio result narration fallback, not true native duplex tool KV
integration. These gaps must not be relabeled completed or purchase safe.


### November 17 cross-modal fairness and input backpressure

The shared read-only room station previously scheduled one Mac event-loop callback
per valid USB observation, even when the previous environmental reading was
still pending. The current Runtime owns **one** coalesced callback and replaces
the pending snapshot with the newest valid receipt under a short thread lock.
The serial reader does not await model/context handling; new human VAD and
camera work are not queued behind unbounded stale room callbacks. Shutdown
discards pending room data, and a closed loop cannot admit a new room epoch.
The raw serial replay fence remains owned by RoomSerialFeed and is unchanged.
See `code/tests/test_room_context_backpressure.py`.

Physical pet events and shared visual changes have different identities.
Two robots reporting identical legitimate touch, bumper, or paw descriptions
are now independently eligible for initiative after the existing shared
speech-floor cooldown; they cannot be mistaken for one physical interaction.
Repeated camera model descriptions across different heads remain eligible
for cross-camera deduplication. Neither change relaxes human speech preemption,
physical motion interlocks, consent, or maximum spontaneous speaking rate.
See `code/tests/test_proactive_fleet_event_identity.py`.

These are source changes with new regression cases, **not executed hardware,
firmware, full pytest or acoustic acceptance**. Qwen Live Harness and Pipecat
remain priority/backpressure design references; no second agent framework,
camera or microphone transport was installed. The independent room callback
blocking contract remains open for arbitrary third-party consumers; the
production Runtime callback uses a short event-loop handoff.


## Complete tool receipt overflow behavior

The shared `desk_robot_voice_intents.pack_grounded_facts` function accepts
**one through six** distinct completed facts for one speech turn, retaining
their typed origins and source order within the existing 1800-character
context cap. Seven or more facts are not silently truncated to the first
six. Likewise, an uncompressible six-fact set produces a bounded
`ValueError`, so the live turn must decline to narrate partial evidence
and release its optional speech ownership. This is the deliberate
fail-closed response to tool receipt overflow, not a lost seventh tool
receipt or permission to invent a summary.

A human can repeat or narrow the question to fit the bounded context.
Actual connected tool execution, the delivered head audio and spoken
receipt incorporation require end-to-end tests; source context packing
alone does not prove a realtime model used the tools. A model may never
interpret the contents of tool results as developer/system instructions,
motor permission, charging confirmation or a new sensor reading.
