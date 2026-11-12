"""No forged telemetry, movement authority, current or pulse rate on the Mac."""
import copy

import httpx
import pytest
from desk_robot.aux import validate_aux
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
                  "shunt_uv": -100, "fuel_valid": True, "monitor_valid": True,
                  "current_calibrated": False},
        "proximity": {"raw": 99, "valid": True, "gesture": 1,
                      "gesture_events": 3, "physically_qualified": False},
    }


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
    assert result["power"]["current_calibrated"] is False
    assert result["proximity"]["gesture"] == 1
    assert result["proximity"]["gesture_events"] == 3
    assert result["proximity"]["physically_qualified"] is False


@pytest.mark.parametrize(
    "group,field,value",
    [
        ("pulse", "ir", -1), ("pulse", "medical", True),
        ("pulse", "bpm", 75), ("pulse", "red", 262144),
        ("pulse", "seq", True), ("pulse", "seq", -1),
        ("angles", "valid_mask", 7), ("angles", "raw", [100, 200]),
        ("angles", "magnet", [0, 0, 0]), ("angles", "present_mask", True),
        ("force", "adc", [0, 99999]), ("force", "valid", 1),
        ("force", "jaw_seq", -1), ("force", "jaw_seq", True),
        ("force", "calibrated", True), ("climate", "rh_centi", 11000),
        ("climate", "temp_centi", float("nan")),
        ("climate", "seq", True), ("climate", "age_ms", -1),
        ("power", "cell_mv", 99000), ("power", "current_calibrated", True),
        ("power", "fuel_valid", 1), ("proximity", "raw", 256),
        ("proximity", "gesture", "left"),
        ("proximity", "gesture_events", -1),
        ("proximity", "physically_qualified", True),
    ],
)
def test_aux_rejects_forged_invalid_or_calibrated_sensors(group, field, value):
    payload = copy.deepcopy(sample())
    payload[group][field] = value
    with pytest.raises(ValueError):
        validate_aux(payload, "robot-01")


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


def test_optional_bmp280_factory_compensation_is_raw_ambient_not_qualification():
    d = sample()
    d["bmp280"] = {
        "present": True, "valid": True, "chip_id": 0x58,
        "temp_centi": 2508, "pressure_pa": 100653,
        "physically_verified": False,
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
        "physically_verified": False,
    }
    d["bmp280"].update(patch)
    with pytest.raises(ValueError):
        validate_aux(d, "robot-01")
