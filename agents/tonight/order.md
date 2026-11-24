# Card order for all ten slots

The order below gives each of the 192 cards one starting owner. Resume claimed work first, then take the first item with the evidence it needs. The original catalog state is shown for reference. Use the live GitHub issue and PR checks on every pass.

A fixture can unblock an independently testable path where the card allows it. A card can finish when its required evidence is available. For a card awaiting an assembly, receipt or operator action, prepare the procedure and keep acceptance open.

[Runbook and copy-paste prompts](README.md) · [Original task catalog](../catalog.md)

## Slot 01

**PR evidence and review.** [Copy-paste prompt](01-pr-evidence-and-review.md)

| Card | State at catalog snapshot | Prerequisites |
| --- | --- | --- |
| [DRR-003 · Match review threads to current behavior](../tasks/repository/003-match-review-threads-to-current-behavior.md) | Ready | Independent |
| [DRR-002 · Find overlapping work before editing](../tasks/repository/002-find-overlapping-work-before-editing.md) | Ready | Independent |
| [DRR-004 · Reproduce the pinned host environment](../tasks/repository/004-reproduce-the-pinned-host-environment.md) | Ready | Independent |
| [DRR-008 · Check measured receipt validation](../tasks/repository/008-check-measured-receipt-validation.md) | Ready | Independent |
| [DRR-007 · Check evidence reviewer authority](../tasks/repository/007-check-evidence-reviewer-authority.md) | Ready | Independent |
| [DRR-151 · Review accepted requirement and real entry point gaps](../tasks/review/151-review-accepted-requirement-and-real-entry-point-gaps.md) | Ready | Independent |
| [DRR-156 · Review acceptance evidence against its claim](../tasks/review/156-review-acceptance-evidence-against-its-claim.md) | Ready | Independent |
| [DRR-010 · Repair links to the evidence ledger](../tasks/repository/010-repair-links-to-the-evidence-ledger.md) | Ready | Independent |
| [DRR-144 · Verify source coverage and accepted feature scope](../tasks/repository/144-verify-source-coverage-and-accepted-feature-scope.md) | Ready | Independent |
| [DRR-001 · Pin the current PR and base revisions](../tasks/repository/001-pin-the-current-pr-and-base-revisions.md) | Already verified | Independent |
| [DRR-005 · Check required CI jobs at one SHA](../tasks/repository/005-check-required-ci-jobs-at-one-sha.md) | Already verified | Independent |
| [DRR-006 · Separate tested source from receipt identity](../tasks/repository/006-separate-tested-source-from-receipt-identity.md) | Ready | Independent |
| [DRR-009 · Record the approved publishing visibility](../tasks/repository/009-record-the-approved-publishing-visibility.md) | Already verified | Independent |
| [DRR-152 · Review reuse and license of one active feature](../tasks/review/152-review-reuse-and-license-of-one-active-feature.md) | Ready | Independent |
| [DRR-159 · Review project scope and superseded requirements](../tasks/review/159-review-project-scope-and-superseded-requirements.md) | Ready | Independent |
| [DRR-160 · Review unresolved workflow responsibility and handoff](../tasks/review/160-review-unresolved-workflow-responsibility-and-handoff.md) | Ready | Independent |

## Slot 02

**Shopping and stock.** [Copy-paste prompt](02-shopping-and-stock.md)

