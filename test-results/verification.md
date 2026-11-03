# Verification — current design updated 2026-11-03

## Current firmware foundation

Sense8MB/PDM/SSD1306 head target and stepper/DC body profiles now compile.
Portable stepper timing and sensor-fault policy are integrated with local-only
recovery: normal job arm cannot clear a fault. The stepper hardware adapter
provides no sensor I/O or calibration, so it refuses arming. Pet animation,
scheduler, memory and pet-mode motion lease remain unimplemented.

No hardware is flashed, assembled or physically accepted; no geometry changed.
Host tests and compilation do not prove camera/audio, mechanical fit, real sensor
behavior, stopping distance or pickups. See
[firmware progress](../docs/firmware-foundation.md) and
[current evidence](firmware-foundation-2026-11-03.json).

Two stepper originals are saved with hashes; source integrity is not mechanical
qualification. The twelve-video audit covers descriptions/resources and selected
code, not full-frame viewing. The conditional target remains $35.45 before charges
and missing reused parts; procurement readiness is false.

[Earlier plan-update verification](plan-update-2026-11-03.json) records the prior
documentation-only checkpoint. The historical90 checks below are a separate older
baseline and do not include these new components.

## Historical software baseline — 2026-10-30

The plan at that date was five identical cores with removable cosmetics, generic
SG90/N20 actuators, separate camera/OLED/audio modules and existing print files.
**90 checks pass: 60 Python, 20 body C++, 10 head overlay/protocol/snapshot.**
Five-robot mock conversation gives all five IDs two turns. No robot has been
printed, assembled, flashed or physically tested.

The **$36.88 first-prototype parts target** assumes one owned usable power bank
and WROOM. It excludes delivery/tax and includes three allowances; the $50 delivered
cap is not yet established. The $7.11 S3/OV2640 bundle is not qualified against
the compiled Freenove pinout/programming/case. Purchase readiness remains false.
See [ten checks](../docs/budget-audit.md) and [fleet guide](../docs/five-robots.md).

## Evidence

| Check | Result |
| --- | --- |
| WROOM firmware, PlatformIO 6.1.18/espressif32 6.9.0 | Previously built; exact artifact size/hash in build-artifacts.json; no firmware changes this revision |
| Body portable C++ control tests with address/undefined-behavior sanitizers | 20/20 pass |
| Both head overlays, reversible install/remove/drift, pin/config checks, native protocol/ACK and fresh-JPEG boundary tests | 10/10 pass |
| Active modular S3 head, pinned ESP-IDF release/v6.1 | Build helper exits 0; app 2500528 bytes, merged 8658489 bytes; no flashing |
| Separate CoreS3 head, pinned ESP-IDF release/v6.1 | Build succeeds, app about 2.54 MiB; no flashing |
| Laptop API/control/calibration/transport/conversation/server adapter/budget/trial and head-identity checks | 60/60 pass |
| Earlier upstream Xiaozhi host suite against the CoreS3 build | 143 tests run, 142 pass, one skipped; historical evidence, not rerun for the modular variant |
| Ruff and whitespace checks | Pass |
| Simulation demo | Generated-image pickup logic succeeds; ten total round-robin utterances across five IDs; physical acceptance remains false |
| Budget/trial gates | Reject incomplete quotes and empty physical trial records as intended |
| Source restore | Four pinned upstream revisions verified; source clones unchanged |
| EVA case | Original 300027-byte 3MF saved; four actual meshes, millimeter units, bounds and SHA-256 verified; no geometry edits |
| Gripper/lift sources | Five original STLs saved, binary record lengths/bounds/hashes checked; original-author CC BY 4.0 versus CC BY-NC-SA 4.0 provenance resolved; no slicing/physical checks |
| SMARS sources | Four original matching screwless chassis/wheel/track STLs and original assembly PDF/ZIP saved; structure/bounds/hashes checked; documents not yet reviewed for print quantities |

The modular build is independent of the preserved CoreS3 copy. Its 15 generated
overlay files were compared byte-for-byte with the current overlay sources.
The actual sdkconfig selects 16 MB flash, octal PSRAM, camera SCCB I²C0 with the
new driver, and OLED I²C1. The camera driver's default I²C1 would conflict with
the OLED; explicit Kconfig selection and a compile guard prevent that setting.
Both dependency locks match the pinned project copy. No camera/audio/display
driver was rewritten. Compilation and fake capture/encoding tests do not prove
actual peripheral behavior or case fit.

Case/source records are under `cad/originals/`. All 13 original CAD/document
files matched saved hashes, STL binary lengths and archive/PDF structure checks.
This is source validation, not topology, slicing or physical-fit validation.
The EVA 3MF requires its four objects to be arranged on the print bed.

The skipped upstream host MCP test requires host C++23/cJSON/mbedTLS development
headers absent on this Mac. Firmware MCP code was compiled by the ESP-IDF build.
There is one non-failing Starlette test-client deprecation warning. Host C++
checks use the installed macOS SDK C++ include path described in `docs/build.md`.

Firmware hashes and board identities are in `build-artifacts.json`. Both head
verification configurations have
an **empty bridge token** and disabled wake word; it is a compile artifact, not
personalized local-server firmware. Generate private settings before any flash.
Build output and private settings are excluded from Git.

Useful local checks from the project root:

