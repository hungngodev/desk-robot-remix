"""No forged telemetry, movement authority, current or pulse rate on the Mac."""
import copy

import httpx
import pytest
from desk_robot.aux import ina226_monitor_warning, validate_aux
from desk_robot.transport import HeadError, HttpHead


def sample(robot="robot-01"):
    return {
        "robot_id": robot,
        "pulse": {"present": True, "valid": True, "part_id": 21,
                  "red": 200, "ir": 30000, "age_ms": 45, "bpm": None,
                  "medical": False},
        "angles": {"raw": [2000, 4095, 0], "present_mask": 3,
                   "valid_mask": 1, "magnet": [32, 0, 0]},
        "force": {"adc": [1024, -55], "jaw_seq": 100, "valid": True, "calibrated": False},
        "climate": {"temp_centi": 2150, "rh_centi": 4555, "valid": True},
        "power": {"cell_mv": 3900, "soc_centi": 7500, "bus_mv": 5000,
                  "shunt_uv": -100, "fuel_valid": True, "fuel_seq": 10,
                  "monitor_valid": True,
                  "current_calibrated": False},
        "proximity": {"raw": 99, "valid": True, "gesture": 1,
                      "gesture_events": 3, "physically_qualified": False},
    }


@pytest.mark.parametrize("fault", ["math_overflow", "shunt_saturated"])
def test_ina226_fault_survives_validation_without_valid_current(fault):
    data = sample()
    power = data["power"]
    power.update(monitor_fault=fault, monitor_valid=False, pack_valid=False,
                 pack_ma=0, pack_seq=12)
    assert validate_aux(data, "robot-01")["power"]["monitor_fault"] == fault
    assert "current unavailable" in ina226_monitor_warning(power)
    with pytest.raises(ValueError, match="INA226"):
        validate_aux({**data, "power": {**power, "monitor_valid": True}}, "robot-01")
    with pytest.raises(ValueError, match="INA226"):
        validate_aux({**data, "power": {**power, "pack_valid": True}}, "robot-01")


@pytest.mark.parametrize("fault", [None, True, 1, [], {}, "unknown"])
def test_ina226_unknown_fault_is_rejected(fault):
    data = sample()
    data["power"].update(monitor_fault=fault, monitor_valid=False)
    with pytest.raises(ValueError, match="INA226"):
        validate_aux(data, "robot-01")


def test_ina226_warning_does_not_invent_fault_for_legacy_or_clean_sample():
    power = sample()["power"]
    assert ina226_monitor_warning(power) is None
    power["monitor_fault"] = "none"
    assert ina226_monitor_warning(power) is None


def test_pn532_tag_telemetry_rejects_forged_evidence():
    good = sample()
    good["nfc"] = {"v": True, "t": 0x12345678, "e": 8, "s": 44}
    assert validate_aux(good, "robot-01")["nfc"]["e"] == 8
    for key, value in (
        ("v", 1), ("t", -1), ("e", True), ("s", -1),
        ("s", 0),
    ):
        bad = copy.deepcopy(good)
        bad["nfc"][key] = value
        with pytest.raises(ValueError, match="PN532"):
            validate_aux(bad, "robot-01")
    bad = copy.deepcopy(good)
    bad["nfc"]["v"] = False
    with pytest.raises(ValueError, match="PN532"):
        validate_aux(bad, "robot-01")


def test_aux_sensors_are_finite_typed_raw_and_unqualified():
    result = validate_aux(sample(), "robot-01")
    assert result["pulse"]["bpm"] is None
    assert result["force"]["calibrated"] is False
    current = sample()
    current["force"]["boot_id"] = 0x12345678
    current["force"]["jaw_age_ms"] = 25
    current["proximity"]["boot_id"] = 0x12345678
    assert validate_aux(current, "robot-01")["force"]["boot_id"] == 0x12345678
    assert validate_aux(current, "robot-01")["force"]["jaw_age_ms"] == 25
    assert validate_aux(current, "robot-01")["proximity"]["boot_id"] == 0x12345678
    assert result["power"]["current_calibrated"] is False
    assert result["proximity"]["gesture"] == 1
    assert result["proximity"]["gesture_events"] == 3
    assert result["proximity"]["physically_qualified"] is False