| Card | State at catalog snapshot | Prerequisites |
| --- | --- | --- |
| [DRR-013 · Collect proof of same-feature use](../tasks/shopping/013-collect-proof-of-same-feature-use.md) | Ready | Independent |
| [DRR-014 · Verify the exact GY-530 carrier](../tasks/shopping/014-verify-the-exact-gy-530-carrier.md) | Blocked | [DRR-013](../tasks/shopping/013-collect-proof-of-same-feature-use.md) (slot 02) |
| [DRR-011 · Reconcile photographed hardware](../tasks/shopping/011-reconcile-photographed-hardware.md) | Ready | Independent |
| [DRR-012 · Allocate paid and available stock](../tasks/shopping/012-allocate-paid-and-available-stock.md) | Blocked | [DRR-011](../tasks/shopping/011-reconcile-photographed-hardware.md) (slot 02) |
| [DRR-015 · Verify both mux variants and addresses](../tasks/shopping/015-verify-both-mux-variants-and-addresses.md) | Ready | Independent |
| [DRR-016 · Confirm the selected playback pair](../tasks/shopping/016-confirm-the-selected-playback-pair.md) | Ready | Independent |
| [DRR-019 · Verify stock and quote expiry](../tasks/shopping/019-verify-stock-and-quote-expiry.md) | Ready | Independent |
| [DRR-021 · Reconcile pilot and full shopping views](../tasks/shopping/021-reconcile-pilot-and-full-shopping-views.md) | Ready | Independent |
| [DRR-125 · Resolve the exact protected pack and connector](../tasks/shopping/125-resolve-the-exact-protected-pack-and-connector.md) | Ready | Independent |
| [DRR-126 · Resolve the exact charger and temperature input](../tasks/shopping/126-resolve-the-exact-charger-and-temperature-input.md) | Blocked | [DRR-125](../tasks/shopping/125-resolve-the-exact-protected-pack-and-connector.md) (slot 02) |
| [DRR-127 · Resolve exact boost and regulator variants](../tasks/shopping/127-resolve-exact-boost-and-regulator-variants.md) | Blocked | [DRR-087](../tasks/power-dock-station/087-resolve-the-exact-protected-1s-path.md) (slot 08) |
| [DRR-128 · Resolve the independent dock supply](../tasks/shopping/128-resolve-the-independent-dock-supply.md) | Ready | Independent |
| [DRR-129 · Resolve the station CO₂ sensor](../tasks/shopping/129-resolve-the-station-co-sensor.md) | Ready | Independent |
| [DRR-022 · Trace each buy line to a real role](../tasks/shopping/022-trace-each-buy-line-to-a-real-role.md) | Ready | Independent |
| [DRR-020 · Compute landed cost and prior spend](../tasks/shopping/020-compute-landed-cost-and-prior-spend.md) | Blocked | [DRR-012](../tasks/shopping/012-allocate-paid-and-available-stock.md) (slot 02), [DRR-018](../tasks/shopping/018-count-retail-packs-and-surplus.md) (slot 02), [DRR-019](../tasks/shopping/019-verify-stock-and-quote-expiry.md) (slot 02) |
| [DRR-121 · Verify the exact complete delivered cart](../tasks/integration/121-verify-the-exact-complete-delivered-cart.md) | Blocked | [DRR-020](../tasks/shopping/020-compute-landed-cost-and-prior-spend.md) (slot 02), [DRR-021](../tasks/shopping/021-reconcile-pilot-and-full-shopping-views.md) (slot 02), [DRR-022](../tasks/shopping/022-trace-each-buy-line-to-a-real-role.md) (slot 02), [DRR-125](../tasks/shopping/125-resolve-the-exact-protected-pack-and-connector.md) (slot 02), [DRR-126](../tasks/shopping/126-resolve-the-exact-charger-and-temperature-input.md) (slot 02), [DRR-127](../tasks/shopping/127-resolve-exact-boost-and-regulator-variants.md) (slot 02), [DRR-128](../tasks/shopping/128-resolve-the-independent-dock-supply.md) (slot 02), [DRR-129](../tasks/shopping/129-resolve-the-station-co-sensor.md) (slot 02) |
| [DRR-017 · Separate manufacturer from seller SKUs](../tasks/shopping/017-separate-manufacturer-from-seller-skus.md) | Ready | Independent |
| [DRR-018 · Count retail packs and surplus](../tasks/shopping/018-count-retail-packs-and-surplus.md) | Ready | Independent |
| [DRR-130 · Reconcile station scope across cart and receipt validation](../tasks/shopping/130-reconcile-station-scope-across-cart-and-receipt-validation.md) | Ready | Independent |
| [DRR-131 · Bind purchase release to qualified source checks](../tasks/shopping/131-bind-purchase-release-to-qualified-source-checks.md) | Ready | Independent |
| [DRR-146 · Confirm stocked WROOM, OLED and positional servos](../tasks/shopping/146-confirm-stocked-wroom-oled-and-positional-servos.md) | Blocked | [DRR-011](../tasks/shopping/011-reconcile-photographed-hardware.md) (slot 02) |
| [DRR-147 · Resolve dock IR receivers and emitters](../tasks/shopping/147-resolve-dock-ir-receivers-and-emitters.md) | Blocked | [DRR-092](../tasks/power-dock-station/092-verify-tag-and-ir-provenance.md) (slot 08) |
| [DRR-148 · Verify each station module has an active reader](../tasks/shopping/148-verify-each-station-module-has-an-active-reader.md) | Blocked | [DRR-096](../tasks/power-dock-station/096-verify-station-identity-timing-and-staleness.md) (slot 08) |
| [DRR-149 · Verify one body accessory’s exact order option](../tasks/shopping/149-verify-one-body-accessory-s-exact-order-option.md) | Blocked | [DRR-134](../tasks/body/134-trace-real-accessory-events-to-one-consumer.md) (slot 03) |
| [DRR-154 · Review hardware suitability for one accepted role](../tasks/review/154-review-hardware-suitability-for-one-accepted-role.md) | Ready | Independent |
| [DRR-155 · Review checkout from the builder’s perspective](../tasks/review/155-review-checkout-from-the-builder-s-perspective.md) | Ready | Independent |
| [DRR-168 · Review selected hardware sourcing alternatives under the cap](../tasks/shopping/168-review-selected-hardware-sourcing-alternatives-under-the-cap.md) | Ready | Independent |
| [DRR-169 · Resolve purchase role max30102](../tasks/shopping/169-resolve-purchase-role-max30102.md) | Ready | Independent |
| [DRR-170 · Resolve purchase role cap1188](../tasks/shopping/170-resolve-purchase-role-cap1188.md) | Ready | Independent |
| [DRR-171 · Resolve purchase role touch_electrodes](../tasks/shopping/171-resolve-purchase-role-touch-electrodes.md) | Ready | Independent |
| [DRR-172 · Resolve purchase role apds9960](../tasks/shopping/172-resolve-purchase-role-apds9960.md) | Ready | Independent |
| [DRR-173 · Resolve purchase role fsr](../tasks/shopping/173-resolve-purchase-role-fsr.md) | Ready | Independent |
| [DRR-174 · Resolve purchase role ads1115](../tasks/shopping/174-resolve-purchase-role-ads1115.md) | Ready | Independent |
| [DRR-175 · Resolve purchase role rgb](../tasks/shopping/175-resolve-purchase-role-rgb.md) | Ready | Independent |
| [DRR-176 · Resolve purchase role logic_level](../tasks/shopping/176-resolve-purchase-role-logic-level.md) | Ready | Independent |
| [DRR-177 · Resolve purchase role max17048](../tasks/shopping/177-resolve-purchase-role-max17048.md) | Ready | Independent |
| [DRR-178 · Resolve purchase role cap_power](../tasks/shopping/178-resolve-purchase-role-cap-power.md) | Ready | Independent |
| [DRR-179 · Resolve purchase role switch_power](../tasks/shopping/179-resolve-purchase-role-switch-power.md) | Ready | Independent |
| [DRR-180 · Resolve purchase role bumper](../tasks/shopping/180-resolve-purchase-role-bumper.md) | Ready | Independent |
| [DRR-181 · Resolve purchase role sht41](../tasks/shopping/181-resolve-purchase-role-sht41.md) | Ready | Independent |
| [DRR-182 · Resolve purchase role pn532](../tasks/shopping/182-resolve-purchase-role-pn532.md) | Ready | Independent |
| [DRR-183 · Resolve purchase role mcp23017](../tasks/shopping/183-resolve-purchase-role-mcp23017.md) | Ready | Independent |
| [DRR-184 · Resolve purchase role haptic_driver](../tasks/shopping/184-resolve-purchase-role-haptic-driver.md) | Ready | Independent |
| [DRR-185 · Resolve purchase role dock_ir_beacon_controller](../tasks/shopping/185-resolve-purchase-role-dock-ir-beacon-controller.md) | Ready | Independent |
| [DRR-186 · Resolve purchase role bme688](../tasks/shopping/186-resolve-purchase-role-bme688.md) | Ready | Independent |
| [DRR-187 · Resolve purchase role ld2410c](../tasks/shopping/187-resolve-purchase-role-ld2410c.md) | Ready | Independent |
| [DRR-188 · Resolve purchase role soil_probe](../tasks/shopping/188-resolve-purchase-role-soil-probe.md) | Ready | Independent |
| [DRR-189 · Resolve purchase role nfc_game_props](../tasks/shopping/189-resolve-purchase-role-nfc-game-props.md) | Superseded / deferred | Independent |
| [DRR-190 · Resolve purchase role amg8833](../tasks/shopping/190-resolve-purchase-role-amg8833.md) | Superseded / deferred | Independent |
| [DRR-191 · Resolve purchase role room_controller](../tasks/shopping/191-resolve-purchase-role-room-controller.md) | Ready | Independent |
| [DRR-192 · Resolve purchase role drv8833_driver_candidate](../tasks/shopping/192-resolve-purchase-role-drv8833-driver-candidate.md) | Ready | Independent |

