"""Read-only ambient telemetry provenance at the actual tool-context route.

The route fake supplies an already authenticated human turn. It deliberately
does not use a physical WROOM or claim mounted sensor calibration.
"""
from copy import deepcopy
from types import SimpleNamespace

import pytest
from desk_robot.api_robot_status import register_robot_status_routes
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _climate(*, seq=12, age_ms=50):
    return {
        "valid": True, "temp_centi": 2312, "rh_centi": 4420,
        "seq": seq, "age_ms": age_ms,
    }


def _bmp(*, seq=71, age_ms=240):
    return {
        "present": True, "valid": True, "chip_id": 0x58,
        "temp_centi": 2200, "pressure_pa": 101325,
        "physically_verified": False, "seq": seq, "age_ms": age_ms,
    }


def _route(initial):
    data = {"robot_id": "robot-01", **deepcopy(initial)}
    heard = []
    authorized_owner = object()
    head = SimpleNamespace()

    async def aux_status():
        return deepcopy(data)

    head.aux_status = aux_status
    fleet = SimpleNamespace(
        heads={"robot-01": head},
        robot=lambda robot_id: object() if robot_id == "robot-01" else None,
    )
    settings = SimpleNamespace(
        mode="simulation",
        robots=[SimpleNamespace(id="robot-01", name="Pet", motion_enabled=False)],
    )
    app = FastAPI()
    register_robot_status_routes(
        app, settings, authorize=lambda: None, coordinator=lambda: fleet,
        requested_tool_context=lambda request, robot_id: (
            authorized_owner if request.headers.get("x-test-turn") == "active"
            else None
        ),
        remember_tool_context=lambda owner, rid, kind, summary: heard.append(
            (owner, rid, kind, summary)
        ),
    )
    return app, data, heard, authorized_owner


@pytest.mark.parametrize("sensor,missing", [
    ("climate", "seq"), ("climate", "age_ms"),
    ("bmp280", "seq"), ("bmp280", "age_ms"),
])
def test_missing_ambient_acquisition_clock_is_diagnostic_only(sensor, missing):
    value = _climate() if sensor == "climate" else _bmp()
    del value[missing]
    app, _data, heard, _owner = _route({sensor: value})
    with TestClient(app) as client:
        response = client.get(
            "/v1/robots/robot-01/aux", headers={"x-test-turn": "active"},
        )
    assert response.status_code == 200
    assert response.json()[sensor]["valid"] is True
    assert heard == []


@pytest.mark.parametrize("sensor,age", [
    ("climate", 1000), ("climate", 0xffffffff),
    ("bmp280", 2000), ("bmp280", 0xffffffff),
])
def test_stale_ambient_age_never_generates_new_tool_fact(sensor, age):
    payload = _climate(age_ms=age) if sensor == "climate" else _bmp(age_ms=age)
    app, _data, heard, _owner = _route({sensor: payload})
    with TestClient(app) as client:
        assert client.get(
            "/v1/robots/robot-01/aux",
            headers={"x-test-turn": "active"},
        ).status_code == 200
    assert heard == []


@pytest.mark.parametrize("sensor", ["climate", "bmp280"])
def test_fresh_ambient_once_then_duplicate_and_replay_remain_silent(sensor):
    first = _climate() if sensor == "climate" else _bmp()
    app, data, heard, owner = _route({sensor: first})
    with TestClient(app) as client:
        def request():
            return client.get(
                "/v1/robots/robot-01/aux",
                headers={"x-test-turn": "active"},
            )
        assert request().status_code == 200
        assert len(heard) == 1
        assert heard[0][:3] == (owner, "robot-01", "sensor_telemetry")
        assert f"seq={first['seq']}" in heard[0][3]
        assert f"age_ms={first['age_ms']}" in heard[0][3]
        request()  # The same cached WROOM sample is not another acquisition.
        assert len(heard) == 1
        data[sensor]["seq"] += 1
        assert request().status_code == 200
        assert len(heard) == 2
        data[sensor]["seq"] -= 1
        assert request().status_code == 200
        assert len(heard) == 2


@pytest.mark.parametrize("sensor", ["climate", "bmp280"])
def test_dashboard_does_not_consume_first_valid_human_ambient_receipt(sensor):
    payload = _climate() if sensor == "climate" else _bmp()
    app, _data, heard, _owner = _route({sensor: payload})
    with TestClient(app) as client:
        assert client.get("/v1/robots/robot-01/aux").status_code == 200
        assert heard == []
        assert client.get(
            "/v1/robots/robot-01/aux",
            headers={"x-test-turn": "active"},
        ).status_code == 200
        assert len(heard) == 1


def test_ambient_provenance_is_source_scoped_and_aggregates_one_receipt():
    app, data, heard, _owner = _route({"climate": _climate(), "bmp280": _bmp()})
    with TestClient(app) as client:
        url = "/v1/robots/robot-01/aux"
        assert client.get(url, headers={"x-test-turn": "active"}).status_code == 200
        assert len(heard) == 1
        assert "SHT41" in heard[0][3] and "BMP280" in heard[0][3]
        assert client.get(url, headers={"x-test-turn": "active"}).status_code == 200
        assert len(heard) == 1
        data["bmp280"]["seq"] += 1
        assert client.get(url, headers={"x-test-turn": "active"}).status_code == 200
        assert len(heard) == 2
        assert "BMP280" in heard[-1][3] and "SHT41" not in heard[-1][3]


@pytest.mark.parametrize("sensor,field,bad", [
    ("climate", "seq", True), ("climate", "age_ms", True),
    ("climate", "temp_centi", 23.4), ("climate", "rh_centi", 10001),
    ("bmp280", "seq", False), ("bmp280", "age_ms", -1),
    ("bmp280", "pressure_pa", float("nan")),
    ("bmp280", "chip_id", 0),
])
def test_ambient_malformed_legacy_value_is_not_promoted(sensor, field, bad):
    payload = _climate() if sensor == "climate" else _bmp()
    payload[field] = bad
    app, _data, heard, _owner = _route({sensor: payload})
    with TestClient(app) as client:
        assert client.get(
            "/v1/robots/robot-01/aux",
            headers={"x-test-turn": "active"},
        ).status_code == 200
    assert heard == []
