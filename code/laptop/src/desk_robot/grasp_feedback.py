"""Bounded tactile grasp using an ADS1115 FSR, never blind servo closure."""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .calibration import Calibration
    from .transport import Head


def grip_angles(start: int, end: int, step: int) -> tuple[int, ...]:
    if (type(start) is not int or type(end) is not int or type(step) is not int
            or not 60 <= start <= 120 or not 60 <= end <= 120
            or start == end or not 1 <= step <= 10):
        raise ValueError("Measured servo limits required")
    direction = 1 if end > start else -1
    return tuple([start, *range(start + direction * step, end, direction * step), end])


def force_adc(payload: dict) -> int:
    group = payload.get("force") if isinstance(payload, dict) else None
    if (not isinstance(group, dict) or group.get("valid") is not True
            or group.get("calibrated") is not False
            or not isinstance(group.get("adc"), list) or len(group["adc"]) != 2
            or type(group["adc"][1]) is not int
            or not -32768 <= group["adc"][1] <= 32767):
        raise ValueError("Missing, invalid or stale ADS1115 gripper force")
    return group["adc"][1]


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
        baseline_a = force_adc(await head.aux_status())
        await asyncio.sleep(0.10)
        baseline_b = force_adc(await head.aux_status())
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise OperationError("Fresh force feedback required before moving jaw") from exc
    if abs(baseline_a - baseline_b) > max(40, threshold // 3):
        raise OperationError("Gripper baseline unstable; jaw not moved")
    baseline = (baseline_a + baseline_b) // 2
    confirmed = 0
    for angle in grip_angles(
        calibration.grip_open, calibration.grip_closed, calibration.grip_step_deg
    )[1:]:
        await health()
        await head.command(f"grip {angle}")
        await asyncio.sleep(0.15)
        await health()
        try:
            measured = force_adc(await head.aux_status())
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise OperationError("Lost fresh force sensor during closing") from exc
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
