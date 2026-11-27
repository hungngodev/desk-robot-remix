"""Repeated physical dock evidence from the existing read-only MCP23017.

This NEVER commands motors, charges a battery, or trusts simulated/provisional
charger status as proof of current flow. A stable 3 sample view is an operator
diagnostic, not electrical qualification.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from time import monotonic

from .aux import validate_aux
from .operations import bounded_head_reply
from .sensor_event_contract import is_finite_number

_DOCK_READ_TIMEOUT_S = 2.0
_DOCK_SAMPLE_MAX_AGE_MS = 500
_DOCK_DEFAULT_DWELL_S = 2.0
_MAX_RETIRED_DOCK_BOOTS = 128


def _newer_u32(new: int, old: int) -> bool:
    delta = (new - old) & 0xffffffff
    return 0 < delta < 0x80000000


@dataclass
class DockContactInhibit:
    """Remember unsafe contact evidence independently of telemetry availability.

    This Mac-side interlock is not a WROOM motion permit or electrical proof.
    """

    inhibited: bool = False
    boot_id: int | None = None
    sequence: int | None = None
    clear_streak: int = 0
    retired_boots: set[int] = field(default_factory=set)

    def invalidate(self) -> None:
        """Missing or stale observations break confirmation, never release it."""
        self.clear_streak = 0

    def observe(self, dock: object, boot_id: int | None, elapsed_ms: float = 0) -> bool:
        """Return whether this is displayable evidence, not motion authority."""
        pins = ("left_seated", "right_seated", "input_good", "charge_indicated")
        if (not isinstance(dock, dict)
                or dock.get("present") is not True or dock.get("valid") is not True
                or dock.get("charging_verified") is not False
                or type(dock.get("seq")) is not int or not 1 <= dock["seq"] <= 0xffffffff
                or type(dock.get("age_ms")) is not int
                or not 0 <= dock["age_ms"] < _DOCK_SAMPLE_MAX_AGE_MS
                or type(elapsed_ms) not in (int, float) or not 0 <= elapsed_ms < 500
                or dock["age_ms"] + elapsed_ms >= _DOCK_SAMPLE_MAX_AGE_MS
                or any(type(dock.get(pin)) is not bool for pin in pins)):
            self.invalidate()
            return False
        asserted = any(dock[pin] for pin in pins)
        if type(boot_id) is not int or not 1 <= boot_id <= 0xffffffff:
            # Legacy pins can conservatively inhibit, never release a latch.
            self.inhibited |= asserted
            self.invalidate()
            return True
        if boot_id in self.retired_boots:
            self.invalidate()
            return False
        if boot_id != self.boot_id:
            if self.boot_id is not None:
                if len(self.retired_boots) >= 8:
                    self.inhibited = True
                    self.invalidate()
                    return False
                self.retired_boots.add(self.boot_id)
            self.boot_id = boot_id
            self.sequence = None
            self.invalidate()
        seq = dock["seq"]
        if (self.sequence is not None
                and not 0 < ((seq - self.sequence) & 0xffffffff) < 0x80000000):
            self.invalidate()
            return False
        self.sequence = seq
        if asserted:
            self.inhibited = True
            self.invalidate()
        elif self.inhibited:
            self.clear_streak += 1
            if self.clear_streak == 3:
                self.inhibited = False
                self.invalidate()
        return True


@dataclass
class DockChargingDwell:
    """Continuous >=2 s monotonic software confirmation for dock charging evidence.

    Requires both independent seat switches closed, valid PGOOD+CHG active state,
    fresh advancing MCP23017 dock and INA226 positive pack-current conversions,
    and one stable nonzero WROOM boot epoch throughout. Any stale, replayed, or
    invalid sample, pin transition, epoch change, or non-charging/negative pack
    current immediately resets the dwell. Separate from charging authorization
    and physical charger qualification, which remain False.
    """

    required_dwell_s: float = _DOCK_DEFAULT_DWELL_S
    min_charge_ma: int = 21
    max_gap_s: float = 1.0
    boot_id: int | None = None
    retired_boots: set[int] = field(default_factory=set)
    last_dock_seq: int | None = None
    last_pack_seq: int | None = None
    dwell_started_at: float | None = None
    last_sample_at: float | None = None

    def __post_init__(self) -> None:
        if (
            not is_finite_number(self.required_dwell_s)
            or not 0.5 <= self.required_dwell_s <= 60.0
            or type(self.min_charge_ma) is not int
            or self.min_charge_ma < 1
            or not is_finite_number(self.max_gap_s)
            or not 0.1 <= self.max_gap_s <= 5.0
        ):
            raise ValueError("Invalid dock charging dwell configuration")

    def reset_dwell(self) -> None:
        self.dwell_started_at = None
        self.last_sample_at = None

    def _status(self, robot_id: str, state: str, *, confirmed: bool, elapsed: float) -> dict:
        return {
            "robot_id": robot_id,
            "state": state,
            "software_charging_confirmed": confirmed,
            "dwell_elapsed_s": round(max(0.0, elapsed), 6),
            "required_dwell_s": self.required_dwell_s,
            "charger_electrically_qualified": False,
            "charging_verified": False,
            "charging_authorized": False,
            "motor_authorized": False,
        }

    def observe_sample(
        self,
        raw_sample: object,
        robot_id: str,
        *,
        received_at: float,
        request_ms: float = 0.0,
    ) -> dict:
        if (
            not isinstance(robot_id, str)
            or not robot_id
            or not is_finite_number(received_at)
            or not is_finite_number(request_ms)
            or not 0.0 <= request_ms < _DOCK_SAMPLE_MAX_AGE_MS
        ):
            self.reset_dwell()
            return self._status(
                str(robot_id), "dock_dwell_invalid_clock", confirmed=False, elapsed=0.0,
            )
        if self.last_sample_at is not None:
            gap = received_at - self.last_sample_at
            if gap <= 0.0 or gap > self.max_gap_s + _DOCK_SAMPLE_MAX_AGE_MS / 1000.0:
                self.reset_dwell()
                return self._status(
                    robot_id, "dock_dwell_window_expired_or_regressed",
                    confirmed=False, elapsed=0.0,
                )
        try:
            sample = validate_aux(raw_sample, robot_id)
        except Exception:
            self.reset_dwell()
            return self._status(
                robot_id, "dock_telemetry_invalid", confirmed=False, elapsed=0.0,
            )
        force_boot = sample["force"].get("boot_id")
        prox_boot = sample["proximity"].get("boot_id")
        boot = (
            force_boot
            if type(force_boot) is int and force_boot > 0 and force_boot == prox_boot
            else None
        )
        if boot is None or boot in self.retired_boots:
            self.reset_dwell()
            return self._status(
                robot_id, "dock_sample_epoch_unverified_or_retired",
                confirmed=False, elapsed=0.0,
            )
        if self.boot_id is not None and boot != self.boot_id:
            if len(self.retired_boots) >= _MAX_RETIRED_DOCK_BOOTS:
                self.reset_dwell()
                return self._status(
                    robot_id, "dock_epoch_fence_exhausted", confirmed=False, elapsed=0.0,
                )
            self.retired_boots.add(self.boot_id)
            self.boot_id = boot
            self.last_dock_seq = None
            self.last_pack_seq = None
            self.reset_dwell()
            return self._status(
                robot_id, "dock_sample_epoch_changed", confirmed=False, elapsed=0.0,
            )
        self.boot_id = boot

        dock = sample.get("dock")
        if dock is None or not dock["present"] or not dock["valid"]:
            self.reset_dwell()
            return self._status(
                robot_id, "dock_telemetry_unavailable", confirmed=False, elapsed=0.0,
            )
        if dock["age_ms"] + request_ms >= _DOCK_SAMPLE_MAX_AGE_MS:
            self.reset_dwell()
            return self._status(
                robot_id, "dock_telemetry_stale_at_consumer",
                confirmed=False, elapsed=0.0,
            )
        dock_seq = dock["seq"]
        if self.last_dock_seq is not None and not _newer_u32(dock_seq, self.last_dock_seq):
            self.reset_dwell()
            return self._status(
                robot_id, "dock_sample_replayed_or_reset", confirmed=False, elapsed=0.0,
            )
        self.last_dock_seq = dock_seq

        dock_state = classify_dock(dock)
        if dock_state != "charger_reports_active":
            self.reset_dwell()
            return self._status(robot_id, dock_state, confirmed=False, elapsed=0.0)

        power = sample["power"]
        pack_age_ms = power.get("pack_age_ms")
        pack_seq = power.get("pack_seq")
        pack_ma = power.get("pack_ma")
        if (
            power.get("pack_valid") is not True
            or type(pack_seq) is not int
            or pack_seq <= 0
            or type(pack_age_ms) is not int
            or not 0 <= pack_age_ms < _DOCK_SAMPLE_MAX_AGE_MS
            or pack_age_ms + request_ms >= _DOCK_SAMPLE_MAX_AGE_MS
            or type(pack_ma) is not int
        ):
            self.reset_dwell()
            return self._status(
                robot_id, "current_sample_stale_or_invalid", confirmed=False, elapsed=0.0,
            )
        if self.last_pack_seq is not None and not _newer_u32(pack_seq, self.last_pack_seq):
            self.reset_dwell()
            return self._status(
                robot_id, "current_sample_replayed", confirmed=False, elapsed=0.0,
            )
        self.last_pack_seq = pack_seq

        if pack_ma < self.min_charge_ma:
            self.reset_dwell()
            return self._status(
                robot_id, "non_charging_or_negative_pack_current",
                confirmed=False, elapsed=0.0,
            )

        if self.dwell_started_at is None:
            self.dwell_started_at = received_at
        self.last_sample_at = received_at
        elapsed = received_at - self.dwell_started_at
        confirmed = elapsed >= self.required_dwell_s
        return self._status(
            robot_id,
            "software_charging_dwell_confirmed" if confirmed else "charger_reports_active",
            confirmed=confirmed,
            elapsed=elapsed,
        )


async def confirm_dock_charging_dwell(
    head,
    robot_id: str,
    *,
    dwell_s: float = _DOCK_DEFAULT_DWELL_S,
    gap: float = 0.30,
    clock: Callable[[], float] = monotonic,
    dwell: DockChargingDwell | None = None,
) -> dict:
    """Poll read-only WROOM dock+INA226 evidence across a continuous >=2 s dwell."""
    if not isinstance(robot_id, str) or not robot_id or not 0.25 <= gap <= 1.0:
        raise ValueError("Invalid dock evidence request")
    tracker = (
        dwell
        if dwell is not None
        else DockChargingDwell(required_dwell_s=dwell_s, max_gap_s=gap)
    )
    max_polls = max(3, int(tracker.required_dwell_s / gap) + 4)
    latest: dict | None = None
    for index in range(max_polls):
        request_at = clock()
        reply = await bounded_head_reply(
            head.aux_status(), seconds=_DOCK_READ_TIMEOUT_S,
            timeout_message="Dock GPIO evidence read timed out",
        )
        received_at = clock()
        request_ms = max(0.0, (received_at - request_at) * 1000.0)
        latest = tracker.observe_sample(
            reply, robot_id, received_at=received_at, request_ms=request_ms,
        )
        if latest["software_charging_confirmed"]:
            return latest
        if tracker.dwell_started_at is None:
            return latest
        if index + 1 < max_polls:
            await asyncio.sleep(gap)
    assert latest is not None
    return latest


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


async def observe_dock_evidence(
    head,
    robot_id: str,
    *,
    gap: float = 0.30,
    dwell_s: float | None = None,
    clock: Callable[[], float] = monotonic,
) -> dict:
    """Read three independently timed body updates, or confirm a >=2 s dwell.

    Require distinct *hardware* MCP23017 GPIO acquisition sequence values.
    HTTP polling delay alone cannot distinguish cached/replayed data.
    There is still no electrical ammeter or charger controller authorization.
    """
    if dwell_s is not None:
        return await confirm_dock_charging_dwell(
            head, robot_id, dwell_s=dwell_s, gap=gap, clock=clock,
        )
    if not isinstance(robot_id, str) or not robot_id or not 0.25 <= gap <= 1.0:
        raise ValueError("Invalid dock evidence request")
    snapshots = []
    sample_sequences = []
    raw_pack_samples = []
    boot_epochs = []
    previous_received_at = None
    for index in range(3):
        # Do not let a cancellation-ignoring alternate telemetry adapter
        # freeze the read-only dock evidence request indefinitely.
        request_at = monotonic()
        # Individual fresh replies do not establish a continuous observation
        # after a suspended task. Permit the requested gap plus one existing
        # source freshness budget for scheduling delay, not an unbounded pause.
        if (previous_received_at is not None
                and request_at - previous_received_at
                > gap + _DOCK_SAMPLE_MAX_AGE_MS / 1000.0):
            return _result(robot_id, "dock_observation_window_expired", False)
        reply = await bounded_head_reply(
            head.aux_status(), seconds=_DOCK_READ_TIMEOUT_S,
            timeout_message="Dock GPIO evidence read timed out",
        )
        # The device's age was stamped before the HTTP response reached Mac.
        # Request latency is a conservative additional lower bound on age.
        previous_received_at = monotonic()
        request_ms = max(0.0, (previous_received_at - request_at) * 1000.0)
        sample = validate_aux(reply, robot_id)
        dock = sample.get("dock")
        if dock is None or not dock["valid"] or not dock["present"]:
            return _result(robot_id, "dock_telemetry_unavailable", False)
        if dock["age_ms"] + request_ms >= _DOCK_SAMPLE_MAX_AGE_MS:
            return _result(robot_id, "dock_telemetry_stale_at_consumer", False)
        # Source freshness is checked in validate_aux; transport time also counts. A new HTTP
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
        pack_age_ms = power.get("pack_age_ms")
        raw_pack_samples.append((
            power.get("pack_valid", False),
            power.get("pack_seq", 0),
            power.get("pack_ma", 0),
            # An old WROOM image without this provenance may still
            # report read-only pins, but never fresh net pack current.
            type(pack_age_ms) is int
            and pack_age_ms + request_ms < _DOCK_SAMPLE_MAX_AGE_MS,
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
        if not all(item[3] for item in raw_pack_samples):
            result["raw_pack_direction"] = "current_sample_stale_or_age_unverified"
            return result
        ids = [item[1] for item in raw_pack_samples]
        if newer(ids[1], ids[0]) and newer(ids[2], ids[1]):
            amps = [item[2] for item in raw_pack_samples]
            result["raw_pack_ma"] = amps
            result["raw_pack_samples_fresh"] = True
            if all(value > 20 for value in amps):
                result["raw_pack_direction"] = "into_pack_unqualified"
                result["raw_seat_current_agreement"] = state == "charger_reports_active"
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
        # Agreement is only a raw diagnostic, never physical seat or charge proof.
        "raw_seat_current_agreement": False,
        "charger_indicator_net_discharge_conflict": False,
        "raw_pack_ma": [],
        "charger_electrically_qualified": False,
        "charging_verified": False,
        "motor_authorized": False,
        "charging_authorized": False,
    }
