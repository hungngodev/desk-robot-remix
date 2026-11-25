# Integrate the first complete unit and verify release evidence

Take [the shared contract](00-contract.md). Deliver an exact-head, end-to-end verification record and one builder route from the canonical list to safe commissioning. This guide owns shared entry-point changes. Each worker can continue to execute and verify their own packet without a coordinator assigning routine work.

## Own these changes

Own shared Mac startup and API registration, `controller.py` cross-feature integration, shared interface and builder docs, workflow updates required by a real new check, end-to-end fixtures and the verification ledger. Domain owners keep their source and unit tests. Review proposed shared edits with the relevant owner and keep rules centralized in the existing authenticated controller and safety paths.

## Work in this order

1. **Make a current head manifest.** Record the active PR SHA, configuration, lockfiles and scope from guide 10. Compare every guide’s claimed behavior with current code, open threads and existing tests. Reuse implemented behavior through a focused gap proof. Record genuine unresolved issues with the owning guide. Review old PRs only where they contain useful gaps. Confirm the publishing destination and its visibility with the operator. Keep the integration PR draft.
2. **Integrate incrementally.** First merge the versioned read-only body fixtures into Sense and Mac paths. Next make map/spatial memory available in fixture and read-only live modes. Add detector and route proposals behind existing config and safety defaults. Add qualified bounded execution through the existing control owner. Enable production paths only when their prerequisites are present and the release rule permits it. Verify default startup on older WROOM/Sense, unavailable detectors, empty SQLite, reboot, no network, and existing voice and dock profiles. Keep scripts and CLI examples usable from a clean checkout.
3. **Run cross-layer replays.** Build normal-path tests around `pose` and fresh JPEG, same-origin stationary anchoring, object observation, controlled navigation, fresh arrival, user cut-in and STOP. Include wrong robot/session IDs, replayed or stale samples, pickup, moved or occluded targets, unsupported firmware, VAD during JPEG capture, cutoff/dock false positives, quiet mode and read-only station data. Inspect that a software denial returns the correct status and a physical safety loop still enforces its own gate. Verify that a new result cannot outlive its session or origin.
4. **Publish one build and measurement route in the existing docs.** Link the delivered cart with quantities and exact seller variants, 2D print scale and 3D files, connector and pin tables, flashing targets and settings, credentials setup guidance, first power, local cutoff, optical/acoustic calibration, tethered motion, grasp, spatial and charge trials. Give each stage the expected observation and a safe stop point on failure. Show the complete list’s unresolved lines and the separate pilot/sample path. Preserve the older support path and source/license attribution.
5. **Close review with evidence.** Refresh the PR head and checks after each integrated change. Inspect related unresolved review threads across the implemented area, including non-code docs and missing acceptance. Mark each resolved path with the commit or test and record any owner/reviewer pending decision. When an exact-SHA run fails, isolate the failing step, reproduce it locally where possible, fix or track the concrete blocker and rerun. Keep all unresolved physical gates and the exact delivered-order evidence explicit in the builder handoff.

## Acceptance

- Run `uv run --no-sync pytest -q -ra tests firmware/head/tests` from `code/`, the tracked lint command and receipt verifiers. Run sanitizer, WROOM, Sense, dock and Feather jobs from [host CI](../../../.github/workflows/host-verification.yml). Check the exact result revision, review comments and required check outcomes. Record any host, workflow or toolchain limits with reproduction paths, exact failed commands and affected claims.
- Verify the source-to-physical trace for robot/dock/station using guides [10](10-requirements-and-shopping.md), [40](40-voice-and-proactive-behavior.md), [60](60-object-recall-and-navigation.md) and [70](70-fit-power-manipulation-and-dock.md). Each acceptance row needs source revision, fixture or real assembly ID, operator evidence and status. Treat historical CI and physical evidence from different assemblies as separate records. Keep the PR in its required draft state until the active release policy allows promotion. [Current build guide](../../guides/build.md), [Verification ledger](../../records/verification.md)


### Independent procurement reviewer approval

For each real procurement receipt, keep the measured record immutable and set
`source_sha` to the tested revision. Use `artifact_sha256` when the record
was added at a later evidence revision. A reviewer must inspect the actual
measurements, equipment, carrier and procedure before signing. Generate the
exact acceptance line with
`verify_procurement_receipts.procurement_review_statement(receipt)`.
The claimed GitHub reviewer must personally post that line as a PR #17
conversation comment (one or more exact acceptance lines, with no other
text) and attach its `review_url` to the release receipt. The verifier binds
the comment author and digest to the exact scope, gate, source, artifact,
device revision, test date and measurement; a name in a file alone cannot
release purchasing. A synthetic fixture or an unrelated green workflow is
not physical approval.
