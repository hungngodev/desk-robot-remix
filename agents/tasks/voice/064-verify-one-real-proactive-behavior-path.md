# DRR-064 · Verify one real proactive behavior path

**State at inventory snapshot** · Blocked

**Authority** · Verification

Exercise the supported entry point and record exact evidence. If a gap remains, hand it to the owner as one scoped change. Use GitHub CI or an isolated checkout when available.

## Before you start

- Check [draft PR #17](https://github.com/hungngodev/desk-robot-remix/pull/17) at the live head. Use the GitHub issue for this card to check ownership, claim the work and save your checkpoint. [Launch and issue instructions](../../README.md)
- Read [chat-mode source](../../shared/00_meta_instructions.md), [work isolation and claims](../../shared/01_agent_worktree_rules.md), [checkpoints and review](../../shared/02_continuation_and_review_loop.md), [push order](../../shared/03_parallel_push_queue.md), [ownership](../../shared/04_scope_and_ownership.md), [release evidence](../../shared/05_acceptance_criteria.md). The scoped paths and the current accepted guide apply to this card.
- Prerequisites · [DRR-055](../../tasks/voice/055-verify-human-vad-takes-priority.md), [DRR-060](../../tasks/voice/060-verify-deliberate-versus-passive-cooldowns.md)

Wait for the required deliverables from [DRR-055](../../tasks/voice/055-verify-human-vad-takes-priority.md), [DRR-060](../../tasks/voice/060-verify-deliberate-versus-passive-cooldowns.md). A matching recorded fixture can support early independent verification where the acceptance describes a replay.

## Scoped work and acceptance

[`code/laptop/src/desk_robot/pet.py`](../../../code/laptop/src/desk_robot/pet.py)

Replay meaningful scene or touch observation through its actual producer and consumer. Check freshness, coalescing and a no-change case.

## Handoff

Record the reviewed SHA, source path or commit, the executed check and its result, and the exact open dependency or next action. Keep simulated evidence, exact-SHA CI and physical results distinct. Mark the issue verified only when this card’s acceptance is met. [Issue completion format](../../README.md#claim-verify-and-hand-off-in-github)

## Sources

[Tab 18 source index](../../coverage.md#tab-18) · [Guide 40](../../../docs/plans/spatial-first-unit/40-voice-and-proactive-behavior.md) · [MAC-10](../../coverage.md#audit-mac-10) · [D05](../../coverage.md#packet-d05) · [T18 p16](../../coverage.md#t18-p16)