@pytest.mark.parametrize("force_boot, proximity_boot", [
    (101, 202), (202, 101), (0, 202), (202, 0), (0, 0),
])
def test_wroom_aux_rejects_inconsistent_epoch_across_sensor_groups(
    force_boot, proximity_boot,
):
    data = sample()
    data["force"]["boot_id"] = force_boot
    data["proximity"]["boot_id"] = proximity_boot
    with pytest.raises(ValueError, match="WROOM auxiliary boot provenance"):
        validate_aux(data, "robot-01")


async def test_mixed_boot_replay_does_not_advance_pet_aux_state():
    from types import SimpleNamespace

    from desk_robot.pet import PetController

    # A retired old proximity response cannot disguise itself as a new
    # whole-WROOM boot or reset counters already accepted under boot 202.
    data = sample()
    data["force"]["boot_id"] = 303
    data["proximity"]["boot_id"] = 101
    state = SimpleNamespace(
        enabled=True, generation=77, aux_reads=12, last_aux_boot_id=202,
        retired_aux_boot_ids={101}, last_gesture_events=7, last_paw_seq=4,
    )
    pet = SimpleNamespace(
        settings=SimpleNamespace(mode="hardware"),
        states={"robot-01": state}, _closed=False,
    )
    with pytest.raises(ValueError, match="WROOM auxiliary boot provenance"):
        await PetController._observe_aux(pet, "robot-01", 77, data)
    assert (state.aux_reads, state.last_aux_boot_id,
            state.retired_aux_boot_ids, state.last_gesture_events,
            state.last_paw_seq) == (12, 202, {101}, 7, 4)


async def test_authenticated_head_rejects_mixed_wroom_boot_id(settings, tokens):
    data = sample()
    data["force"]["boot_id"] = 101
    data["proximity"]["boot_id"] = 202
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=data)
    )) as client:
        head = HttpHead(settings.robots[0], client)
        with pytest.raises(HeadError):
            await head.aux_status()


@pytest.mark.parametrize(
    "group,field,value",
    [
        ("pulse", "ir", -1), ("pulse", "medical", True),
        ("pulse", "bpm", 75), ("pulse", "red", 262144),
        ("pulse", "seq", True), ("pulse", "seq", -1),
        ("angles", "valid_mask", 7), ("angles", "raw", [100, 200]),
        ("angles", "magnet", [0, 0, 0]), ("angles", "present_mask", True),
        ("force", "adc", [0, 99999]), ("force", "valid", 1),
        ("force", "adc", [0, -32768]), ("force", "adc", [0, 32767]),
        ("force", "jaw_seq", -1), ("force", "jaw_seq", True),
        ("force", "boot_id", -1), ("force", "boot_id", True),
        ("force", "boot_id", 4294967296),
        ("force", "jaw_age_ms", -1), ("force", "jaw_age_ms", True),
        ("force", "jaw_age_ms", 4294967296),
        ("force", "jaw_age_ms", 500),
        ("force", "calibrated", True), ("climate", "rh_centi", 11000),
        ("climate", "temp_centi", float("nan")),
        ("climate", "seq", True), ("climate", "age_ms", -1),
        ("power", "cell_mv", 99000), ("power", "current_calibrated", True),
        ("power", "fuel_valid", 1), ("power", "fuel_seq", True),
        ("power", "fuel_seq", 0), ("power", "fuel_seq", -1),
        ("power", "fuel_seq", 4294967296), ("proximity", "raw", 256),
        ("proximity", "gesture", "left"),
        ("proximity", "gesture_events", -1),
        ("proximity", "boot_id", -1),
        ("proximity", "boot_id", True),
        ("proximity", "boot_id", 4294967296),
        ("proximity", "physically_qualified", True),
    ],
)
def test_aux_rejects_forged_invalid_or_calibrated_sensors(group, field, value):
    payload = copy.deepcopy(sample())
    payload[group][field] = value
    with pytest.raises(ValueError):
        validate_aux(payload, "robot-01")


