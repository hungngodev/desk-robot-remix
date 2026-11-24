# Run one small task per Chat worker

Open up to ten fresh chats at a time. Paste one numbered prompt into each. Each run chooses **one card and one small check**, records the result in GitHub, and ends. The same slot prompt can select the next eligible check in a **new** chat in a later batch.

The 192 cards are a backlog for multiple batches. A broad card may need several short runs, each with its own evidence. Cards that need actual hardware, checkout, or operator evidence stay open until that evidence exists. [Task catalog](../catalog.md), [Draft PR #17](https://github.com/hungngodev/desk-robot-remix/pull/17)

## Copy a prompt for each new chat

| Prompt | First card | First small check |
| --- | --- | --- |
| [01 · PR evidence and review](01-pr-evidence-and-review.md) | DRR-003 | Match one unresolved review thread to current code and evidence |
| [02 · Shopping and stock](02-shopping-and-stock.md) | DRR-013 | Check same-use examples for the exact GY-530 ranging carrier |
| [03 · Body and odometry](03-body-and-odometry.md) | DRR-040 | Verify a body pose reply with one valid and one invalid fixture |
| [04 · Sense head and camera](04-sense-head-and-camera.md) | DRR-049 | Check one camera sequence replay rejection |
| [05 · Voice and behavior](05-voice-and-behavior.md) | DRR-055 | Check one human speech event interrupting one active TTS response |
| [06 · Map and memory](06-map-and-memory.md) | DRR-068 | Verify one known projection and one rejected ray |
| [07 · Object recall and navigation](07-object-recall-and-navigation.md) | DRR-077 | Compare the existing detector to one documented candidate on a known fixture or existing result |
| [08 · Power, dock and station](08-power-dock-and-station.md) | DRR-087 | Trace one protected pack-to-charger interface on paper |
| [09 · CAD and builder](09-cad-and-builder.md) | DRR-098 | Trace one selected original CAD file to its license |
| [10 · Integration and replays](10-integration-and-replays.md) | DRR-153 | Review one body-to-Sense pose contract boundary |

Paste any ready slots in parallel. Slot 01 may initialize the shared publication issue if GitHub allows it. Other workers can start using their task issues or tagged PR comments. [Card order and prerequisites](order.md), [Issue access fallback](issue-recovery.md)

## What one run does

1. **Select once.** Check the live PR head, card issue, prerequisites and active claim. Use the starter if its small check is available. If it is complete, blocked, or claimed by another worker, choose one eligible check from your slot. An incomplete card’s recorded next check can be the assignment for a new run.
2. **Do the selected check.** Use the card’s authority and ordinary entry point. A read-only review returns evidence. A verification checks one scenario. An authorized implementation run fixes one small defect and exercises its focused check. If the card is broader, record exactly which portion you covered.
3. **Post and stop.** Record the starting SHA, exact check, observed result, evidence link, and next check or blocker. Mark the card verified only if all its acceptance is evidenced. When its check is complete, blocked or out of reach with current tools, release the claim and end the run. A pending CI run gets a SHA and check link in the issue. [Task receipt](closeout.md)

Use the publication queue and non-forced updates for authorized pushes. If another worker owns the push or required CI is still running, record the prepared branch or patch and its verification for a later publication run. A short agent can leave a staged result and exit. [Publication and issue access](issue-recovery.md)

## Start the next batch in fresh chats

- **Check the receipt.** A ready next check on the same card can go to a fresh chat with the same slot prompt. The worker reads GitHub and skips already verified work.
- **Follow dependencies.** Once DRR-040 posts the pose fixture, slots 04 and 06 can use it for DRR-047 and DRR-066. A later slot 10 run can take DRR-109 when both results exist. DRR-013’s comparison can unblock DRR-014. For other cards, follow the prerequisite links in the order.
- **Collect CI separately.** When an issue’s checks have finished, paste the [one-result CI prompt](ci-result.md) into a fresh chat. It checks one pending publication receipt and stops.
- **Leave external gates visible.** Keep an assembly test or final checkout card open until the required evidence arrives. A later short run can verify that receipt.

GitHub is the handoff between runs. A completed chat cannot pick up a dependency or check that finishes later. Each fresh chat uses the last issue or PR comment and performs one small assignment. [Draft PR #17](https://github.com/hungngodev/desk-robot-remix/pull/17)
