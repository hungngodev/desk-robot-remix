"""Read-only physical dock diagnostics cannot masquerade as verified charging."""
import copy

import pytest
from desk_robot.dock_evidence import DockContactInhibit, classify_dock, observe_dock_evidence


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
    (False, False, False, True, "charge_signal_without_input_fault"),
    (False, False, True, False, "charger_input_without_seat"),
    (False, False, True, True, "charge_signal_without_seat_fault"),
    (False, True, False, False, "asymmetric_seat_or_fault"),
    (False, True, False, True, "charge_signal_without_input_fault"),
    (False, True, True, False, "asymmetric_seat_or_fault"),
    (False, True, True, True, "asymmetric_seat_or_fault"),
    (True, False, False, False, "asymmetric_seat_or_fault"),
    (True, False, False, True, "charge_signal_without_input_fault"),
    (True, False, True, False, "asymmetric_seat_or_fault"),
    (True, False, True, True, "asymmetric_seat_or_fault"),
    (True, True, False, False, "seated_but_unpowered"),
    (True, True, False, True, "charge_signal_without_input_fault"),
    (True, True, True, False, "input_present_not_charging"),
    (True, True, True, True, "charger_reports_active"),
])
def test_independent_input_truth_table(left, right, good, charging, state):
    dock = payload()["dock"]
    dock.update(left_seated=left, right_seated=right,
                input_good=good, charge_indicated=charging)
    assert classify_dock(dock) == state


@pytest.mark.parametrize(("left", "right"), [(True, False), (False, True)])
@pytest.mark.parametrize("charging", [False, True])
async def test_asymmetric_seat_both_orientations_refuse_charge_and_motion(
    monkeypatch, left, right, charging,
):
    async def fast(_seconds):
        pass

    monkeypatch.setattr("desk_robot.dock_evidence.asyncio.sleep", fast)
    samples = fresh_samples()
    for frame in samples:
        frame["dock"].update(
            left_seated=left, right_seated=right,
            input_good=True, charge_indicated=charging,
        )
    head = FakeHead(samples)
    result = await observe_dock_evidence(head, "robot-01")
    assert result["state"] == "asymmetric_seat_or_fault"
    assert result["stable_three_samples"] is True
    assert result["charging_verified"] is False
    assert result["charging_authorized"] is False
    assert result["motor_authorized"] is False
    assert result["raw_pack_direction"] == "not_available"
    assert head.commands == []



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
            pack_seq=index + 40, pack_age_ms=35, monitor_valid=True,
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
            pack_age_ms=35,
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
            pack_seq=9, pack_age_ms=35, monitor_valid=True,
        )
    result = await observe_dock_evidence(FakeHead(samples), "robot-01")
    assert result["stable_three_samples"]  # independent dock pin samples pass
    assert result["raw_pack_direction"] == "acquisition_replay"
    assert result["raw_pack_samples_fresh"] is False
    assert result["raw_pack_ma"] == []
    assert result["charging_verified"] is False


@pytest.mark.parametrize(("source_age_ms", "transport_ms", "fresh"), [
    (35, 20, True),
    (480, 100, False),
    (499, 2, False),
])
async def test_pack_current_consumer_age_is_independent_of_dock_pin_age(
    monkeypatch, source_age_ms, transport_ms, fresh,
):
    import desk_robot.dock_evidence as evidence

    now = [200.0]
    monkeypatch.setattr(evidence, "monotonic", lambda: now[0])

    async def fast(_seconds):
        pass

    monkeypatch.setattr(evidence.asyncio, "sleep", fast)

    class TimedHead(FakeHead):
        async def aux_status(self):
            now[0] += transport_ms / 1000.0
            return await super().aux_status()

    samples = fresh_samples()
    for index, record in enumerate(samples):
        record["dock"]["age_ms"] = 10
        record["power"].update(
            shunt_uv=-150, pack_ma=-30, pack_valid=True,
            pack_seq=index + 1, monitor_valid=True,
            pack_age_ms=source_age_ms,
        )
    head = TimedHead(samples)
    result = await observe_dock_evidence(head, "robot-01")
    assert result["stable_three_samples"]
    assert result["state"] == "charger_reports_active"
    assert result["raw_pack_samples_fresh"] is fresh
    assert result["raw_pack_direction"] == (
        "out_of_pack_unqualified" if fresh
        else "current_sample_stale_or_age_unverified"
    )
    assert result["raw_pack_ma"] == ([-30] * 3 if fresh else [])
    assert result["charger_indicator_net_discharge_conflict"] is fresh
    assert not result["battery_current_measured"]
    assert not result["charging_verified"] and not result["charging_authorized"]
    assert head.commands == []