## Slot 03

**Body and odometry.** [Copy-paste prompt](03-body-and-odometry.md)

| Card | State at catalog snapshot | Prerequisites |
| --- | --- | --- |
| [DRR-040 · Verify the bounded read-only body pose](../tasks/motion/040-verify-the-bounded-read-only-body-pose.md) | Ready | Independent |
| [DRR-024 · Verify local arm and disarm authority](../tasks/body/024-verify-local-arm-and-disarm-authority.md) | Ready | Independent |
| [DRR-025 · Verify the requested drive pulse cap](../tasks/body/025-verify-the-requested-drive-pulse-cap.md) | Ready | Independent |
| [DRR-026 · Verify watchdog on control loss](../tasks/body/026-verify-watchdog-on-control-loss.md) | Ready | Independent |
| [DRR-027 · Keep UART work off the safety loop](../tasks/body/027-keep-uart-work-off-the-safety-loop.md) | Ready | Independent |
| [DRR-028 · Verify the four downward lanes](../tasks/body/028-verify-the-four-downward-lanes.md) | Ready | Independent |
| [DRR-029 · Verify forward ranging](../tasks/body/029-verify-forward-ranging.md) | Ready | Independent |
| [DRR-031 · Exercise stale, invalid and missing ranging](../tasks/body/031-exercise-stale-invalid-and-missing-ranging.md) | Ready | Independent |
| [DRR-032 · Exercise bumper and mux faults](../tasks/body/032-exercise-bumper-and-mux-faults.md) | Ready | Independent |
| [DRR-041 · Verify pose origin invalidation](../tasks/motion/041-verify-pose-origin-invalidation.md) | Blocked | [DRR-040](../tasks/motion/040-verify-the-bounded-read-only-body-pose.md) (slot 03) |
| [DRR-035 · Evaluate wheel encoder choice and fit](../tasks/motion/035-evaluate-wheel-encoder-choice-and-fit.md) | Ready | Independent |
| [DRR-036 · Verify signed counts and wrap](../tasks/motion/036-verify-signed-counts-and-wrap.md) | Blocked | [DRR-035](../tasks/motion/035-evaluate-wheel-encoder-choice-and-fit.md) (slot 03) |
| [DRR-037 · Separate measured wheel travel from commands](../tasks/motion/037-separate-measured-wheel-travel-from-commands.md) | Blocked | [DRR-036](../tasks/motion/036-verify-signed-counts-and-wrap.md) (slot 03) |
| [DRR-042 · Verify jaw force and feedback timing](../tasks/motion/042-verify-jaw-force-and-feedback-timing.md) | Ready | Independent |
| [DRR-135 · Verify operator recovery through ordinary controls](../tasks/body/135-verify-operator-recovery-through-ordinary-controls.md) | Blocked | [DRR-024](../tasks/body/024-verify-local-arm-and-disarm-authority.md) (slot 03), [DRR-026](../tasks/body/026-verify-watchdog-on-control-loss.md) (slot 03) |
| [DRR-023 · Isolate legacy motor targets](../tasks/body/023-isolate-legacy-motor-targets.md) | Ready | Independent |
| [DRR-030 · Verify side and rear lanes are read-only](../tasks/body/030-verify-side-and-rear-lanes-are-read-only.md) | Ready | Independent |
| [DRR-033 · Qualify mounted IMU pickup and put-down](../tasks/body/033-qualify-mounted-imu-pickup-and-put-down.md) | Blocked | [DRR-041](../tasks/motion/041-verify-pose-origin-invalidation.md) (slot 03) |
| [DRR-034 · Measure the swept stopping envelope](../tasks/body/034-measure-the-swept-stopping-envelope.md) | Blocked | [DRR-028](../tasks/body/028-verify-the-four-downward-lanes.md) (slot 03), [DRR-029](../tasks/body/029-verify-forward-ranging.md) (slot 03), [DRR-031](../tasks/body/031-exercise-stale-invalid-and-missing-ranging.md) (slot 03), [DRR-032](../tasks/body/032-exercise-bumper-and-mux-faults.md) (slot 03), [DRR-090](../tasks/power-dock-station/090-prove-independent-cutoff-under-cpu-stall.md) (slot 08) |
| [DRR-038 · Measure wheel radius and track width](../tasks/motion/038-measure-wheel-radius-and-track-width.md) | Blocked | [DRR-035](../tasks/motion/035-evaluate-wheel-encoder-choice-and-fit.md) (slot 03) |
| [DRR-039 · Verify stationary IMU correction](../tasks/motion/039-verify-stationary-imu-correction.md) | Blocked | [DRR-037](../tasks/motion/037-separate-measured-wheel-travel-from-commands.md) (slot 03) |
| [DRR-043 · Qualify fitted lift and jaw endpoints](../tasks/motion/043-qualify-fitted-lift-and-jaw-endpoints.md) | Blocked | [DRR-042](../tasks/motion/042-verify-jaw-force-and-feedback-timing.md) (slot 03) |
| [DRR-044 · Qualify keys and wrapped candy separately](../tasks/motion/044-qualify-keys-and-wrapped-candy-separately.md) | Blocked | [DRR-043](../tasks/motion/043-qualify-fitted-lift-and-jaw-endpoints.md) (slot 03), [DRR-034](../tasks/body/034-measure-the-swept-stopping-envelope.md) (slot 03) |
| [DRR-133 · Verify unsafe attitude and slow lift latch](../tasks/body/133-verify-unsafe-attitude-and-slow-lift-latch.md) | Ready | Independent |
| [DRR-134 · Trace real accessory events to one consumer](../tasks/body/134-trace-real-accessory-events-to-one-consumer.md) | Ready | Independent |
| [DRR-136 · Compare stepper and guarded DC candidates](../tasks/body/136-compare-stepper-and-guarded-dc-candidates.md) | Ready | Independent |
| [DRR-161 · Verify accessory mux and same-address isolation](../tasks/body/161-verify-accessory-mux-and-same-address-isolation.md) | Ready | Independent |

## Slot 04

**Sense head and camera.** [Copy-paste prompt](04-sense-head-and-camera.md)

