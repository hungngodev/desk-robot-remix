# Verification — 2026-10-28

Software preparation is complete for the first physical build stage. **The robot
has not been printed, assembled, flashed or physically tested.** This is an
experimental integration, not a validated autonomous pickup product.

## Evidence

| Check | Result |
| --- | --- |
| WROOM firmware, PlatformIO 6.1.18/espressif32 6.9.0 | Build succeeds; 273185 flash bytes, 21840 static RAM bytes |
| Body portable C++ control tests with address/undefined-behavior sanitizers | 20/20 pass |
| Head overlay install/remove/drift/pin tests and native command/ACK tests | 6/6 pass |
| Separate CoreS3 head, pinned ESP-IDF release/v6.1 | Build succeeds, app about 2.54 MiB; no flashing |
| Laptop API/control/calibration/transport/conversation/server adapter/budget/trial checks | 35/35 pass |
| Upstream Xiaozhi host suite against the overlaid build | 143 tests run, 142 pass, one skipped |
| Ruff and whitespace checks | Pass |
| Simulation demo | Pickup logic succeeds; six total alternating utterances; physical acceptance remains false |
| Budget/trial gates | Reject incomplete quotes and empty physical trial records as intended |
| Source restore | Four pinned upstream revisions verified; source clones unchanged |

The skipped upstream host MCP test requires host C++23/cJSON/mbedTLS development
headers absent on this Mac. Firmware MCP code was compiled by the ESP-IDF build.
There is one non-failing Starlette test-client deprecation warning. Host C++
checks use the installed macOS SDK C++ include path described in `docs/build.md`.

Firmware hashes are in `build-artifacts.json`. The head verification binary has
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
bash scripts/build_head.sh
uv run desk-robot --config config/simulation.toml demo
python3 scripts/check_budget.py
python3 scripts/check_trials.py
```

Use the C++ include workaround in the build guide if the local compiler cannot
find standard headers. The upstream suite is run from its build copy with the
coordinator Python and the same include-path workaround.

## Scope and quality review

The final integration keeps the stock camera/audio/display drivers and a unique
board identity, and adds a version-checked reversible overlay. The body has a
strict bounded parser, boot disarm, independent drive deadline and watchdog.
Invalid commands/status polls do not renew control. Watchdog keeps last servo
PWM; explicit disarm detaches. An uncertain ACK is never retried as movement.

The head starts its bridge after Wi-Fi/lwIP initialization; camera capture runs
outside the control HTTP task, and JPEG storage is released before deleting the
FreeRTOS task. Camera snapshots and upstream capture/explain share one lock.
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

- Download/inspect the original STL files and confirm the two linked lift files'
  originating terms. No CAD files have been edited; Fusion MCP is unavailable.
- Measure actual servo fit and flat-key floor clearance, print and bench-test the
  gripper. Perform ten trials per key/candy category before the full build.
- Finalize motor and battery/charger quotes, mounting clearance and current
  capability. The $123.25 figure includes allowances; purchase readiness is false.
- Confirm the real WROOM board/USB port and CoreS3 Lite LCD revision. No serial
  port has been selected and no firmware uploaded.
- Verify voltage stability, current/temperature, stopping time, motor polarity,
  camera frames, microphone, speaker and UART on real hardware.
- Install/run Qwen3, SenseVoice, Kokoro and YOLO-World weights/providers. They were
  not downloaded; FFmpeg is currently absent. Full voice/vision inference has not
  been exercised. The base demo uses mock speech and generated images.
- Measure camera geometry and raised-jaw visibility. A planar projection and two
  image detections can misidentify a pickup; human physical trials remain separate.
- Assemble/validate robot two only after robot one achieves >=8/10 per category.
  Test distinct addressing, actual audio turn-taking, disconnects and cancellation.

`physical-trials.csv` is an empty recording template. `physical-summary.json`
correctly records zero actual attempts and no physical acceptance pass.
