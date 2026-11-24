# Record work when GitHub issue access is limited

Use this within the selected short task. Keep one receipt and one active claim.

1. Search all issue states for the card’s exact DRR ID and read its current comments and linked review threads. If a matching issue exists and is accessible, use it.
2. If the issue is absent and GitHub permits issue creation, open one issue for the card when it is ready to claim. Use the standard issue fields. Refresh the issue list before opening it. If creation races, use the earliest matching issue and link any duplicate only when it contains useful evidence.
3. If the worker can comment on PR #17 but cannot create or write the task issue, use a PR conversation comment beginning with the exact card ID and one of the statuses below. Include the source card link and starting SHA. Find existing task comments, replies and issue claims before publishing another record.
4. When the publication issue is absent and creation is unavailable, use a PR conversation comment labeled with the publication status. Check the issue and PR conversation for claims before publishing, even if workers started on different surfaces. When neither is writable, complete the selected read-only check with the available access. Keep any unpublished evidence in the final response and avoid editing or publishing through an unverified claim.

Use these stable labels and include test or commit links so any active worker can pick up the work.

```text
DRR-NNN CLAIM · slot, exact scope, starting SHA, expiry if writing
DRR-NNN CHECKPOINT · SHA, result, missing evidence, next action
DRR-NNN VERIFIED · verified output and checks, scope still open
DRR-NNN BLOCKED · exact missing input, owner, next action
PR #17 PUBLICATION CLAIM · slot, expected head SHA, commit, expiry
PR #17 PUBLICATION RESULT · pushed SHA, check link, terminal or pending
SLOT NN EXIT · verified cards, pending checks, released paths, next eligible cards
```

Before any edit, reread the earliest compatible active claims and current files. Use an isolated worktree or staging branch. Set an explicit expiry on a write or push claim, renew it with the checkpoint while still working, and check it again before editing or publishing. A later worker may adopt a released or expired claim only after confirming the live head, open review threads, and that nobody else has a newer live claim on the same files. A completed task requires its acceptance evidence even when close permissions are unavailable. [Issue fields and claim rules](../README.md#claim-verify-and-hand-off-in-github)
