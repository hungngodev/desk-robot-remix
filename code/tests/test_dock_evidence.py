"""Read-only physical dock diagnostics cannot masquerade as verified charging."""
import copy

import pytest
from desk_robot.dock_evidence import classify_dock, observe_dock_evidence


def payload():
    return {
        "robot_id": "robot-01",
        "pulse": {"present": False, "valid": False, "part_id": 0,
                  "red": 0, "ir": 0, "age_ms": 0, "bpm": None, "medical": False},
        "angles": {"raw": [0, 0, 0], "present_mask": 0,
                   "valid_mask": 0, "magnet": [0, 0, 0]},
        "force": {"adc": [0, 0], "jaw_seq": 0, "valid": False,
                  "calibrated": False, "boot_id": 17},
        "climate": {"temp_centi": 0, "rh_centi": 0, "valid": False},
        "power": {"cell_mv": 0, "soc_centi": 0, "bus_mv": 0, "shunt_uv": 0,
                  "fuel_valid": False, "monitor_valid": False,
                  "current_calibrated": False},
        "proximity": {"raw": 0, "valid": False, "gesture": 0,
                      "gesture_events": 0, "physically_qualified": False,
                      "boot_id": 17},
        "dock": {
            "present": True, "valid": True, "left_seated": True,
            "right_seated": True, "input_good": True,
            "charge_indicated": True, "charging_verified": False,
            "seq": 1, "age_ms": 35,
        },
    }


def fresh_samples(count=3):
    readings = [payload() for _ in range(count)]
    for seq, sample in enumerate(readings, 1):
        sample["dock"]["seq"] = seq
    return readings


class FakeHead:
    def __init__(self, samples):
        self.samples = iter(samples)
        self.commands = []

    async def aux_status(self):
        return next(self.samples)

    async def command(self, command):
        self.commands.append(command)


async def test_three_stable_charger_indications_are_not_battery_proof(monkeypatch):
    async def fast(_seconds):
        pass
    monkeypatch.setattr("desk_robot.dock_evidence.asyncio.sleep", fast)
    head = FakeHead(fresh_samples())
    result = await observe_dock_evidence(head, "robot-01")
    assert result["state"] == "charger_reports_active"
    assert result["stable_three_samples"] is True
    assert result["source"] == "wroom_mcp23017_dock_status_pins_unqualified"
    assert "bq24074" not in result["source"].lower()
    assert "bq24075" not in result["source"].lower()
    assert result["charging_verified"] is False
    assert result["battery_current_measured"] is False
    assert result["charger_electrically_qualified"] is False
    assert result["motor_authorized"] is False
    assert head.commands == []


@pytest.mark.parametrize(("transport_ms", "source_age_ms", "expected_stable"), [
    (1200, 35, False),
    (20, 35, True),
    (10, 499, False),
])
async def test_dock_gpio_consumer_age_includes_http_transport(
    monkeypatch, transport_ms, source_age_ms, expected_stable,
):
    import desk_robot.dock_evidence as evidence

    now = [100.0]
    monkeypatch.setattr(evidence, "monotonic", lambda: now[0])

    async def fast(_seconds):
        pass

    monkeypatch.setattr(evidence.asyncio, "sleep", fast)
    samples = fresh_samples()
    for record in samples:
        record["dock"]["age_ms"] = source_age_ms

    class TimedHead(FakeHead):
        async def aux_status(self):
            # Different genuine WROOM acquisitions may still arrive too late.
            now[0] += transport_ms / 1000.0
            return await super().aux_status()

    head = TimedHead(samples)
    report = await observe_dock_evidence(head, "robot-01")
    assert report["stable_three_samples"] is expected_stable
    assert report["state"] == (
        "charger_reports_active" if expected_stable
        else "dock_telemetry_stale_at_consumer"
    )
    assert not report["charging_verified"]
    assert not report["motor_authorized"]
    assert not report["charging_authorized"]
    assert head.commands == []


async def test_asymmetric_switch_or_changing_input_refuses_seated_claim(monkeypatch):
    async def fast(_seconds):
        pass
    monkeypatch.setattr("desk_robot.dock_evidence.asyncio.sleep", fast)
    asym = payload()
    asym["dock"]["right_seated"] = False
    asym_frames = [copy.deepcopy(asym) for _ in range(3)]
    for seq, frame in enumerate(asym_frames, 1):
        frame["dock"]["seq"] = seq
    head = FakeHead(asym_frames)
    assert (await observe_dock_evidence(head, "robot-01"))["state"] == "asymmetric_seat_or_fault"
    changed = payload()
    changed["dock"]["charge_indicated"] = False
    first = payload()
    second = copy.deepcopy(changed)
    third = copy.deepcopy(changed)
    second["dock"]["seq"], third["dock"]["seq"] = 2, 3
    head = FakeHead([first, second, third])
    result = await observe_dock_evidence(head, "robot-01")
    assert result["state"] == "dock_evidence_changed"
    assert result["stable_three_samples"] is False