@pytest.mark.parametrize("clipped", [-32768, 32767])
def test_clipped_jaw_adc_is_visible_only_as_invalid_diagnostic(clipped):
    data = sample()
    data["force"]["adc"][1] = clipped
    data["force"]["valid"] = False
    result = validate_aux(data, "robot-01")
    assert result["force"]["adc"][1] == clipped
    assert result["force"]["valid"] is False


def test_expired_jaw_age_is_allowed_only_as_invalid_diagnostic():
    data = sample()
    data["force"].update({"jaw_age_ms": 501, "valid": False})
    result = validate_aux(data, "robot-01")
    assert result["force"]["jaw_age_ms"] == 501
    assert result["force"]["valid"] is False


def test_decoupled_per_channel_force_validity_and_cross_channel_isolation():
    # 1. Fresh belly with clipped jaw: valid=False, jaw_valid=False, belly_valid=True
    data = sample()
    data["force"].update({
        "adc": [1024, 32767],
        "belly_seq": 10,
        "belly_age_ms": 15,
        "belly_valid": True,
        "jaw_seq": 20,
        "jaw_age_ms": 15,
        "jaw_valid": False,
        "valid": False,
    })
    result = validate_aux(data, "robot-01")
    assert result["force"]["belly_valid"] is True
    assert result["force"]["jaw_valid"] is False
    assert result["force"]["valid"] is False

    # 2. Fresh jaw with stale belly: valid=False, jaw_valid=True, belly_valid=False
    data = sample()
    data["force"].update({
        "adc": [500, 1000],
        "belly_seq": 10,
        "belly_age_ms": 600,
        "belly_valid": False,
        "jaw_seq": 21,
        "jaw_age_ms": 20,
        "jaw_valid": True,
        "valid": False,
    })
    result = validate_aux(data, "robot-01")
    assert result["force"]["belly_valid"] is False
    assert result["force"]["jaw_valid"] is True
    assert result["force"]["valid"] is False

    # 3. Both valid: valid=True, jaw_valid=True, belly_valid=True
    data = sample()
    data["force"].update({
        "adc": [1024, 1000],
        "belly_seq": 11,
        "belly_age_ms": 25,
        "belly_valid": True,
        "jaw_seq": 22,
        "jaw_age_ms": 25,
        "jaw_valid": True,
        "valid": True,
    })
    result = validate_aux(data, "robot-01")
    assert result["force"]["valid"] is True

    # 4. Contradiction: valid=True when either channel is marked invalid or out of range
    for bad_update in [
        {"belly_valid": False, "jaw_valid": True, "valid": True},
        {"belly_valid": True, "jaw_valid": False, "valid": True},
        {"belly_valid": True, "jaw_valid": True, "valid": False},
        {"belly_valid": True, "belly_age_ms": 500, "jaw_valid": True, "valid": True},
        {"belly_valid": True, "belly_seq": 0, "jaw_valid": True, "valid": True},
        {"belly_valid": True, "adc": [32767, 1000], "jaw_valid": True, "valid": True},
        {"belly_valid": True, "adc": [-32768, 1000], "jaw_valid": True, "valid": True},
        {"belly_valid": True, "adc": [1000, 32767], "jaw_valid": True, "valid": True},
    ]:
        bad = copy.deepcopy(data)
        bad["force"].update(bad_update)
        with pytest.raises(ValueError, match="Invalid uncalibrated FSR sample"):
            validate_aux(bad, "robot-01")


async def test_authenticated_head_aux_rejects_wrong_source(settings, tokens):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=sample())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        head = HttpHead(settings.robots[0], client)
        result = await head.aux_status()
        assert result["pulse"]["valid"]
        assert [r.url.path for r in requests] == ["/api/aux"]


async def test_authenticated_head_aux_rejects_wrong_robot(settings, tokens):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda req: httpx.Response(200, json=sample("robot-02"))
        )
    ) as client:
        head = HttpHead(settings.robots[0], client)
        with pytest.raises(HeadError):
            await head.aux_status()


