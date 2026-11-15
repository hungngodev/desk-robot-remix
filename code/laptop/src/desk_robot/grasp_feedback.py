"""Bounded tactile grasp using distinct fresh ADS1115 jaw sample sequences."""
from __future__ import annotations

import asyncio
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
            or start == end or not 1 <= step <= 10):
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
            or type(group.get("jaw_seq")) is not int
            or not 1 <= group["jaw_seq"] <= 0xffffffff):
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
    *, health: Callable[[], Awaitable[dict]],
) -> dict:
    from .controller import OperationError

    threshold = calibration.grip_force_delta_raw
    ceiling = calibration.grip_force_limit_raw
    if threshold is None or ceiling is None:
        raise OperationError("Measured gripper sensor calibration missing")
    try:
        baseline_a, seq_a = force_observation(
            await asyncio.wait_for(head.aux_status(), timeout=_FORCE_READ_TIMEOUT_S)
        )
        # One ADS1115 jaw channel conversion approximately every 144ms;
        # require distinct observations, not repeated reads of one ADC value.
        await asyncio.sleep(0.18)
        baseline_b, seq_b = force_observation(
            await asyncio.wait_for(head.aux_status(), timeout=_FORCE_READ_TIMEOUT_S)
        )
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
            await asyncio.wait_for(health(), timeout=_HEALTH_READ_TIMEOUT_S)
            await asyncio.wait_for(
                head.command(f"grip {angle}"), timeout=_GRIP_COMMAND_TIMEOUT_S
            )
            await asyncio.sleep(0.18)
            await asyncio.wait_for(health(), timeout=_HEALTH_READ_TIMEOUT_S)
            try:
                measured, seq = force_observation(
                    await asyncio.wait_for(
                        head.aux_status(), timeout=_FORCE_READ_TIMEOUT_S
                    )
                )
            except (KeyError, TypeError, ValueError, AttributeError,
            TimeoutError) as exc:
                raise OperationError("Lost fresh force sensor during closing") from exc
            if not _fresh_jaw_sequence(seq, latest_seq):
                raise OperationError("No new jaw sample after servo movement")
            latest_seq = seq
            raw_delta = (measured - baseline) * calibration.grip_force_sign
            if raw_delta > ceiling:
                raise OperationError("Gripper raw force ceiling exceeded")
            confirmed = confirmed + 1 if raw_delta >= threshold else 0
            if confirmed >= 2:
                return {
                    "commanded_angle": angle, "contact_delta_raw": raw_delta,
                    "baseline_raw": baseline, "position_measured": False,
                    "force_newtons_measured": False, "physical_acceptance_pass": False,
                }
        raise OperationError("Closed jaw limit reached with no tactile contact")
    except (Exception, asyncio.CancelledError):
        # Cancellation also can arrive AFTER a jaw command has moved the servo.
        # A failed partial grasp can leave a powered MG90S squeezing an object.
        # Transport failures and hardware timeout exceptions matter too: a
        # remote command or ADC read can fail AFTER a previous jaw close.
        # Never interpret a missing ACK as proof the servo did not move.
        # Attempt to relax ONLY through the already measured 'open' angle and
        # ONLY while the WROOM still reports fresh local safety authority.
        # If touch/cliff/IMU disarmed the body, NEVER bypass that interlock.
        try:
            await asyncio.wait_for(health(), timeout=_HEALTH_READ_TIMEOUT_S)
            await asyncio.wait_for(
                head.command(f"grip {calibration.grip_open}"),
                timeout=_GRIP_COMMAND_TIMEOUT_S,
            )
        except Exception:
            pass  # Preserve the primary failure; body stop/watchdog is next.
        raise
