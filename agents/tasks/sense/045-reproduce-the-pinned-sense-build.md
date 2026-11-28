# DRR-045 · Reproduce the pinned Sense build

**State at inventory snapshot** · Already verified

**Authority** · Verification

Exercise the supported entry point and record exact evidence. If a gap remains, hand it to the owner as one scoped change. Use GitHub CI or an isolated checkout when available.

## Before you start

- Check [draft PR #17](https://github.com/hungngodev/desk-robot-remix/pull/17) at the live head. Use the GitHub issue for this card to check ownership, claim the work and save your checkpoint. [Launch and issue instructions](../../README.md)
- Read [chat-mode source](../../shared/00_meta_instructions.md), [work isolation and claims](../../shared/01_agent_worktree_rules.md), [checkpoints and review](../../shared/02_continuation_and_review_loop.md), [push order](../../shared/03_parallel_push_queue.md), [ownership](../../shared/04_scope_and_ownership.md), [release evidence](../../shared/05_acceptance_criteria.md). The scoped paths and the current accepted guide apply to this card.
- Prerequisites · Start independently from the current PR and scoped evidence.

[Sense ESP-IDF job](https://github.com/hungngodev/desk-robot-remix/actions/runs/45339777773/job/138260368383) passed on 79dc1dc5. This is compile evidence for that SHA.

## Scoped work and acceptance

[`code/firmware/head`](../../../code/firmware/head) · [`.github/workflows/host-verification.yml`](../../../.github/workflows/host-verification.yml)

Verify the exact overlay and ESP-IDF target on the selected SHA. Report an unavailable toolchain or build failure at the failing step.

## Handoff

Record the reviewed SHA, source path or commit, the executed check and its result, and the exact open dependency or next action. Keep simulated evidence, exact-SHA CI and physical results distinct. Mark the issue verified only when this card’s acceptance is met. [Issue completion format](../../README.md#claim-verify-and-hand-off-in-github)

## Sources

[Tab 17 source index](../../coverage.md#tab-17) · [Guide 30](../../../docs/plans/spatial-first-unit/30-sense-camera-and-interface.md) · [HEAD-06](../../coverage.md#audit-head-06) · [A03](../../coverage.md#packet-a03) · [D04](../../coverage.md#packet-d04) · [T17 p13](../../coverage.md#t17-p13)