@pytest.mark.parametrize(("left", "right", "good", "charging", "state"), [
    (False, False, False, False, "not_seated"),
    (True, True, False, False, "seated_but_unpowered"),
    (True, True, True, False, "input_present_not_charging"),
    (False, False, True, True, "charge_signal_without_seat_fault"),
    (False, False, True, False, "charger_input_without_seat"),
    (False, False, False, True, "charge_signal_without_input_fault"),
    (True, True, False, True, "charge_signal_without_input_fault"),
])
def test_independent_input_truth_table(left, right, good, charging, state):
    dock = payload()["dock"]
    dock.update(left_seated=left, right_seated=right,
                input_good=good, charge_indicated=charging)
    assert classify_dock(dock) == state



async def test_real_aux_path_preserves_chg_without_pgood_as_read_only_fault(monkeypatch):
    # CHG and PGOOD are independent active-low hardware signals.
    # A contradictory acquisition is a fault to surface, not an
    # exception that prevents the Mac's diagnostic from reaching the user.
    from desk_robot.aux import validate_aux

    async def fast(_seconds):
        pass
    monkeypatch.setattr("desk_robot.dock_evidence.asyncio.sleep", fast)
    samples = fresh_samples()
    for frame in samples:
        frame["dock"].update(input_good=False, charge_indicated=True)
        assert validate_aux(frame, "robot-01")["dock"]["charge_indicated"]
    head = FakeHead(samples)
    result = await observe_dock_evidence(head, "robot-01")
    assert result["state"] == "charge_signal_without_input_fault"
    assert result["stable_three_samples"]
    assert not result["charger_electrically_qualified"]
    assert not result["charging_verified"]
    assert not result["motor_authorized"]
    assert not result["charging_authorized"]
    assert head.commands == []


async def test_active_charger_with_no_seat_is_fault_not_routine_input(monkeypatch):
    async def fast(_seconds):
        pass
    monkeypatch.setattr("desk_robot.dock_evidence.asyncio.sleep", fast)
    samples = fresh_samples()
    for record in samples:
        record["dock"]["left_seated"] = False
        record["dock"]["right_seated"] = False
    head = FakeHead(samples)
    result = await observe_dock_evidence(head, "robot-01")
    assert result["state"] == "charge_signal_without_seat_fault"
    assert result["stable_three_samples"] is True
    assert result["charging_verified"] is False
    assert result["charging_authorized"] is False
    assert result["motor_authorized"] is False
    assert head.commands == []


async def test_dock_evidence_refuses_forged_battery_charge_and_robot_identity():
    bad = payload()
    bad["dock"]["charging_verified"] = True
    head = FakeHead([bad])
    with pytest.raises(ValueError):
        await observe_dock_evidence(head, "robot-01")
    head = FakeHead([payload()])
    with pytest.raises(ValueError):
        await observe_dock_evidence(head, "robot-02")


@pytest.mark.parametrize("missing_group", ["force", "proximity"])
async def test_dock_legacy_missing_boot_epoch_is_never_stable(
    monkeypatch, missing_group,
):
    async def fast(_seconds):
        pass
    monkeypatch.setattr("desk_robot.dock_evidence.asyncio.sleep", fast)
    samples = fresh_samples()
    for sample in samples:
        sample[missing_group].pop("boot_id")
    result = await observe_dock_evidence(FakeHead(samples), "robot-01")
    assert result["state"] == "dock_sample_epoch_unverified_or_changed"
    assert result["stable_three_samples"] is False
    assert result["raw_pack_direction"] == "not_available"
    assert not result["charging_authorized"] and not result["motor_authorized"]


async def test_reboot_with_monotonic_dock_and_pack_sequences_is_not_stable(
    monkeypatch,
):
    async def fast(_seconds):
        pass
    monkeypatch.setattr("desk_robot.dock_evidence.asyncio.sleep", fast)
    samples = fresh_samples()
    for index, sample in enumerate(samples):
        sample["power"].update(
            shunt_uv=150, pack_ma=30, pack_valid=True,
            pack_seq=index + 40, monitor_valid=True,
        )
    # A restarted WROOM may produce different monotonic GPIO and INA226
    # sequences. Require one boot epoch rather than trusting those counts.
    for sample in samples[1:]:
        sample["force"]["boot_id"] = 18
        sample["proximity"]["boot_id"] = 18
    result = await observe_dock_evidence(FakeHead(samples), "robot-01")
    assert result["state"] == "dock_sample_epoch_unverified_or_changed"
    assert not result["stable_three_samples"]
    assert result["raw_pack_direction"] == "not_available"
    assert not result["raw_pack_samples_fresh"]
    assert not result["charging_verified"] and not result["charging_authorized"]


async def test_replayed_cached_dock_status_is_not_independent_physical_evidence(monkeypatch):
    async def fast(_seconds):
        pass
    monkeypatch.setattr("desk_robot.dock_evidence.asyncio.sleep", fast)
    same = payload()
    result = await observe_dock_evidence(
        FakeHead([copy.deepcopy(same) for _ in range(3)]), "robot-01",
    )
    assert result["state"] == "dock_sample_replayed_or_reset"
    assert result["stable_three_samples"] is False
    assert result["charging_verified"] is False


