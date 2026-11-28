# Sense camera, body bridge and hardware coexistence

Take [the shared contract](00-contract.md). Deliver one authenticated Sense interface for fresh JPEG and read-only body pose evidence. Preserve the currently selected camera, display and audio path. Give Mac consumers realistic freshness constraints and measured timings.

## Own these changes

Own `code/firmware/head/sense/`, head overlay implementation, overlay installer and head tests. Coordinate any common overlay change with existing head variants. Guide 20 owns WROOM. Guide 50 owns the Mac pose parser and transforms. Guide 40 owns Mac speech policy. Send shared interface documentation and API examples to [90](90-integration-and-release-evidence.md).

## Work in this order

1. **Reconfirm the exact build.** Read the active Sense mapping and installed overlay at the current head. Keep the onboard PDM GPIO42/41, OLED GPIO5/6, I²S GPIO4/7/8, UART TX2/RX1 and stock camera mapping. Confirm WROOM UART RX16/TX17, 3.3 V signaling and common ground. Preserve the existing 32 kHz speaker-side rate for MAX98357A, 16 kHz PDM and AEC reference and pinned PCM conversion. Keep the current audio generation invalidation. Send fit and connector data for the speaker and mic to 70.
2. **Add pose forwarding on the existing authenticated bridge.** Agree guide 20’s `pose` wire fixture and version. Mirror the authorization and identity checks of `GET /api/ir` for `GET /api/pose`. Serialize requests on the existing UART lock with bounded reads, strict parse and expected command response matching. Return the current `robot_id` and exact validated body fields. Give old firmware an explicit unsupported status and timeouts or parse faults a bounded unavailable/error response. Preserve source clock units. Status polling cannot keep the body alive or retry in a way that blocks STOP or speech. Do not expose a raw UART command tunnel.
3. **Preserve fresh frame ownership.** Reuse `GET /api/camera.jpg`, frame buffers and existing camera lock shared by voice, grasp, in-session vision and HTTP. Preserve `X-Desk-Camera-Boot`, `X-Desk-Camera-Sequence` and `X-Desk-Camera-Complete-Us`. Treat completion time as a head monotonic JPEG encoding event. Capture into a bounded queue, release every frame on error/cancel, and define freshness when the head restarts. Measure buffering lag before changing discard/drain policy. Advance the sequence only for a newly encoded accepted frame and identify duplicate or replay reports. Keep existing clients compatible.
4. **Measure and document coexistence.** Capture camera timing with OLED, PDM, speaker and UART busy. Record per-run resolution/FPS settings, buffer or heap pressure, resets, duplicate detection and cancellation latency. Measure optical lag separately with a known changing target and application timestamps. Hand Mac the fixture needed to bracket a stationary camera request against pose/motion. Hold the last uncalibrated spatial observation outside control decisions.

## Sense scheduler invariants

The OLED task consumes one coherent WROOM status snapshot under a short lock that is never held across UART or display I/O. Missing and expired observations retain the fault display. Freshness and the continuous audio retry throttle use the full monotonic uptime; the initial audio delay is 10 seconds and retries are spaced at least 5 seconds apart, including across a 32-bit millisecond rollover. Keep the existing BOOT privacy latch and Xiaozhi transport failure epoch as independent admission gates. Host tests do not qualify physical audio, display latency or motor STOP timing.

## Acceptance

- From `code/`, run `uv run --no-sync pytest -q firmware/head/tests tests/test_head_camera_bench.py tests/test_bench_head_camera.py`. Use the Sense ESP-IDF job in [host CI](../../../.github/workflows/host-verification.yml) for the pinned target build. Pass authenticated and unauthenticated requests, wrong robot IDs, old firmware, malformed or out-of-range wire data, busy UART, sequence replay, reboot and cancellation. Exercise camera contention with voice and confirm traffic cannot delay a stop command beyond the current contract.
- Deliver a positive JSON fixture with an unchanged body boot/origin, a distinct reboot fixture, an unavailable response and three JPEG headers with their units. Capture physical optical lag and actual audio coexistence evidence before claiming the hardware passes. [Interface contract](../../guides/interfaces.md), [Sense AEC](../../guides/sense-aec-port.md)