async def test_old_pack_telemetry_without_age_cannot_claim_fresh_current(monkeypatch):
    async def fast(_seconds):
        pass

    monkeypatch.setattr("desk_robot.dock_evidence.asyncio.sleep", fast)
    samples = fresh_samples()
    for index, record in enumerate(samples):
        record["power"].update(
            shunt_uv=150, pack_ma=30, pack_valid=True,
            pack_seq=index + 9, monitor_valid=True,
        )
    result = await observe_dock_evidence(FakeHead(samples), "robot-01")
    assert result["stable_three_samples"]
    assert not result["raw_pack_samples_fresh"]
    assert result["raw_pack_direction"] == "current_sample_stale_or_age_unverified"
    assert not result["charging_verified"] and not result["charging_authorized"]


@pytest.mark.parametrize("invalid", [True, -1, 0.5, 500, 0xffffffff + 1])
def test_pack_age_source_contract_rejects_unqualified_timestamp(invalid):
    from desk_robot.aux import validate_aux

    frame = payload()
    frame["power"].update(
        shunt_uv=150, pack_ma=30, pack_valid=True, pack_seq=1,
        monitor_valid=True, pack_age_ms=invalid,
    )
    with pytest.raises(ValueError, match="INA226 pack"):
        validate_aux(frame, "robot-01")


def test_wroom_pack_age_field_uses_real_monitor_sample_clock():
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1]
              / "firmware/body/lib/BodyControl/BodyControl.cpp").read_text()
    assert r'"pack_age_ms":%lu' not in source  # source escapes JSON in C++
    assert r'\"pack_age_ms\":%lu' in source
    assert "now_ms - a.gauge.monitor_at_ms" in source
    assert "a.gauge.monitor_sample_seq != 0U" in source


@pytest.mark.parametrize("pause_after", [1, 2])
async def test_dock_observation_expires_after_scheduling_pause_and_retry_is_fresh(
    monkeypatch, pause_after,
):
    import desk_robot.dock_evidence as evidence

    now = [100.0]
    sleep_calls = [0]
    monkeypatch.setattr(evidence, "monotonic", lambda: now[0])

    async def delayed_sleep(seconds):
        sleep_calls[0] += 1
        now[0] += seconds + (2.0 if sleep_calls[0] == pause_after else 0.05)

    monkeypatch.setattr(evidence.asyncio, "sleep", delayed_sleep)
    head = FakeHead(fresh_samples(pause_after + 3))

    expired = await observe_dock_evidence(head, "robot-01")
    assert expired["state"] == "dock_observation_window_expired"
    assert not expired["stable_three_samples"]
    assert not expired["raw_pack_samples_fresh"]
    assert not expired["charging_authorized"]
    assert not expired["motor_authorized"]

    # A subsequent request must read three new samples, not use the
    # aborted attempt's partial observations.
    retry = await observe_dock_evidence(head, "robot-01")
    assert retry["state"] == "charger_reports_active"
    assert retry["stable_three_samples"]
    assert not retry["charging_verified"]
    assert not retry["charging_authorized"]
    assert not retry["motor_authorized"]
    assert head.commands == []


