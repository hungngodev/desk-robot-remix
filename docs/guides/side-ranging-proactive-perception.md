# All eight VL53L0X directions: real sensor telemetry to proactive perception

Status November 10 2026. The body firmware ALREADY operates a real TCA9548A 0x70 with five critical cliff/forward channels (0..4) plus three supplemental read-only channels (5..7, left/right/rear) in the `esp32_full` profile. The new work uses those **actual** three readings in Mac pet behavior rather than inventing another driver, assuming all eight are one safety policy, or treating a shopping list as a hardware test.

## Reused existing code

* `code/firmware/body/lib/TofBus/TofBus.cpp` reuses pinned Pololu VL53L0X initialization and nonblocking checked I2C reads. `DESK_ROBOT_EXTRA_RANGERS` determines whether the three extras are present.
* `code/firmware/body/src/main.cpp` forwards fresh extra raw distance, validity and timestamp to WROOM `BodyControl::sample_side_range`. It also compares the shared `TofBus` error counter before and after each poll and invalidates **all three published optional valid flags immediately** when a new mux or I2C fault occurs. Raw values and prior presence remain diagnostic only; the Mac source gate already resets invalid channels rather than treating cached samples as new events.
* `code/firmware/body/lib/BodyControl/BodyControl.cpp` already publishes an authenticated read-only `side_ranges` block: `mm[3]`, `age_ms[3]`, `present_mask`, `valid_mask`, `motion_certified=false`.
* `code/laptop/src/desk_robot/side_ranging.py` now parses those original values, requires real valid samples younger than 350 ms, at least 60 ms between accepted WROOM conversion timestamps in hardware mode (host-derived estimates are legacy/simulation only) and two consecutive near samples to generate a change. Two clearly far samples rearm a channel. Missing, stale, malformed or disconnected channels reset that channel's baseline.
* The real pet `_touch_from_body` status poll now passes authenticated status to `_observe_side_ranges`. This stores one original `side_object` memory with exact WROOM direction and triggers the existing shared camera sampling/voice cooldown. No motor command is added. The five critical local WROOM cliff paths are unchanged.

## Calibration gating

Both of these parameters are required in the chosen robot's PRIVATE TOML configuration before enabling any side interaction:

```toml
# Put inside the selected [[robots]] table, not at top level.
side_interactions_qualified = true
side_near_threshold_mm = 170
```

**170 is only an example, not a measured default. Do NOT turn the flag on from a desk guess.** Measure the assembled actual left/right/rear sensor lens angles, track occlusion, bracket geometry and actual readings against a ruler. For each of three directions, collect near/far data with a book or cup at 10, 15, 20, 30 cm and verify 95% of valid, correctly identified active/clear trials. Select one conservative threshold based on actual sensor position and suppress cross-reflections. Establish normal room light and WiFi/Mac polling delays, too.

Use `code/scripts/calibrate_side_ranges.py` to analyze 20 independently recorded near and 20 far readings **for each** of left, right and rear (120 total labeled readings). The input is a JSONL file; each line includes `robot_id`, `direction`, `label` (near or far), `sample_id`, and the unmodified authenticated WROOM `side_ranges` object from `GET /v1/robots/{id}/status`. The analyzer rejects stale, invalid, duplicate and overlapping measurements, suggests a single shared threshold and leaves `physical_acceptance_pass=false`. Keep all three `sample_ms` values and the nonzero WROOM `boot_id` in the unmodified object. Use a single boot epoch, strictly advancing conversion timestamps for each direction (uint32 rollover is supported), a positive unique integer `sample_id` per direction, valid/present masks, and `motion_certified=false`. The runtime also requires at least 60 ms between accepted conversions; collect trials at that spacing or longer. Operator-supplied sample IDs alone do not prove independent physical ToF conversions, so review the original serial timestamps and actual ruler distances.

```bash
cd code
uv run --no-sync python scripts/calibrate_side_ranges.py \
  --robot robot-01 --input /path/to/labeled-side-ranges.jsonl
```

A camera/VLM may describe the triggered image but cannot claim a motor can safely turn or drive from these extra direction readings. Only channels 0..4 and the existing local verified WROOM safety guard are motion critical. No "motion certified" bit becomes true because the model noticed an object.

## Acceptance tests and limits

`code/tests/test_side_ranging.py` tests independently updated real time samples, no double counting of one body status frame, invalid masks, reconnection baseline, hysteresis rearm and strict no-motor observation. That is **mock evidence only**, not real VL53L0X geometry or sensor reliability.

At physical acceptance, confirm the original safety five still fail closed when the optional mux bus NACKs, present/valid mask and 350ms age from real serial, and at least 20 left/right/rear approach/retraction trials per direction. Check known surface materials, reflectivity, side walls and angles before enabling proactive camera prompts. Do not multiply by five purchased sets until one full pet is validated.

This is a full-feature sensor integration without discarding any of the other per-robot sensor, voice, vision, grasp, charging, dock, key/candy or peer conversation scope.

### November 12 shared I2C failure integration

A newly observed TCA9548A select/readback failure or bounded I2C transaction fault must invalidate optional side/rear readings across BOTH owners: `TofBus::failed` clears the adapter's cached optional validity, and WROOM `main.cpp` calls `BodyControl::invalidate_side_ranges` when `TofBus::errors()` advances. The WROOM `status.side_ranges.valid_mask` becomes zero immediately. The Mac `SideRangeEvents` owner already rejects a cleared valid bit and requires independent fresh readings before another event. No LLM or optional extra sensor gains motor authorization.

Source commits `dc9fb75`, `999f6f2`, `5006f24`, `034b346`, `81bb36d`, `84c58b4`, `77064ba`, and the C++ test string correction `aa63924`. Existing `tof_mux_tests.cpp` covered mux NACK, wrong/stuck readback and optional mux contention before this integration; do not add a duplicate driver or test file. New regressions cover invalid cached extras and WROOM published masks, but these specific tests remain **unexecuted** pending the full host CMake/fake Wire build and firmware compile. The real eight sensor wiring and geometry remain physically unqualified.
