# DRR-123 · Verify the final integrated head

**State at inventory snapshot** · Blocked

**Authority** · Verification

Exercise the supported entry point and record exact evidence. If a gap remains, hand it to the owner as one scoped change. Use GitHub CI or an isolated checkout when available.

## Before you start

- Check [draft PR #17](https://github.com/hungngodev/desk-robot-remix/pull/17) at the live head. Use the GitHub issue for this card to check ownership, claim the work and save your checkpoint. [Launch and issue instructions](../../README.md)
- Read [chat-mode source](../../shared/00_meta_instructions.md), [work isolation and claims](../../shared/01_agent_worktree_rules.md), [checkpoints and review](../../shared/02_continuation_and_review_loop.md), [push order](../../shared/03_parallel_push_queue.md), [ownership](../../shared/04_scope_and_ownership.md), [release evidence](../../shared/05_acceptance_criteria.md). The scoped paths and the current accepted guide apply to this card.
- Prerequisites · [DRR-005](../../tasks/repository/005-check-required-ci-jobs-at-one-sha.md), [DRR-112](../../tasks/integration/112-integrate-bounded-execution-via-the-current-motion-owner.md), [DRR-113](../../tasks/integration/113-replay-old-hardware-and-degraded-startup.md), [DRR-114](../../tasks/integration/114-replay-stale-and-wrong-robot-pose-and-jpeg.md), [DRR-115](../../tasks/integration/115-replay-lost-anchor-and-pickup.md), [DRR-116](../../tasks/integration/116-replay-moved-occluded-and-falsely-detected-objects.md), [DRR-117](../../tasks/integration/117-replay-user-cut-in-and-stop-under-load.md), [DRR-118](../../tasks/integration/118-replay-dock-false-positives-and-station-isolation.md), [DRR-119](../../tasks/integration/119-trace-the-digital-portions-of-a1-a12.md), [DRR-122](../../tasks/integration/122-resolve-related-review-threads-with-evidence.md)

Wait for the required deliverables from [DRR-112](../../tasks/integration/112-integrate-bounded-execution-via-the-current-motion-owner.md), [DRR-113](../../tasks/integration/113-replay-old-hardware-and-degraded-startup.md), [DRR-114](../../tasks/integration/114-replay-stale-and-wrong-robot-pose-and-jpeg.md), [DRR-115](../../tasks/integration/115-replay-lost-anchor-and-pickup.md), [DRR-116](../../tasks/integration/116-replay-moved-occluded-and-falsely-detected-objects.md), [DRR-117](../../tasks/integration/117-replay-user-cut-in-and-stop-under-load.md), [DRR-118](../../tasks/integration/118-replay-dock-false-positives-and-station-isolation.md), [DRR-119](../../tasks/integration/119-trace-the-digital-portions-of-a1-a12.md), [DRR-122](../../tasks/integration/122-resolve-related-review-threads-with-evidence.md). A matching recorded fixture can support early independent verification where the acceptance describes a replay.

## Scoped work and acceptance

[`.github/workflows/host-verification.yml`](../../../.github/workflows/host-verification.yml)

Inspect or run all required jobs for one exact integrated SHA. Separate unavailable checks, software passes and open field evidence.

## Handoff

Record the reviewed SHA, source path or commit, the executed check and its result, and the exact open dependency or next action. Keep simulated evidence, exact-SHA CI and physical results distinct. Mark the issue verified only when this card’s acceptance is met. [Issue completion format](../../README.md#claim-verify-and-hand-off-in-github)

## Sources

[Tab 22 source index](../../coverage.md#tab-22) · [Guide 90](../../../docs/plans/spatial-first-unit/90-integration-and-release-evidence.md) · [DOC-05](../../coverage.md#audit-doc-05) · [SHIP-02](../../coverage.md#audit-ship-02) · [F01](../../coverage.md#packet-f01) · [T22 p16](../../coverage.md#t22-p16)