def dock_pin_sample(seq, *, asserted_pin=None, asserted=False, age=5):
    pin = asserted_pin or ("left_seated" if asserted else None)
    return dict(
        present=True, valid=True, charging_verified=False, seq=seq, age_ms=age,
        left_seated=(pin == "left_seated"),
        right_seated=(pin == "right_seated"),
        input_good=(pin == "input_good"),
        charge_indicated=(pin == "charge_indicated"),
    )


@pytest.mark.parametrize(
    "pin_name",
    ["left_seated", "right_seated", "input_good", "charge_indicated"],
)
def test_dock_inhibit_one_hot_pins_and_streak_reset(pin_name):
    guard = DockContactInhibit()
    assert guard.observe(dock_pin_sample(1, asserted_pin=pin_name), 17)
    assert guard.inhibited
    # Two consecutive fresh all-clear packets must not release yet.
    assert guard.observe(dock_pin_sample(2), 17)
    assert guard.inhibited
    assert guard.observe(dock_pin_sample(3), 17)
    assert guard.inhibited
    # A newly asserted pin resets the clear streak so clear #1/#2 must restart.
    assert guard.observe(dock_pin_sample(4, asserted_pin=pin_name), 17)
    assert guard.inhibited
    for seq in (5, 6):
        assert guard.observe(dock_pin_sample(seq), 17)
        assert guard.inhibited
    # Only the third consecutive fresh all-clear releases.
    assert guard.observe(dock_pin_sample(7), 17)
    assert not guard.inhibited


@pytest.mark.parametrize(
    "pin_name",
    ["left_seated", "right_seated", "input_good", "charge_indicated"],
)
async def test_mac_aux_telemetry_ingestion_inhibits_for_each_one_hot_pin(
    tmp_path, pin_name,
):
    from pathlib import Path

    from desk_robot.config import load_settings
    from desk_robot.conversation import Conversation
    from desk_robot.memory import MemoryStore
    from desk_robot.pet import PetController, SceneChange
    from desk_robot.simulator import SimulatedChat, SimulatedSpeaker

    class NoScene:
        async def compare(self, *_a, **_kw):
            return SceneChange("none", "", 0.0)

    root = Path(__file__).resolve().parents[2]
    settings = load_settings(root / "code/config/fleet.simulation.toml")
    settings.mode = "hardware"
    memory = MemoryStore(tmp_path, [r.id for r in settings.robots])
    conversation = Conversation(settings, SimulatedChat(), SimulatedSpeaker(), memory=memory)
    inhibit_events = []
    pet = PetController(
        settings, {}, conversation, memory, NoScene(),
        on_dock_inhibit_changed=lambda rid, flag: inhibit_events.append((rid, flag)),
    )
    state = pet.states["robot-01"]
    state.enabled = True
    state.generation = 1

    def make_aux(seq: int, asserted: str | None = None) -> dict:
        frame = payload()
        frame["dock"] = dock_pin_sample(seq, asserted_pin=asserted)
        return frame

    try:
        await pet._observe_aux(
            "robot-01", 1, make_aux(1, asserted=pin_name), request_elapsed_ms=5.0,
        )
        assert pet.is_dock_charging_inhibited("robot-01") is True
        assert inhibit_events == [("robot-01", True)]
        await pet._observe_aux("robot-01", 1, make_aux(2), request_elapsed_ms=5.0)
        await pet._observe_aux("robot-01", 1, make_aux(3), request_elapsed_ms=5.0)
        assert pet.is_dock_charging_inhibited("robot-01") is True
        await pet._observe_aux("robot-01", 1, make_aux(4), request_elapsed_ms=5.0)
        assert pet.is_dock_charging_inhibited("robot-01") is False
        assert inhibit_events == [("robot-01", True), ("robot-01", False)]
    finally:
        state.enabled = False
        await pet.close()


def test_dock_inhibit_missing_replayed_and_legacy_cannot_release():
    guard = DockContactInhibit()
    assert guard.observe(dock_pin_sample(5, asserted=True), 17)
    assert guard.inhibited
    assert not guard.observe(None, 17)
    guard.invalidate()
    assert not guard.observe(dock_pin_sample(4), 17)
    assert not guard.observe(dock_pin_sample(5), 17)
    assert guard.observe(dock_pin_sample(6), None)
    assert guard.inhibited
    for seq in (6, 7):
        assert guard.observe(dock_pin_sample(seq), 17)
        assert guard.inhibited
    assert guard.observe(dock_pin_sample(8), 17)
    assert not guard.inhibited


