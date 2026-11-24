# DRR-094 · Measure net charge and thermal faults

**State at inventory snapshot** · Blocked

**Authority** · Operator evidence

Prepare or inspect the procedure and later reconcile real operator evidence. The card itself grants no permission to energize, charge, move, purchase or perform a physical trial.

## Before you start

- Check [draft PR #17](https://github.com/hungngodev/desk-robot-remix/pull/17) at the live head. Use the GitHub issue for this card to check ownership, claim the work and save your checkpoint. [Launch and issue instructions](../../README.md)
- Read [chat-mode source](../../shared/00_meta_instructions.md), [work isolation and claims](../../shared/01_agent_worktree_rules.md), [checkpoints and review](../../shared/02_continuation_and_review_loop.md), [push order](../../shared/03_parallel_push_queue.md), [ownership](../../shared/04_scope_and_ownership.md), [release evidence](../../shared/05_acceptance_criteria.md). The scoped paths and the current accepted guide apply to this card.
- Prerequisites · [DRR-087](../../tasks/power-dock-station/087-resolve-the-exact-protected-1s-path.md), [DRR-089](../../tasks/power-dock-station/089-verify-signed-shunt-saturation-endpoints.md), [DRR-091](../../tasks/power-dock-station/091-verify-passive-dock-fit.md), [DRR-093](../../tasks/power-dock-station/093-verify-contact-and-seat-evidence.md)

A qualified assembly, the specified operator evidence, and authorization for that trial are required. Digital prerequisites still open: [DRR-087](../../tasks/power-dock-station/087-resolve-the-exact-protected-1s-path.md), [DRR-089](../../tasks/power-dock-station/089-verify-signed-shunt-saturation-endpoints.md), [DRR-091](../../tasks/power-dock-station/091-verify-passive-dock-fit.md), [DRR-093](../../tasks/power-dock-station/093-verify-contact-and-seat-evidence.md).

## Scoped work and acceptance

[`docs/hardware/charging-design-and-validation.md`](../../../docs/hardware/charging-design-and-validation.md)

Use the authorized staged electrical procedure and exact 1S stack. Record net pack current, seat, temperature and fault response.

## Handoff

Record the reviewed SHA, source path or commit, the executed check and its result, and the exact open dependency or next action. Keep simulated evidence, exact-SHA CI and physical results distinct. Mark the issue verified only when this card’s acceptance is met. [Issue completion format](../../README.md#claim-verify-and-hand-off-in-github)

## Sources

[Tab 21 source index](../../coverage.md#tab-21) · [Guide 70](../../../docs/plans/spatial-first-unit/70-fit-power-manipulation-and-dock.md) · [PWR-03](../../coverage.md#audit-pwr-03) · [E01](../../coverage.md#packet-e01) · [E03](../../coverage.md#packet-e03) · [T21 p16](../../coverage.md#t21-p16)
