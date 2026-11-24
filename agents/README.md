# Desk Robot Remix worker assignments

Give a worker one card link from the [task catalog](catalog.md). Each card names the work, authority, source, shared rules, prerequisites, scoped paths and acceptance evidence. Start from [draft PR #17](https://github.com/hungngodev/desk-robot-remix/pull/17) and refresh its head before assessing a claim or publishing.

## Find an assignment

The catalog contains **192 cards** from all 22 source tabs. At the reviewed revision, **94 are ready**, **91 are blocked**, **5 are already verified**, and **2 are deferred**. These are planning states. The issue holds live progress.

- [Repository and evidence](catalog.md#repository)
- [Inventory and purchasing](catalog.md#shopping)
- [WROOM safety and sensing](catalog.md#body)
- [Odometry and manipulation](catalog.md#motion)
- [Sense head and camera](catalog.md#sense)
- [Voice, tools and behavior](catalog.md#voice)
- [Map, calibration and memory](catalog.md#map)
- [Object recall and navigation](catalog.md#navigation)
- [Power, dock and station](catalog.md#power-dock-station)
- [CAD and builder experience](catalog.md#builder)
- [Integration, replays and release](catalog.md#integration)
- [Independent review](catalog.md#review)

A few independent entry points are [review one requirement and normal entry point](tasks/review/151-review-accepted-requirement-and-real-entry-point-gaps.md), [collect same-feature sourcing evidence](tasks/shopping/013-collect-proof-of-same-feature-use.md), [verify local arm and disarm](tasks/body/024-verify-local-arm-and-disarm-authority.md), and [verify JPEG freshness](tasks/sense/049-verify-jpeg-metadata-and-reject-replay.md). An operator-evidence card can prepare a test or reconcile supplied evidence while its physical gate is open.

## Start a worker with one link

Paste this into a new Chat mode worker and replace the bracketed text with the card link.

> Take [one task card link]. Refresh draft PR #17, read the card’s shared rules, and look for an existing issue or claim. Follow the card’s authority and verify its one deliverable. Save the current SHA, evidence and next action to the issue after each complete check. If blocked, record the specific missing input and advance independent authorized work in the same queue. Keep review-only work read-only. Use the shared publication queue when authorized to push.

Use GitHub file, commit, check and issue views. Read each file linked from the card. A worker with a worktree uses an isolated checkout. A GitHub-only worker can use an isolated branch if supported. With read or comment access, record findings and use real linked CI where available. Report commands that could not run. Continue until executable scope is verified or a specific remaining blocker requires an external change. Runtime limits can interrupt a run, so save checkpoints as you go.

## Claim, verify and hand off in GitHub

Use one issue per launched card. Search by the stable ID before creating it. The issue title is `DRR-NNN · card title`. Use native blocking links when supported and repeat the dependencies in the issue body for plain-text readers. [GitHub issue dependencies](https://docs.github.com/en/issues/tracking-your-work-with-issues/using-issues/creating-issue-dependencies)

```text
Card link:
Authority:
Blocking issues and the evidence each must provide:
Claim (worker, starting full SHA, owned paths or interface):
Current checkpoint (observed result, check link, next action):
Completion (commit or exact reviewed SHA, executed checks, evidence):
Open gates (missing measurement, permission or owner handoff):
```

1. Read the existing issue and related PR threads. Check current head, ownership and affected behavior. If claims collide, use the earliest visible valid claim and keep alternate work independent. One writer owns a shared interface or path at a time.
2. Advance a small verifiable unit. After a result, update the issue. Review-only authority allows assessment and authorized findings. Implementation authority comes from the launched card and the operator’s permissions. Share a fixture early if another worker can progress with it.
3. Close the issue only after the card’s acceptance is evidenced. With comment-only access, post the same completion evidence and leave the issue open for a permitted closer. A dependent worker checks that the exact fixture, commit, or receipt it needs is present. A failed or canceled CI run and a planned measurement are open evidence.

## Publish without colliding

Use one shared GitHub Issue titled `PR #17 publication queue` once workers begin publishing. Develop and verify independently. Before pushing, check the queue and current required CI. Claim the next push with starting SHA. The earliest eligible claim goes first, refreshes the branch and its review threads, and uses a non-forced update. Post the new SHA and checks. Release the slot after those checks reach a terminal result, including any failed or superseded result with a concrete follow-up. While waiting, return to independent tasks. [Host CI](../.github/workflows/host-verification.yml), [GitHub Actions concurrency](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency)

## Prompt sources and precedence

The [source crosswalk](coverage.md) covers all 22 tabs, 75 audit actions, 33 packets, 96 procedures and 200 source entries. The [verbatim Tab 22 export](raw/tab_22_raw.txt) is the approved public source archive. Other full prompt captures stay local. The [shared contract](../docs/plans/spatial-first-unit/00-contract.md) and the current [repository instructions](../AGENTS.md) define the operating boundaries. Apply the review-only override to review cards, current decisions to live implementation, and the scoped acceptance conditions to each individual card.

The retained parent excerpts are [head manifest](workers/worker_01_head_manifest/PROMPT.md), [integration](workers/worker_02_incremental_integration/PROMPT.md), [replays](workers/worker_03_cross_layer_replays/PROMPT.md), [builder route](workers/worker_04_builder_docs_and_route/PROMPT.md) and [evidence and review](workers/worker_05_evidence_and_review_closure/PROMPT.md).
