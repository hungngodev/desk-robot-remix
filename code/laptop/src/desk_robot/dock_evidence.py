"""Repeated physical dock evidence from the existing read-only MCP23017.

This NEVER commands motors, charges a battery, or trusts simulated/provisional
charger status as proof of current flow. A stable 3 sample view is an operator
diagnostic, not electrical qualification.
"""
from __future__ import annotations

import asyncio

from .aux import validate_aux

_DOCK_READ_TIMEOUT_S = 2.0


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
        # CHG asserted while both independent seat switches are open is a
        # contact/status contradiction, not an ordinary unseated input.
        if input_good and indicated:
            return "charge_signal_without_seat_fault"
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
    raw_pack_samples = []
    boot_epochs = []
    for index in range(3):
        # Do not let a cancellation-ignoring alternate telemetry adapter
        # freeze the read-only dock evidence request indefinitely.
        from .controller import _bounded_head_reply
        sample = validate_aux(await _bounded_head_reply(
            head.aux_status(), seconds=_DOCK_READ_TIMEOUT_S,
            timeout_message="Dock GPIO evidence read timed out",
        ), robot_id)
        dock = sample.get("dock")
        if dock is None or not dock["valid"] or not dock["present"]:
            return _result(robot_id, "dock_telemetry_unavailable", False)
        # Validity and freshness are checked in validate_aux. A new HTTP
        # response by itself does NOT mean a new physical GPIO conversion.
        sample_sequences.append(dock["seq"])
        # Both groups share one WROOM boot, but legacy captures may omit
        # the epoch. No three-sample stability claim may cross a controller
        # restart or use unproven sequence provenance.
        force_boot = sample["force"].get("boot_id")
        proximity_boot = sample["proximity"].get("boot_id")
        boot_epochs.append(
            force_boot if type(force_boot) is int and force_boot > 0
            and force_boot == proximity_boot else None
        )
        power = sample["power"]
        raw_pack_samples.append((
            power.get("pack_valid", False),
            power.get("pack_seq", 0),
            power.get("pack_ma", 0),
        ))
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

    if boot_epochs[0] is None or any(
        epoch != boot_epochs[0] for epoch in boot_epochs[1:]
    ):
        return _result(robot_id, "dock_sample_epoch_unverified_or_changed", False)
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
    result = _result(robot_id, state, bool(present and valid))
    # Unlike CHG's active-low indicator, these signs come from genuine
    # INA226 shunt register conversions in the WROOM. Never trust three
    # cached HTTPS replies as three new battery-current measurements.
    # Raw mA is ALWAYS uncalibrated and cannot enable dock charging.
    if all(item[0] and item[1] > 0 for item in raw_pack_samples):
        ids = [item[1] for item in raw_pack_samples]
        if newer(ids[1], ids[0]) and newer(ids[2], ids[1]):
            amps = [item[2] for item in raw_pack_samples]
            result["raw_pack_ma"] = amps
            result["raw_pack_samples_fresh"] = True
            if all(value > 20 for value in amps):
                result["raw_pack_direction"] = "into_pack_unqualified"
            elif all(value < -20 for value in amps):
                result["raw_pack_direction"] = "out_of_pack_unqualified"
                # TI BQ24075 CHG reports charge *state*, not net pack
                # current. DPPM may reduce charge or let pack supplement the
                # live system. Never label a sustained negative pack current
                # as successful battery charging.
                if state == "charger_reports_active":
                    result["charger_indicator_net_discharge_conflict"] = True
            else:
                result["raw_pack_direction"] = "indeterminate"
        else:
            result["raw_pack_direction"] = "acquisition_replay"
    return result


def _result(robot_id: str, state: str, stable: bool) -> dict:
    return {
        "robot_id": robot_id,
        "state": state,
        "stable_three_samples": stable,
        # The WROOM observes GPIO levels, not an authenticated charger
        # IC identity. The BQ24075 candidate is not an installed board.
        "source": "wroom_mcp23017_dock_status_pins_unqualified",
        "physical_contact_verified": False,
        "battery_current_measured": False,
        "raw_pack_direction": "not_available",
        "raw_pack_samples_fresh": False,
        "charger_indicator_net_discharge_conflict": False,
        "raw_pack_ma": [],
        "charger_electrically_qualified": False,
        "charging_verified": False,
        "motor_authorized": False,
        "charging_authorized": False,
    }
