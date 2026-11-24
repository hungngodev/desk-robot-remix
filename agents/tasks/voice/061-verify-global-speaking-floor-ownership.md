# DRR-061 · Verify global speaking-floor ownership

**State at inventory snapshot** · Ready

**Authority** · Verification

Exercise the supported entry point and record exact evidence. If a gap remains, hand it to the owner as one scoped change. Use GitHub CI or an isolated checkout when available.

## Before you start

- Check [draft PR #17](https://github.com/hungngodev/desk-robot-remix/pull/17) at the live head. Use the GitHub issue for this card to check ownership, claim the work and save your checkpoint. [Launch and issue instructions](../../README.md)
- Read [chat-mode source](../../shared/00_meta_instructions.md), [work isolation and claims](../../shared/01_agent_worktree_rules.md), [checkpoints and review](../../shared/02_continuation_and_review_loop.md), [push order](../../shared/03_parallel_push_queue.md), [ownership](../../shared/04_scope_and_ownership.md), [release evidence](../../shared/05_acceptance_criteria.md). The scoped paths and the current accepted guide apply to this card.
- Prerequisites · Start independently from the current PR and scoped evidence.

Start at the live PR head and check existing claims and evidence.

## Scoped work and acceptance

[`code/laptop/src/desk_robot/conversation.py`](../../../code/laptop/src/desk_robot/conversation.py)

Replay two pets for acquire, release and say. Verify partial playback counting, correct session ownership and no wrong-pet release.

## Handoff

Record the reviewed SHA, source path or commit, the executed check and its result, and the exact open dependency or next action. Keep simulated evidence, exact-SHA CI and physical results distinct. Mark the issue verified only when this card’s acceptance is met. [Issue completion format](../../README.md#claim-verify-and-hand-off-in-github)

## Sources

[Tab 18 source index](../../coverage.md#tab-18) · [Guide 40](../../../docs/plans/spatial-first-unit/40-voice-and-proactive-behavior.md) · [MAC-02](../../coverage.md#audit-mac-02) · [MAC-03](../../coverage.md#audit-mac-03) · [D01](../../coverage.md#packet-d01) · [D05](../../coverage.md#packet-d05) · [T18 p17](../../coverage.md#t18-p17) · [T18 p18](../../coverage.md#t18-p18)