| Card | State at catalog snapshot | Prerequisites |
| --- | --- | --- |
| [DRR-049 · Verify JPEG metadata and reject replay](../tasks/sense/049-verify-jpeg-metadata-and-reject-replay.md) | Ready | Independent |
| [DRR-047 · Verify authenticated Sense pose forwarding](../tasks/sense/047-verify-authenticated-sense-pose-forwarding.md) | Blocked | [DRR-040](../tasks/motion/040-verify-the-bounded-read-only-body-pose.md) (slot 03) |
| [DRR-048 · Verify malformed or unsupported pose responses](../tasks/sense/048-verify-malformed-or-unsupported-pose-responses.md) | Blocked | [DRR-040](../tasks/motion/040-verify-the-bounded-read-only-body-pose.md) (slot 03) |
| [DRR-050 · Verify shared camera ownership and buffer release](../tasks/sense/050-verify-shared-camera-ownership-and-buffer-release.md) | Ready | Independent |
| [DRR-046 · Verify accepted Sense pins and audio rates](../tasks/sense/046-verify-accepted-sense-pins-and-audio-rates.md) | Ready | Independent |
| [DRR-052 · Verify actual device playback receipts](../tasks/sense/052-verify-actual-device-playback-receipts.md) | Ready | Independent |
| [DRR-045 · Reproduce the pinned Sense build](../tasks/sense/045-reproduce-the-pinned-sense-build.md) | Already verified | Independent |
| [DRR-051 · Measure optical capture lag](../tasks/sense/051-measure-optical-capture-lag.md) | Blocked | [DRR-049](../tasks/sense/049-verify-jpeg-metadata-and-reject-replay.md) (slot 04), [DRR-050](../tasks/sense/050-verify-shared-camera-ownership-and-buffer-release.md) (slot 04) |
| [DRR-053 · Measure fitted-head acoustic timing](../tasks/sense/053-measure-fitted-head-acoustic-timing.md) | Blocked | [DRR-046](../tasks/sense/046-verify-accepted-sense-pins-and-audio-rates.md) (slot 04), [DRR-052](../tasks/sense/052-verify-actual-device-playback-receipts.md) (slot 04) |
| [DRR-054 · Qualify fitted OLED and deliberate touch](../tasks/sense/054-qualify-fitted-oled-and-deliberate-touch.md) | Blocked | [DRR-046](../tasks/sense/046-verify-accepted-sense-pins-and-audio-rates.md) (slot 04) |

## Slot 05

**Voice and behavior.** [Copy-paste prompt](05-voice-and-behavior.md)

| Card | State at catalog snapshot | Prerequisites |
| --- | --- | --- |
| [DRR-055 · Verify human VAD takes priority](../tasks/voice/055-verify-human-vad-takes-priority.md) | Ready | Independent |
| [DRR-057 · Verify interrupted speech onset is retained](../tasks/voice/057-verify-interrupted-speech-onset-is-retained.md) | Blocked | [DRR-055](../tasks/voice/055-verify-human-vad-takes-priority.md) (slot 05) |
| [DRR-058 · Verify echo-only rejection criteria](../tasks/voice/058-verify-echo-only-rejection-criteria.md) | Ready | Independent |
| [DRR-059 · Verify quiet mode changes](../tasks/voice/059-verify-quiet-mode-changes.md) | Ready | Independent |
| [DRR-060 · Verify deliberate versus passive cooldowns](../tasks/voice/060-verify-deliberate-versus-passive-cooldowns.md) | Ready | Independent |
| [DRR-061 · Verify global speaking-floor ownership](../tasks/voice/061-verify-global-speaking-floor-ownership.md) | Ready | Independent |
| [DRR-062 · Reject obsolete tool results](../tasks/voice/062-reject-obsolete-tool-results.md) | Ready | Independent |
| [DRR-056 · Verify obsolete playback cancellation](../tasks/voice/056-verify-obsolete-playback-cancellation.md) | Blocked | [DRR-052](../tasks/sense/052-verify-actual-device-playback-receipts.md) (slot 04) |
| [DRR-063 · Verify grounded spoken tool results](../tasks/voice/063-verify-grounded-spoken-tool-results.md) | Blocked | [DRR-062](../tasks/voice/062-reject-obsolete-tool-results.md) (slot 05) |
| [DRR-064 · Verify one real proactive behavior path](../tasks/voice/064-verify-one-real-proactive-behavior-path.md) | Blocked | [DRR-055](../tasks/voice/055-verify-human-vad-takes-priority.md) (slot 05), [DRR-060](../tasks/voice/060-verify-deliberate-versus-passive-cooldowns.md) (slot 05) |
| [DRR-137 · Verify consent applies to live media](../tasks/voice/137-verify-consent-applies-to-live-media.md) | Ready | Independent |
| [DRR-065 · Measure concurrent Mac and Xiaozhi sessions](../tasks/voice/065-measure-concurrent-mac-and-xiaozhi-sessions.md) | Blocked | [DRR-061](../tasks/voice/061-verify-global-speaking-floor-ownership.md) (slot 05) |
| [DRR-141 · Verify a coordinated social activity outcome](../tasks/voice/141-verify-a-coordinated-social-activity-outcome.md) | Blocked | [DRR-061](../tasks/voice/061-verify-global-speaking-floor-ownership.md) (slot 05), [DRR-064](../tasks/voice/064-verify-one-real-proactive-behavior-path.md) (slot 05) |
| [DRR-142 · Qualify real fitted-head barge-in](../tasks/voice/142-qualify-real-fitted-head-barge-in.md) | Blocked | [DRR-053](../tasks/sense/053-measure-fitted-head-acoustic-timing.md) (slot 04), [DRR-055](../tasks/voice/055-verify-human-vad-takes-priority.md) (slot 05), [DRR-056](../tasks/voice/056-verify-obsolete-playback-cancellation.md) (slot 05), [DRR-057](../tasks/voice/057-verify-interrupted-speech-onset-is-retained.md) (slot 05), [DRR-058](../tasks/voice/058-verify-echo-only-rejection-criteria.md) (slot 05) |
| [DRR-162 · Verify tool and perception provenance under camera generation changes](../tasks/voice/162-verify-tool-and-perception-provenance-under-camera-generation-changes.md) | Blocked | [DRR-049](../tasks/sense/049-verify-jpeg-metadata-and-reject-replay.md) (slot 04), [DRR-062](../tasks/voice/062-reject-obsolete-tool-results.md) (slot 05) |
| [DRR-163 · Verify isolated policy for user opt-in and silence](../tasks/voice/163-verify-isolated-policy-for-user-opt-in-and-silence.md) | Blocked | [DRR-059](../tasks/voice/059-verify-quiet-mode-changes.md) (slot 05), [DRR-137](../tasks/voice/137-verify-consent-applies-to-live-media.md) (slot 05) |

