# DRR-010 · Repair links to the evidence ledger

**State at inventory snapshot** · Ready

**Authority** · Scoped implementation when launched

Confirm the gap still exists, then make the smallest change within this scope. Exercise the normal entry point and verify related review comments before handing off.

## Before you start

- Check [draft PR #17](https://github.com/hungngodev/desk-robot-remix/pull/17) at the live head. Use the GitHub issue for this card to check ownership, claim the work and save your checkpoint. [Launch and issue instructions](../../README.md)
- Read [chat-mode source](../../shared/00_meta_instructions.md), [work isolation and claims](../../shared/01_agent_worktree_rules.md), [checkpoints and review](../../shared/02_continuation_and_review_loop.md), [push order](../../shared/03_parallel_push_queue.md), [ownership](../../shared/04_scope_and_ownership.md), [release evidence](../../shared/05_acceptance_criteria.md). The scoped paths and the current accepted guide apply to this card.
- Prerequisites · Start independently from the current PR and scoped evidence.

Start at the live PR head and check existing claims and evidence.

## Scoped work and acceptance

[`docs/README.md`](../../../docs/README.md) · [`docs/records/verification.md`](../../../docs/records/verification.md)

Follow builder and reviewer entry links on a clean checkout. Verify they resolve to the canonical ledger and preserve evidence records.

## Handoff

Record the reviewed SHA, source path or commit, the executed check and its result, and the exact open dependency or next action. Keep simulated evidence, exact-SHA CI and physical results distinct. Mark the issue verified only when this card’s acceptance is met. [Issue completion format](../../README.md#claim-verify-and-hand-off-in-github)

## Sources

[Tab 22 source index](../../coverage.md#tab-22) · [Guide 90](../../../docs/plans/spatial-first-unit/90-integration-and-release-evidence.md) · [DOC-06](../../coverage.md#audit-doc-06) · [DOC-10](../../coverage.md#audit-doc-10) · [A05](../../coverage.md#packet-a05) · [T22 p15](../../coverage.md#t22-p15)
