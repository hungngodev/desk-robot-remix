# WROOM safety, wheel encoders and odometry

Take [the shared contract](00-contract.md). Deliver a deterministic, timestamped body pose estimate and the same local fault behavior with the Mac, Sense or network absent. Return measured uncertainty and stale state downstream. Keep the first body development and HIL tests disarmed or lifted until the appropriate fixture and cutoff gates pass.

## Own these changes

Own `code/firmware/body/`, its host tests and body-side pin allocation. Share the proposed `pose` reply with [30](30-sense-camera-and-interface.md) and [50](50-map-and-spatial-memory.md). Guide 70 owns the physical harness/CAD and cutoff validation. Deliver verified connector, current and encoder requirements to [10](10-requirements-and-shopping.md).

## Work in this order

1. **Reproduce the present behavior.** Run the existing `CliffGuard`, `TofBus`, `BodyControl`, `StepperDrive`, `AccessorySensors`, `TerminalIr` and reply-queue tests. Trace motor permission and loss of valid control from parser to output. Review the active stepper and guarded DC profiles and every protected motor, sleep, fault and heartbeat pin. Confirm 3.3 V levels, pullups, input-only pins, strapping and SRAM/timing margin before assigning encoder channels. Inspect the existing AS5600 usage and pinned upstream ESP32 counter support. [ESP-IDF 4.4 PCNT](https://docs.espressif.com/projects/esp-idf/en/release-v4.4/esp32/api-reference/peripherals/pcnt.html)
2. **Choose a source of actual wheel displacement.** Confirm encoder availability, placement, observed direction, gearing and counts at the loaded wheel. Count signed ticks with hardware-supported capture where the selected encoder supports it. If an angle sensor is the available interface, qualify wrap, sample rate and direction under worst-case wheel speed. Keep commanded position, emitted motor steps and measured wheel travel as distinct signals. Record accessible wheel motion, magnet/bracket fit, wheel radius, track width and travel per count. Keep unavailable state when the chosen hardware cannot report supported displacement.
3. **Estimate and invalidate pose.** At a bounded rate integrate paired measured wheel motion and calibrated IMU yaw with a monotonic clock. Apply zero-velocity correction only during qualified stationary intervals. Represent poor IMU quality, saturation, unmatched wheel samples, resets and stale timestamps as degraded or unavailable. Break the old origin on pickup and other continuity losses. Freeze navigation eligibility through a reboot or invalidation until a new trustworthy origin exists. Keep the counter snapshot and reply bounded and independent of the motor timing loop.
4. **Expose the versioned read-only reply.** Use the existing UART dispatch and output queue. Propose `pose` over 115200 baud, 8N1, ASCII CRLF with no arguments. Send version `v=1`, body boot identifier, origin, strictly increasing sample sequence, body monotonic sample-start time, `x_mm`, `y_mm`, `yaw_mrad` and `quality` (`valid`, `degraded`, `unavailable`). Agree bounded field widths, canonical names (`body_boot`, `origin`, `seq`, `sample_us`, `x_mm`, `y_mm`, `yaw_mrad`, `quality`) and the reply budget with 30 before deploying. Document exactly how origin and boot change and how timeout and an older body are represented. No pose read refreshes the control watchdog or arms the robot. Fuzz parser bounds locally as ordinary input validation, including overflow, repeated and truncated fields and unknown versions.
5. **Prove fault priority under load.** Preserve throughput for local ToF safety on `0x70` when accessory `0x71`, IMU, serial queue or encoder faults occur. Confirm local STOP and latch, watchdog expiration, reset and deliberate rearm. Run worst-case scheduled reads, heavy pose polling and simultaneous wheel counting. Measure loop latency and queue drops. Hand off the actual cutoff wiring and safe-state readings to 70 for separate CPU-stall validation.

## Head-to-body authority boundary

The production Sense background status poll and the HTTP status, aux, IR,
optics and pose routes issue only fixed read-only UART verbs; camera workers
and WiFi audio reconnection do not issue body control. The WROOM runs its
own active-wheel host silence limit (200 ms), maximum drive duration
(250 ms), and idle control watchdog (500 ms). Normal operator keepalive
can renew the host lease but cannot extend an existing drive pulse.
Only a local USB receiver may clear a body fault using `rearm`, after
healthy interlocks; recovery does not restore an old motion command.

The head cancels queued nonurgent transactions across STOP/HALT generations
and rejects ARM, drive, lift, grip and keepalive queued for 200 ms or more
before UART transmission. STOP/HALT are exempt from this age gate.
These defenses do not cryptographically authenticate the head-to-WROOM
UART. A compromised head that can emit otherwise valid operator commands
is outside the read-only endpoint guarantee; it still cannot use UART
`rearm` or override independent WROOM safety interlocks.

Run the native joint head-parser/WROOM regression with
`pytest -q firmware/head/tests/test_cross_board_safety.py` from `code/`.
The synthetic range readings test software timing only, not physical
cliff geometry, stopping distance or motor cutoff.

## Acceptance

- Run `cmake -S code/firmware/body -B /tmp/desk-robot-body-host -DBODY_SANITIZERS=ON -DCMAKE_BUILD_TYPE=Debug`, then `cmake --build /tmp/desk-robot-body-host --parallel 2` and `ctest --test-dir /tmp/desk-robot-body-host --output-on-failure`. Build `esp32_full` and `esp32_dc_full` with the pinned PlatformIO command in [host CI](../../../.github/workflows/host-verification.yml). Exercise no ticks during commanded motion, free spin, reverse counts on a bench, rollover, reboot, pickup, stale/degraded samples, mux faults, heartbeat loss and request flooding.
- Send guides 30 and 50 positive and negative UART fixtures plus the effective build profile and parameter units. Verify 250 ms motion bound, 500 ms loss of control, and safe responses to missing ranging. Tethered surface and hardware-cutoff measurements must carry the exact assembly and separate evidence IDs. [Electrical guard](../../hardware/dc-motor-independent-watchdog.md), [Cliff geometry](../../hardware/2026-11-17-vl53l0x-cliff-geometry-release.md)
