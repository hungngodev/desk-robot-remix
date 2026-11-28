# Receipt for one short task

Post this in the selected task issue or as a tagged PR comment.

```text
DRR card and slot:
Reviewed full SHA:
One check performed:
Observed outcome and evidence link:
Card state: verified / partial / blocked / waiting for CI
Remaining acceptance or exact next small check:
Missing input and responsible owner, if blocked:
Prepared commit or branch, if any:
CI SHA and check URL, if pending:
Claim released:
```

Use **verified** when the card’s whole acceptance has evidence. Use **partial** when this run proved one check within a larger card. Distinguish observed code or fixture behavior from real operator evidence. Include the exact SHA and link for a check started but still pending.

Once the receipt is recorded, end the run. If GitHub writes are unavailable, return the same receipt in chat. A fresh worker reads it to select the next small check. [Issue fallback](issue-recovery.md)
