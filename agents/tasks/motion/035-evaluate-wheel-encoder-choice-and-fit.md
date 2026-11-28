# DRR-035 · Evaluate wheel encoder choice and fit

**State at inventory snapshot** · Ready

**Authority** · Review only

Inspect and report. Use read-only checks. Post distinct findings in the existing review thread when authorized. Route any fix to the appropriate implementation task.

## Before you start

- Check [draft PR #17](https://github.com/hungngodev/desk-robot-remix/pull/17) at the live head. Use the GitHub issue for this card to check ownership, claim the work and save your checkpoint. [Launch and issue instructions](../../README.md)
- Read [chat-mode source](../../shared/00_meta_instructions.md), [work isolation and claims](../../shared/01_agent_worktree_rules.md), [checkpoints and review](../../shared/02_continuation_and_review_loop.md), [push order](../../shared/03_parallel_push_queue.md), [ownership](../../shared/04_scope_and_ownership.md), [release evidence](../../shared/05_acceptance_criteria.md). The scoped paths and the current accepted guide apply to this card.
- Prerequisites · Start independently from the current PR and scoped evidence.

Start at the live PR head and check existing claims and evidence.

## Scoped work and acceptance

[`docs/plans/spatial-first-unit/20-body-safety-and-odometry.md`](../../../docs/plans/spatial-first-unit/20-body-safety-and-odometry.md)

Identify exact encoder or AS5600 variant, coupling, rate, GPIO and bracket constraints. Record the real wheel displacement evidence needed.

## Handoff

Record the reviewed SHA, source path or commit, the executed check and its result, and the exact open dependency or next action. Keep simulated evidence, exact-SHA CI and physical results distinct. Mark the issue verified only when this card’s acceptance is met. [Issue completion format](../../README.md#claim-verify-and-hand-off-in-github)

## Sources

[Tab 16 source index](../../coverage.md#tab-16) · [Guide 20](../../../docs/plans/spatial-first-unit/20-body-safety-and-odometry.md) · [C07](../../coverage.md#packet-c07) · [T16 p14](../../coverage.md#t16-p14)