async def test_out_of_order_or_rebooted_dock_sequence_fails_closed(monkeypatch):
    async def fast(_seconds):
        pass
    monkeypatch.setattr("desk_robot.dock_evidence.asyncio.sleep", fast)
    samples = fresh_samples()
    samples[1]["dock"]["seq"] = 9
    samples[2]["dock"]["seq"] = 1
    result = await observe_dock_evidence(FakeHead(samples), "robot-01")
    assert result["state"] == "dock_sample_replayed_or_reset"
    assert not result["stable_three_samples"]


@pytest.mark.parametrize("field,value", [
    ("seq", 0), ("seq", "1"), ("seq", True), ("age_ms", 500),
    ("age_ms", -1), ("age_ms", 0.5),
])
async def test_dock_status_cannot_claim_valid_without_fresh_hardware_sample(
    field, value,
):
    bad = payload()
    bad["dock"][field] = value
    with pytest.raises(ValueError):
        await observe_dock_evidence(FakeHead([bad]), "robot-01")


@pytest.mark.parametrize(("sequences", "expected_stable"), [
    ((0xffffffff, 1, 2), True),
    ((1, 0xfffffffe, 2), False),
    ((0xfffffffe, 0xfffffffe, 1), False),
])
async def test_dock_gpio_sequence_rollover_matches_wroom_half_range_rule(
    monkeypatch, sequences, expected_stable,
):
    async def fast(_seconds):
        pass

    monkeypatch.setattr("desk_robot.dock_evidence.asyncio.sleep", fast)
    samples = fresh_samples()
    for sample, sequence in zip(samples, sequences, strict=True):
        sample["dock"]["seq"] = sequence
    result = await observe_dock_evidence(FakeHead(samples), "robot-01")
    assert result["stable_three_samples"] is expected_stable
    assert result["state"] == (
        "charger_reports_active" if expected_stable
        else "dock_sample_replayed_or_reset"
    )
    assert result["charging_verified"] is False
    assert result["motor_authorized"] is False




async def test_uncooperative_dock_evidence_read_times_out_without_charge_claim(
    monkeypatch,
):
    """A stuck authenticated GPIO poller cannot invent stable charge evidence."""
    import asyncio

    import desk_robot.dock_evidence as evidence

    monkeypatch.setattr(evidence, "_DOCK_READ_TIMEOUT_S", 0.04)
    entered = asyncio.Event()
    release = asyncio.Event()

    class StubbornHead(FakeHead):
        async def aux_status(self):
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                await release.wait()
                return await super().aux_status()

    head = StubbornHead(fresh_samples())
    try:
        with pytest.raises(TimeoutError, match="Dock GPIO evidence read timed out"):
            await asyncio.wait_for(
                observe_dock_evidence(head, "robot-01"), timeout=0.5,
            )
        assert entered.is_set()
        assert head.commands == []
    finally:
        release.set()
        await asyncio.sleep(0)
    assert head.commands == []


@pytest.mark.parametrize(("raw_ma", "expected"), [
    (30, "into_pack_unqualified"),
    (-30, "out_of_pack_unqualified"),
    (0, "indeterminate"),
])
async def test_new_ina226_current_receipts_report_direction_without_charger_authority(
    monkeypatch, raw_ma, expected,
):
    async def fast(_seconds):
        pass
    monkeypatch.setattr("desk_robot.dock_evidence.asyncio.sleep", fast)
    samples = fresh_samples()
    for index, data in enumerate(samples):
        data["power"].update(
            shunt_uv=raw_ma * 5,
            pack_ma=raw_ma,
            pack_valid=True,
            pack_seq=index + 19,
            monitor_valid=True,
        )
    result = await observe_dock_evidence(FakeHead(samples), "robot-01")
    assert result["state"] == "charger_reports_active"
    assert result["stable_three_samples"]
    assert result["raw_pack_direction"] == expected
    assert result["charger_indicator_net_discharge_conflict"] is (
        raw_ma < -20)
    assert result["raw_pack_samples_fresh"] is True
    assert result["raw_pack_ma"] == [raw_ma] * 3
    assert result["battery_current_measured"] is False
    assert result["charging_verified"] is False
    assert result["charging_authorized"] is False


async def test_raw_pack_replay_cannot_forge_three_current_conversions(monkeypatch):
    async def fast(_seconds):
        pass
    monkeypatch.setattr("desk_robot.dock_evidence.asyncio.sleep", fast)
    samples = fresh_samples()
    for data in samples:
        data["power"].update(
            shunt_uv=150, pack_ma=30, pack_valid=True,
            pack_seq=9, monitor_valid=True,
        )
    result = await observe_dock_evidence(FakeHead(samples), "robot-01")
    assert result["stable_three_samples"]  # independent dock pin samples pass
    assert result["raw_pack_direction"] == "acquisition_replay"
    assert result["raw_pack_samples_fresh"] is False
    assert result["raw_pack_ma"] == []
    assert result["charging_verified"] is False