@pytest.mark.parametrize("patch", [
    {"seq": 0}, {"seq": True}, {"seq": -1},
    {"age_ms": -1}, {"age_ms": 2000}, {"age_ms": "50"},
])
def test_optional_bmp280_acquisition_identity_rejects_replay_or_bad_age(patch):
    d = sample()
    d["bmp280"] = {
        "present": True, "valid": True, "chip_id": 0x58,
        "temp_centi": 2508, "pressure_pa": 100653,
        "seq": 10, "age_ms": 50, "physically_verified": False,
    }
    d["bmp280"].update(patch)
    with pytest.raises(ValueError):
        validate_aux(d, "robot-01")


def test_optional_bmp280_factory_compensation_is_raw_ambient_not_qualification():
    d = sample()
    d["bmp280"] = {
        "present": True, "valid": True, "chip_id": 0x58,
        "temp_centi": 2508, "pressure_pa": 100653,
        "seq": 10, "age_ms": 50, "physically_verified": False,
    }
    assert validate_aux(d, "robot-01")["bmp280"]["pressure_pa"] == 100653


@pytest.mark.parametrize("patch", [
    {"chip_id": 0x60},  # BME280 is not BMP280
    {"pressure_pa": 0},
    {"pressure_pa": 150000},
    {"physically_verified": True},
    {"temp_centi": float("nan")},
    {"valid": False},
])
def test_bmp280_bad_identity_stale_or_unqualified_claim_rejected(patch):
    d = sample()
    d["bmp280"] = {
        "present": True, "valid": True, "chip_id": 0x58,
        "temp_centi": 2508, "pressure_pa": 100653,
        "seq": 10, "age_ms": 50, "physically_verified": False,
    }
    d["bmp280"].update(patch)
    with pytest.raises(ValueError):
        validate_aux(d, "robot-01")


@pytest.mark.parametrize("shunt_uv,pack_ma", [
    (25, 5), (-100, -20), (40, 8), (0, 0),
])
def test_5milliohm_ina226_pack_current_calculation_not_charger_permission(
    shunt_uv, pack_ma,
):
    data = sample()
    data["power"].update({
        "shunt_uv": shunt_uv, "pack_ma": pack_ma,
        "pack_valid": True, "pack_seq": 42,
        "current_calibrated": False,
    })
    assert validate_aux(data, "robot-01")["power"]["pack_ma"] == pack_ma
    assert data["power"]["current_calibrated"] is False


@pytest.mark.parametrize("patch", [
    {"pack_valid": True, "pack_seq": 0},
    {"pack_valid": 1},
    {"pack_seq": True},
    {"pack_ma": 19},
    {"pack_ma": float("nan")},
    {"pack_ma": 40000},
    {"pack_valid": True, "pack_ma": 5, "shunt_uv": -25},
    {"pack_valid": False, "pack_ma": 5},
    {"pack_valid": True, "monitor_valid": False},
    {"shunt_uv": 81920},
])
def test_uncalibrated_pack_current_never_accepts_replay_or_forgery(patch):
    data = sample()
    data["power"].update({
        "shunt_uv": 25, "pack_ma": 5,
        "pack_valid": True, "pack_seq": 42,
    })
    data["power"].update(patch)
    with pytest.raises(ValueError, match="INA226|battery"):
        validate_aux(data, "robot-01")


@pytest.mark.parametrize("age", [0, 250])
def test_pulse_validity_matches_wroom_inclusive_freshness_boundary(age):
    data = sample()
    data["pulse"]["age_ms"] = age
    assert validate_aux(data, "robot-01")["pulse"]["valid"] is True


@pytest.mark.parametrize("age", [251, 400, 0xffffffff])
@pytest.mark.parametrize("reported_valid", [True, False])
def test_stale_pulse_is_only_an_invalid_raw_diagnostic(age, reported_valid):
    data = sample()
    data["pulse"].update({"age_ms": age, "valid": reported_valid})
    original = copy.deepcopy(data)
    result = validate_aux(data, "robot-01")
    assert result["pulse"] == {**original["pulse"], "valid": False}
    assert {k: v for k, v in result.items() if k != "pulse"} == {
        k: v for k, v in original.items() if k != "pulse"
    }
    assert data == original


