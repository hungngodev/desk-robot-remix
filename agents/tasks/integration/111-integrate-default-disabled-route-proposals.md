# DRR-111 · Integrate default-disabled route proposals

**State at inventory snapshot** · Blocked

**Authority** · Scoped implementation when launched

Confirm the gap still exists, then make the smallest change within this scope. Exercise the normal entry point and verify related review comments before handing off.

## Before you start

- Check [draft PR #17](https://github.com/hungngodev/desk-robot-remix/pull/17) at the live head. Use the GitHub issue for this card to check ownership, claim the work and save your checkpoint. [Launch and issue instructions](../../README.md)
- Read [chat-mode source](../../shared/00_meta_instructions.md), [work isolation and claims](../../shared/01_agent_worktree_rules.md), [checkpoints and review](../../shared/02_continuation_and_review_loop.md), [push order](../../shared/03_parallel_push_queue.md), [ownership](../../shared/04_scope_and_ownership.md), [release evidence](../../shared/05_acceptance_criteria.md). The scoped paths and the current accepted guide apply to this card.
- Prerequisites · [DRR-079](../../tasks/navigation/079-verify-target-and-hard-negative-fixtures.md), [DRR-083](../../tasks/navigation/083-reject-unsupported-or-stale-travel.md), [DRR-110](../../tasks/integration/110-integrate-fixture-and-read-only-map-modes.md)

Wait for the required deliverables from [DRR-079](../../tasks/navigation/079-verify-target-and-hard-negative-fixtures.md), [DRR-083](../../tasks/navigation/083-reject-unsupported-or-stale-travel.md), [DRR-110](../../tasks/integration/110-integrate-fixture-and-read-only-map-modes.md). A matching recorded fixture can support early independent verification where the acceptance describes a replay.

## Scoped work and acceptance

[`code/laptop/src/desk_robot/controller.py`](../../../code/laptop/src/desk_robot/controller.py)

Verify deterministic proposals through the existing setting and controller. Default config, stale map and failed detector must produce no motion.

## Handoff

Record the reviewed SHA, source path or commit, the executed check and its result, and the exact open dependency or next action. Keep simulated evidence, exact-SHA CI and physical results distinct. Mark the issue verified only when this card’s acceptance is met. [Issue completion format](../../README.md#claim-verify-and-hand-off-in-github)

## Sources

[Tab 22 source index](../../coverage.md#tab-22) · [Guide 90](../../../docs/plans/spatial-first-unit/90-integration-and-release-evidence.md) · [T20 p15](../../coverage.md#t20-p15) · [T22 p13](../../coverage.md#t22-p13)
