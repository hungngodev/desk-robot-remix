# DRR-034 · Measure the swept stopping envelope

**State at inventory snapshot** · Blocked

**Authority** · Operator evidence

Prepare or inspect the procedure and later reconcile real operator evidence. The card itself grants no permission to energize, charge, move, purchase or perform a physical trial.

## Before you start

- Check [draft PR #17](https://github.com/hungngodev/desk-robot-remix/pull/17) at the live head. Use the GitHub issue for this card to check ownership, claim the work and save your checkpoint. [Launch and issue instructions](../../README.md)
- Read [chat-mode source](../../shared/00_meta_instructions.md), [work isolation and claims](../../shared/01_agent_worktree_rules.md), [checkpoints and review](../../shared/02_continuation_and_review_loop.md), [push order](../../shared/03_parallel_push_queue.md), [ownership](../../shared/04_scope_and_ownership.md), [release evidence](../../shared/05_acceptance_criteria.md). The scoped paths and the current accepted guide apply to this card.
- Prerequisites · [DRR-028](../../tasks/body/028-verify-the-four-downward-lanes.md), [DRR-029](../../tasks/body/029-verify-forward-ranging.md), [DRR-031](../../tasks/body/031-exercise-stale-invalid-and-missing-ranging.md), [DRR-032](../../tasks/body/032-exercise-bumper-and-mux-faults.md), [DRR-090](../../tasks/power-dock-station/090-prove-independent-cutoff-under-cpu-stall.md)

A qualified assembly, the specified operator evidence, and authorization for that trial are required. Digital prerequisites still open: [DRR-028](../../tasks/body/028-verify-the-four-downward-lanes.md), [DRR-029](../../tasks/body/029-verify-forward-ranging.md), [DRR-031](../../tasks/body/031-exercise-stale-invalid-and-missing-ranging.md), [DRR-032](../../tasks/body/032-exercise-bumper-and-mux-faults.md), [DRR-090](../../tasks/power-dock-station/090-prove-independent-cutoff-under-cpu-stall.md).

## Scoped work and acceptance

[`docs/hardware/2026-11-17-vl53l0x-cliff-geometry-release.md`](../../../docs/hardware/2026-11-17-vl53l0x-cliff-geometry-release.md)

On the authorized tether/catch fixture record actual lanes, surfaces, detection, coast and swept turns. Bound margin before footprint reaches an edge.

## Handoff

Record the reviewed SHA, source path or commit, the executed check and its result, and the exact open dependency or next action. Keep simulated evidence, exact-SHA CI and physical results distinct. Mark the issue verified only when this card’s acceptance is met. [Issue completion format](../../README.md#claim-verify-and-hand-off-in-github)

## Sources

[Tab 16 source index](../../coverage.md#tab-16) · [Guide 20](../../../docs/plans/spatial-first-unit/20-body-safety-and-odometry.md) · [BODY-07](../../coverage.md#audit-body-07) · [C03](../../coverage.md#packet-c03) · [T16 p17](../../coverage.md#t16-p17) · [T21 p15](../../coverage.md#t21-p15)
