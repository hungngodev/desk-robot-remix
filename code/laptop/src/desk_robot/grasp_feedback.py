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
    if (not isinstance(group, dict) or group.get("valid") is not True
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

    async def read_force() -> tuple[int, int]:
        nonlocal force_boot_seen, force_boot_id, force_boot_changed
        started = time.monotonic()
        sample = await _bounded_head_reply(
            head.aux_status(), seconds=_FORCE_READ_TIMEOUT_S,
            timeout_message="ADS1115 jaw force read timed out",
        )
        request_elapsed_ms = max(0, int((time.monotonic() - started) * 1000))
        if not isinstance(sample, dict) or sample.get("robot_id") != robot_id:
            raise ValueError("Foreign or missing jaw sensor robot identity")
        observation = force_observation(sample)
        group = sample["force"]
        # Physical servo movement must not trust a legacy/partial AUX
        # adapter with no acquisition clock or reboot fence. Keep the
        # optional metadata allowance in force_observation for read-only
        # inspection, but require both fields at this motion boundary.
        age_ms = group.get("jaw_age_ms")
        if (type(age_ms) is not int or not 0 <= age_ms < 500
                or age_ms + request_elapsed_ms >= 500):
            raise ValueError("Missing or expired jaw ADC acquisition age")
        observed_boot = group.get("boot_id")
        if (type(observed_boot) is not int
                or not 0 <= observed_boot <= 0xffffffff):
            raise ValueError("Missing or invalid WROOM boot identity for jaw evidence")
        if force_boot_seen and observed_boot != force_boot_id:
            # Across a CPU reboot the jaw sequence may look like uint32 wrap.
            # Do not issue another close OR a best-effort relief on the new
            # unarmed session, even if an alternate health adapter says yes.
            force_boot_changed = True
            raise ValueError("WROOM reboot invalidated grasp force sequence")
        force_boot_seen = True
        force_boot_id = observed_boot
        return observation

    async def confirmed_health() -> None:
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

    try:
        baseline_a, seq_a = await read_force()
        # One ADS1115 jaw channel conversion approximately every 144ms;
        # require distinct observations, not repeated reads of one ADC value.
        await asyncio.sleep(0.18)
        baseline_b, seq_b = await read_force()
    except (KeyError, TypeError, ValueError, AttributeError,
            TimeoutError) as exc:
        raise OperationError("Fresh force feedback required before moving jaw") from exc
    if not _fresh_jaw_sequence(seq_b, seq_a):
        raise OperationError("No new ADS1115 jaw sample; jaw not moved")
    if abs(baseline_a - baseline_b) > max(40, threshold // 3):
        raise OperationError("Gripper baseline unstable; jaw not moved")
    baseline = (baseline_a + baseline_b) // 2
    confirmed = 0
    latest_seq = seq_b
    try:
        for angle in grip_angles(
            calibration.grip_open, calibration.grip_closed, calibration.grip_step_deg
        )[1:]:
            await confirmed_health()
            await _bounded_head_reply(
                head.command(f"grip {angle}"), seconds=_GRIP_COMMAND_TIMEOUT_S,
                timeout_message="Gripper servo command unconfirmed",
            )
            await asyncio.sleep(0.18)
            await confirmed_health()
            try:
                measured, seq = await read_force()
            except (KeyError, TypeError, ValueError, AttributeError,
            TimeoutError) as exc:
                raise OperationError("Lost fresh force sensor during closing") from exc
            if not _fresh_jaw_sequence(seq, latest_seq):
                raise OperationError("No new jaw sample after servo movement")
            latest_seq = seq
            raw_delta = (measured - baseline) * calibration.grip_force_sign
            if raw_delta > ceiling:
                raise OperationError("Gripper raw force ceiling exceeded")
            # Contradictory FSR polarity cannot mean that the jaws are clear.
            # Stop rather than continue closing on reversed sensor evidence.
            if raw_delta <= -threshold:
                raise OperationError("Gripper feedback contradicts calibrated FSR polarity")
            confirmed = confirmed + 1 if raw_delta >= threshold else 0
            if confirmed >= 2:
                return {
                    "commanded_angle": angle, "contact_delta_raw": raw_delta,
                    "baseline_raw": baseline, "position_measured": False,
                    "force_newtons_measured": False, "physical_acceptance_pass": False,
                }
        raise OperationError("Closed jaw limit reached with no tactile contact")
    except (Exception, asyncio.CancelledError):
        if force_boot_changed:
            raise  # No commands of any kind after a newly observed reboot.
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
            await _bounded_head_reply(
                head.command(f"grip {calibration.grip_open}"),
                seconds=_GRIP_COMMAND_TIMEOUT_S,
                timeout_message="Gripper relief command unconfirmed",
            )
        except Exception:
            pass  # Preserve the primary failure; body stop/watchdog is next.
        raise