async def test_authenticated_head_isolates_stale_valid_pulse(settings, tokens):
    data = sample()
    data["pulse"]["age_ms"] = 400
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=data)
    )) as client:
        head = HttpHead(settings.robots[0], client)
        result = await head.aux_status()
    assert result["pulse"] == {**data["pulse"], "valid": False}
    for group in ("force", "climate", "power", "proximity", "angles"):
        assert result[group] == data[group]


@pytest.mark.parametrize("patch", [
    {"present": False}, {"seq": 0}, {"medical": True}, {"age_ms": -1},
])
def test_stale_pulse_does_not_bypass_schema_or_identity_guards(patch):
    data = sample()
    data["pulse"]["age_ms"] = 400
    data["pulse"].update(patch)
    with pytest.raises(ValueError, match="MAX30102"):
        validate_aux(data, "robot-01")


@pytest.mark.parametrize("ir_first", [True, False])
def test_aux_accepts_unqualified_fifo_layout_and_wheel_metadata(ir_first):
    data = sample()
    data["pulse"].update({
        "fifo_ir_first": ir_first,
        "fifo_layout_physically_verified": False,
    })
    data["angles"]["wheel_travel_qualified"] = False
    assert validate_aux(data, "robot-01") == data


@pytest.mark.parametrize("group,field,value", [
    ("pulse", "fifo_ir_first", 1),
    ("pulse", "fifo_ir_first", None),
    ("pulse", "fifo_layout_physically_verified", True),
    ("pulse", "fifo_layout_physically_verified", 0),
    ("angles", "wheel_travel_qualified", True),
    ("angles", "wheel_travel_qualified", 0),
])
def test_aux_rejects_forged_optional_physical_qualification(group, field, value):
    data = sample()
    data[group][field] = value
    with pytest.raises(ValueError):
        validate_aux(data, "robot-01")


@pytest.mark.parametrize("group", ["force", "proximity"])
def test_wroom_aux_rejects_zero_epoch_even_when_other_group_is_legacy(group):
    data = sample()
    data[group]["boot_id"] = 0
    with pytest.raises(ValueError, match="WROOM auxiliary boot provenance"):
        validate_aux(data, "robot-01")
    data[group]["boot_id"] = 101
    assert validate_aux(data, "robot-01")[group]["boot_id"] == 101
    del data[group]["boot_id"]
    assert validate_aux(data, "robot-01") == data


@pytest.mark.parametrize("channel", ["red", "ir"])
@pytest.mark.parametrize("raw", [0, 262142, 262143])
def test_pulse_adc_rail_matches_firmware_quality_guard(channel, raw):
    data = sample()
    data["pulse"].update({channel: raw, "seq": 7, "age_ms": 20})
    original = copy.deepcopy(data)
    result = validate_aux(data, "robot-01")
    assert result == {
        **original,
        "pulse": {**original["pulse"], "valid": raw != 262143},
    }
    assert data == original


async def test_authenticated_head_isolates_clipped_pulse(settings, tokens):
    data = sample()
    data["pulse"].update({"ir": 262143, "seq": 8})
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=data)
    )) as client:
        head = HttpHead(settings.robots[0], client)
        result = await head.aux_status()
    assert result == {**data, "pulse": {**data["pulse"], "valid": False}}


@pytest.mark.parametrize("age,accepted", [
    (0, True),
    (499, True),
    (500, False),
    (0xffffffff, False),
    (True, False),
    (-1, False),
    (None, False),
])
@pytest.mark.parametrize("field", ["fuel_age_ms", "pack_age_ms"])
def test_power_acquisition_age_boundaries_reject_stale_or_invalid_metadata(
    field, age, accepted,
):
    data = sample()
    data["power"].update({
        "shunt_uv": 25, "pack_ma": 5, "pack_valid": True, "pack_seq": 42,
        field: age,
    })
    if accepted:
        assert validate_aux(data, "robot-01")["power"][field] == age
    else:
        with pytest.raises(ValueError, match="MAX17048|INA226"):
            validate_aux(data, "robot-01")


