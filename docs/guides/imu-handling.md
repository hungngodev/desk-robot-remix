# Real MPU6050 handling reactions from already-integrated WROOM telemetry

Status 2026-11-11: **source integrated and mock tests committed, no real IMU orientation or activity threshold calibrated**. This is one additional part of the original full five-robot product, not a substitute for local cliff/bumper safety.

## No new board, bus, motor owner or IMU driver

The first pet already uses an MPU6050 on the WROOM upstream 3.3V I2C bus (SDA GPIO21, SCL GPIO22). Existing code `code/firmware/body/lib/BerryImu/BerryImu.cpp` reads raw acceleration/rotation at up to 20Hz, using the actual MPU6050 manufacturer's registers. It wakes the board, configures `ACCEL_CONFIG 0x00` as ±2g, `GYRO_CONFIG 0x00` as ±250 degrees/s, and publishes `imu.family=4`, `imu.valid`, `imu.age_ms`, `imu.acc[3]`, `imu.gyro[3]` in the already authenticated WROOM body status. This data exists **independently of video and network inference**.

The new `code/laptop/src/desk_robot/handling.py` consumes those exact values and physical scales (16,384 counts/g, 131 counts per degree per second). It adapts the physically grounded distinction used by [xioTechnologies/Fusion](https://github.com/xioTechnologies/Fusion) between a gravity orientation measurement under low rotation and movement where dynamic acceleration makes tilt inference unreliable. **We do not copy or pretend to run its full calibrated AHRS**, because the robot has not measured body axes, temperature drift, or magnetic heading. The read-only handler now computes a provisional per-session gyro zero-rate offset from eight fresh quiet MPU6050 samples. It rejects calibration if any gyro axis wanders more than 1 degree per second from its eight-sample mean, and subtracts the stable bias from subsequent rotation magnitude checks. This is software stationarity screening only, not a measured factory bias, qualified orientation or temperature-compensated AHRS. This small adapter instead uses source raw magnitudes and a startup gravity direction, enough for conservative, opt-in playful pet reactions.

## Event path and behavior

1. The existing WROOM safety loop polls local cliff/obstacle/bumper/touch and remains the sole motor authority.
2. The same WROOM firmware separately samples MPU6050 raw six-axis values. No new `Wire.begin()`, mux lane, busy-wait or GPIO is needed.
3. The XIAO head forwards the existing body status. The Mac's dedicated touch/status task (approximately every 150ms) calls `PetController._observe_imu()` **after** checking WROOM local safety faults.
4. The Mac demands `family == 4`, actual source `valid == true`, `age_ms <= 200`, 16-bit integer arrays and both commanded wheels at zero with no active drive permit. It does not reuse BerryIMU values under a false MPU scale or react to movement caused by the robot's own commanded tracks.
5. Unless `handling_interactions_qualified == true`, no event or memory is emitted. After explicit opt-in, the first eight consecutive quiet samples with approximately 1g acceleration establish the **current physically placed upright** reference and a local zero-rate gyro bias estimate. An unstable eight-sample gyro mean rejects calibration rather than averaging real movement into zero. Continuous motion or any stale/disconnected source resets that reference.
6. Two subsequent sustained samples outside a chosen orientation angle generate a single `handling_tilt` edge. Returning within half that angle clears the event latch. This is a *relative pose change*, not a calibrated absolute axis/roll and not proof that someone picked it up.
7. Two bursts where acceleration deviates from 1g together with marked gyro rotation generate one `handling_shake` event with a three-second rate limit. The gyro gate is essential: a bump or sensor noise alone must not be called a shake.
8. `PetController` records an honestly attributed first-hand sensor observation, optionally suggests a short spontaneous reaction when the existing pet speaker lease permits, and triggers the **same** camera frame scheduler through `handling_tilt` or `handling_shake`. That is the intended sensor + camera + speech fusion. No camera image or memory can operate the motors.

## Physical setup and exact operator procedure

Before opting in, use the original firmware's read-only USB status and verify the actual labelled MPU6050 breakout, level shifter/pullups (3.3V bus), board orientation, wiring security and stable 1g resting magnitude. Do not assume the photo of a BerryIMU uses MPU6050 sensitivity.

In the real private `code/config/local.toml` under the specific `[[robots]]` after actual physical qualification:

```toml
handling_interactions_qualified = true
handling_tilt_threshold_deg = 38
handling_shake_delta_mg = 550
```

Place the assembled pet upright on a stable flat desk with its tracks stopped. Start pet mode. Hold it still for at least the first eight 150ms reads so the software learns a relative gravity baseline, then gradually tilt and return to neutral, followed by a short careful hand movement. The two event kinds must correspond to real recorded body status before allowing spontaneous voice reactions. Start with `quiet = true` if you need to observe sensor memory without sound. In the absence of any verified IMU module or mounting, leave the default `false`.

The example thresholds above are **not factory safety settings**; they are software bounds that still require tuning against measured data from the actual hardware. A failed/offline IMU, commands in motion, invalid types, a long sample gap or unknown BerryIMU family must yield **no handling event**. No motor stop, servo permit, automatic roaming or charging result is based on these gestures.

## Reproducible threshold candidate from real WROOM frames

After collecting actual read-only WROOM status JSON from **one** stationary
mounted robot, prepare a JSON Lines file with at least 8 independent upright
conversions, 4 deliberate held tilts and 4 actual gentle shakes, plus the
separate repeat trials below. Each line has a physical label, monotonic
acquisition time, flashed firmware revision, mechanical IMU mount revision
and the **unchanged real body status object**, including motor and IMU fields:

```json
{"label":"upright","time_monotonic_s":100.0,"firmware_commit":"actual-flashed-sha","mount_id":"actual-imu-mount","body":{"drive_ms":0,"motor":{"m0":0,"m1":0},"imu":{"family":4,"gyro_id":104,"valid":true,"age_ms":20,"boot_id":123,"sample_ms":100000,"acc":[0,0,16384],"gyro":[0,0,0]}}}
```

That row is an **illustrative format only**, not proof of a captured MPU6050
conversion. Do not submit copied or synthetic rows as physical evidence.
Capture genuine GPIO/I2C body status from the currently flashed WROOM, maintain
monotonically increasing sample_ms, and retain the raw log, unit identity,
mounting orientation and physical rig notes. During all these observations,
wheel command and drive permit must be zero; use controlled benchtop handling
without loaded wheel movement.

The repository also provides an optional **read-only** capture helper which
polls the existing authenticated Mac WROOM status route and refuses moving
wheels, wrong robot identity, stale acquisitions and rebooted WROOM epochs.
The operator must physically establish each labeled condition when prompted;
the helper never moves or arms the robot. From `code/`, after configuring the
private API token through [Local AI setup](local-ai.md). Use the actual coordinator
URL (default port 8765, not the capture helper's historical 8008 default) and
its operator bearer environment name, not the model tool credential. Keep
actuator power disconnected for these hand-applied trials. Save the trial in a
new ignored private directory/file, and substitute the actual flashed firmware
SHA, mount identity and robot ID:

```bash
uv run --no-sync --env-file config/local.env python scripts/capture_handling_trials.py \
  --url http://127.0.0.1:8765 --token-env DESK_ROBOT_API_TOKEN \
  --robot robot-01 --firmware-commit ACTUAL_FLASHED_SHA --mount-id ACTUAL_MOUNT \
  --output config/local.handling-trials.jsonl
uv run --no-sync python scripts/calibrate_handling.py config/local.handling-trials.jsonl
```

If the private coordinator configuration uses a different port or token name,
pass the actual value. The capture helper rejects an existing output path;
retain each raw trial under its own private filename. Preserve all native
low-g metadata in the original IMU object when present: `low_g_valid` must be
true, `low_g_irq` false, and `low_g_seq` unchanged across all three phases.
A native low-g event, mixed metadata, reboot or acquisition replay invalidates
the trial rather than becoming a qualified handling threshold.

The JSONL records a host monotonic **receipt time**, not a synchronized IMU
conversion clock. Only actual `imu.sample_ms` and `imu.boot_id` establish
conversion sequence and physical boot provenance. Preserve the separate
hardware stopwatch/thermal notes rather than inventing timestamps.

You can also collect real status evidence independently and run from `code/`:

```bash
uv run --no-sync python scripts/calibrate_handling.py path/to/actual-trials.jsonl
```

The checker shares the existing MPU6050 raw decoder and manufacturer scales.
It rejects mixed mounts or firmware, boot resets, repeated/stale samples,
unstable stationary gyro offsets, implausible acceleration and overlapping
positive versus negative angle or shake distributions. It reports separate
candidate tilt degrees and shake delta milligravity within runtime bounds,
together with observed class separation, **not** a physical certificate.
Only after independently confirming the ten-repeat acceptance trials, hot/cold
gyro offset behavior, mounting axes, false reactions, sensor timing and lack
of motor authority may the operator copy those candidate knobs into the
private local configuration and set `handling_interactions_qualified=true`.

The automated tests of this checker use synthetic frames exclusively to prove
its failure conditions. Its JSON always reports
`thresholds_physically_qualified=false` and
`motor_authorization=false` even if supplied samples separate perfectly.

## Acceptance checklist

* Use an actual serial trace from the real WROOM with at least 8 stationary frames from the physically upright mounted MPU6050, verified axes, counts, temperature, freshness and startup gyro zero-rate bias. Repeat startup after cold and warm operation and record drift; the source does not yet perform temperature compensation. A different six-axis breakout requires its own scaling and version check.
* Repeat 10 stationary quiet episodes, 10 deliberate body tilts (return to neutral each time), 10 actual hand movements, 10 robot self-driven motor turns, and 10 deliberately stale/disconnected or forged status frames.
* Require that the Mac reports motion only on the operator-qualified cases, never invents a person's identity, pickup, gesture or visual observation, and never authorizes motion. Record false positives, missed events and VLM first-response latency.
* Verify new triggered camera frames reflect the **same physical robot** and do not interrupt urgent WROOM safety or the human's own speech.
* Store the measurements in `docs/records/` and link the actual hardware test commit before marking `BENCH_VERIFIED`.

## Source and test map

`code/laptop/src/desk_robot/handling.py` is the small new read-only classifier. `code/laptop/src/desk_robot/pet.py` connects it to the real head status, provenance memory, existing group speech lease and camera hub. `code/laptop/src/desk_robot/multimodal.py` accepts the two kinds as selected frame triggers. `code/tests/test_handling.py` checks the pure raw scaling, fresh status rules, hysteresis, timing, startup posture and inert behavior by default. `code/tests/test_handling_integration.py` checks the real pet to memory/trigger route with a simulated WROOM payload, no robot body or audio hardware. Neither file is a real board test.

**Reused references:** [xioTechnologies Fusion, MIT](https://github.com/xioTechnologies/Fusion), [jrowberg i2cdevlib MPU6050 registers](https://github.com/jrowberg/i2cdevlib), [InvenSense MPU6000/6050 specification](https://jensd.dk/edu/space/cansat/gy80gy87gy88gy91/datasheet/MPU6050.pdf). We reuse actual firmware register/scales and conservative measurement concepts rather than transcribing unrelated full fusion state machines.
