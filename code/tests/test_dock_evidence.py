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
                  "calibrated": False},
        "climate": {"temp_centi": 0, "rh_centi": 0, "valid": False},
        "power": {"cell_mv": 0, "soc_centi": 0, "bus_mv": 0, "shunt_uv": 0,
                  "fuel_valid": False, "monitor_valid": False,
                  "current_calibrated": False},
        "proximity": {"raw": 0, "valid": False, "gesture": 0,
                      "gesture_events": 0, "physically_qualified": False},
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
    assert result["charging_verified"] is False
    assert result["battery_current_measured"] is False
    assert result["charger_electrically_qualified"] is False
    assert result["motor_authorized"] is False
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
    (False, False, True, True, "charger_input_without_seat"),
    (False, False, False, True, "charge_signal_without_input_fault"),
    (True, True, False, True, "charge_signal_without_input_fault"),
])
def test_independent_input_truth_table(left, right, good, charging, state):
    dock = payload()["dock"]
    dock.update(left_seated=left, right_seated=right,
                input_good=good, charge_indicated=charging)
    assert classify_dock(dock) == state


async def test_dock_evidence_refuses_forged_battery_charge_and_robot_identity():
    bad = payload()
    bad["dock"]["charging_verified"] = True
    head = FakeHead([bad])
    with pytest.raises(ValueError):
        await observe_dock_evidence(head, "robot-01")
    head = FakeHead([payload()])
    with pytest.raises(ValueError):
        await observe_dock_evidence(head, "robot-02")


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


