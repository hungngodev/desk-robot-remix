# DRR-001 · Pin the current PR and base revisions

**State at inventory snapshot** · Already verified

**Authority** · Verification

Exercise the supported entry point and record exact evidence. If a gap remains, hand it to the owner as one scoped change. Use GitHub CI or an isolated checkout when available.

## Before you start

- Check [draft PR #17](https://github.com/hungngodev/desk-robot-remix/pull/17) at the live head. Use the GitHub issue for this card to check ownership, claim the work and save your checkpoint. [Launch and issue instructions](../../README.md)
- Read [chat-mode source](../../shared/00_meta_instructions.md), [work isolation and claims](../../shared/01_agent_worktree_rules.md), [checkpoints and review](../../shared/02_continuation_and_review_loop.md), [push order](../../shared/03_parallel_push_queue.md), [ownership](../../shared/04_scope_and_ownership.md), [release evidence](../../shared/05_acceptance_criteria.md). The scoped paths and the current accepted guide apply to this card.
- Prerequisites · Start independently from the current PR and scoped evidence.

[Live PR snapshot](https://github.com/hungngodev/desk-robot-remix/pull/17/commits/79dc1dc509b5891c2a7744e5260d9c8ff05ee628) recorded head 79dc1dc5, base aa7fb7de, draft status and intact root tree. Refresh this snapshot at launch.

## Scoped work and acceptance

[`.github/workflows/host-verification.yml`](../../../.github/workflows/host-verification.yml)

Record the live draft PR, full head and base SHAs and expected root tree. Compare them with the checkout before trusting evidence.

## Handoff

Record the reviewed SHA, source path or commit, the executed check and its result, and the exact open dependency or next action. Keep simulated evidence, exact-SHA CI and physical results distinct. Mark the issue verified only when this card’s acceptance is met. [Issue completion format](../../README.md#claim-verify-and-hand-off-in-github)

## Sources

[Tab 22 source index](../../coverage.md#tab-22) · [Guide 90](../../../docs/plans/spatial-first-unit/90-integration-and-release-evidence.md) · [DOC-05](../../coverage.md#audit-doc-05) · [A01](../../coverage.md#packet-a01) · [T22 p12](../../coverage.md#t22-p12)
