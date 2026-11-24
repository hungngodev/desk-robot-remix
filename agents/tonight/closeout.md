# Closeout in the worker’s original run

Save evidence as work progresses. A platform cutoff can end the run before the final step.

Before ending voluntarily, the worker runs this check and executes any useful authorized step it finds.

- Check the latest PR head, each claimed card, and the reviews that affect its scope. Reconcile meaningful changes since the last checkpoint.
- Look for newly runnable child cards and unclaimed work across the full order. Compare exact paths and test scopes against live claims before helping another slot.
- Check any CI you own at the exact SHA. Keep pending, superseded and failed runs separate from verified results. Post the link and verification owner for follow-up.
- Post a slot exit checkpoint with verified cards, exact SHAs and evidence, pending checks, external blockers, paths released, and the next runnable cards. Use the task issue, publication issue or tagged PR comment. If GitHub writes are unavailable, provide the same fields in the final response.
- If you see no other active claim and have useful execution time, add a brief project summary to the publication record. Use the visible issue evidence. Leave uninspected and unresolved cards open.

The run can end when independent authorized work is exhausted, the remaining work requires specific external changes, or the execution limit arrives. A worker with a ready card should start it before closing out. [Full order](order.md), [Issue fallback](issue-recovery.md)
