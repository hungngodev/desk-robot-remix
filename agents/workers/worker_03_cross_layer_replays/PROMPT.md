# Worker 03: Cross-Layer Replays

This parent prompt preserves the source excerpt. Choose a smaller assignment from the [task catalog](../../catalog.md).

## Assigned Scope
Task 3 from work order in Google Doc Tab 22.

## Verbatim Task Prompt
```markdown
3. **Run cross-layer replays.** Build normal-path tests around `pose` and fresh JPEG, same-origin stationary anchoring, object observation, controlled navigation, fresh arrival, user cut-in and STOP. Include wrong robot/session IDs, replayed or stale samples, pickup, moved or occluded targets, unsupported firmware, VAD during JPEG capture, cutoff/dock false positives, quiet mode and read-only station data. Inspect that a software denial returns the correct status and a physical safety loop still enforces its own gate. Verify that a new result cannot outlive its session or origin.
```

## Shared Operational Rules
Every worker must follow the shared operating rules before and during execution:
- [Meta Instructions](../../shared/00_meta_instructions.md)
- [Agent Worktree Rules](../../shared/01_agent_worktree_rules.md)
- [Continuation and Review Loop](../../shared/02_continuation_and_review_loop.md)
- [Parallel Push Queue Protocol](../../shared/03_parallel_push_queue.md)
- [Acceptance Criteria](../../shared/05_acceptance_criteria.md)

- [Scope and Ownership](../../shared/04_scope_and_ownership.md)