@pytest.mark.parametrize("shunt_uv,accepted", [
    (-81918, False),
    (-81917, True),
    (81915, True),
    (81916, False),
])
def test_ina226_nonrail_shunt_bounds_match_signed_asymmetric_limits(
    shunt_uv, accepted,
):
    data = sample()
    data["power"]["shunt_uv"] = shunt_uv
    if accepted:
        assert validate_aux(data, "robot-01")["power"]["shunt_uv"] == shunt_uv
    else:
        with pytest.raises(ValueError, match="INA226"):
            validate_aux(data, "robot-01")


@pytest.mark.parametrize("raw, saturated", [(254, False), (255, True)])
def test_apds_proximity_adc_rail_is_not_live_evidence(raw, saturated):
    data = sample()
    data["proximity"]["raw"] = raw
    original = copy.deepcopy(data)
    result = validate_aux(data, "robot-01")
    assert result["proximity"]["valid"] is not saturated
    assert result["proximity"].get("saturated", False) is saturated
    assert data == original


def test_apds_flag_and_pulse_clipping_are_independently_invalidated():
    data = sample()
    data["pulse"]["ir"] = 262143
    data["proximity"]["saturated"] = True
    result = validate_aux(data, "robot-01")
    assert result["pulse"]["valid"] is False
    assert result["proximity"]["valid"] is False
    assert result["proximity"]["saturated"] is True
    data["proximity"]["saturated"] = 1
    with pytest.raises(ValueError, match="APDS9960"):
        validate_aux(data, "robot-01")


@pytest.mark.parametrize("value", [-1, 0, 2499, 4501, 6001, True, False,
                                  float("nan"), float("inf"), 3900.0, None])
def test_claimed_valid_aux_voltage(value):
    data = sample()
    data["power"]["cell_mv"] = value
    with pytest.raises(ValueError, match="battery"):
        validate_aux(data, "robot-01")


@pytest.mark.parametrize("value", [0, 2499])
def test_invalid_aux_voltage_remains_diagnostic(value):
    data = sample()
    data["power"].update(cell_mv=value, fuel_valid=False)
    assert validate_aux(data, "robot-01")["power"]["fuel_valid"] is False


@pytest.mark.parametrize("value", [2500, 4500])
def test_claimed_valid_aux_voltage_bounds(value):
    data = sample()
    data["power"]["cell_mv"] = value
    assert validate_aux(data, "robot-01")["power"]["fuel_valid"] is True

@pytest.mark.parametrize("patch", [
    {"seq": [0, 2, 0]}, {"seq": [True, 2, 0]}, {"seq": [1, 2]},
    {"seq": [1, float("nan"), 0]}, {"age_ms": [350, 10, 0]},
    {"age_ms": [349, 350, 0]}, {"age_ms": [float("inf"), 10, 0]},
    {"age_ms": [349, 10, -1]}, {"age_ms": None}, {"boot_id": 0},
    {"boot_id": True}, {"boot_id": float("inf")},
])
def test_angle_acquisition_rejects_invalid_metadata(patch):
    data = sample()
    data["angles"].update({
        "valid_mask": 3, "magnet": [32, 32, 0],
        "seq": [1, 2, 0], "age_ms": [349, 10, 0], "boot_id": 7,
    })
    data["angles"].update(patch)
    with pytest.raises(ValueError, match="AS5600"):
        validate_aux(data, "robot-01")


def test_angle_acquisition_accepts_legacy_and_invalid_channel_diagnostics():
    data = sample()
    assert validate_aux(data, "robot-01") == data
    data["angles"].update({
        "seq": [1, 0, 0], "age_ms": [349, 0xffffffff, 0], "boot_id": 7,
    })
    assert validate_aux(data, "robot-01") == data
    del data["angles"]["age_ms"]
    with pytest.raises(ValueError, match="AS5600"):
        validate_aux(data, "robot-01")
