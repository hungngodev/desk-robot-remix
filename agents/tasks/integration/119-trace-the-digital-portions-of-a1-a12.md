# DRR-119 · Trace the digital portions of A1–A12

**State at inventory snapshot** · Blocked

**Authority** · Verification

Exercise the supported entry point and record exact evidence. If a gap remains, hand it to the owner as one scoped change. Use GitHub CI or an isolated checkout when available.

## Before you start

- Check [draft PR #17](https://github.com/hungngodev/desk-robot-remix/pull/17) at the live head. Use the GitHub issue for this card to check ownership, claim the work and save your checkpoint. [Launch and issue instructions](../../README.md)
- Read [chat-mode source](../../shared/00_meta_instructions.md), [work isolation and claims](../../shared/01_agent_worktree_rules.md), [checkpoints and review](../../shared/02_continuation_and_review_loop.md), [push order](../../shared/03_parallel_push_queue.md), [ownership](../../shared/04_scope_and_ownership.md), [release evidence](../../shared/05_acceptance_criteria.md). The scoped paths and the current accepted guide apply to this card.
- Prerequisites · [DRR-005](../../tasks/repository/005-check-required-ci-jobs-at-one-sha.md), [DRR-008](../../tasks/repository/008-check-measured-receipt-validation.md)

Wait for the required deliverables from [DRR-008](../../tasks/repository/008-check-measured-receipt-validation.md). A matching recorded fixture can support early independent verification where the acceptance describes a replay.

## Scoped work and acceptance

[`docs/records/verification.md`](../../../docs/records/verification.md)

For each accepted product criterion attach the normal-path software check and distinct physical requirement. Preserve missing measurements.

## Handoff

Record the reviewed SHA, source path or commit, the executed check and its result, and the exact open dependency or next action. Keep simulated evidence, exact-SHA CI and physical results distinct. Mark the issue verified only when this card’s acceptance is met. [Issue completion format](../../README.md#claim-verify-and-hand-off-in-github)

## Sources

[Tab 22 source index](../../coverage.md#tab-22) · [Guide 90](../../../docs/plans/spatial-first-unit/90-integration-and-release-evidence.md) · [DOC-09](../../coverage.md#audit-doc-09) · [SHIP-01](../../coverage.md#audit-ship-01) · [A05](../../coverage.md#packet-a05) · [F01](../../coverage.md#packet-f01) · [T22 p16](../../coverage.md#t22-p16)
