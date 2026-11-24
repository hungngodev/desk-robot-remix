# DRR-020 · Compute landed cost and prior spend

**State at inventory snapshot** · Blocked

**Authority** · Verification

Exercise the supported entry point and record exact evidence. If a gap remains, hand it to the owner as one scoped change. Use GitHub CI or an isolated checkout when available.

## Before you start

- Check [draft PR #17](https://github.com/hungngodev/desk-robot-remix/pull/17) at the live head. Use the GitHub issue for this card to check ownership, claim the work and save your checkpoint. [Launch and issue instructions](../../README.md)
- Read [chat-mode source](../../shared/00_meta_instructions.md), [work isolation and claims](../../shared/01_agent_worktree_rules.md), [checkpoints and review](../../shared/02_continuation_and_review_loop.md), [push order](../../shared/03_parallel_push_queue.md), [ownership](../../shared/04_scope_and_ownership.md), [release evidence](../../shared/05_acceptance_criteria.md). The scoped paths and the current accepted guide apply to this card.
- Prerequisites · [DRR-012](../../tasks/shopping/012-allocate-paid-and-available-stock.md), [DRR-018](../../tasks/shopping/018-count-retail-packs-and-surplus.md), [DRR-019](../../tasks/shopping/019-verify-stock-and-quote-expiry.md)

Wait for the required deliverables from [DRR-012](../../tasks/shopping/012-allocate-paid-and-available-stock.md), [DRR-018](../../tasks/shopping/018-count-retail-packs-and-surplus.md), [DRR-019](../../tasks/shopping/019-verify-stock-and-quote-expiry.md). A matching recorded fixture can support early independent verification where the acceptance describes a replay.

## Scoped work and acceptance

[`code/scripts/procurement_release.py`](../../../code/scripts/procurement_release.py)

Reconcile exact cents for all known spend, shipping, tax and discounts across one robot, one dock and one shared station. Compute any gap to $50.

## Handoff

Record the reviewed SHA, source path or commit, the executed check and its result, and the exact open dependency or next action. Keep simulated evidence, exact-SHA CI and physical results distinct. Mark the issue verified only when this card’s acceptance is met. [Issue completion format](../../README.md#claim-verify-and-hand-off-in-github)

## Sources

[Tab 15 source index](../../coverage.md#tab-15) · [Guide 10](../../../docs/plans/spatial-first-unit/10-requirements-and-shopping.md) · [BUY-04](../../coverage.md#audit-buy-04) · [BUY-09](../../coverage.md#audit-buy-09) · [BUY-12](../../coverage.md#audit-buy-12) · [B04](../../coverage.md#packet-b04) · [T15 p17](../../coverage.md#t15-p17)