## Slot 06

**Map and memory.** [Copy-paste prompt](06-map-and-memory.md)

| Card | State at catalog snapshot | Prerequisites |
| --- | --- | --- |
| [DRR-068 · Verify ground projection and bad rays](../tasks/map/068-verify-ground-projection-and-bad-rays.md) | Ready | Independent |
| [DRR-066 · Verify Mac pose decoding and freshness](../tasks/map/066-verify-mac-pose-decoding-and-freshness.md) | Blocked | [DRR-040](../tasks/motion/040-verify-the-bounded-read-only-body-pose.md) (slot 03) |
| [DRR-073 · Verify private SQLite migration](../tasks/map/073-verify-private-sqlite-migration.md) | Ready | Independent |
| [DRR-074 · Verify per-robot memory isolation](../tasks/map/074-verify-per-robot-memory-isolation.md) | Blocked | [DRR-073](../tasks/map/073-verify-private-sqlite-migration.md) (slot 06) |
| [DRR-075 · Verify deletion and retention](../tasks/map/075-verify-deletion-and-retention.md) | Blocked | [DRR-073](../tasks/map/073-verify-private-sqlite-migration.md) (slot 06) |
| [DRR-076 · Verify truthful observation recency](../tasks/map/076-verify-truthful-observation-recency.md) | Blocked | [DRR-073](../tasks/map/073-verify-private-sqlite-migration.md) (slot 06), [DRR-074](../tasks/map/074-verify-per-robot-memory-isolation.md) (slot 06) |
| [DRR-070 · Verify stationary pose and JPEG pairing](../tasks/map/070-verify-stationary-pose-and-jpeg-pairing.md) | Blocked | [DRR-049](../tasks/sense/049-verify-jpeg-metadata-and-reject-replay.md) (slot 04), [DRR-066](../tasks/map/066-verify-mac-pose-decoding-and-freshness.md) (slot 06) |
| [DRR-071 · Verify anchor corrections and invalidation](../tasks/map/071-verify-anchor-corrections-and-invalidation.md) | Blocked | [DRR-068](../tasks/map/068-verify-ground-projection-and-bad-rays.md) (slot 06), [DRR-070](../tasks/map/070-verify-stationary-pose-and-jpeg-pairing.md) (slot 06) |
| [DRR-072 · Verify grid states and freshness](../tasks/map/072-verify-grid-states-and-freshness.md) | Blocked | [DRR-066](../tasks/map/066-verify-mac-pose-decoding-and-freshness.md) (slot 06) |
| [DRR-138 · Verify shared scene deduplication](../tasks/voice/138-verify-shared-scene-deduplication.md) | Blocked | [DRR-074](../tasks/map/074-verify-per-robot-memory-isolation.md) (slot 06) |
| [DRR-139 · Verify observation sharing by exact event ID](../tasks/voice/139-verify-observation-sharing-by-exact-event-id.md) | Blocked | [DRR-074](../tasks/map/074-verify-per-robot-memory-isolation.md) (slot 06) |
| [DRR-140 · Report trimmed observations truthfully](../tasks/voice/140-report-trimmed-observations-truthfully.md) | Blocked | [DRR-075](../tasks/map/075-verify-deletion-and-retention.md) (slot 06) |
| [DRR-067 · Calibrate camera intrinsics per resolution](../tasks/map/067-calibrate-camera-intrinsics-per-resolution.md) | Blocked | [DRR-051](../tasks/sense/051-measure-optical-capture-lag.md) (slot 04) |
| [DRR-069 · Verify tag identity and actual placement](../tasks/map/069-verify-tag-identity-and-actual-placement.md) | Blocked | [DRR-091](../tasks/power-dock-station/091-verify-passive-dock-fit.md) (slot 08) |

## Slot 07

**Object recall and navigation.** [Copy-paste prompt](07-object-recall-and-navigation.md)

| Card | State at catalog snapshot | Prerequisites |
| --- | --- | --- |
| [DRR-077 · Benchmark local detector candidates](../tasks/navigation/077-benchmark-local-detector-candidates.md) | Ready | Independent |
| [DRR-078 · Pin the selected detector’s provenance](../tasks/navigation/078-pin-the-selected-detector-s-provenance.md) | Blocked | [DRR-077](../tasks/navigation/077-benchmark-local-detector-candidates.md) (slot 07) |
| [DRR-079 · Verify target and hard-negative fixtures](../tasks/navigation/079-verify-target-and-hard-negative-fixtures.md) | Blocked | [DRR-077](../tasks/navigation/077-benchmark-local-detector-candidates.md) (slot 07) |
| [DRR-080 · Verify remembered-target lookup](../tasks/navigation/080-verify-remembered-target-lookup.md) | Blocked | [DRR-074](../tasks/map/074-verify-per-robot-memory-isolation.md) (slot 06), [DRR-076](../tasks/map/076-verify-truthful-observation-recency.md) (slot 06) |
| [DRR-082 · Verify planner footprint and stop margin](../tasks/navigation/082-verify-planner-footprint-and-stop-margin.md) | Blocked | [DRR-072](../tasks/map/072-verify-grid-states-and-freshness.md) (slot 06) |
| [DRR-083 · Reject unsupported or stale travel](../tasks/navigation/083-reject-unsupported-or-stale-travel.md) | Blocked | [DRR-072](../tasks/map/072-verify-grid-states-and-freshness.md) (slot 06), [DRR-082](../tasks/navigation/082-verify-planner-footprint-and-stop-margin.md) (slot 07) |
| [DRR-081 · Verify bounded search for moved or occluded targets](../tasks/navigation/081-verify-bounded-search-for-moved-or-occluded-targets.md) | Blocked | [DRR-079](../tasks/navigation/079-verify-target-and-hard-negative-fixtures.md) (slot 07), [DRR-080](../tasks/navigation/080-verify-remembered-target-lookup.md) (slot 07) |
| [DRR-084 · Verify cancellation between motion requests](../tasks/navigation/084-verify-cancellation-between-motion-requests.md) | Blocked | [DRR-083](../tasks/navigation/083-reject-unsupported-or-stale-travel.md) (slot 07) |
| [DRR-085 · Require fresh arrival evidence](../tasks/navigation/085-require-fresh-arrival-evidence.md) | Blocked | [DRR-080](../tasks/navigation/080-verify-remembered-target-lookup.md) (slot 07), [DRR-083](../tasks/navigation/083-reject-unsupported-or-stale-travel.md) (slot 07) |
| [DRR-158 · Review one error and recovery path](../tasks/review/158-review-one-error-and-recovery-path.md) | Ready | Independent |
| [DRR-086 · Qualify re-anchor and moved-start returns](../tasks/navigation/086-qualify-re-anchor-and-moved-start-returns.md) | Blocked | [DRR-034](../tasks/body/034-measure-the-swept-stopping-envelope.md) (slot 03), [DRR-067](../tasks/map/067-calibrate-camera-intrinsics-per-resolution.md) (slot 06), [DRR-069](../tasks/map/069-verify-tag-identity-and-actual-placement.md) (slot 06), [DRR-071](../tasks/map/071-verify-anchor-corrections-and-invalidation.md) (slot 06), [DRR-085](../tasks/navigation/085-require-fresh-arrival-evidence.md) (slot 07), [DRR-112](../tasks/integration/112-integrate-bounded-execution-via-the-current-motion-owner.md) (slot 10) |

