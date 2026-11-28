"""Read-only ambient telemetry provenance at the actual tool-context route.

The route fake supplies an already authenticated human turn. It deliberately
does not use a physical WROOM or claim mounted sensor calibration.
"""
import asyncio
import math
from copy import deepcopy
from types import SimpleNamespace

import pytest
from desk_robot.api_robot_status import register_robot_status_routes
from fastapi import FastAPI, HTTPException
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


def _route(initial, *, before_reply=None):
    data = {
        "robot_id": "robot-01",
        "force": {"boot_id": 123}, "proximity": {"boot_id": 123},
        **deepcopy(initial),
    }
    heard = []
    current_turn = SimpleNamespace(epoch=1)
    head = SimpleNamespace()

    async def aux_status():
        if before_reply is not None:
            await before_reply()
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
    def remember(owner, rid, kind, summary):
        if owner[1] != current_turn.epoch:
            return False
        heard.append((owner, rid, kind, summary))
        return True

    def current_tool_context(owner, robot_id, message):
        # Only a genuinely current tool turn may return a slow raw sample.
        if owner is None or owner[1] != current_turn.epoch:
            raise HTTPException(409, message)

    register_robot_status_routes(
        app, settings, authorize=lambda: None, coordinator=lambda: fleet,
        requested_tool_context=lambda request, robot_id: (
            (current_turn, current_turn.epoch)
            if request.headers.get("x-test-turn") == "active" else None
        ),
        remember_tool_context=remember,
        current_tool_context=current_tool_context,
    )
    return app, data, heard, (current_turn, 1)


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
            "/v1/robots/robot-01/aux", headers={"x-test-turn": "active", "x-desk-robot-tool-receipt": "1"},
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
            headers={"x-test-turn": "active", "x-desk-robot-tool-receipt": "1"},
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
                headers={"x-test-turn": "active", "x-desk-robot-tool-receipt": "1"},
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
            headers={"x-test-turn": "active", "x-desk-robot-tool-receipt": "1"},
        ).status_code == 200
        assert len(heard) == 1


def test_ambient_provenance_is_source_scoped_and_aggregates_one_receipt():
    app, data, heard, _owner = _route({"climate": _climate(), "bmp280": _bmp()})
    with TestClient(app) as client:
        url = "/v1/robots/robot-01/aux"
        assert client.get(url, headers={"x-test-turn": "active", "x-desk-robot-tool-receipt": "1"}).status_code == 200
        assert len(heard) == 1
        assert "SHT41" in heard[0][3] and "BMP280" in heard[0][3]
        assert client.get(url, headers={"x-test-turn": "active", "x-desk-robot-tool-receipt": "1"}).status_code == 200
        assert len(heard) == 1
        data["bmp280"]["seq"] += 1
        assert client.get(url, headers={"x-test-turn": "active", "x-desk-robot-tool-receipt": "1"}).status_code == 200
        assert len(heard) == 2
        assert "BMP280" in heard[-1][3] and "SHT41" not in heard[-1][3]


@pytest.mark.parametrize("sensor,field,bad", [
    ("climate", "seq", True), ("climate", "age_ms", True),
    ("climate", "temp_centi", 23.4), ("climate", "rh_centi", 10001),
    ("bmp280", "seq", False), ("bmp280", "age_ms", -1),
    ("bmp280", "pressure_pa", float("nan")),
    ("bmp280", "pressure_pa", float("inf")),
    ("bmp280", "pressure_pa", float("-inf")),
    ("bmp280", "chip_id", 0),
])
def test_ambient_malformed_legacy_value_is_not_promoted(sensor, field, bad):
    payload = _climate() if sensor == "climate" else _bmp()
    payload[field] = bad
    app, _data, heard, _owner = _route({sensor: payload})
    with TestClient(app) as client:
        response = client.get(
            "/v1/robots/robot-01/aux",
            headers={"x-test-turn": "active", "x-desk-robot-tool-receipt": "1"},
        )
    assert response.status_code == 200
    if isinstance(bad, float) and not math.isfinite(bad):
        assert response.json()[sensor][field] is None
    assert heard == []


