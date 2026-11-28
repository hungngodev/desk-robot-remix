# DRR-131 · Bind purchase release to qualified source checks

**State at inventory snapshot** · Ready

**Authority** · Verification

Exercise the supported entry point and record exact evidence. If a gap remains, hand it to the owner as one scoped change. Use GitHub CI or an isolated checkout when available.

## Before you start

- Check [draft PR #17](https://github.com/hungngodev/desk-robot-remix/pull/17) at the live head. Use the GitHub issue for this card to check ownership, claim the work and save your checkpoint. [Launch and issue instructions](../../README.md)
- Read [chat-mode source](../../shared/00_meta_instructions.md), [work isolation and claims](../../shared/01_agent_worktree_rules.md), [checkpoints and review](../../shared/02_continuation_and_review_loop.md), [push order](../../shared/03_parallel_push_queue.md), [ownership](../../shared/04_scope_and_ownership.md), [release evidence](../../shared/05_acceptance_criteria.md). The scoped paths and the current accepted guide apply to this card.
- Prerequisites · Start independently from the current PR and scoped evidence.

Start at the live PR head and check existing claims and evidence.

## Scoped work and acceptance

[`code/tests/test_procurement_release_cli_gate.py`](../../../code/tests/test_procurement_release_cli_gate.py)

Fixture a qualified same-SHA run, wrong SHA and failed required job. Verify strict purchase release distinguishes them.

## Handoff

Record the reviewed SHA, source path or commit, the executed check and its result, and the exact open dependency or next action. Keep simulated evidence, exact-SHA CI and physical results distinct. Mark the issue verified only when this card’s acceptance is met. [Issue completion format](../../README.md#claim-verify-and-hand-off-in-github)

## Sources

[Tab 14 source index](../../coverage.md#tab-14) · [Guide 10](../../../docs/plans/spatial-first-unit/10-requirements-and-shopping.md) · [DOC-03](../../coverage.md#audit-doc-03) · [A04](../../coverage.md#packet-a04) · [B01](../../coverage.md#packet-b01) · [T15 p16](../../coverage.md#t15-p16)