## Slot 08

**Power, dock and station.** [Copy-paste prompt](08-power-dock-and-station.md)

| Card | State at catalog snapshot | Prerequisites |
| --- | --- | --- |
| [DRR-087 · Resolve the exact protected 1S path](../tasks/power-dock-station/087-resolve-the-exact-protected-1s-path.md) | Ready | Independent |
| [DRR-088 · Verify rail and connector limits](../tasks/power-dock-station/088-verify-rail-and-connector-limits.md) | Blocked | [DRR-087](../tasks/power-dock-station/087-resolve-the-exact-protected-1s-path.md) (slot 08) |
| [DRR-089 · Verify signed shunt saturation endpoints](../tasks/power-dock-station/089-verify-signed-shunt-saturation-endpoints.md) | Ready | Independent |
| [DRR-092 · Verify tag and IR provenance](../tasks/power-dock-station/092-verify-tag-and-ir-provenance.md) | Ready | Independent |
| [DRR-093 · Verify contact and seat evidence](../tasks/power-dock-station/093-verify-contact-and-seat-evidence.md) | Ready | Independent |
| [DRR-095 · Verify atomic station samples](../tasks/power-dock-station/095-verify-atomic-station-samples.md) | Ready | Independent |
| [DRR-096 · Verify station identity, timing and staleness](../tasks/power-dock-station/096-verify-station-identity-timing-and-staleness.md) | Ready | Independent |
| [DRR-097 · Verify consented station-to-pet behavior](../tasks/power-dock-station/097-verify-consented-station-to-pet-behavior.md) | Blocked | [DRR-095](../tasks/power-dock-station/095-verify-atomic-station-samples.md) (slot 08), [DRR-096](../tasks/power-dock-station/096-verify-station-identity-timing-and-staleness.md) (slot 08) |
| [DRR-145 · Verify independent electrical docking boundary](../tasks/power-dock-station/145-verify-independent-electrical-docking-boundary.md) | Blocked | [DRR-087](../tasks/power-dock-station/087-resolve-the-exact-protected-1s-path.md) (slot 08), [DRR-128](../tasks/shopping/128-resolve-the-independent-dock-supply.md) (slot 02) |
| [DRR-132 · Reconcile historical BME688 assertions](../tasks/power-dock-station/132-reconcile-historical-bme688-assertions.md) | Already verified | Independent |
| [DRR-090 · Prove independent cutoff under CPU stall](../tasks/power-dock-station/090-prove-independent-cutoff-under-cpu-stall.md) | Blocked | [DRR-023](../tasks/body/023-isolate-legacy-motor-targets.md) (slot 03), [DRR-087](../tasks/power-dock-station/087-resolve-the-exact-protected-1s-path.md) (slot 08) |
| [DRR-091 · Verify passive dock fit](../tasks/power-dock-station/091-verify-passive-dock-fit.md) | Blocked | [DRR-099](../tasks/builder/099-verify-the-selected-assembly-dimensions.md) (slot 09) |
| [DRR-094 · Measure net charge and thermal faults](../tasks/power-dock-station/094-measure-net-charge-and-thermal-faults.md) | Blocked | [DRR-087](../tasks/power-dock-station/087-resolve-the-exact-protected-1s-path.md) (slot 08), [DRR-089](../tasks/power-dock-station/089-verify-signed-shunt-saturation-endpoints.md) (slot 08), [DRR-091](../tasks/power-dock-station/091-verify-passive-dock-fit.md) (slot 08), [DRR-093](../tasks/power-dock-station/093-verify-contact-and-seat-evidence.md) (slot 08) |
| [DRR-143 · Qualify dock approach before electrical tests](../tasks/power-dock-station/143-qualify-dock-approach-before-electrical-tests.md) | Blocked | [DRR-034](../tasks/body/034-measure-the-swept-stopping-envelope.md) (slot 03), [DRR-091](../tasks/power-dock-station/091-verify-passive-dock-fit.md) (slot 08), [DRR-092](../tasks/power-dock-station/092-verify-tag-and-ir-provenance.md) (slot 08), [DRR-093](../tasks/power-dock-station/093-verify-contact-and-seat-evidence.md) (slot 08) |
| [DRR-164 · Verify physical station controller and transport](../tasks/power-dock-station/164-verify-physical-station-controller-and-transport.md) | Blocked | [DRR-095](../tasks/power-dock-station/095-verify-atomic-station-samples.md) (slot 08), [DRR-096](../tasks/power-dock-station/096-verify-station-identity-timing-and-staleness.md) (slot 08), [DRR-148](../tasks/shopping/148-verify-each-station-module-has-an-active-reader.md) (slot 02) |

## Slot 09

**CAD and builder.** [Copy-paste prompt](09-cad-and-builder.md)

