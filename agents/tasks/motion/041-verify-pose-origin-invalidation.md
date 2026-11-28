# DRR-041 · Verify pose origin invalidation

**State at inventory snapshot** · Blocked

**Authority** · Verification

Exercise the supported entry point and record exact evidence. If a gap remains, hand it to the owner as one scoped change. Use GitHub CI or an isolated checkout when available.

## Before you start

- Check [draft PR #17](https://github.com/hungngodev/desk-robot-remix/pull/17) at the live head. Use the GitHub issue for this card to check ownership, claim the work and save your checkpoint. [Launch and issue instructions](../../README.md)
- Read [chat-mode source](../../shared/00_meta_instructions.md), [work isolation and claims](../../shared/01_agent_worktree_rules.md), [checkpoints and review](../../shared/02_continuation_and_review_loop.md), [push order](../../shared/03_parallel_push_queue.md), [ownership](../../shared/04_scope_and_ownership.md), [release evidence](../../shared/05_acceptance_criteria.md). The scoped paths and the current accepted guide apply to this card.
- Prerequisites · [DRR-040](../../tasks/motion/040-verify-the-bounded-read-only-body-pose.md)

Wait for the required deliverables from [DRR-040](../../tasks/motion/040-verify-the-bounded-read-only-body-pose.md). A matching recorded fixture can support early independent verification where the acceptance describes a replay.

## Scoped work and acceptance

[`code/firmware/body`](../../../code/firmware/body)

Replay pickup, reboot and continuity loss. Verify old origin samples cannot become valid data in a new origin.

## Handoff

Record the reviewed SHA, source path or commit, the executed check and its result, and the exact open dependency or next action. Keep simulated evidence, exact-SHA CI and physical results distinct. Mark the issue verified only when this card’s acceptance is met. [Issue completion format](../../README.md#claim-verify-and-hand-off-in-github)

## Sources

[Tab 16 source index](../../coverage.md#tab-16) · [Guide 20](../../../docs/plans/spatial-first-unit/20-body-safety-and-odometry.md) · [BODY-08](../../coverage.md#audit-body-08) · [C04](../../coverage.md#packet-c04) · [T16 p15](../../coverage.md#t16-p15)