```sh
uv run --extra dev pytest -q
uv run --extra dev ruff check laptop/src laptop/server/overlay laptop/server/*.py tests scripts firmware/head/*.py
cmake --build .tools/body-host
ctest --test-dir .tools/body-host --output-on-failure
python3 -m unittest discover -s firmware/head/tests -v
bash scripts/build_head.sh --board modular
uv run desk-robot --config config/fleet.simulation.toml demo
python3 scripts/check_budget.py
python3 scripts/check_trials.py
```

Use the C++ include workaround in the build guide if the local compiler cannot
find standard headers. The upstream suite is run from its build copy with the
coordinator Python and the same include-path workaround.

## Five-unit additions verified 2026-10-30

- Two-to-five participants; distinct IDs, bounded dynamic limits (six/six/eight/ten),
  independent histories, every utterance delivered digitally to all peers.
- No overlapping transmissions; all-five mute/session cleanup on completion,
  cancellation, repeated stop, a canceled stop caller, stopped queued speech,
  encoding interruption and disconnected/replaced heads tested.
- API/CLI reject duplicates, oversized groups and invalid turn counts; legacy
  pair limits retained. Hardware fleet examples have motion off and blank real
  device IDs; each duplicate still needs its own measured calibration.
- Missing credentials append without rotation, reject symlinks/duplicate entries,
  retain existing file bytes and use mode 0600. Three new fleet credentials were
  added to ignored local.env; all previous content preserved and no values shown.
- Private head settings resolve the selected fleet's exact credential name.
  Temporary fifth-head fixture verifies ID/token selection, stale-setting removal,
  unchanged public config, restrictive permissions and no token output.
- Named head/power/current readiness gates prevent an allowance-based cheap list
  from being reported as order ready. Original CAD remains unchanged.

Current commands: `.venv/bin/pytest -q` (60 pass), Ruff plus whitespace checks
(pass), `ctest --test-dir .tools/body-host --output-on-failure` (20 pass), head
unittest suite (10 pass, with the documented local SDK C++ include path). No
runtime firmware source changed, so prior head/body builds are preserved rather
than presented as builds for the unqualified cheap camera board.

## Scope and quality review

The final integration keeps the stock camera/audio/display drivers and a unique
board identity, and adds a version-checked reversible overlay. The body has a
strict bounded parser, boot disarm, independent drive deadline and watchdog.
Invalid commands/status polls do not renew control. Watchdog keeps last servo
PWM; explicit disarm detaches. An uncertain ACK is never retried as movement.

The head starts its bridge after Wi-Fi/lwIP initialization; camera capture runs
outside the control HTTP task, and JPEG storage is released before deleting the
FreeRTOS task. Camera snapshots and upstream capture/explain share one lock.
The modular snapshot adapter captures anew before encoding, rejects failed or
unsupported frames and bounds encoded output. The OLED initially shows stock
monochrome emotion glyphs/text; smooth EVA-style eyes remain a later adapter.
Normal voice motion goes through the coordinator; raw head motion tools are
opt-in debugging to avoid competing commands or a stop that later resumes a job.

The coordinator consumes a short, per-robot operator permit, bounds job duration,
cancels on keepalive failure and sends stop on exit. Tests exercise invalid
calibration, wrong ACK/identity, camera/lost-target failures, cancellation,
deadlines and conversation limits. Model credentials cannot enable movement.
The speech adapter checks selected device identities, suppresses acoustic input
while routing digital transcripts and reports transmission rather than measured
playback. These are software checks and source review, not independent hardware
or mechanical certification.

## Still unverified / next actions

- Review original assembly documents for print quantities/orientation; perform
  slicer/topology/fit checks. Source files are collected, not edited or sliced;
  Fusion MCP was unavailable; no geometry changes have been made.
- Measure actual servo fit and flat-key floor clearance, print and bench-test the
  gripper. Perform ten trials per key/candy category before the full build.
- Qualify the cheap head board, actual generic driver package, motor/servo loaded
  currents and existing power bank rating/weight/mount. Finalize speaker mounting and
  delivered charges under $50; $36.88 is a target with allowances, not a cart.
- Confirm exact selected camera sensor/lens, display PCB mount, speaker size and
  head-to-rover bracket/clearance. No component is a measured case drop-in yet.
- Bench-test the compiled modular S3 head and fresh-JPEG adapter on actual
  modules. Confirm OLED address/orientation and camera sensor/byte order. The
  old CoreS3 image cannot be used on the Freenove board.
- Confirm the real WROOM board/USB port. No serial port has been selected and no
  firmware uploaded.
- Verify voltage stability, current/temperature, stopping time, motor polarity,
  camera frames, microphone, speaker and UART on real hardware.
- Install/run Qwen3, SenseVoice, Kokoro and YOLO-World weights/providers. They were
  not downloaded; FFmpeg is currently absent. Full voice/vision inference has not
  been exercised. The base demo uses mock speech and generated images.
- Measure camera geometry and raised-jaw visibility. A planar projection and two
  image detections can misidentify a pickup; human physical trials remain separate.
- Duplicate the validated core four times only after robot one achieves >=8/10
  per category. Test all-five addressing, physical audio timing, disconnects,
  cancellation and cosmetic clearance. Exact owned fleet inventory is unknown.

`physical-trials.csv` is an empty recording template. `physical-summary.json`
correctly records zero actual attempts and no physical acceptance pass.
