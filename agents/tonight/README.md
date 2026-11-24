# Launch ten fire-and-forget workers

Open ten Chat-mode workers and paste one numbered prompt into each, once. Each prompt includes the starter card, the rules for continuing on its own, and how to leave verified evidence in GitHub. The workers do their own dependency checks, issue recovery, and closeout during their original run.

The goal is to finish as many executable cards as each run can reach and preserve a usable checkpoint for the rest. The catalog has 192 cards. Of these, 27 require operator evidence such as measurements or real checkout records. Workers can prepare those procedures and record the exact missing evidence. [Task catalog](../catalog.md), [Draft PR #17](https://github.com/hungngodev/desk-robot-remix/pull/17)

## Paste once into each worker

| Copy this prompt | First card | Preferred cards after the starter |
| --- | --- | --- |
| [01 · PR evidence and review](01-pr-evidence-and-review.md) | DRR-003 · Match open review threads to current behavior | Repository evidence, selected independent reviews, publication queue setup |
| [02 · Shopping and stock](02-shopping-and-stock.md) | DRR-013 · Find proven same-feature sourcing | Inventory, exact parts, landed costs and delivered cart |
| [03 · Body and odometry](03-body-and-odometry.md) | DRR-040 · Verify the body pose fixture | WROOM safety, wheel observations and jaw feedback |
| [04 · Sense head and camera](04-sense-head-and-camera.md) | DRR-049 · Check JPEG metadata and reject replay | Head bridge, camera, audio device and overlay |
| [05 · Voice and behavior](05-voice-and-behavior.md) | DRR-055 · Verify human VAD priority | Interruption, stale playback, quiet, tools and initiative |
| [06 · Map and memory](06-map-and-memory.md) | DRR-068 · Verify ground projection | Pose ingest, anchors, grid, persistence and isolation |
| [07 · Object recall and navigation](07-object-recall-and-navigation.md) | DRR-077 · Compare local detector candidates | Target evidence, bounded search, routes and arrival |
| [08 · Power, dock and station](08-power-dock-and-station.md) | DRR-087 · Resolve the protected 1S path | Power, cutoff, dock evidence and shared station |
| [09 · CAD and builder](09-cad-and-builder.md) | DRR-098 · Verify CAD originals and licenses | Fit, prints, wiring, flashing and assembly |
| [10 · Integration and replays](10-integration-and-replays.md) | DRR-153 · Review the body/Sense/Mac pose boundary | Shared entry points, replays and integrated evidence |

Paste 01 first, then 02–10 in separate chats. The starters run in parallel. Slot 01 tries to open the publication issue, while the other slots start work. Every worker has its own recovery path if issue access or the publication issue is unavailable. [Card order and prerequisites](order.md), [Issue access fallback](issue-recovery.md)

## How workers keep moving within one run

1. **Inspect and claim.** Start at the live PR head. Look for existing work, an active writer, and exact prerequisite evidence. Claim one card and, for an edit, one exact set of paths or one shared interface. Keep a fresh GitHub checkpoint before a potentially long operation and after each verifiable change.
2. **Complete a small unit and immediately continue.** Record the code, fixture, check, review result or precise blocker. If a fix already landed, verify it and advance. A passing test, published commit, pending CI or blocked card is an intermediate result. Keep working on another eligible card.
3. **Open the next dependency yourself.** When a fixture or other prerequisite lands, post its link and the affected child’s card ID. If that child is now runnable and has no active claimant, the producer or any active worker with the right authority can claim it. Preferred slots guide the first pass. A stopped preferred worker does not hold up its eligible descendants.
4. **Use the shared queue at publication.** Work in isolation and let the current required checks settle before the next routine push. Refresh the head and both claim surfaces before publishing. Use non-forced updates only. While waiting, do useful independent work and recheck the exact CI SHA after a meaningful result.
5. **Do a final global ready sweep.** Before ending, check your current claim, newly enabled children, other slots with ready unclaimed work, and relevant CI/review outcomes. When an authorized action remains, take it. If the only remaining work depends on a live peer or CI, use a short supported wait or another useful inspection and recheck once within the run. Preserve a precise handoff when all remaining work needs external evidence, permissions or a new execution window. [Automatic closeout checklist](closeout.md)

## Handoffs across slots

- **Pose and map.** DRR-040 publishes the body fixture. DRR-047 and DRR-066 can then run in parallel. When both have evidence, an active worker can claim DRR-109. DRR-070 also needs DRR-049 and DRR-066. DRR-071 needs DRR-068 and DRR-070.
- **Shopping.** DRR-013 supplies comparison evidence for DRR-014. DRR-020 waits for verified stock allocation, pack logic and quotes. DRR-121 requires exact selections and real checkout evidence.
- **Voice.** DRR-055 feeds DRR-057 and DRR-064. DRR-056 needs DRR-052 playback evidence. DRR-117 uses verified interruption and playback cancellation evidence.
- **Motion and release.** DRR-110, 111 and 112 integrate the digital path when their prerequisites are ready. Use fixtures or fake actuation. DRR-086, 120 and 124 keep their separate physical and fleet gates.

## Where to see progress

- **Task issue** for the card’s claim, checkpoint, evidence, and blocker. If workers cannot open the issue, look for a tagged comment on draft PR #17.
- **Publication issue or tagged publication comments** for the active push claim, published SHA and CI link.
- **Worker exit checkpoint** for what finished, what remains eligible, and the exact missing evidence. A worker exiting while another is still active leaves the checkpoint so the other worker can consume it.

GitHub preserves the work and lets an active peer pick it up. Chat mode can end a run at its execution limit. Once all runs have ended, a later CI result or dependency update cannot wake them. The checkpoints identify the unfinished work if you choose a later launch. [Draft PR #17](https://github.com/hungngodev/desk-robot-remix/pull/17)