def test_dock_inhibit_reboot_and_retired_epoch_do_not_release():
    guard = DockContactInhibit()
    assert guard.observe(dock_pin_sample(100, asserted=True), 17)
    assert guard.observe(dock_pin_sample(1), 18)
    assert guard.inhibited
    assert not guard.observe(dock_pin_sample(101), 17)
    assert guard.inhibited
    for seq in (2, 3, 4):
        assert guard.observe(dock_pin_sample(seq), 18)
    assert not guard.inhibited


@pytest.mark.parametrize("elapsed", [495, float("nan"), float("inf"), -1, True])
def test_dock_inhibit_invalid_or_expired_never_releases(elapsed):
    guard = DockContactInhibit()
    assert guard.observe(dock_pin_sample(1, asserted=True), 17)
    assert not guard.observe(dock_pin_sample(2), 17, elapsed)
    assert guard.inhibited


def test_dock_inhibit_rollover_and_replay_break_confirmation():
    guard = DockContactInhibit()
    assert guard.observe(dock_pin_sample(0xfffffffe, asserted=True), 17)
    assert guard.observe(dock_pin_sample(0xffffffff), 17)
    assert guard.observe(dock_pin_sample(1), 17)
    assert not guard.observe(dock_pin_sample(1), 17)
    for seq in (2, 3):
        assert guard.observe(dock_pin_sample(seq), 17)
        assert guard.inhibited
    assert guard.observe(dock_pin_sample(4), 17)
    assert not guard.inhibited


def test_dock_inhibit_huge_age_cannot_raise_or_release():
    guard = DockContactInhibit()
    assert guard.observe(dock_pin_sample(1, asserted=True), 17)
    assert not guard.observe(dock_pin_sample(2, age=10**1000), 17, 0.5)
    assert guard.inhibited


@pytest.mark.parametrize("shunt", [-81920, -81919, -81918, 81916, 81917, 81918, 81919, 81920])
@pytest.mark.parametrize("include_pack", [False, True])
def test_saturated_shunt_cannot_be_valid_telemetry(shunt, include_pack):
    from desk_robot.aux import validate_aux

    frame = payload()
    frame["power"].update(shunt_uv=shunt, monitor_valid=True)
    if include_pack:
        frame["power"].update(
            pack_ma=int(shunt / 5), pack_valid=True, pack_seq=1, pack_age_ms=35,
        )
    with pytest.raises(ValueError, match="INA226 saturated shunt"):
        validate_aux(frame, "robot-01")


@pytest.mark.parametrize("shunt", [-81917, -81915, 0, 81915])
@pytest.mark.parametrize("include_pack", [False, True])
def test_unsaturated_shunt_wire_boundaries_remain_valid(shunt, include_pack):
    from desk_robot.aux import validate_aux

    frame = payload()
    frame["power"].update(shunt_uv=shunt, monitor_valid=True)
    if include_pack:
        frame["power"].update(
            pack_ma=int(shunt / 5), pack_valid=True, pack_seq=1, pack_age_ms=35,
        )
    assert validate_aux(frame, "robot-01")["power"]["monitor_valid"]


@pytest.mark.parametrize("shunt", [-81920, 81917])
def test_invalid_shunt_diagnostic_does_not_invalidate_other_sensors(shunt):
    from desk_robot.aux import validate_aux

    frame = payload()
    frame["power"].update(
        shunt_uv=shunt, monitor_valid=False, pack_valid=False,
        pack_ma=0, pack_seq=1, pack_age_ms=35,
    )
    result = validate_aux(frame, "robot-01")
    assert result["power"]["monitor_valid"] is False
    assert result["dock"]["valid"] is True
