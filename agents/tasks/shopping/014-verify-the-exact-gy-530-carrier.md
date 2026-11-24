# DRR-014 · Verify the exact GY-530 carrier

**State at inventory snapshot** · Blocked

**Authority** · Review only

Inspect and report. Use read-only checks. Post distinct findings in the existing review thread when authorized. Route any fix to the appropriate implementation task.

## Before you start

- Check [draft PR #17](https://github.com/hungngodev/desk-robot-remix/pull/17) at the live head. Use the GitHub issue for this card to check ownership, claim the work and save your checkpoint. [Launch and issue instructions](../../README.md)
- Read [chat-mode source](../../shared/00_meta_instructions.md), [work isolation and claims](../../shared/01_agent_worktree_rules.md), [checkpoints and review](../../shared/02_continuation_and_review_loop.md), [push order](../../shared/03_parallel_push_queue.md), [ownership](../../shared/04_scope_and_ownership.md), [release evidence](../../shared/05_acceptance_criteria.md). The scoped paths and the current accepted guide apply to this card.
- Prerequisites · [DRR-013](../../tasks/shopping/013-collect-proof-of-same-feature-use.md)

Wait for the required deliverables from [DRR-013](../../tasks/shopping/013-collect-proof-of-same-feature-use.md). A matching recorded fixture can support early independent verification where the acceptance describes a replay.

## Scoped work and acceptance

[`docs/hardware/full-feature-plan.json`](../../../docs/hardware/full-feature-plan.json)

Resolve the exact evaluation SKU, 3.3 V signals/pullups and mounting footprint. Preserve qualification required before filling the seven other lanes.

## Handoff

Record the reviewed SHA, source path or commit, the executed check and its result, and the exact open dependency or next action. Keep simulated evidence, exact-SHA CI and physical results distinct. Mark the issue verified only when this card’s acceptance is met. [Issue completion format](../../README.md#claim-verify-and-hand-off-in-github)

## Sources

[Tab 15 source index](../../coverage.md#tab-15) · [Guide 10](../../../docs/plans/spatial-first-unit/10-requirements-and-shopping.md) · [BUY-10](../../coverage.md#audit-buy-10) · [B05](../../coverage.md#packet-b05) · [T15 p15](../../coverage.md#t15-p15)