@pytest.mark.parametrize("sensor", ["climate", "bmp280"])
def test_new_wroom_boot_resets_sensor_cursor_without_replaying_retired_boot(sensor):
    sample = _climate(seq=120) if sensor == "climate" else _bmp(seq=120)
    app, data, heard, _owner = _route({sensor: sample})
    with TestClient(app) as client:
        def request():
            return client.get(
                "/v1/robots/robot-01/aux", headers={"x-test-turn": "active", "x-desk-robot-tool-receipt": "1"},
            )

        assert request().status_code == 200
        assert len(heard) == 1
        data["force"]["boot_id"] = data["proximity"]["boot_id"] = 124
        data[sensor]["seq"] = 1
        assert request().status_code == 200
        assert len(heard) == 2
        assert "seq=1" in heard[-1][3]

        # A delayed old boot cannot reclaim a retired source epoch.
        data["force"]["boot_id"] = data["proximity"]["boot_id"] = 123
        data[sensor]["seq"] = 121
        assert request().status_code == 200
        assert len(heard) == 2

        data["force"]["boot_id"] = data["proximity"]["boot_id"] = 124
        data[sensor]["seq"] = 1
        assert request().status_code == 200
        assert len(heard) == 2
        data[sensor]["seq"] = 2
        assert request().status_code == 200
        assert len(heard) == 3


@pytest.mark.parametrize("boot", [None, 0, True, "123"])
def test_missing_or_untyped_boot_epoch_keeps_ambient_diagnostic_only(boot):
    app, data, heard, _owner = _route({"climate": _climate()})
    if boot is None:
        del data["force"]["boot_id"]
    else:
        data["force"]["boot_id"] = boot
    with TestClient(app) as client:
        assert client.get(
            "/v1/robots/robot-01/aux", headers={"x-test-turn": "active", "x-desk-robot-tool-receipt": "1"},
        ).status_code == 200
    assert heard == []


def test_canceled_turn_does_not_consume_sensor_acquisition():
    canceled = False
    owner = None

    async def interrupt_before_aux_returns():
        nonlocal canceled
        if not canceled:
            await asyncio.sleep(0)
            owner[0].epoch += 1
            canceled = True

    app, _data, heard, owner = _route(
        {"climate": _climate(seq=51)}, before_reply=interrupt_before_aux_returns,
    )
    with TestClient(app) as client:
        def request():
            return client.get(
                "/v1/robots/robot-01/aux", headers={"x-test-turn": "active", "x-desk-robot-tool-receipt": "1"},
            )

        assert request().status_code == 409
        assert heard == []
        assert request().status_code == 200
        assert len(heard) == 1
        assert "seq=51" in heard[0][3]
        assert request().status_code == 200
        assert len(heard) == 1


@pytest.mark.parametrize("sensor", ["climate", "bmp280"])
@pytest.mark.parametrize("invalid_valid", [False, 1, "true", None])
def test_non_true_valid_flag_rejected_and_does_not_burn_sequence(sensor, invalid_valid):
    payload = _climate(seq=19, age_ms=25) if sensor == "climate" else _bmp(seq=19, age_ms=25)
    payload["valid"] = invalid_valid
    app, data, heard, _owner = _route({sensor: payload})
    headers = {"x-test-turn": "active", "x-desk-robot-tool-receipt": "1"}
    with TestClient(app) as client:
        assert client.get("/v1/robots/robot-01/aux", headers=headers).status_code == 200
        assert heard == []
        data[sensor]["valid"] = True
        assert client.get("/v1/robots/robot-01/aux", headers=headers).status_code == 200
        assert len(heard) == 1
        assert "seq=19" in heard[0][3]


@pytest.mark.parametrize("present_value", [False, 1, None, "missing"])
def test_bmp_presence_must_be_strict_boolean_true(present_value):
    bmp = _bmp(seq=25, age_ms=40)
    if present_value == "missing":
        del bmp["present"]
    else:
        bmp["present"] = present_value
    app, _data, heard, _owner = _route({"bmp280": bmp})
    headers = {"x-test-turn": "active", "x-desk-robot-tool-receipt": "1"}
    with TestClient(app) as client:
        assert client.get("/v1/robots/robot-01/aux", headers=headers).status_code == 200
    assert heard == []


