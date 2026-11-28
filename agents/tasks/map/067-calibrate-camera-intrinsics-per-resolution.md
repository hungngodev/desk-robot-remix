# DRR-067 · Calibrate camera intrinsics per resolution

**State at inventory snapshot** · Blocked

**Authority** · Operator evidence

Prepare or inspect the procedure and later reconcile real operator evidence. The card itself grants no permission to energize, charge, move, purchase or perform a physical trial.

## Before you start

- Check [draft PR #17](https://github.com/hungngodev/desk-robot-remix/pull/17) at the live head. Use the GitHub issue for this card to check ownership, claim the work and save your checkpoint. [Launch and issue instructions](../../README.md)
- Read [chat-mode source](../../shared/00_meta_instructions.md), [work isolation and claims](../../shared/01_agent_worktree_rules.md), [checkpoints and review](../../shared/02_continuation_and_review_loop.md), [push order](../../shared/03_parallel_push_queue.md), [ownership](../../shared/04_scope_and_ownership.md), [release evidence](../../shared/05_acceptance_criteria.md). The scoped paths and the current accepted guide apply to this card.
- Prerequisites · [DRR-051](../../tasks/sense/051-measure-optical-capture-lag.md)

A qualified assembly, the specified operator evidence, and authorization for that trial are required. Digital prerequisites still open: [DRR-051](../../tasks/sense/051-measure-optical-capture-lag.md).

## Scoped work and acceptance

[`code/scripts/calibrate_dock_camera.py`](../../../code/scripts/calibrate_dock_camera.py)

Use measured checkerboard observations for the identified lens and resolution. Record calibration identity and residuals.

## Handoff

Record the reviewed SHA, source path or commit, the executed check and its result, and the exact open dependency or next action. Keep simulated evidence, exact-SHA CI and physical results distinct. Mark the issue verified only when this card’s acceptance is met. [Issue completion format](../../README.md#claim-verify-and-hand-off-in-github)

## Sources

[Tab 19 source index](../../coverage.md#tab-19) · [Guide 50](../../../docs/plans/spatial-first-unit/50-map-and-spatial-memory.md) · [T17 p16](../../coverage.md#t17-p16) · [T19 p14](../../coverage.md#t19-p14)
