# All launch batches and exact prompts

This is the complete copy-paste runbook. It links directly to all **192 card prompts**. Launch up to ten fresh chats at a time. There are **16 digital batches** for 158 cards and **6 conditional batches** for 27 cards needing operator evidence. The remaining seven cards have an existing verified or deferred disposition.

## Run the book from start to finish

1. Open [Batch 01](batch-01.md). Copy each box into a separate fresh Chat-mode chat. Each worker attempts one card and one small check, posts the result in GitHub, then stops.
2. As chats end, use the next numbered batch. A batch is an order of launch candidates. Check the prerequisites listed above each box against the task issue or tagged PR receipt. Leave an item open if its evidence is missing and launch an already eligible item from a later batch to fill the slot. Skip the slot later if its check is already done.
3. Treat a partial receipt as proof of only that check. A fresh chat can perform the named next distinct check on the same card. A passed digital check is not a receipt for physical acceptance. GitHub holds the handoff between short runs.
4. If CI is pending or a prepared change needs publication, use the [short follow-up prompts](#ci-and-publication) in fresh chats. They cover one result or change each. Once the evidence is accepted, continue with the dependent items.
5. Launch conditional batches as relevant operator evidence arrives. Leave missing evidence visible on the issue. Use the [existing dispositions](#already-verified-or-deferred) for cards that need no new launch at the catalog snapshot.

A chat cannot start another chat. You launch each box yourself. A cap of ten **active** chats allows successive batches. A cap of ten **total** launches covers ten small checks.

[Download the complete Markdown runbook with every copy box in one file](https://raw.githubusercontent.com/hungngodev/desk-robot-remix/6255d0524deacf980dc0d2b224e209b853cee282/agents/tonight/batches.md).

## Jump to a batch

| Batch | Prompts | Launch condition |
| --- | ---: | --- |
| [Batch 01](batch-01.md) | 10 | Digital · prerequisite evidence |
| [Batch 02](batch-02.md) | 10 | Digital · prerequisite evidence |
| [Batch 03](batch-03.md) | 10 | Digital · prerequisite evidence |
| [Batch 04](batch-04.md) | 10 | Digital · prerequisite evidence |
| [Batch 05](batch-05.md) | 10 | Digital · prerequisite evidence |
| [Batch 06](batch-06.md) | 10 | Digital · prerequisite evidence |
| [Batch 07](batch-07.md) | 10 | Digital · prerequisite evidence |
| [Batch 08](batch-08.md) | 10 | Digital · prerequisite evidence |
| [Batch 09](batch-09.md) | 10 | Digital · prerequisite evidence |
| [Batch 10](batch-10.md) | 10 | Digital · prerequisite evidence |
| [Batch 11](batch-11.md) | 10 | Digital · prerequisite evidence |
| [Batch 12](batch-12.md) | 10 | Digital · prerequisite evidence |
| [Batch 13](batch-13.md) | 10 | Digital · prerequisite evidence |
| [Batch 14](batch-14.md) | 10 | Digital · prerequisite evidence |
| [Batch 15](batch-15.md) | 10 | Digital · prerequisite evidence |
| [Batch 16](batch-16.md) | 8 | Digital · prerequisite evidence |
| [Batch 17](batch-17.md) | 10 | Conditional · operator evidence |
| [Batch 18](batch-18.md) | 10 | Conditional · operator evidence |
| [Batch 19](batch-19.md) | 4 | Conditional · operator evidence |
| [Batch 20](batch-20.md) | 1 | Conditional · operator evidence |
| [Batch 21](batch-21.md) | 1 | Conditional · operator evidence |
| [Batch 22](batch-22.md) | 1 | Conditional · operator evidence |

## CI and publication

### Check one CI result

```text
Work in Chat mode on hungngodev/desk-robot-remix and draft PR #17. Choose one open DRR issue or tagged PR publication comment with a pending CI receipt. Check its exact published SHA and workflow once. I authorize you to post that result to the existing GitHub issue or PR conversation.

If CI passed for the receipt SHA, link the exact checks and mark only the acceptance that this software evidence proves. If CI failed, record one failed check with its link. If the SHA was superseded, record that and the current SHA separately. If it is still running, return the exact pending link. If no receipt is available, say so. Finish after this one lookup. Do not wait for CI, edit robot code, push a change, or claim another card.
```

### Publish one prepared change

```text
Chat mode on hungngodev/desk-robot-remix draft PR #17. Select exactly one prepared implementation change already recorded in a DRR issue or tagged PR publication receipt. I authorize publishing this one ready change through the existing shared publication queue. Verify exact scope, branch or patch, review state, current head and completed prerequisite checks. Follow AGENTS.md, check both claim surfaces and use a non-forced update against the expected head. If the slot is busy, required evidence is missing, or the patch conflicts with the live head, report the precise blocker and stop. If it publishes, record the new SHA and check link on the existing receipt, release the publication claim as directed, and stop. Keep the PR draft.
```

## Already verified or deferred

Keep these seven dispositions unless fresh evidence or an accepted scope change makes an item actionable. The original copy block remains available for each card.

### DRR-001

**Pin the current PR and base revisions** · Verification · Already verified.

Prerequisites · Independent. [Card](../tasks/repository/001-pin-the-current-pr-and-base-revisions.md)

```text
Chat mode. Work only on DRR-001 in hungngodev/desk-robot-remix draft PR #17.
Card: https://github.com/hungngodev/desk-robot-remix/blob/impl/mac-hardware-safety-preflight-2026-11-10/agents/tasks/repository/001-pin-the-current-pr-and-base-revisions.md
Small check: Use the card’s acceptance to choose the first uncovered small check in this scope. Record the live draft PR, full head and base SHAs and expected root tree. Compare them with the checkout before trusting evidence.
Search for the exact DRR issue and verify live head, prerequisites and claims. I authorize opening or updating this card’s issue or posting its tagged PR receipt if issue access is unavailable. Use a next distinct check already named in an incomplete card’s receipt, if available. If the remaining check is verified, claimed, or blocked, record the exact reason and end.
Run one read-only review or verification check within the card’s scope. Cite actual evidence and record whether you ran the check or inspected it.
Post the full SHA, one result, evidence, remaining acceptance, and the exact next distinct check or blocker. Mark the card verified only if all its acceptance has evidence. Release the claim and stop after this result. The operator launches every new run.
```

### DRR-005

**Check required CI jobs at one SHA** · Verification · Already verified.

Prerequisites · Independent. [Card](../tasks/repository/005-check-required-ci-jobs-at-one-sha.md)

```text
Chat mode. Work only on DRR-005 in hungngodev/desk-robot-remix draft PR #17.
Card: https://github.com/hungngodev/desk-robot-remix/blob/impl/mac-hardware-safety-preflight-2026-11-10/agents/tasks/repository/005-check-required-ci-jobs-at-one-sha.md
Small check: Use the card’s acceptance to choose the first uncovered small check in this scope. Match each required job to one current PR SHA. Record links and distinguish passing, failing, pending, replaced and unavailable checks.
Search for the exact DRR issue and verify live head, prerequisites and claims. I authorize opening or updating this card’s issue or posting its tagged PR receipt if issue access is unavailable. Use a next distinct check already named in an incomplete card’s receipt, if available. If the remaining check is verified, claimed, or blocked, record the exact reason and end.
Run one read-only review or verification check within the card’s scope. Cite actual evidence and record whether you ran the check or inspected it.
Post the full SHA, one result, evidence, remaining acceptance, and the exact next distinct check or blocker. Mark the card verified only if all its acceptance has evidence. Release the claim and stop after this result. The operator launches every new run.
```

### DRR-009

**Record the approved publishing visibility** · Verification · Already verified.

Prerequisites · Independent. [Card](../tasks/repository/009-record-the-approved-publishing-visibility.md)

```text
Chat mode. Work only on DRR-009 in hungngodev/desk-robot-remix draft PR #17.
Card: https://github.com/hungngodev/desk-robot-remix/blob/impl/mac-hardware-safety-preflight-2026-11-10/agents/tasks/repository/009-record-the-approved-publishing-visibility.md
Small check: Use the card’s acceptance to choose the first uncovered small check in this scope. Verify public PR #17 is the approved destination for the organization commit. Keep the Google Doc address and scope beyond the approved raw Tab 22 export local.
Search for the exact DRR issue and verify live head, prerequisites and claims. I authorize opening or updating this card’s issue or posting its tagged PR receipt if issue access is unavailable. Use a next distinct check already named in an incomplete card’s receipt, if available. If the remaining check is verified, claimed, or blocked, record the exact reason and end.
Run one read-only review or verification check within the card’s scope. Cite actual evidence and record whether you ran the check or inspected it.
Post the full SHA, one result, evidence, remaining acceptance, and the exact next distinct check or blocker. Mark the card verified only if all its acceptance has evidence. Release the claim and stop after this result. The operator launches every new run.
```

### DRR-045

**Reproduce the pinned Sense build** · Verification · Already verified.

Prerequisites · Independent. [Card](../tasks/sense/045-reproduce-the-pinned-sense-build.md)

```text
Chat mode. Work only on DRR-045 in hungngodev/desk-robot-remix draft PR #17.
Card: https://github.com/hungngodev/desk-robot-remix/blob/impl/mac-hardware-safety-preflight-2026-11-10/agents/tasks/sense/045-reproduce-the-pinned-sense-build.md
Small check: Use the card’s acceptance to choose the first uncovered small check in this scope. Verify the exact overlay and ESP-IDF target on the selected SHA. Report an unavailable toolchain or build failure at the failing step.
Search for the exact DRR issue and verify live head, prerequisites and claims. I authorize opening or updating this card’s issue or posting its tagged PR receipt if issue access is unavailable. Use a next distinct check already named in an incomplete card’s receipt, if available. If the remaining check is verified, claimed, or blocked, record the exact reason and end.
Run one read-only review or verification check within the card’s scope. Cite actual evidence and record whether you ran the check or inspected it.
Post the full SHA, one result, evidence, remaining acceptance, and the exact next distinct check or blocker. Mark the card verified only if all its acceptance has evidence. Release the claim and stop after this result. The operator launches every new run.
```

### DRR-132

**Reconcile historical BME688 assertions** · Verification · Already verified.

Prerequisites · Independent. [Card](../tasks/power-dock-station/132-reconcile-historical-bme688-assertions.md)

```text
Chat mode. Work only on DRR-132 in hungngodev/desk-robot-remix draft PR #17.
Card: https://github.com/hungngodev/desk-robot-remix/blob/impl/mac-hardware-safety-preflight-2026-11-10/agents/tasks/power-dock-station/132-reconcile-historical-bme688-assertions.md
Small check: Use the card’s acceptance to choose the first uncovered small check in this scope. Run the current station profile case against its actual completed-conversion behavior. Determine whether the historical assertions already landed.
Search for the exact DRR issue and verify live head, prerequisites and claims. I authorize opening or updating this card’s issue or posting its tagged PR receipt if issue access is unavailable. Use a next distinct check already named in an incomplete card’s receipt, if available. If the remaining check is verified, claimed, or blocked, record the exact reason and end.
Run one read-only review or verification check within the card’s scope. Cite actual evidence and record whether you ran the check or inspected it.
Post the full SHA, one result, evidence, remaining acceptance, and the exact next distinct check or blocker. Mark the card verified only if all its acceptance has evidence. Release the claim and stop after this result. The operator launches every new run.
```

### DRR-189

**Resolve purchase role nfc_game_props** · Review only · Superseded / deferred.

Prerequisites · Independent. [Card](../tasks/shopping/189-resolve-purchase-role-nfc-game-props.md)

```text
Chat mode. Work only on DRR-189 in hungngodev/desk-robot-remix draft PR #17.
Card: https://github.com/hungngodev/desk-robot-remix/blob/impl/mac-hardware-safety-preflight-2026-11-10/agents/tasks/shopping/189-resolve-purchase-role-nfc-game-props.md
Small check: Use the card’s acceptance to choose the first uncovered small check in this scope. Verify the selected versus deferred token paths against the current station scope. Check interoperability with the reader and token quantities if selected. Attach exact supplier SKU or inspected-stock evidence, quantity, landed price or unknown state, and the ownership link. Record a specific blocker for any missing choice.
Search for the exact DRR issue and verify live head, prerequisites and claims. I authorize opening or updating this card’s issue or posting its tagged PR receipt if issue access is unavailable. Use a next distinct check already named in an incomplete card’s receipt, if available. If the remaining check is verified, claimed, or blocked, record the exact reason and end.
Run one read-only review or verification check within the card’s scope. Cite actual evidence and record whether you ran the check or inspected it.
Post the full SHA, one result, evidence, remaining acceptance, and the exact next distinct check or blocker. Mark the card verified only if all its acceptance has evidence. Release the claim and stop after this result. The operator launches every new run.
```

### DRR-190

**Resolve purchase role amg8833** · Review only · Superseded / deferred.

Prerequisites · Independent. [Card](../tasks/shopping/190-resolve-purchase-role-amg8833.md)

```text
Chat mode. Work only on DRR-190 in hungngodev/desk-robot-remix draft PR #17.
Card: https://github.com/hungngodev/desk-robot-remix/blob/impl/mac-hardware-safety-preflight-2026-11-10/agents/tasks/shopping/190-resolve-purchase-role-amg8833.md
Small check: Use the card’s acceptance to choose the first uncovered small check in this scope. Verify current deferred-optional status and compatible IR array family. Produce an order line only if the operator selects the role. Attach exact supplier SKU or inspected-stock evidence, quantity, landed price or unknown state, and the ownership link. Record a specific blocker for any missing choice.
Search for the exact DRR issue and verify live head, prerequisites and claims. I authorize opening or updating this card’s issue or posting its tagged PR receipt if issue access is unavailable. Use a next distinct check already named in an incomplete card’s receipt, if available. If the remaining check is verified, claimed, or blocked, record the exact reason and end.
Run one read-only review or verification check within the card’s scope. Cite actual evidence and record whether you ran the check or inspected it.
Post the full SHA, one result, evidence, remaining acceptance, and the exact next distinct check or blocker. Mark the card verified only if all its acceptance has evidence. Release the claim and stop after this result. The operator launches every new run.
```
