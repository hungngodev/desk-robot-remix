# DRR-165 · Publish the current builder route from verified references

**State at inventory snapshot** · Blocked

**Authority** · Scoped implementation when launched

Confirm the gap still exists, then make the smallest change within this scope. Exercise the normal entry point and verify related review comments before handing off.

## Before you start

- Check [draft PR #17](https://github.com/hungngodev/desk-robot-remix/pull/17) at the live head. Use the GitHub issue for this card to check ownership, claim the work and save your checkpoint. [Launch and issue instructions](../../README.md)
- Read [chat-mode source](../../shared/00_meta_instructions.md), [work isolation and claims](../../shared/01_agent_worktree_rules.md), [checkpoints and review](../../shared/02_continuation_and_review_loop.md), [push order](../../shared/03_parallel_push_queue.md), [ownership](../../shared/04_scope_and_ownership.md), [release evidence](../../shared/05_acceptance_criteria.md). The scoped paths and the current accepted guide apply to this card.
- Prerequisites · [DRR-104](../../tasks/builder/104-verify-the-connector-to-connector-harness.md), [DRR-105](../../tasks/builder/105-verify-2d-scale-and-orientation.md), [DRR-106](../../tasks/builder/106-reproduce-clean-checkout-cad-exports.md), [DRR-107](../../tasks/builder/107-verify-flashing-and-first-power-instructions.md)

Wait for the required deliverables from [DRR-104](../../tasks/builder/104-verify-the-connector-to-connector-harness.md), [DRR-105](../../tasks/builder/105-verify-2d-scale-and-orientation.md), [DRR-106](../../tasks/builder/106-reproduce-clean-checkout-cad-exports.md), [DRR-107](../../tasks/builder/107-verify-flashing-and-first-power-instructions.md). A matching recorded fixture can support early independent verification where the acceptance describes a replay.

## Scoped work and acceptance

[`docs/guides/build.md`](../../../docs/guides/build.md)

Consolidate the existing links into one route for cart, prints, firmware, commissioning and acceptance. Preserve attribution and explicitly mark unavailable physical evidence.

## Handoff

Record the reviewed SHA, source path or commit, the executed check and its result, and the exact open dependency or next action. Keep simulated evidence, exact-SHA CI and physical results distinct. Mark the issue verified only when this card’s acceptance is met. [Issue completion format](../../README.md#claim-verify-and-hand-off-in-github)

## Sources

[Tab 21 source index](../../coverage.md#tab-21) · [Guide 70](../../../docs/plans/spatial-first-unit/70-fit-power-manipulation-and-dock.md) · [T22 p15](../../coverage.md#t22-p15)
