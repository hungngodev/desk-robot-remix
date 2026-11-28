# Collect one finished CI result

Copy this prompt into a fresh Chat-mode worker when task issues have CI evidence to collect.

```text
Work in Chat mode on hungngodev/desk-robot-remix and draft PR #17. Choose one open DRR issue or tagged PR publication comment with a pending CI receipt. Check its exact published SHA and workflow once. I authorize you to post that result to the existing GitHub issue or PR conversation.

If CI passed for the receipt SHA, link the exact checks and mark only the acceptance that this software evidence proves. If CI failed, record one failed check with its link. If the SHA was superseded, record that and the current SHA separately. If it is still running, return the exact pending link. If no receipt is available, say so. Finish after this one lookup. Do not wait for CI, edit robot code, push a change, or claim another card.
```
