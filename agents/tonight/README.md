# Run the Desk Robot Remix backlog tonight

Use the ten numbered prompts below. Copy the text inside each prompt’s box into a separate Chat-mode worker. Each prompt already names its first card and the worker’s queue. Keep at most ten workers active. Reuse the same ten prompts throughout the night.

The goal is to verify every actionable digital card the workers can reach, then account for every other card with evidence or a named dependency. The audited catalog has 192 cards. Of these, 27 require operator evidence, including measurements or real checkout records. Those cards can have their procedures prepared tonight, and their acceptance stays open until the relevant evidence exists. [Task catalog](../catalog.md), [Draft PR #17](https://github.com/hungngodev/desk-robot-remix/pull/17)

## First launch

| Copy this prompt | First card | What the worker covers after it |
| --- | --- | --- |
| [01 · PR evidence and review](01-pr-evidence-and-review.md) | DRR-003 · Match open review threads to current behavior | Repository evidence, selected independent reviews, and the one-time publication queue setup |
| [02 · Shopping and stock](02-shopping-and-stock.md) | DRR-013 · Find proven same-feature sourcing | Inventory, exact parts, landed cost, purchase scope and delivered cart |
| [03 · Body and odometry](03-body-and-odometry.md) | DRR-040 · Verify the body pose fixture | WROOM safety, wheel observations, jaw feedback and controlled movement prerequisites |
| [04 · Sense head and camera](04-sense-head-and-camera.md) | DRR-049 · Check JPEG metadata and reject replay | Head bridge, camera, audio device and overlay coexistence |
| [05 · Voice and behavior](05-voice-and-behavior.md) | DRR-055 · Verify human VAD priority | Barge-in, stale playback, quiet, tools, group speech and initiative |
| [06 · Map and memory](06-map-and-memory.md) | DRR-068 · Verify ground projection | Pose ingest, anchors, grid, persistence, isolation and recency |
| [07 · Object recall and navigation](07-object-recall-and-navigation.md) | DRR-077 · Compare local detector candidates | Target evidence, bounded search, safe routes and arrival |
| [08 · Power, dock and station](08-power-dock-and-station.md) | DRR-087 · Resolve the protected 1S path | Power, local cutoff, dock evidence and shared station |
| [09 · CAD and builder](09-cad-and-builder.md) | DRR-098 · Verify the CAD originals and licenses | Fit, prints, wiring, flashing and the assembly guide |
| [10 · Integration and replays](10-integration-and-replays.md) | DRR-153 · Review the body/Sense/Mac pose boundary | Shared entry points, end-to-end replays and integrated evidence |

The starter cards can run in parallel. Paste 01 first, then 02–10 in separate chats. Workers can inspect and test while worker 01 opens the shared publication issue. Each worker opens or reuses its own task issue as it starts a card. Give worker 01 access to create and comment on repository Issues. If a slot can comment but cannot open an issue, use the [issue access and recovery prompt](issue-recovery.md) in worker 01’s existing chat. [Per-slot card order](order.md)

## Run order after the first launch

1. **First pass.** Workers start their named cards after checking the live head and active claims. Each worker keeps moving down its own order once it verifies an item. A card printed later in the list can start sooner if its prerequisites are available. A card printed first can be skipped if blocked.
2. **As evidence arrives.** Check for stopped workers after the first 30 minutes, then about once an hour. Keep active slots running. When a worker finishes or stops, use the table below. Recheck dependency issues when a fixture, commit, or receipt lands, including after an unrelated card finishes.
3. **When a code change is ready.** Prepare changes in isolated branches or worktrees. Verified changes share one publication queue on PR #17. Workers can bundle several independently verified small changes that already belong to the same claim and review scope. Let current required CI settle before the next routine push, and keep unrelated work moving during the wait.
4. **Final pass.** About an hour before your own cutoff, paste the [nightly closeout prompt](closeout.md) into worker 01’s existing chat. It checks unresolved work and pulls together a single GitHub status summary. Keep the other nine slots on executable cards. Before stopping, each slot posts its last verified SHA, unfinished claims and exact next action.

### When to rerun a prompt

| What you see | What you paste |
| --- | --- |
| A worker stopped after a finding, test, or commit and lists work it can do | Paste **that same numbered prompt** into the same chat. If the chat ended, use a new chat for the same slot. |
| A worker paused on pending CI | If it is still working, let it continue. If it stopped, paste the same prompt. It reads the existing issue, checks the exact SHA, and advances other available cards. |
| A worker says a dependency is missing and its issue now has the fixture or receipt | Rerun the **slot that owns the dependent card** using its same prompt. The slot reads the evidence and selects the now-ready card. |
| A worker says its issue is done | Rerun the same slot if it stopped and the order still has available items. The worker skips the verified card and continues. |
| A worker reached its runtime limit | Start a new chat with the **same slot prompt** once the old run has ended. It resumes from GitHub. Keep one active worker per slot. |
| A worker can see GitHub but cannot create its issue | Paste [issue recovery](issue-recovery.md) into slot 01 with the worker’s stopping message. Retry the original slot after the issue exists. |
| A worker needs an actual hardware trial, supplier receipt, access or a decision | Let it record the exact requirement and advance other work. Rerun it after the missing evidence or access is provided. |
| All useful work in that slot is waiting on external inputs | Leave the checks and blocked issues visible. Use another slot that has ready work, or use the closeout prompt to identify a useful unclaimed card. |

## Follow evidence through the main dependencies

- **Pose and map.** DRR-040 publishes the body fixture. DRR-047 in slot 04 and DRR-066 in slot 06 can then run in parallel. DRR-109 in slot 10 can use both results. DRR-070 also needs DRR-049 and DRR-066. DRR-071 needs DRR-068 and DRR-070.
- **Shopping.** DRR-013 supplies comparison evidence for DRR-014. Scope and pricing proceed in parallel. DRR-020 waits for verified stock allocation, pack logic and quotes. DRR-121 needs the complete exact part decisions and real checkout evidence.
- **Voice.** DRR-055 can feed DRR-057 and DRR-064. DRR-056 needs the device playback evidence from DRR-052. DRR-117 uses verified interruption and playback cancellation evidence.
- **Motion and qualification.** DRR-110, 111 and 112 integrate the digital path in order when their prerequisites are ready. Replay with fixtures or fake actuation. DRR-086, 120 and 124 have separate physical or fleet gates. Their issue status stays open until those are satisfied.

## What counts as done tonight

- **Verified** means the card’s normal path and acceptance have evidence for the stated SHA, fixture, cart, or assembly. Close the issue when authorized. A permitted reviewer can use a completion comment when the worker lacks close access.
- **Blocked** names the missing evidence or permission, its owner, and what will happen when it arrives. A worker can advance a separate digital card while that gate is open.
- **Waiting for CI** records the pushed SHA and workflow link. Check required jobs for that SHA. If replaced by a later push, record which run was replaced and verify the applicable newer revision. Carry forward evidence only after checking what changed.
- **Deferred** preserves the accepted defer reason. Reopen an optional or superseded part only with an applicable decision.

At closeout, ask the worker summary for counts by slot, what actually landed, active CI, and exact carryovers. Keep PR #17 draft. This runbook guides software work and preparation for measured trials. It provides no physical-test or purchasing authorization.
