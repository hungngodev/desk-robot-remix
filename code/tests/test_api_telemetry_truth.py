"""Read-only status endpoints distinguish absent adapters from raw evidence."""

from types import SimpleNamespace

import httpx
import pytest
from desk_robot.api_robot_status import register_robot_status_routes
from desk_robot.transport import HeadError
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _status_client(heads, *, room_enabled=False, room_error=None, mode="hardware"):
    app = FastAPI()
    app.state.runtime = SimpleNamespace(room_feed=SimpleNamespace(last_error=room_error))
    heard = []
    owner = SimpleNamespace(robot=lambda _: None, heads=heads)
    register_robot_status_routes(
        app, SimpleNamespace(mode=mode, robots=[], room_station_enabled=room_enabled),
        authorize=lambda: None, coordinator=lambda: owner,
        requested_tool_context=lambda request, robot_id: object(),
        remember_tool_context=lambda *args: heard.append(args),
        current_tool_context=lambda *args: None,
    )
    return TestClient(app, raise_server_exceptions=False), heard


@pytest.mark.parametrize("route", ["status", "aux"])
def test_missing_head_returns_unavailable_not_internal_error(route):
    client, heard = _status_client({})
    with client:
        result = client.get(f"/v1/robots/robot-01/{route}")
    assert result.status_code == 503
    assert result.json()["detail"] == "Telemetry head unavailable"
    if route == "status":
        assert result.json()["health"] == {
            "head": "adapter_unavailable", "body": "unconfirmed",
            "room_station": "disabled", "state": "degraded",
            "physical_acceptance_pass": False,
        }
    else:
        assert result.json() == {"detail": "Telemetry head unavailable"}
    assert heard == []


def test_missing_status_reader_is_unavailable():
    client, heard = _status_client({"robot-01": object()})
    with client:
        result = client.get("/v1/robots/robot-01/status")
    assert result.status_code == 503
    assert result.json()["detail"] == "Status adapter unavailable"
    assert result.json()["health"]["body"] == "unconfirmed"
    assert heard == []


def test_unsupported_aux_reader_remains_diagnostic():
    client, heard = _status_client({"robot-01": object()})
    with client:
        result = client.get("/v1/robots/robot-01/aux")
    assert result.status_code == 200
    assert result.json()["available"] is False
    assert heard == []


def test_status_preserves_incomplete_source_metadata():
    packet = {"robot_id": "robot-01", "armed": False, "imu": {"valid": False}}

    async def status():
        return packet

    client, _ = _status_client({"robot-01": SimpleNamespace(status=status)})
    with client:
        result = client.get("/v1/robots/robot-01/status")
    assert result.status_code == 200
    health = result.json().pop("health")
    assert health["head"] == "responded"
    assert health["body"] == "status_received"
    assert {k: v for k, v in result.json().items() if k != "health"} == packet
    assert "health" not in packet


@pytest.mark.parametrize(("code", "identity", "reply", "expected"), [
    (504, "robot-01", "body ACK timeout; command outcome uncertain", "serial_timeout"),
    (504, "robot-02", "body ACK timeout; command outcome uncertain", "unconfirmed"),
    (504, "robot-01", "gateway timeout", "unconfirmed"),
    (503, "robot-01", "body telemetry busy", "unavailable"),
])
def test_status_only_attributes_matching_bridge_error(code, identity, reply, expected):
    async def status():
        response = httpx.Response(code, request=httpx.Request("GET", "http://head/api/status"),
                                  json={"robot_id": identity, "ok": False, "reply": reply})
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise HeadError("head request failed") from exc

    client, heard = _status_client({"robot-01": SimpleNamespace(status=status)})
    with client:
        result = client.get("/v1/robots/robot-01/status")
    assert result.status_code == 503
    health = result.json()["health"]
    assert health["body"] == expected
    assert health["head"] == ("unconfirmed" if expected == "unconfirmed" else "responded")
    assert health["state"] == "degraded"
    assert heard == []


def test_head_connection_failure_does_not_claim_body_failure():
    async def status():
        raise HeadError("head request failed") from httpx.ConnectError("offline")

    client, heard = _status_client({"robot-01": SimpleNamespace(status=status)})
    with client:
        result = client.get("/v1/robots/robot-01/status")
    assert result.status_code == 503
    assert result.json()["health"]["head"] == "unreachable"
    assert result.json()["health"]["body"] == "unconfirmed"
    assert heard == []


@pytest.mark.parametrize(("error", "expected"), [
    ("SerialException", "unavailable"),
    ("Room observation callback failed: RuntimeError", "callback_error"),
    (None, "unverified"),
])
def test_room_status_does_not_overwrite_body_receipt(error, expected):
    async def status():
        return {"robot_id": "robot-01", "armed": False}

    client, _ = _status_client({"robot-01": SimpleNamespace(status=status)},
                               room_enabled=True, room_error=error)
    with client:
        result = client.get("/v1/robots/robot-01/status")
    assert result.status_code == 200
    health = result.json()["health"]
    assert health["room_station"] == expected
    assert health["body"] == "status_received"
    assert health["state"] == ("reported" if error is None else "degraded")
    assert health["physical_acceptance_pass"] is False


