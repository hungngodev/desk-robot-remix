# DRR-051 · Measure optical capture lag

**State at inventory snapshot** · Blocked

**Authority** · Operator evidence

Prepare or inspect the procedure and later reconcile real operator evidence. The card itself grants no permission to energize, charge, move, purchase or perform a physical trial.

## Before you start

- Check [draft PR #17](https://github.com/hungngodev/desk-robot-remix/pull/17) at the live head. Use the GitHub issue for this card to check ownership, claim the work and save your checkpoint. [Launch and issue instructions](../../README.md)
- Read [chat-mode source](../../shared/00_meta_instructions.md), [work isolation and claims](../../shared/01_agent_worktree_rules.md), [checkpoints and review](../../shared/02_continuation_and_review_loop.md), [push order](../../shared/03_parallel_push_queue.md), [ownership](../../shared/04_scope_and_ownership.md), [release evidence](../../shared/05_acceptance_criteria.md). The scoped paths and the current accepted guide apply to this card.
- Prerequisites · [DRR-049](../../tasks/sense/049-verify-jpeg-metadata-and-reject-replay.md), [DRR-050](../../tasks/sense/050-verify-shared-camera-ownership-and-buffer-release.md)

A qualified assembly, the specified operator evidence, and authorization for that trial are required. Digital prerequisites still open: [DRR-049](../../tasks/sense/049-verify-jpeg-metadata-and-reject-replay.md), [DRR-050](../../tasks/sense/050-verify-shared-camera-ownership-and-buffer-release.md).

## Scoped work and acceptance

[`code/scripts/bench_head_camera.py`](../../../code/scripts/bench_head_camera.py)

Use a changing target at known timing on the assembled Sense. Record resolution, load, optical evidence and a usable capture-lag bound.

## Handoff

Record the reviewed SHA, source path or commit, the executed check and its result, and the exact open dependency or next action. Keep simulated evidence, exact-SHA CI and physical results distinct. Mark the issue verified only when this card’s acceptance is met. [Issue completion format](../../README.md#claim-verify-and-hand-off-in-github)

## Sources

[Tab 17 source index](../../coverage.md#tab-17) · [Guide 30](../../../docs/plans/spatial-first-unit/30-sense-camera-and-interface.md) · [HEAD-04](../../coverage.md#audit-head-04) · [D03](../../coverage.md#packet-d03) · [T17 p16](../../coverage.md#t17-p16) · [T19 p14](../../coverage.md#t19-p14)