| Card | State at catalog snapshot | Prerequisites |
| --- | --- | --- |
| [DRR-098 · Verify CAD originals and derivative licenses](../tasks/builder/098-verify-cad-originals-and-derivative-licenses.md) | Ready | Independent |
| [DRR-099 · Verify the selected assembly dimensions](../tasks/builder/099-verify-the-selected-assembly-dimensions.md) | Blocked | [DRR-098](../tasks/builder/098-verify-cad-originals-and-derivative-licenses.md) (slot 09) |
| [DRR-106 · Reproduce clean-checkout CAD exports](../tasks/builder/106-reproduce-clean-checkout-cad-exports.md) | Ready | Independent |
| [DRR-104 · Verify the connector-to-connector harness](../tasks/builder/104-verify-the-connector-to-connector-harness.md) | Blocked | [DRR-015](../tasks/shopping/015-verify-both-mux-variants-and-addresses.md) (slot 02), [DRR-087](../tasks/power-dock-station/087-resolve-the-exact-protected-1s-path.md) (slot 08) |
| [DRR-105 · Verify 2D scale and orientation](../tasks/builder/105-verify-2d-scale-and-orientation.md) | Blocked | [DRR-099](../tasks/builder/099-verify-the-selected-assembly-dimensions.md) (slot 09) |
| [DRR-107 · Verify flashing and first-power instructions](../tasks/builder/107-verify-flashing-and-first-power-instructions.md) | Blocked | [DRR-104](../tasks/builder/104-verify-the-connector-to-connector-harness.md) (slot 09) |
| [DRR-165 · Publish the current builder route from verified references](../tasks/builder/165-publish-the-current-builder-route-from-verified-references.md) | Blocked | [DRR-104](../tasks/builder/104-verify-the-connector-to-connector-harness.md) (slot 09), [DRR-105](../tasks/builder/105-verify-2d-scale-and-orientation.md) (slot 09), [DRR-106](../tasks/builder/106-reproduce-clean-checkout-cad-exports.md) (slot 09), [DRR-107](../tasks/builder/107-verify-flashing-and-first-power-instructions.md) (slot 09) |
| [DRR-166 · Verify the final print pack contents against actual measurements](../tasks/builder/166-verify-the-final-print-pack-contents-against-actual-measurements.md) | Blocked | [DRR-099](../tasks/builder/099-verify-the-selected-assembly-dimensions.md) (slot 09), [DRR-105](../tasks/builder/105-verify-2d-scale-and-orientation.md) (slot 09), [DRR-106](../tasks/builder/106-reproduce-clean-checkout-cad-exports.md) (slot 09) |
| [DRR-100 · Verify pack restraint and connector fit](../tasks/builder/100-verify-pack-restraint-and-connector-fit.md) | Blocked | [DRR-087](../tasks/power-dock-station/087-resolve-the-exact-protected-1s-path.md) (slot 08), [DRR-099](../tasks/builder/099-verify-the-selected-assembly-dimensions.md) (slot 09) |
| [DRR-101 · Verify all eight optical paths and retention](../tasks/builder/101-verify-all-eight-optical-paths-and-retention.md) | Blocked | [DRR-014](../tasks/shopping/014-verify-the-exact-gy-530-carrier.md) (slot 02), [DRR-099](../tasks/builder/099-verify-the-selected-assembly-dimensions.md) (slot 09) |
| [DRR-102 · Verify servo sweep and interference](../tasks/builder/102-verify-servo-sweep-and-interference.md) | Blocked | [DRR-099](../tasks/builder/099-verify-the-selected-assembly-dimensions.md) (slot 09) |
| [DRR-103 · Verify the speaker and microphone openings](../tasks/builder/103-verify-the-speaker-and-microphone-openings.md) | Blocked | [DRR-016](../tasks/shopping/016-confirm-the-selected-playback-pair.md) (slot 02), [DRR-099](../tasks/builder/099-verify-the-selected-assembly-dimensions.md) (slot 09) |
| [DRR-108 · Walk the complete assembly and commissioning route](../tasks/builder/108-walk-the-complete-assembly-and-commissioning-route.md) | Blocked | [DRR-100](../tasks/builder/100-verify-pack-restraint-and-connector-fit.md) (slot 09), [DRR-101](../tasks/builder/101-verify-all-eight-optical-paths-and-retention.md) (slot 09), [DRR-102](../tasks/builder/102-verify-servo-sweep-and-interference.md) (slot 09), [DRR-103](../tasks/builder/103-verify-the-speaker-and-microphone-openings.md) (slot 09), [DRR-105](../tasks/builder/105-verify-2d-scale-and-orientation.md) (slot 09), [DRR-106](../tasks/builder/106-reproduce-clean-checkout-cad-exports.md) (slot 09), [DRR-107](../tasks/builder/107-verify-flashing-and-first-power-instructions.md) (slot 09) |
| [DRR-157 · Review the assembled builder route as a new user](../tasks/review/157-review-the-assembled-builder-route-as-a-new-user.md) | Ready | Independent |

## Slot 10

**Integration and replays.** [Copy-paste prompt](10-integration-and-replays.md)

