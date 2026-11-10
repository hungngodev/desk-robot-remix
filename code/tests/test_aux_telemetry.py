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
        "force": {"adc": [1024, -55], "valid": True, "calibrated": False},
        "climate": {"temp_centi": 2150, "rh_centi": 4555, "valid": True},
        "power": {"cell_mv": 3900, "soc_centi": 7500, "bus_mv": 5000,
                  "shunt_uv": -100, "fuel_valid": True, "monitor_valid": True,
                  "current_calibrated": False},
        "proximity": {"raw": 99, "valid": True, "gesture": 1,
                      "gesture_events": 3, "physically_qualified": False},
    }


def test_aux_sensors_are_finite_typed_raw_and_unqualified():
    result = validate_aux(sample(), "robot-01")
    assert result["pulse"]["bpm"] is None
    assert result["force"]["calibrated"] is False
    assert result["power"]["current_calibrated"] is False
    assert result["proximity"]["gesture"] is None


@pytest.mark.parametrize(
    "group,field,value",
    [
        ("pulse", "ir", -1), ("pulse", "medical", True),
        ("pulse", "bpm", 75), ("pulse", "red", 262144),
        ("angles", "valid_mask", 7), ("angles", "raw", [100, 200]),
        ("angles", "magnet", [0, 0, 0]), ("angles", "present_mask", True),
        ("force", "adc", [0, 99999]), ("force", "valid", 1),
        ("force", "calibrated", True), ("climate", "rh_centi", 11000),
        ("climate", "temp_centi", float("nan")),
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
