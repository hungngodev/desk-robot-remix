# Historical verification snapshots

The JSON files in this directory are archived observations, not a live status feed.
Their original values and dates are retained; missing dates or source SHAs are
unknown, not reconstructed from today's clock. The evidence_scope and
current_head_verified fields identify historical evidence, not current-head
verification.

In particular, budget.json contains legacy planning allowances, not a current
landed quote or remaining purchasing allowance. doctor.json records an older
environment, not today's credentials, dependencies, or robot connectivity.
Build and simulation results do not qualify physical hardware.

For new evidence, from code/ run the current verifier with an unused output
path: `python scripts/verify_system.py --suite all --report /tmp/new-verification.json`.
Run `python scripts/check_budget.py` and `desk-robot doctor` in the configured
environment. Use the verifier's exit status together with both checkout snapshots
and stage results; a passing stage alone is not an exact-commit pass.

For shared-branch CI, check PR #17's actual head and its own required jobs.
See [verification.md](../verification.md). Physical acceptance and procurement
remain subject to independent release gates. Do not overwrite archived reports
with current receipts.
