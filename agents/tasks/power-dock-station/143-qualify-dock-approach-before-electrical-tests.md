# DRR-143 · Qualify dock approach before electrical tests

**State at inventory snapshot** · Blocked

**Authority** · Operator evidence

Prepare or inspect the procedure and later reconcile real operator evidence. The card itself grants no permission to energize, charge, move, purchase or perform a physical trial.

## Before you start

- Check [draft PR #17](https://github.com/hungngodev/desk-robot-remix/pull/17) at the live head. Use the GitHub issue for this card to check ownership, claim the work and save your checkpoint. [Launch and issue instructions](../../README.md)
- Read [chat-mode source](../../shared/00_meta_instructions.md), [work isolation and claims](../../shared/01_agent_worktree_rules.md), [checkpoints and review](../../shared/02_continuation_and_review_loop.md), [push order](../../shared/03_parallel_push_queue.md), [ownership](../../shared/04_scope_and_ownership.md), [release evidence](../../shared/05_acceptance_criteria.md). The scoped paths and the current accepted guide apply to this card.
- Prerequisites · [DRR-034](../../tasks/body/034-measure-the-swept-stopping-envelope.md), [DRR-091](../../tasks/power-dock-station/091-verify-passive-dock-fit.md), [DRR-092](../../tasks/power-dock-station/092-verify-tag-and-ir-provenance.md), [DRR-093](../../tasks/power-dock-station/093-verify-contact-and-seat-evidence.md)

A qualified assembly, the specified operator evidence, and authorization for that trial are required. Digital prerequisites still open: [DRR-034](../../tasks/body/034-measure-the-swept-stopping-envelope.md), [DRR-091](../../tasks/power-dock-station/091-verify-passive-dock-fit.md), [DRR-092](../../tasks/power-dock-station/092-verify-tag-and-ir-provenance.md), [DRR-093](../../tasks/power-dock-station/093-verify-contact-and-seat-evidence.md).

## Scoped work and acceptance

[`docs/guides/build.md`](../../../docs/guides/build.md)

Use the approved fixture and passive dock with contacts unpowered. Record bounded approach, seat and safe failure without blind recovery.

## Handoff

Record the reviewed SHA, source path or commit, the executed check and its result, and the exact open dependency or next action. Keep simulated evidence, exact-SHA CI and physical results distinct. Mark the issue verified only when this card’s acceptance is met. [Issue completion format](../../README.md#claim-verify-and-hand-off-in-github)

## Sources

[Tab 21 source index](../../coverage.md#tab-21) · [Guide 70](../../../docs/plans/spatial-first-unit/70-fit-power-manipulation-and-dock.md) · [DOCK-03](../../coverage.md#audit-dock-03) · [E02](../../coverage.md#packet-e02) · [T21 p16](../../coverage.md#t21-p16)