| Card | State at catalog snapshot | Prerequisites |
| --- | --- | --- |
| [DRR-153 · Review a boundary between two working subsystems](../tasks/review/153-review-a-boundary-between-two-working-subsystems.md) | Ready | Independent |
| [DRR-109 · Integrate read-only pose contract](../tasks/integration/109-integrate-read-only-pose-contract.md) | Blocked | [DRR-040](../tasks/motion/040-verify-the-bounded-read-only-body-pose.md) (slot 03), [DRR-047](../tasks/sense/047-verify-authenticated-sense-pose-forwarding.md) (slot 04), [DRR-066](../tasks/map/066-verify-mac-pose-decoding-and-freshness.md) (slot 06) |
| [DRR-113 · Replay old hardware and degraded startup](../tasks/integration/113-replay-old-hardware-and-degraded-startup.md) | Blocked | [DRR-109](../tasks/integration/109-integrate-read-only-pose-contract.md) (slot 10) |
| [DRR-114 · Replay stale and wrong-robot pose and JPEG](../tasks/integration/114-replay-stale-and-wrong-robot-pose-and-jpeg.md) | Blocked | [DRR-049](../tasks/sense/049-verify-jpeg-metadata-and-reject-replay.md) (slot 04), [DRR-066](../tasks/map/066-verify-mac-pose-decoding-and-freshness.md) (slot 06) |
| [DRR-115 · Replay lost anchor and pickup](../tasks/integration/115-replay-lost-anchor-and-pickup.md) | Blocked | [DRR-041](../tasks/motion/041-verify-pose-origin-invalidation.md) (slot 03), [DRR-071](../tasks/map/071-verify-anchor-corrections-and-invalidation.md) (slot 06) |
| [DRR-117 · Replay user cut-in and STOP under load](../tasks/integration/117-replay-user-cut-in-and-stop-under-load.md) | Blocked | [DRR-055](../tasks/voice/055-verify-human-vad-takes-priority.md) (slot 05), [DRR-056](../tasks/voice/056-verify-obsolete-playback-cancellation.md) (slot 05) |
| [DRR-118 · Replay dock false positives and station isolation](../tasks/integration/118-replay-dock-false-positives-and-station-isolation.md) | Blocked | [DRR-092](../tasks/power-dock-station/092-verify-tag-and-ir-provenance.md) (slot 08), [DRR-093](../tasks/power-dock-station/093-verify-contact-and-seat-evidence.md) (slot 08), [DRR-096](../tasks/power-dock-station/096-verify-station-identity-timing-and-staleness.md) (slot 08) |
| [DRR-110 · Integrate fixture and read-only map modes](../tasks/integration/110-integrate-fixture-and-read-only-map-modes.md) | Blocked | [DRR-071](../tasks/map/071-verify-anchor-corrections-and-invalidation.md) (slot 06), [DRR-073](../tasks/map/073-verify-private-sqlite-migration.md) (slot 06), [DRR-109](../tasks/integration/109-integrate-read-only-pose-contract.md) (slot 10) |
| [DRR-111 · Integrate default-disabled route proposals](../tasks/integration/111-integrate-default-disabled-route-proposals.md) | Blocked | [DRR-079](../tasks/navigation/079-verify-target-and-hard-negative-fixtures.md) (slot 07), [DRR-083](../tasks/navigation/083-reject-unsupported-or-stale-travel.md) (slot 07), [DRR-110](../tasks/integration/110-integrate-fixture-and-read-only-map-modes.md) (slot 10) |
| [DRR-112 · Integrate bounded execution via the current motion owner](../tasks/integration/112-integrate-bounded-execution-via-the-current-motion-owner.md) | Blocked | [DRR-024](../tasks/body/024-verify-local-arm-and-disarm-authority.md) (slot 03), [DRR-025](../tasks/body/025-verify-the-requested-drive-pulse-cap.md) (slot 03), [DRR-026](../tasks/body/026-verify-watchdog-on-control-loss.md) (slot 03), [DRR-084](../tasks/navigation/084-verify-cancellation-between-motion-requests.md) (slot 07), [DRR-111](../tasks/integration/111-integrate-default-disabled-route-proposals.md) (slot 10) |
| [DRR-116 · Replay moved, occluded and falsely detected objects](../tasks/integration/116-replay-moved-occluded-and-falsely-detected-objects.md) | Blocked | [DRR-079](../tasks/navigation/079-verify-target-and-hard-negative-fixtures.md) (slot 07), [DRR-081](../tasks/navigation/081-verify-bounded-search-for-moved-or-occluded-targets.md) (slot 07), [DRR-085](../tasks/navigation/085-require-fresh-arrival-evidence.md) (slot 07) |
| [DRR-119 · Trace the digital portions of A1–A12](../tasks/integration/119-trace-the-digital-portions-of-a1-a12.md) | Blocked | [DRR-005](../tasks/repository/005-check-required-ci-jobs-at-one-sha.md) (slot 01), [DRR-008](../tasks/repository/008-check-measured-receipt-validation.md) (slot 01) |
| [DRR-122 · Resolve related review threads with evidence](../tasks/integration/122-resolve-related-review-threads-with-evidence.md) | Blocked | [DRR-003](../tasks/repository/003-match-review-threads-to-current-behavior.md) (slot 01) |
| [DRR-123 · Verify the final integrated head](../tasks/integration/123-verify-the-final-integrated-head.md) | Blocked | [DRR-005](../tasks/repository/005-check-required-ci-jobs-at-one-sha.md) (slot 01), [DRR-112](../tasks/integration/112-integrate-bounded-execution-via-the-current-motion-owner.md) (slot 10), [DRR-113](../tasks/integration/113-replay-old-hardware-and-degraded-startup.md) (slot 10), [DRR-114](../tasks/integration/114-replay-stale-and-wrong-robot-pose-and-jpeg.md) (slot 10), [DRR-115](../tasks/integration/115-replay-lost-anchor-and-pickup.md) (slot 10), [DRR-116](../tasks/integration/116-replay-moved-occluded-and-falsely-detected-objects.md) (slot 10), [DRR-117](../tasks/integration/117-replay-user-cut-in-and-stop-under-load.md) (slot 10), [DRR-118](../tasks/integration/118-replay-dock-false-positives-and-station-isolation.md) (slot 10), [DRR-119](../tasks/integration/119-trace-the-digital-portions-of-a1-a12.md) (slot 10), [DRR-122](../tasks/integration/122-resolve-related-review-threads-with-evidence.md) (slot 10) |
| [DRR-120 · Trace physical acceptance to one assembly](../tasks/integration/120-trace-physical-acceptance-to-one-assembly.md) | Blocked | [DRR-034](../tasks/body/034-measure-the-swept-stopping-envelope.md) (slot 03), [DRR-044](../tasks/motion/044-qualify-keys-and-wrapped-candy-separately.md) (slot 03), [DRR-086](../tasks/navigation/086-qualify-re-anchor-and-moved-start-returns.md) (slot 07), [DRR-094](../tasks/power-dock-station/094-measure-net-charge-and-thermal-faults.md) (slot 08), [DRR-108](../tasks/builder/108-walk-the-complete-assembly-and-commissioning-route.md) (slot 09), [DRR-119](../tasks/integration/119-trace-the-digital-portions-of-a1-a12.md) (slot 10), [DRR-142](../tasks/voice/142-qualify-real-fitted-head-barge-in.md) (slot 05), [DRR-143](../tasks/power-dock-station/143-qualify-dock-approach-before-electrical-tests.md) (slot 08) |
| [DRR-124 · Gate expansion on the complete first unit](../tasks/integration/124-gate-expansion-on-the-complete-first-unit.md) | Blocked | [DRR-120](../tasks/integration/120-trace-physical-acceptance-to-one-assembly.md) (slot 10), [DRR-121](../tasks/integration/121-verify-the-exact-complete-delivered-cart.md) (slot 02), [DRR-123](../tasks/integration/123-verify-the-final-integrated-head.md) (slot 10) |
| [DRR-150 · Qualify real five-pet stationary behavior](../tasks/integration/150-qualify-real-five-pet-stationary-behavior.md) | Blocked | [DRR-065](../tasks/voice/065-measure-concurrent-mac-and-xiaozhi-sessions.md) (slot 05), [DRR-124](../tasks/integration/124-gate-expansion-on-the-complete-first-unit.md) (slot 10), [DRR-141](../tasks/voice/141-verify-a-coordinated-social-activity-outcome.md) (slot 05) |
| [DRR-167 · Verify installed station and dock evidence stays per assembly](../tasks/integration/167-verify-installed-station-and-dock-evidence-stays-per-assembly.md) | Blocked | [DRR-008](../tasks/repository/008-check-measured-receipt-validation.md) (slot 01), [DRR-093](../tasks/power-dock-station/093-verify-contact-and-seat-evidence.md) (slot 08), [DRR-096](../tasks/power-dock-station/096-verify-station-identity-timing-and-staleness.md) (slot 08) |
