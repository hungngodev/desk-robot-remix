# DRR-132 · Reconcile historical BME688 assertions

**State at inventory snapshot** · Already verified

**Authority** · Verification

Exercise the supported entry point and record exact evidence. If a gap remains, hand it to the owner as one scoped change. Use GitHub CI or an isolated checkout when available.

## Before you start

- Check [draft PR #17](https://github.com/hungngodev/desk-robot-remix/pull/17) at the live head. Use the GitHub issue for this card to check ownership, claim the work and save your checkpoint. [Launch and issue instructions](../../README.md)
- Read [chat-mode source](../../shared/00_meta_instructions.md), [work isolation and claims](../../shared/01_agent_worktree_rules.md), [checkpoints and review](../../shared/02_continuation_and_review_loop.md), [push order](../../shared/03_parallel_push_queue.md), [ownership](../../shared/04_scope_and_ownership.md), [release evidence](../../shared/05_acceptance_criteria.md). The scoped paths and the current accepted guide apply to this card.
- Prerequisites · Start independently from the current PR and scoped evidence.

[Current station tests](https://github.com/hungngodev/desk-robot-remix/blob/79dc1dc509b5891c2a7744e5260d9c8ff05ee628/code/tests/test_room_station_full_profile.py) passed as part of the 78 focused local tests on 79dc1dc5. The tests cover completed conversion and rejection of old gas data. Installed measurements remain open.

## Scoped work and acceptance

[`code/tests/test_room_station_full_profile.py`](../../../code/tests/test_room_station_full_profile.py)

Run the current station profile case against its actual completed-conversion behavior. Determine whether the historical assertions already landed.

## Handoff

Record the reviewed SHA, source path or commit, the executed check and its result, and the exact open dependency or next action. Keep simulated evidence, exact-SHA CI and physical results distinct. Mark the issue verified only when this card’s acceptance is met. [Issue completion format](../../README.md#claim-verify-and-hand-off-in-github)

## Sources

[Tab 09 source index](../../coverage.md#tab-09) · [Guide 70](../../../docs/plans/spatial-first-unit/70-fit-power-manipulation-and-dock.md) · [DOC-01](../../coverage.md#audit-doc-01) · [E04](../../coverage.md#packet-e04) · [T21 p17](../../coverage.md#t21-p17)
