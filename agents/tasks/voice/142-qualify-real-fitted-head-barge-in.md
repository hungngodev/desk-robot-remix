# DRR-142 · Qualify real fitted-head barge-in

**State at inventory snapshot** · Blocked

**Authority** · Operator evidence

Prepare or inspect the procedure and later reconcile real operator evidence. The card itself grants no permission to energize, charge, move, purchase or perform a physical trial.

## Before you start

- Check [draft PR #17](https://github.com/hungngodev/desk-robot-remix/pull/17) at the live head. Use the GitHub issue for this card to check ownership, claim the work and save your checkpoint. [Launch and issue instructions](../../README.md)
- Read [chat-mode source](../../shared/00_meta_instructions.md), [work isolation and claims](../../shared/01_agent_worktree_rules.md), [checkpoints and review](../../shared/02_continuation_and_review_loop.md), [push order](../../shared/03_parallel_push_queue.md), [ownership](../../shared/04_scope_and_ownership.md), [release evidence](../../shared/05_acceptance_criteria.md). The scoped paths and the current accepted guide apply to this card.
- Prerequisites · [DRR-053](../../tasks/sense/053-measure-fitted-head-acoustic-timing.md), [DRR-055](../../tasks/voice/055-verify-human-vad-takes-priority.md), [DRR-056](../../tasks/voice/056-verify-obsolete-playback-cancellation.md), [DRR-057](../../tasks/voice/057-verify-interrupted-speech-onset-is-retained.md), [DRR-058](../../tasks/voice/058-verify-echo-only-rejection-criteria.md)

A qualified assembly, the specified operator evidence, and authorization for that trial are required. Digital prerequisites still open: [DRR-053](../../tasks/sense/053-measure-fitted-head-acoustic-timing.md), [DRR-055](../../tasks/voice/055-verify-human-vad-takes-priority.md), [DRR-056](../../tasks/voice/056-verify-obsolete-playback-cancellation.md), [DRR-057](../../tasks/voice/057-verify-interrupted-speech-onset-is-retained.md), [DRR-058](../../tasks/voice/058-verify-echo-only-rejection-criteria.md).

## Scoped work and acceptance

[`docs/guides/audio-barge-in.md`](../../../docs/guides/audio-barge-in.md)

Record 19/20 audible stops in 500 ms, 18/20 retained and understood intents, no obsolete playback resume and zero echo-only triggers in ten minutes.

## Handoff

Record the reviewed SHA, source path or commit, the executed check and its result, and the exact open dependency or next action. Keep simulated evidence, exact-SHA CI and physical results distinct. Mark the issue verified only when this card’s acceptance is met. [Issue completion format](../../README.md#claim-verify-and-hand-off-in-github)

## Sources

[Tab 18 source index](../../coverage.md#tab-18) · [Guide 40](../../../docs/plans/spatial-first-unit/40-voice-and-proactive-behavior.md) · [HEAD-03](../../coverage.md#audit-head-03) · [MAC-10](../../coverage.md#audit-mac-10) · [D02](../../coverage.md#packet-d02) · [T18 p15](../../coverage.md#t18-p15)
