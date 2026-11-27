# 2026-11-12 Xiaozhi playback interruption ownership research

## Current source status (2026-11-27, DRX-1733)

The November 12 research below is historical; the proposed source work is
no longer wholly unimplemented. The locked Xiaozhi revisions remain unchanged.
In [the Sense overlay](../../code/firmware/head/install_overlay.py), urgent
`tts stop` with `flush: true` schedules `ResetDecoder()` and disables
codec output. Output admission and completion check `playback_generation_`.
`DeskPlaybackPrefix` and `on_playback_committed` report cumulative digital
I2S write progress through `desk_robot_i2s_progress` only for contiguous
complete media frames in the current generation. This is not a STOP receipt,
DMA drain proof or acoustic silence.

The [Mac conversation owner](../../code/laptop/src/desk_robot/conversation.py)
validates device identity, explicit flush acknowledgement, drained queue,
zero integer queued samples and a non-stale integer flush generation when
the speaker declares drain-receipt support. The
[actual Xiaozhi bridge](../../code/laptop/server/overlay/desk_robot_bridge.py)
still returns `head_flush_requested: true`,
`head_flush_acknowledged: false` and `audible_stop_verified: false`.
A transport response must not be promoted to confirmed head drain.

Existing source regressions include
[`test_sense_reuses_upstream_i2s_writer_with_finite_stop_bound`](../../code/firmware/head/tests/test_overlay.py)
and [generation-bound drain fault tests](../../code/tests/test_audio_abort_confirmation.py)
with a simulated head receipt, including missing, stale and wrong-head
receipts. These are not a demonstrated physical STOP ACK. The remaining
gate is a real same-device, generation-bound stop/drain receipt and the
physical A2 acoustic trial with separate stage timings. This source review
does not establish that any test or hardware trial ran.

## Historical November 12 research

Scope: source research only, canonical draft PR #17. No new audio owner, firmware patch, hardware claim or charger/motion authority.

## Upstream candidates and actual reuse

The repository already pins `78/xiaozhi-esp32` at `c435f99a88066029ec2dbd2d758c8cc9d051565b` and `xinnan-tech/xiaozhi-esp32-server` at `d9c2e8c5d92627b670dec57d72a07a4226a410a3` in `code/upstream-lock.json`; both are recorded MIT in `docs/ATTRIBUTION.md`. Preserve those exact revisions and notices. The upstream current-main `main/audio/audio_service.cc` visibly increments `playback_generation_`, clears encode/decode/playback queues, and conditionally invokes `on_playback_drained` on `AudioService::Stop()`. Its protocol documents `SendAbortSpeaking` and an idle transition on abort. These are useful reuse patterns, but **current main is not proof of behavior in our pinned October revision**, nor of our XIAO port.

Sources:
* https://github.com/78/xiaozhi-esp32/blob/main/main/audio/audio_service.cc
* https://github.com/78/xiaozhi-esp32/blob/main/docs/websocket.md
* https://github.com/xinnan-tech/xiaozhi-esp32-server
* Existing lock: `code/upstream-lock.json`

## Cross-boundary acceptance gap

A Mac `asyncio` callback completing, a transport abort being sent, or software Opus queues becoming empty does **not by itself prove** that the I2S hardware/DMA output has stopped. The head may still have buffered PCM, an in-flight decoder, or a previous generation of audio. Do not treat `on_playback_drained` as an acoustic ACK until its actual pinned implementation and codec output contract have been traced. Five simultaneous pets compound the risk: a late completion for pet A must not release pet B's speech lease, and a prior generation's completion must not acknowledge a newer interruption.

Proposed smallest integration, **not implemented**: use the existing head audio owner, existing authenticated per-device transport and existing fleet speech floor. Add a monotonically increasing per-head playback generation to the abort request and eventual head ACK, if the pinned protocol permits a compatible extension. ACK must be emitted only after queue invalidation **and** the relevant codec/I2S stop or drain completion, with an explicit timeout that fails closed. Keep Mac single-flight interruption tasks and human VAD priority. If the codec lacks a trustworthy completion callback, report `stop_requested` and `physical_stop_unverified` separately; do not manufacture an ACK.

## Next independently testable action

First inspect pinned `AudioService::Stop`, `MarkPlaybackDrainedLocked`, codec write/output tasks and the current XIAO firmware's actual playback/abort implementation. Compare against main before porting any upstream code. Then write a deterministic host/head contract regression with a delayed old-generation ACK, an absent ACK, and a newer playback generation, asserting that none falsely releases the current speech floor. A later real five-head bench test must timestamp VAD arrival, abort dispatch, head queue clear, I2S stop and microphone-observed acoustic silence. No repository test, head build or physical trial was run for this note.
