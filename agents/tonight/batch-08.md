# Batch 08

[Previous batch](batch-07.md) · [All batches](batches.md) · [Next batch](batch-09.md)

Copy one box into each fresh Chat-mode chat. You launch the chats. Check prerequisites before pasting.

**Digital** · Check each box’s prerequisites before launch.

### DRR-113

**Replay old hardware and degraded startup** · Verification · Blocked.

Prerequisites · [DRR-109](batch-03.md#drr-109). [Card](../tasks/integration/113-replay-old-hardware-and-degraded-startup.md)

```text
Chat mode. Work only on DRR-113 in hungngodev/desk-robot-remix draft PR #17.
Card: https://github.com/hungngodev/desk-robot-remix/blob/impl/mac-hardware-safety-preflight-2026-11-10/agents/tasks/integration/113-replay-old-hardware-and-degraded-startup.md
Small check: Use the card’s acceptance to choose the first uncovered small check in this scope. Use old firmware, missing detector, empty SQLite, reboot and loss of network to exercise ordinary startup fallbacks.
Search for the exact DRR issue and verify live head, prerequisites and claims. I authorize opening or updating this card’s issue or posting its tagged PR receipt if issue access is unavailable. Use a next distinct check already named in an incomplete card’s receipt, if available. If the remaining check is verified, claimed, or blocked, record the exact reason and end.
Run one read-only review or verification check within the card’s scope. Cite actual evidence and record whether you ran the check or inspected it.
Post the full SHA, one result, evidence, remaining acceptance, and the exact next distinct check or blocker. Mark the card verified only if all its acceptance has evidence. Release the claim and stop after this result. The operator launches every new run.
```

### DRR-114

**Replay stale and wrong-robot pose and JPEG** · Verification · Blocked.

Prerequisites · [DRR-049](batch-01.md#drr-049), [DRR-066](batch-02.md#drr-066). [Card](../tasks/integration/114-replay-stale-and-wrong-robot-pose-and-jpeg.md)

```text
Chat mode. Work only on DRR-114 in hungngodev/desk-robot-remix draft PR #17.
Card: https://github.com/hungngodev/desk-robot-remix/blob/impl/mac-hardware-safety-preflight-2026-11-10/agents/tasks/integration/114-replay-stale-and-wrong-robot-pose-and-jpeg.md
Small check: Use the card’s acceptance to choose the first uncovered small check in this scope. Use duplicates, stale samples and wrong robot at the pose/JPEG boundary. Verify no fused observation or map contamination.
Search for the exact DRR issue and verify live head, prerequisites and claims. I authorize opening or updating this card’s issue or posting its tagged PR receipt if issue access is unavailable. Use a next distinct check already named in an incomplete card’s receipt, if available. If the remaining check is verified, claimed, or blocked, record the exact reason and end.
Run one read-only review or verification check within the card’s scope. Cite actual evidence and record whether you ran the check or inspected it.
Post the full SHA, one result, evidence, remaining acceptance, and the exact next distinct check or blocker. Mark the card verified only if all its acceptance has evidence. Release the claim and stop after this result. The operator launches every new run.
```

### DRR-115

**Replay lost anchor and pickup** · Verification · Blocked.

Prerequisites · [DRR-041](batch-05.md#drr-041), [DRR-071](batch-04.md#drr-071). [Card](../tasks/integration/115-replay-lost-anchor-and-pickup.md)

```text
Chat mode. Work only on DRR-115 in hungngodev/desk-robot-remix draft PR #17.
Card: https://github.com/hungngodev/desk-robot-remix/blob/impl/mac-hardware-safety-preflight-2026-11-10/agents/tasks/integration/115-replay-lost-anchor-and-pickup.md
Small check: Use the card’s acceptance to choose the first uncovered small check in this scope. Use pickup after a known anchor and an outstanding camera result. Verify pre-pickup evidence cannot restore old map state.
Search for the exact DRR issue and verify live head, prerequisites and claims. I authorize opening or updating this card’s issue or posting its tagged PR receipt if issue access is unavailable. Use a next distinct check already named in an incomplete card’s receipt, if available. If the remaining check is verified, claimed, or blocked, record the exact reason and end.
Run one read-only review or verification check within the card’s scope. Cite actual evidence and record whether you ran the check or inspected it.
Post the full SHA, one result, evidence, remaining acceptance, and the exact next distinct check or blocker. Mark the card verified only if all its acceptance has evidence. Release the claim and stop after this result. The operator launches every new run.
```

### DRR-116

**Replay moved, occluded and falsely detected objects** · Verification · Blocked.

Prerequisites · [DRR-079](batch-02.md#drr-079), [DRR-081](batch-07.md#drr-081), [DRR-085](batch-06.md#drr-085). [Card](../tasks/integration/116-replay-moved-occluded-and-falsely-detected-objects.md)

```text
Chat mode. Work only on DRR-116 in hungngodev/desk-robot-remix draft PR #17.
Card: https://github.com/hungngodev/desk-robot-remix/blob/impl/mac-hardware-safety-preflight-2026-11-10/agents/tasks/integration/116-replay-moved-occluded-and-falsely-detected-objects.md
Small check: Use the card’s acceptance to choose the first uncovered small check in this scope. Exercise the three target negatives on the normal recall path. Require truthful outcome and no false arrival or unsafe command.
Search for the exact DRR issue and verify live head, prerequisites and claims. I authorize opening or updating this card’s issue or posting its tagged PR receipt if issue access is unavailable. Use a next distinct check already named in an incomplete card’s receipt, if available. If the remaining check is verified, claimed, or blocked, record the exact reason and end.
Run one read-only review or verification check within the card’s scope. Cite actual evidence and record whether you ran the check or inspected it.
Post the full SHA, one result, evidence, remaining acceptance, and the exact next distinct check or blocker. Mark the card verified only if all its acceptance has evidence. Release the claim and stop after this result. The operator launches every new run.
```

### DRR-117

**Replay user cut-in and STOP under load** · Verification · Blocked.

Prerequisites · [DRR-055](batch-01.md#drr-055), [DRR-056](batch-05.md#drr-056). [Card](../tasks/integration/117-replay-user-cut-in-and-stop-under-load.md)

```text
Chat mode. Work only on DRR-117 in hungngodev/desk-robot-remix draft PR #17.
Card: https://github.com/hungngodev/desk-robot-remix/blob/impl/mac-hardware-safety-preflight-2026-11-10/agents/tasks/integration/117-replay-user-cut-in-and-stop-under-load.md
Small check: Use the card’s acceptance to choose the first uncovered small check in this scope. Exercise interruption and independent user STOP during pending capture and TTS. Require stop priority and no stale audio resume.
Search for the exact DRR issue and verify live head, prerequisites and claims. I authorize opening or updating this card’s issue or posting its tagged PR receipt if issue access is unavailable. Use a next distinct check already named in an incomplete card’s receipt, if available. If the remaining check is verified, claimed, or blocked, record the exact reason and end.
Run one read-only review or verification check within the card’s scope. Cite actual evidence and record whether you ran the check or inspected it.
Post the full SHA, one result, evidence, remaining acceptance, and the exact next distinct check or blocker. Mark the card verified only if all its acceptance has evidence. Release the claim and stop after this result. The operator launches every new run.
```

### DRR-118

**Replay dock false positives and station isolation** · Verification · Blocked.

Prerequisites · [DRR-092](batch-05.md#drr-092), [DRR-093](batch-05.md#drr-093), [DRR-096](batch-04.md#drr-096). [Card](../tasks/integration/118-replay-dock-false-positives-and-station-isolation.md)

```text
Chat mode. Work only on DRR-118 in hungngodev/desk-robot-remix draft PR #17.
Card: https://github.com/hungngodev/desk-robot-remix/blob/impl/mac-hardware-safety-preflight-2026-11-10/agents/tasks/integration/118-replay-dock-false-positives-and-station-isolation.md
Small check: Use the card’s acceptance to choose the first uncovered small check in this scope. Verify a false dock observation cannot claim charge and stale/cross-station evidence cannot move a pet or contaminate identity.
Search for the exact DRR issue and verify live head, prerequisites and claims. I authorize opening or updating this card’s issue or posting its tagged PR receipt if issue access is unavailable. Use a next distinct check already named in an incomplete card’s receipt, if available. If the remaining check is verified, claimed, or blocked, record the exact reason and end.
Run one read-only review or verification check within the card’s scope. Cite actual evidence and record whether you ran the check or inspected it.
Post the full SHA, one result, evidence, remaining acceptance, and the exact next distinct check or blocker. Mark the card verified only if all its acceptance has evidence. Release the claim and stop after this result. The operator launches every new run.
```

### DRR-122

**Resolve related review threads with evidence** · Verification · Blocked.

Prerequisites · [DRR-003](batch-01.md#drr-003). [Card](../tasks/integration/122-resolve-related-review-threads-with-evidence.md)

```text
Chat mode. Work only on DRR-122 in hungngodev/desk-robot-remix draft PR #17.
Card: https://github.com/hungngodev/desk-robot-remix/blob/impl/mac-hardware-safety-preflight-2026-11-10/agents/tasks/integration/122-resolve-related-review-threads-with-evidence.md
Small check: Use the card’s acceptance to choose the first uncovered small check in this scope. At the live PR head verify assigned comments against code and checks. Link the fixing change or supported disposition before resolving a thread.
Search for the exact DRR issue and verify live head, prerequisites and claims. I authorize opening or updating this card’s issue or posting its tagged PR receipt if issue access is unavailable. Use a next distinct check already named in an incomplete card’s receipt, if available. If the remaining check is verified, claimed, or blocked, record the exact reason and end.
Run one read-only review or verification check within the card’s scope. Cite actual evidence and record whether you ran the check or inspected it.
Post the full SHA, one result, evidence, remaining acceptance, and the exact next distinct check or blocker. Mark the card verified only if all its acceptance has evidence. Release the claim and stop after this result. The operator launches every new run.
```

### DRR-126

**Resolve the exact charger and temperature input** · Review only · Blocked.

Prerequisites · [DRR-125](batch-06.md#drr-125). [Card](../tasks/shopping/126-resolve-the-exact-charger-and-temperature-input.md)

```text
Chat mode. Work only on DRR-126 in hungngodev/desk-robot-remix draft PR #17.
Card: https://github.com/hungngodev/desk-robot-remix/blob/impl/mac-hardware-safety-preflight-2026-11-10/agents/tasks/shopping/126-resolve-the-exact-charger-and-temperature-input.md
Small check: Use the card’s acceptance to choose the first uncovered small check in this scope. Check exact charger module, NTC and adapter compatibility, rail/current constraints, code driver and delivered SKU.
Search for the exact DRR issue and verify live head, prerequisites and claims. I authorize opening or updating this card’s issue or posting its tagged PR receipt if issue access is unavailable. Use a next distinct check already named in an incomplete card’s receipt, if available. If the remaining check is verified, claimed, or blocked, record the exact reason and end.
Run one read-only review or verification check within the card’s scope. Cite actual evidence and record whether you ran the check or inspected it.
Post the full SHA, one result, evidence, remaining acceptance, and the exact next distinct check or blocker. Mark the card verified only if all its acceptance has evidence. Release the claim and stop after this result. The operator launches every new run.
```

### DRR-127

**Resolve exact boost and regulator variants** · Review only · Blocked.

Prerequisites · [DRR-087](batch-01.md#drr-087). [Card](../tasks/shopping/127-resolve-exact-boost-and-regulator-variants.md)

```text
Chat mode. Work only on DRR-127 in hungngodev/desk-robot-remix draft PR #17.
Card: https://github.com/hungngodev/desk-robot-remix/blob/impl/mac-hardware-safety-preflight-2026-11-10/agents/tasks/shopping/127-resolve-exact-boost-and-regulator-variants.md
Small check: Use the card’s acceptance to choose the first uncovered small check in this scope. Resolve supplier options, dropout, startup/load constraints and actual harness mounts. Keep sustained-load evidence separate.
Search for the exact DRR issue and verify live head, prerequisites and claims. I authorize opening or updating this card’s issue or posting its tagged PR receipt if issue access is unavailable. Use a next distinct check already named in an incomplete card’s receipt, if available. If the remaining check is verified, claimed, or blocked, record the exact reason and end.
Run one read-only review or verification check within the card’s scope. Cite actual evidence and record whether you ran the check or inspected it.
Post the full SHA, one result, evidence, remaining acceptance, and the exact next distinct check or blocker. Mark the card verified only if all its acceptance has evidence. Release the claim and stop after this result. The operator launches every new run.
```

### DRR-129

**Resolve the station CO₂ sensor** · Review only · Ready.

Prerequisites · Independent. [Card](../tasks/shopping/129-resolve-the-station-co-sensor.md)

```text
Chat mode. Work only on DRR-129 in hungngodev/desk-robot-remix draft PR #17.
Card: https://github.com/hungngodev/desk-robot-remix/blob/impl/mac-hardware-safety-preflight-2026-11-10/agents/tasks/shopping/129-resolve-the-station-co-sensor.md
Small check: Use the card’s acceptance to choose the first uncovered small check in this scope. Verify SCD40 or a proven compatible candidate’s exact variant, wiring, reader, sale option and delivered cost for one shared station.
Search for the exact DRR issue and verify live head, prerequisites and claims. I authorize opening or updating this card’s issue or posting its tagged PR receipt if issue access is unavailable. Use a next distinct check already named in an incomplete card’s receipt, if available. If the remaining check is verified, claimed, or blocked, record the exact reason and end.
Run one read-only review or verification check within the card’s scope. Cite actual evidence and record whether you ran the check or inspected it.
Post the full SHA, one result, evidence, remaining acceptance, and the exact next distinct check or blocker. Mark the card verified only if all its acceptance has evidence. Release the claim and stop after this result. The operator launches every new run.
```

[Previous batch](batch-07.md) · [All batches](batches.md) · [Next batch](batch-09.md)
