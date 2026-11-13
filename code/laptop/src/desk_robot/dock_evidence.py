"""Repeated physical dock evidence from the existing read-only MCP23017.

This NEVER commands motors, charges a battery, or trusts simulated/provisional
charger status as proof of current flow. A stable 3 sample view is an operator
diagnostic, not electrical qualification.
"""
from __future__ import annotations

import asyncio

from .aux import validate_aux


def classify_dock(dock: dict) -> str:
    """Strict independent seat and charger-pin truth table."""
    if not dock["present"] or not dock["valid"]:
        return "dock_telemetry_unavailable"
    left, right = dock["left_seated"], dock["right_seated"]
    input_good = dock["input_good"]
    indicated = dock["charge_indicated"]
    # CHG without valid power input is contradictory, not merely unseated
    # or unpowered. Never hide a charger fault in an ordinary dock state.
    if indicated and not input_good:
        return "charge_signal_without_input_fault"
    if left != right:
        return "asymmetric_seat_or_fault"
    if not left and not right:
        return "charger_input_without_seat" if input_good else "not_seated"
    if not input_good:
        return "seated_but_unpowered"
    return "charger_reports_active" if indicated else "input_present_not_charging"


async def observe_dock_evidence(head, robot_id: str, *, gap: float = 0.30) -> dict:
    """Read three independently timed body updates, require stable dock pins.

    Require three different *hardware* MCP23017 GPIO acquisition sequence
    values. HTTP polling delay alone cannot distinguish cached/replayed data.
    There is still no electrical ammeter or charger controller authorization.
    """
    if not isinstance(robot_id, str) or not robot_id or not 0.25 <= gap <= 1.0:
        raise ValueError("Invalid dock evidence request")
    snapshots = []
    sample_sequences = []
    for index in range(3):
        sample = validate_aux(await asyncio.wait_for(head.aux_status(), timeout=2), robot_id)
        dock = sample.get("dock")
        if dock is None or not dock["valid"] or not dock["present"]:
            return _result(robot_id, "dock_telemetry_unavailable", False)
        # Validity and freshness are checked in validate_aux. A new HTTP
        # response by itself does NOT mean a new physical GPIO conversion.
        sample_sequences.append(dock["seq"])
        snapshots.append((
            dock["present"], dock["valid"], dock["left_seated"],
            dock["right_seated"], dock["input_good"], dock["charge_indicated"],
        ))
        if index != 2:
            await asyncio.sleep(gap)
    # Match the WROOM's unsigned sequence freshness rule at uint32 rollover.
    # An old/replayed sample, or a huge backwards jump, still fails closed.
    def newer(new: int, old: int) -> bool:
        delta = (new - old) & 0xffffffff
        return 0 < delta < 0x80000000

    if not (newer(sample_sequences[1], sample_sequences[0])
            and newer(sample_sequences[2], sample_sequences[1])):
        return _result(robot_id, "dock_sample_replayed_or_reset", False)
    if snapshots[0] != snapshots[1] or snapshots[1] != snapshots[2]:
        return _result(robot_id, "dock_evidence_changed", False)
    present, valid, left, right, input_good, charge_indicated = snapshots[2]
    state = classify_dock({
        "present": present, "valid": valid, "left_seated": left,
        "right_seated": right, "input_good": input_good,
        "charge_indicated": charge_indicated,
    })
    return _result(robot_id, state, bool(present and valid))


def _result(robot_id: str, state: str, stable: bool) -> dict:
    return {
        "robot_id": robot_id,
        "state": state,
        "stable_three_samples": stable,
        "source": "wroom_mcp23017_bq24074_status_pins",
        "physical_contact_verified": False,
        "battery_current_measured": False,
        "charger_electrically_qualified": False,
        "charging_verified": False,
        "motor_authorized": False,
        "charging_authorized": False,
    }
