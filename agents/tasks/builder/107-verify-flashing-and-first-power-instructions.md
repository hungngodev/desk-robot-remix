# DRR-107 · Verify flashing and first-power instructions

**State at inventory snapshot** · Blocked

**Authority** · Review only

Inspect and report. Use read-only checks. Post distinct findings in the existing review thread when authorized. Route any fix to the appropriate implementation task.

## Before you start

- Check [draft PR #17](https://github.com/hungngodev/desk-robot-remix/pull/17) at the live head. Use the GitHub issue for this card to check ownership, claim the work and save your checkpoint. [Launch and issue instructions](../../README.md)
- Read [chat-mode source](../../shared/00_meta_instructions.md), [work isolation and claims](../../shared/01_agent_worktree_rules.md), [checkpoints and review](../../shared/02_continuation_and_review_loop.md), [push order](../../shared/03_parallel_push_queue.md), [ownership](../../shared/04_scope_and_ownership.md), [release evidence](../../shared/05_acceptance_criteria.md). The scoped paths and the current accepted guide apply to this card.
- Prerequisites · [DRR-104](../../tasks/builder/104-verify-the-connector-to-connector-harness.md)

Wait for the required deliverables from [DRR-104](../../tasks/builder/104-verify-the-connector-to-connector-harness.md). A matching recorded fixture can support early independent verification where the acceptance describes a replay.

## Scoped work and acceptance

[`docs/guides/build.md`](../../../docs/guides/build.md)

Trace selected firmware targets/settings and logic-only bringup from a fresh checkout. Verify observed values and safe stop points are specified.

## Handoff

Record the reviewed SHA, source path or commit, the executed check and its result, and the exact open dependency or next action. Keep simulated evidence, exact-SHA CI and physical results distinct. Mark the issue verified only when this card’s acceptance is met. [Issue completion format](../../README.md#claim-verify-and-hand-off-in-github)

## Sources

[Tab 21 source index](../../coverage.md#tab-21) · [Guide 70](../../../docs/plans/spatial-first-unit/70-fit-power-manipulation-and-dock.md) · [CAD-06](../../coverage.md#audit-cad-06) · [CAD-08](../../coverage.md#audit-cad-08) · [E06](../../coverage.md#packet-e06) · [T21 p13](../../coverage.md#t21-p13) · [T22 p15](../../coverage.md#t22-p15)
