"""Bounded tactile grasp using distinct fresh ADS1115 jaw sample sequences."""
from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .calibration import Calibration
    from .transport import Head

# An optional accessory ADC read must not indefinitely hold a live jaw.
# The real HTTP head already has its own transport timeout; this also
# bounds a stalled alternate head adapter before the next servo pulse.
_FORCE_READ_TIMEOUT_S = 2.0
# The transport has its own request deadline, but preserve local bounds for
# alternate head adapters and cancellation after an unacknowledged jaw pulse.
_GRIP_COMMAND_TIMEOUT_S = 2.5
_HEALTH_READ_TIMEOUT_S = 2.5
# Seven multiplexed accessory lanes and alternating ADS1115 belly/jaw
# conversions can take ~336 ms between real jaw acquisitions. Retry an
# unchanged, still-valid sequence within a bounded deadline rather than
# mistaking a healthy ADC for a stall after one 180 ms sleep.
_JAW_FRESH_WAIT_S = 0.45
_JAW_POLL_INTERVAL_S = 0.075
_JAW_MAX_POLLS = 5


# At four degrees per independent conversion and ~336 ms cadence, a full
# 60-degree opening can take about five seconds. This is a bounded software
# wait, not a physical timing guarantee.
_RELIEF_WAIT_S = 6.0
_RELIEF_POLL_INTERVAL_S = 0.075


async def await_commanded_jaw_target(
    health: Callable[[], Awaitable[dict]], target: int,
) -> None:
    """Wait for commanded opening, never infer measured position or force."""
    from .controller import OperationError

    async with asyncio.timeout(_RELIEF_WAIT_S):
        while True:
            status = await health()
            servo = status.get("servo")
            if (not isinstance(servo, dict)
                    or servo.get("attached") is not True
                    or servo.get("position_source") != "commanded"
                    or type(servo.get("grip_target")) is not int
                    or servo["grip_target"] != target
                    or type(servo.get("grip")) is not int
                    or not 60 <= servo["grip"] <= 120):
                raise OperationError("Gripper commanded target not confirmed")
            if servo["grip"] == target:
                return
            await asyncio.sleep(_RELIEF_POLL_INTERVAL_S)


def grip_angles(start: int, end: int, step: int) -> tuple[int, ...]:
    if (type(start) is not int or type(end) is not int or type(step) is not int
            or not 60 <= start <= 120 or not 60 <= end <= 120
            or start == end or not 1 <= step <= 4):
        raise ValueError("Measured servo limits required")
    direction = 1 if end > start else -1
    return tuple([start, *range(start + direction * step, end, direction * step), end])


def force_observation(payload: dict) -> tuple[int, int]:
    """Raw ADC jaw + independent hardware conversion sequence."""
    group = payload.get("force") if isinstance(payload, dict) else None
    jaw_valid = group.get("jaw_valid", group.get("valid")) if isinstance(group, dict) else None
    if (not isinstance(group, dict) or jaw_valid is not True
            or group.get("calibrated") is not False
            or not isinstance(group.get("adc"), list) or len(group["adc"]) != 2
            or type(group["adc"][1]) is not int
            or not -32768 <= group["adc"][1] <= 32767
            # A clipped ADC cannot establish the jaw's actual force.
            or group["adc"][1] in (-32768, 32767)  # saturated ADS1115
            or type(group.get("jaw_seq")) is not int
            or not 1 <= group["jaw_seq"] <= 0xffffffff
            # Older bench adapters may omit jaw age. Real WROOM firmware
            # reports it from the jaw conversion, never the belly channel.
            or ("jaw_age_ms" in group and (
                type(group["jaw_age_ms"]) is not int or
                not 0 <= group["jaw_age_ms"] < 500))):
        raise ValueError("Missing, invalid or stale ADS1115 gripper sample")
    return group["adc"][1], group["jaw_seq"]


def force_adc(payload: dict) -> int:
    return force_observation(payload)[0]


def _fresh_jaw_sequence(new: int, previous: int) -> bool:
    """Accept only forward ADS1115 hardware conversions, including uint32 wrap.

    WROOM's 32-bit acquisition counter may roll over, skipping the invalid
    zero sentinel. Half-range ordering rejects old/replayed and reset frames.
    """
    delta = (new - previous) & 0xffffffff
    return 0 < delta < 0x80000000


