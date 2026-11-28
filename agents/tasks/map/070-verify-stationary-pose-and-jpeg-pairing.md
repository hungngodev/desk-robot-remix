# DRR-070 · Verify stationary pose and JPEG pairing

**State at inventory snapshot** · Blocked

**Authority** · Verification

Exercise the supported entry point and record exact evidence. If a gap remains, hand it to the owner as one scoped change. Use GitHub CI or an isolated checkout when available.

## Before you start

- Check [draft PR #17](https://github.com/hungngodev/desk-robot-remix/pull/17) at the live head. Use the GitHub issue for this card to check ownership, claim the work and save your checkpoint. [Launch and issue instructions](../../README.md)
- Read [chat-mode source](../../shared/00_meta_instructions.md), [work isolation and claims](../../shared/01_agent_worktree_rules.md), [checkpoints and review](../../shared/02_continuation_and_review_loop.md), [push order](../../shared/03_parallel_push_queue.md), [ownership](../../shared/04_scope_and_ownership.md), [release evidence](../../shared/05_acceptance_criteria.md). The scoped paths and the current accepted guide apply to this card.
- Prerequisites · [DRR-049](../../tasks/sense/049-verify-jpeg-metadata-and-reject-replay.md), [DRR-066](../../tasks/map/066-verify-mac-pose-decoding-and-freshness.md)

Wait for the required deliverables from [DRR-049](../../tasks/sense/049-verify-jpeg-metadata-and-reject-replay.md), [DRR-066](../../tasks/map/066-verify-mac-pose-decoding-and-freshness.md). A matching recorded fixture can support early independent verification where the acceptance describes a replay.

## Scoped work and acceptance

[`code/laptop/src/desk_robot/spatial_bracket.py`](../../../code/laptop/src/desk_robot/spatial_bracket.py)

Replay stationary capture brackets and reject changed motion epoch, camera boot, identity or unreasonable age.

## Handoff

Record the reviewed SHA, source path or commit, the executed check and its result, and the exact open dependency or next action. Keep simulated evidence, exact-SHA CI and physical results distinct. Mark the issue verified only when this card’s acceptance is met. [Issue completion format](../../README.md#claim-verify-and-hand-off-in-github)

## Sources

[Tab 19 source index](../../coverage.md#tab-19) · [Guide 50](../../../docs/plans/spatial-first-unit/50-map-and-spatial-memory.md) · [MAC-04](../../coverage.md#audit-mac-04) · [T17 p15](../../coverage.md#t17-p15) · [T19 p15](../../coverage.md#t19-p15)