@pytest.mark.parametrize(("fault", "warning"), [
    ("none", None),
    ("math_overflow", "Last INA226 conversion reported math overflow; current unavailable."),
    ("shunt_saturated", "Last INA226 shunt reading saturated; current unavailable."),
])
def test_aux_monitor_fault_is_readonly_diagnostic(fault, warning):
    power = {"monitor_fault": fault, "monitor_valid": False, "pack_valid": False}

    async def aux_status():
        return {"robot_id": "robot-01", "power": power}

    client, heard = _status_client({"robot-01": SimpleNamespace(aux_status=aux_status)})
    with client:
        result = client.get("/v1/robots/robot-01/aux")
    assert result.status_code == 200
    assert result.json()["power"] == {**power, "monitor_warning": warning}
    assert "monitor_warning" not in power
    assert heard == []


@pytest.mark.parametrize("power", [
    {"monitor_fault": "unknown", "monitor_valid": False},
    {"monitor_fault": "math_overflow", "monitor_valid": True},
    {"monitor_fault": "shunt_saturated", "monitor_valid": False, "pack_valid": True},
])
def test_invalid_aux_monitor_fault_rejects_before_context_admission(power):
    async def aux_status():
        return {
            "robot_id": "robot-01", "power": power,
            "force": {"boot_id": 42}, "proximity": {"boot_id": 42},
            "climate": {"valid": True, "seq": 1, "age_ms": 0,
                        "temp_centi": 2200, "rh_centi": 4000},
        }

    client, heard = _status_client({"robot-01": SimpleNamespace(aux_status=aux_status)})
    with client:
        result = client.get("/v1/robots/robot-01/aux")
    assert heard == []
    assert result.status_code == 503
    assert result.json() == {"error": "Invalid INA226 monitor fault provenance"}


@pytest.mark.parametrize("fault", [
    "floor_out_of_range", "front_obstacle", "stale_sample",
    "missing_sample", "bus_failure",
])
def test_status_retains_reported_wroom_fault_code(fault):
    async def status():
        return {
            "robot_id": "robot-01", "armed": False,
            "safety": {"required": True, "ready": False, "fault": fault},
        }

    client, heard = _status_client({"robot-01": SimpleNamespace(status=status)})
    with client:
        result = client.get("/v1/robots/robot-01/status")
    assert result.status_code == 200
    assert result.json()["safety"]["fault"] == fault
    assert result.json()["armed"] is False
    assert result.json()["health"]["physical_acceptance_pass"] is False
    assert heard[0][-1].endswith(f"safety_fault={fault}")


@pytest.mark.parametrize(("failure", "head_state", "body_state"), [
    (httpx.ConnectError("offline"), "unreachable", "unconfirmed"),
    (httpx.ConnectTimeout("offline"), "unreachable", "unconfirmed"),
    (httpx.ReadTimeout("no response"), "unconfirmed", "unconfirmed"),
    (TimeoutError("deadline"), "unconfirmed", "unconfirmed"),
])
def test_status_disconnect_never_reuses_previous_sensor_receipt(failure, head_state, body_state):
    first = {"robot_id": "robot-01", "armed": True,
             "imu": {"valid": True, "age_ms": 0},
             "safety": {"ready": True, "fault": "none"}}
    recovered = {"robot_id": "robot-01", "armed": False,
                 "imu": {"valid": False, "age_ms": 500},
                 "safety": {"ready": False, "fault": "stale_sample"}}
    readings = iter((first, failure, recovered))

    async def status():
        reading = next(readings)
        if isinstance(reading, TimeoutError):
            raise reading
        if isinstance(reading, Exception):
            raise HeadError("head request failed") from reading
        return reading

    client, heard = _status_client({"robot-01": SimpleNamespace(status=status)})
    with client:
        before = client.get("/v1/robots/robot-01/status")
        assert before.status_code == 200
        assert before.json()["imu"] == first["imu"]
        assert len(heard) == 1

        offline = client.get("/v1/robots/robot-01/status")
        assert offline.status_code == 503
        assert offline.json() == {
            "robot_id": "robot-01", "error": "Robot status unavailable",
            "health": {"head": head_state, "body": body_state,
                       "room_station": "disabled", "state": "degraded",
                       "physical_acceptance_pass": False},
        }
        assert len(heard) == 1

        after = client.get("/v1/robots/robot-01/status")
        assert after.status_code == 200
        assert after.json() == {
            **recovered,
            "health": {"head": "responded", "body": "status_received",
                       "room_station": "disabled", "state": "reported",
                       "physical_acceptance_pass": False},
        }
        assert len(heard) == 2
        assert heard[-1][-1].endswith("safety_fault=stale_sample")
