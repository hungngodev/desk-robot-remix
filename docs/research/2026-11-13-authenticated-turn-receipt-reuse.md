# November 13: authenticated turn identity for delayed read only tool evidence

Owner: Robot Open Source Research. Canonical draft PR #17 only. Verified branch head before this note: `4e7430dfe0b4256a4e90f504bde101bf7b79034c` (GitHub compare against branch: identical). Fetched 35 issue comments, zero submitted reviews and zero inline review threads. Latest issue comments include verification-first warnings and native tool interruption changes; no second broker or PR is justified.

## Existing source and exact gap

Read current `code/laptop/src/desk_robot/brain_context.py`, `multimodal.py`, `conversation.py`, `pet.py`, `memory.py` and `runtime.py`. The shared context composer distinguishes physical evidence, uncertain camera inference, hearsay and local memory. The camera hub already preserves newer same-kind receipts and refuses equal-time replacement. These protections order *completion* but do not prove that a completed receipt was requested by the human turn currently speaking. An old tool can finish after a new ASR turn and have a newer receipt timestamp. Promoting it as current question evidence is a real provenance hazard; the exact end-to-end race has not yet been executed.

## Upstream reuse comparison and licensing

* LangGraph (https://github.com/langchain-ai/langgraph, MIT; https://github.com/langchain-ai/langgraph/blob/main/LICENSE) documents short-lived thread-scoped checkpointer state separately from long-lived cross-thread store (https://github.com/langchain-ai/docs/blob/main/src/oss/langgraph/persistence.mdx). Reuse the **identity and scope pattern**, not the graph runtime. Existing per-pet SQLite memory is already the durable store. A new framework or database is unnecessary.
* LiveKit Agents (https://github.com/livekit/agents, Apache 2.0; https://github.com/livekit/agents/blob/main/LICENSE) has explicit interruption completion and speech handles (https://docs.livekit.io/reference/python/livekit/agents/). Reuse the **cancellation/acknowledgment boundary**: stopping speech and invalidating pending model/tool output are separate transitions. Do not import a competing microphone, speaker or VAD owner. LiveKit turn detection models carry a separate model license and must not be silently imported.
* Existing pinned Xiaozhi transport, Mac tool execution, camera hub and WROOM physical authorization remain the only owners. These upstream references are design comparisons, not copied source. Before transplanting any code, pin its exact Git commit and preserve applicable license/NOTICE.

## Smallest source integration for implementation owner

1. Trace the authenticated XIAO completed ASR event through Mac read-only tool dispatch, tool completion and `CameraFrameHub.remember_tool`. Reuse any already existing speech epoch/generation field rather than inventing a second counter. Do not derive trust from an LLM-provided turn ID.
2. Bind each receipt to `(robot_id, session_generation, human_turn_generation, tool_request_id)` at trusted dispatch, and carry it unchanged through asynchronous completion. A result without verifiable identity may be kept as explicitly historical telemetry but must not be promoted as an answer to the current human question. Preserve legitimate results within the same ongoing turn and bounded background evidence.
3. On human interruption or session replacement, revoke pending old-turn speech/tool eligibility before a late completion can enter current-turn context. Keep acoustic ACK and transmitted-but-unverified speech history distinct; do not assert that network send means heard playback. Never turn a tool receipt into motion or charging authority.
4. Add deterministic regressions: old-turn request completes *after* a new turn, equal timestamp from a different turn, same-turn valid delayed result, cancellation racing completion, cross-pet request isolation and restart/session-generation collision. Verify red on the parent and green on the patch using exact blobs.
5. Coordinate with current native MiniCPM/Xiaozhi queue eviction fixes before editing. Avoid resetting the entire camera hub on each VAD, losing valid same-turn receipts or creating a second tool broker.

No source patch was made here because trusted dispatch identity and its full call chain need to be traced together before safely changing the receipt schema. No tests, builds or physical trials were executed. PR remains draft; battery, dock, CAD, grasp and five real pets remain unqualified.