async def guarded_grasp(
    head: "Head", calibration: "Calibration",
    *, robot_id: str, health: Callable[[], Awaitable[dict]],
) -> dict:
    from .controller import OperationError, _bounded_head_reply

    threshold = calibration.grip_force_delta_raw
    ceiling = calibration.grip_force_limit_raw
    if threshold is None or ceiling is None:
        raise OperationError("Measured gripper sensor calibration missing")
    if not isinstance(robot_id, str) or not robot_id:
        raise ValueError("Gripper requires the configured robot identity")

    force_boot_seen = False
    force_boot_id: int | None = None
    force_boot_changed = False

    async def read_force() -> tuple[int, int, float]:
        nonlocal force_boot_seen, force_boot_id, force_boot_changed
        started = time.monotonic()
        sample = await _bounded_head_reply(
            head.aux_status(), seconds=_FORCE_READ_TIMEOUT_S,
            timeout_message="ADS1115 jaw force read timed out",
        )
        if not isinstance(sample, dict) or sample.get("robot_id") != robot_id:
            raise ValueError("Foreign or missing jaw sensor robot identity")
        # Fence a new or unknown WROOM epoch before decoding any jaw data.
        # A simultaneous channel fault must not mask a reboot and allow relief.
        group = sample.get("force")
        observed_boot = group.get("boot_id") if isinstance(group, dict) else None
        if (type(observed_boot) is not int
                or not 1 <= observed_boot <= 0xffffffff):
            # A zero or malformed boot after movement cannot authorize even
            # a relief pulse against a possibly reset controller.
            if force_boot_seen:
                force_boot_changed = True
            raise ValueError("Missing or invalid WROOM boot identity for jaw evidence")
        if force_boot_seen and observed_boot != force_boot_id:
            # Across a CPU reboot the jaw sequence may look like uint32 wrap.
            # Do not issue another close OR a best-effort relief on the new
            # unarmed session, even if an alternate health adapter says yes.
            force_boot_changed = True
            raise ValueError("WROOM reboot invalidated grasp force sequence")
        observation = force_observation(sample)
        # Read-only legacy adapters may infer validity from composite force.valid,
        # but physical jaw motion needs the actual fresh jaw ADC channel verdict.
        if group.get("jaw_valid") is not True:
            raise ValueError("Missing independent jaw ADC channel validity")
        # Physical servo movement must not trust a legacy/partial AUX
        # adapter with no acquisition clock or reboot fence. Keep the
        # optional metadata allowance in force_observation for read-only
        # inspection, but require both fields at this motion boundary.
        age_ms = group.get("jaw_age_ms")
        if type(age_ms) is not int or not 0 <= age_ms < 500:
            raise ValueError("Missing or expired jaw ADC acquisition age")
        # Charge the full AUX round trip against the acquisition lifetime.
        # Preserve this deadline across every later awaited health check.
        expires_at = started + (500 - age_ms) / 1000
        if time.monotonic() >= expires_at:
            raise ValueError("Missing or expired jaw ADC acquisition age")
        force_boot_seen = True
        force_boot_id = observed_boot
        return *observation, expires_at

    async def confirmed_health() -> dict:
        nonlocal force_boot_changed
        # The normal Coordinator raises for disarmed/foreign WROOM status,
        # but an alternate head/health adapter may merely return a false
        # verdict. Never interpret completion of that callback as a permit.
        status = await _bounded_head_reply(
            health(), seconds=_HEALTH_READ_TIMEOUT_S,
            timeout_message="Gripper WROOM health check timed out",
        )
        if (not isinstance(status, dict)
                or status.get("armed") is not True
                or ("robot_id" in status and status["robot_id"] != robot_id)):
            raise OperationError("Gripper operation blocked by WROOM health")
        # A fresh armed verdict from a different WROOM boot cannot authorize
        # a jaw pulse against an older ADC sample. The production WROOM
        # status carries imu.boot_id; allow older minimal test adapters with
        # no imu group, but fail closed if a supplied identity is missing,
        # invalid or disagrees with the force source.
        if "imu" in status:
            imu = status["imu"]
            health_boot = imu.get("boot_id") if isinstance(imu, dict) else None
            if (type(health_boot) is not int
                    or not 1 <= health_boot <= 0xffffffff
                    or health_boot != force_boot_id):
                force_boot_changed = True
                raise OperationError("Gripper WROOM health boot mismatched jaw source")
        return status

    async def read_new_jaw(previous_seq: int, failure: str) -> tuple[int, int, float]:
        """Wait for one distinct same-boot conversion, not repeated cached ADC.

        Old/backward sequence values, invalid sample age, a changed boot or
        failed local safety authority immediately veto another jaw pulse.
        A healthy but not-yet-updated ADS1115 may consume at most one bounded
        wait; no fresh result is synthesized from elapsed time.
        """
        async with asyncio.timeout(_JAW_FRESH_WAIT_S):
            for attempt in range(_JAW_MAX_POLLS):
                measured, seq, expires_at = await read_force()
                if _fresh_jaw_sequence(seq, previous_seq):
                    return measured, seq, expires_at
                if seq != previous_seq or attempt == _JAW_MAX_POLLS - 1:
                    raise OperationError(failure)
                await asyncio.sleep(_JAW_POLL_INTERVAL_S)
                await confirmed_health()
        raise OperationError(failure)

    try:
        baseline_a, seq_a, _ = await read_force()
        # A seven-lane mux can expose the same last completed conversion
        # after 180 ms. Poll for a new hardware ID before declaring a stall.
        await asyncio.sleep(0.18)
        baseline_b, seq_b, jaw_expires_at = await read_new_jaw(
            seq_a, "No new ADS1115 jaw sample; jaw not moved",
        )
    except (KeyError, TypeError, ValueError, AttributeError,
            TimeoutError) as exc:
        raise OperationError("Fresh force feedback required before moving jaw") from exc
    if abs(baseline_a - baseline_b) > max(40, threshold // 3):
        raise OperationError("Gripper baseline unstable; jaw not moved")
    baseline = (baseline_a + baseline_b) // 2
    latest_seq = seq_b
    motion_attempted = False
    try:
        for angle in grip_angles(
            calibration.grip_open, calibration.grip_closed, calibration.grip_step_deg
        )[1:]:
            await confirmed_health()
            if time.monotonic() >= jaw_expires_at:
                raise OperationError("Jaw ADC evidence expired before closing dispatch")
            motion_attempted = True
            reply = await _bounded_head_reply(
                head.command(f"grip {angle}"), seconds=_GRIP_COMMAND_TIMEOUT_S,
                timeout_message="Gripper servo command unconfirmed",
            )
            # A missing receipt is an uncertain pulse, not a successful close.
            # Even alternate adapters must return the exact authenticated ACK.
            if (type(reply) is not dict
                or reply.get("ok") is not True
                or reply.get("robot_id") != robot_id
                or reply.get("reply") != f"OK grip angle={angle}"
            ):
                raise OperationError("Unmatched gripper command ACK")
            await asyncio.sleep(0.18)
            await confirmed_health()
            # Confirm contact at the same commanded angle. A further
            # closing pulse would compress the object before confirmation.
            for confirmation in range(2):
                if confirmation:
                    await confirmed_health()
                try:
                    measured, seq, jaw_expires_at = await read_new_jaw(
                        latest_seq, "No new jaw sample after servo movement",
                    )
                except (KeyError, TypeError, ValueError, AttributeError,
                        TimeoutError) as exc:
                    raise OperationError("Lost fresh force sensor during closing") from exc
                latest_seq = seq
                raw_delta = (measured - baseline) * calibration.grip_force_sign
                # Match the WROOM's exclusive calibrated closing limit.
                if raw_delta >= ceiling:
                    raise OperationError("Gripper raw force ceiling exceeded")
                # Contradictory polarity is not evidence of a clear jaw.
                if raw_delta <= -threshold:
                    raise OperationError("Gripper feedback contradicts calibrated FSR polarity")
                if raw_delta < threshold:
                    break
                if confirmation:
                    # Health may change during the final awaited AUX read.
                    await confirmed_health()
                    if time.monotonic() >= jaw_expires_at:
                        raise OperationError("Jaw ADC evidence expired before contact confirmation")
                    return {
                        "commanded_angle": angle, "contact_delta_raw": raw_delta,
                        "baseline_raw": baseline, "position_measured": False,
                        "force_newtons_measured": False, "physical_acceptance_pass": False,
                    }
        raise OperationError("Closed jaw limit reached with no tactile contact")
    except (Exception, asyncio.CancelledError) as failure:
        if force_boot_changed or not motion_attempted:
            raise  # No relief across a reboot or before any attempted close.
        # Cancellation also can arrive AFTER a jaw command has moved the servo.
        # A failed partial grasp can leave a powered MG90S squeezing an object.
        # Transport failures and hardware timeout exceptions matter too: a
        # remote command or ADC read can fail AFTER a previous jaw close.
        # Never interpret a missing ACK as proof the servo did not move.
        # Attempt to relax ONLY through the already measured 'open' angle and
        # ONLY while the WROOM still reports fresh local safety authority.
        # If touch/cliff/IMU disarmed the body, NEVER bypass that interlock.
        try:
            await confirmed_health()
            reply = await _bounded_head_reply(
                head.command(f"grip {calibration.grip_open}"),
                seconds=_GRIP_COMMAND_TIMEOUT_S,
                timeout_message="Gripper relief command unconfirmed",
            )
            if (type(reply) is not dict
                    or reply.get("ok") is not True
                    or reply.get("robot_id") != robot_id
                    or reply.get("reply") != f"OK grip angle={calibration.grip_open}"):
                raise OperationError("Unmatched gripper relief command ACK")
            # Ordinary failure must not let Coordinator HALT freeze a
            # still-opening jaw. Cancellation remains immediately preemptible.
            if not isinstance(failure, asyncio.CancelledError):
                await await_commanded_jaw_target(confirmed_health, calibration.grip_open)
        except Exception:
            pass  # Preserve the primary failure; body stop/watchdog is next.
        raise