def test_mismatched_force_and_proximity_boot_epochs_reject_ambient_provenance():
    app, data, heard, _owner = _route({"climate": _climate(seq=30, age_ms=20)})
    data["force"]["boot_id"] = 123
    data["proximity"]["boot_id"] = 124
    headers = {"x-test-turn": "active", "x-desk-robot-tool-receipt": "1"}
    with TestClient(app) as client:
        assert client.get("/v1/robots/robot-01/aux", headers=headers).status_code == 200
    assert heard == []


@pytest.mark.parametrize("sensor", ["climate", "bmp280"])
def test_uint32_sequence_wrap_and_half_range_boundary(sensor):
    payload = _climate(seq=0xFFFFFFFF, age_ms=10) if sensor == "climate" else _bmp(seq=0xFFFFFFFF, age_ms=10)
    app, data, heard, _owner = _route({sensor: payload})
    headers = {"x-test-turn": "active", "x-desk-robot-tool-receipt": "1"}
    with TestClient(app) as client:
        assert client.get("/v1/robots/robot-01/aux", headers=headers).status_code == 200
        assert len(heard) == 1

        data[sensor]["seq"] = 1
        assert client.get("/v1/robots/robot-01/aux", headers=headers).status_code == 200
        assert len(heard) == 2

        data[sensor]["seq"] = 0xFFFFFFFF
        assert client.get("/v1/robots/robot-01/aux", headers=headers).status_code == 200
        assert len(heard) == 2

        # Exactly 0x80000000 ahead of 1 sits outside strictly-newer half-range.
        data[sensor]["seq"] = 0x80000001
        assert client.get("/v1/robots/robot-01/aux", headers=headers).status_code == 200
        assert len(heard) == 2

        data[sensor]["seq"] = 2
        assert client.get("/v1/robots/robot-01/aux", headers=headers).status_code == 200
        assert len(heard) == 3


@pytest.mark.parametrize(("sensor", "max_valid_age"), [("climate", 999), ("bmp280", 1999)])
def test_positive_max_age_boundaries_are_accepted(monkeypatch, sensor, max_valid_age):
    from desk_robot import api_robot_status

    # Isolate the wire age boundary from host request timing.
    monkeypatch.setattr(api_robot_status, "monotonic_ns", lambda: 0)
    payload = _climate(seq=99, age_ms=max_valid_age) if sensor == "climate" else _bmp(seq=99, age_ms=max_valid_age)
    app, _data, heard, _owner = _route({sensor: payload})
    headers = {"x-test-turn": "active", "x-desk-robot-tool-receipt": "1"}
    with TestClient(app) as client:
        assert client.get("/v1/robots/robot-01/aux", headers=headers).status_code == 200
    assert len(heard) == 1
    assert "seq=99" in heard[0][3]


@pytest.mark.parametrize("sensor,ttl", [("climate", 1000), ("bmp280", 2000)])
def test_transport_elapsed_expires_ambient_without_consuming_sequence(monkeypatch, sensor, ttl):
    from desk_robot import api_robot_status

    payload = _climate(seq=99, age_ms=ttl - 10) if sensor == "climate" else _bmp(
        seq=99, age_ms=ttl - 10,
    )
    app, _data, heard, _owner = _route({sensor: payload})
    # Exact TTL, then 1 ms below TTL, then a duplicate fresh sample.
    ticks = iter([0, 10_000_000, 20_000_000, 29_000_000, 30_000_000, 30_000_000])
    monkeypatch.setattr(api_robot_status, "monotonic_ns", lambda: next(ticks))
    headers = {"x-test-turn": "active", "x-desk-robot-tool-receipt": "1"}
    with TestClient(app) as client:
        url = "/v1/robots/robot-01/aux"
        response = client.get(url, headers=headers)
        assert response.status_code == 200
        assert response.json()[sensor]["age_ms"] == ttl - 10
        assert heard == []
        assert client.get(url, headers=headers).status_code == 200
        assert len(heard) == 1
        assert "seq=99" in heard[0][3]
        assert client.get(url, headers=headers).status_code == 200
        assert len(heard) == 1
