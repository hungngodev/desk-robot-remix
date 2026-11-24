# DRR-032 · Exercise bumper and mux faults

**State at inventory snapshot** · Ready

**Authority** · Verification

Exercise the supported entry point and record exact evidence. If a gap remains, hand it to the owner as one scoped change. Use GitHub CI or an isolated checkout when available.

## Before you start

- Check [draft PR #17](https://github.com/hungngodev/desk-robot-remix/pull/17) at the live head. Use the GitHub issue for this card to check ownership, claim the work and save your checkpoint. [Launch and issue instructions](../../README.md)
- Read [chat-mode source](../../shared/00_meta_instructions.md), [work isolation and claims](../../shared/01_agent_worktree_rules.md), [checkpoints and review](../../shared/02_continuation_and_review_loop.md), [push order](../../shared/03_parallel_push_queue.md), [ownership](../../shared/04_scope_and_ownership.md), [release evidence](../../shared/05_acceptance_criteria.md). The scoped paths and the current accepted guide apply to this card.
- Prerequisites · Start independently from the current PR and scoped evidence.

Start at the live PR head and check existing claims and evidence.

## Scoped work and acceptance

[`code/firmware/body/tests`](../../../code/firmware/body/tests)

Verify pressed/disconnected bumper and bus faults stop and latch. Check accessory traffic cannot override the result.

## Handoff

Record the reviewed SHA, source path or commit, the executed check and its result, and the exact open dependency or next action. Keep simulated evidence, exact-SHA CI and physical results distinct. Mark the issue verified only when this card’s acceptance is met. [Issue completion format](../../README.md#claim-verify-and-hand-off-in-github)

## Sources

[Tab 16 source index](../../coverage.md#tab-16) · [Guide 20](../../../docs/plans/spatial-first-unit/20-body-safety-and-odometry.md) · [BODY-07](../../coverage.md#audit-body-07) · [C02](../../coverage.md#packet-c02) · [C03](../../coverage.md#packet-c03) · [T16 p13](../../coverage.md#t16-p13) · [T16 p17](../../coverage.md#t16-p17) · [T21 p15](../../coverage.md#t21-p15)
