"""Observable status route contracts, including rejected receipt retries."""
from copy import deepcopy
from types import SimpleNamespace

import pytest
from desk_robot.api_robot_status import register_robot_status_routes
from desk_robot.transport import HeadError
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient


@pytest.fixture
def routes():
    payload = {
        "robot_id": "robot-01",
        "force": {"boot_id": 7}, "proximity": {"boot_id": 7},
        "climate": {"valid": True, "seq": 12, "age_ms": 1,
                    "temp_centi": 2312, "rh_centi": 4420},
        "bmp280": {"valid": True, "present": True, "chip_id": 0x58,
                   "seq": 21, "age_ms": 1, "temp_centi": 2200, "pressure_pa": 101325},
    }
    state = SimpleNamespace(admit=False, receipts=[], authorized=True)
    head = SimpleNamespace()

    async def aux_status():
        return deepcopy(payload)

    async def status():
        return {"robot_id": "robot-01", "backend": "test", "armed": False,
                "safety": {"fault": "none"}}

    def authorize():
        if not state.authorized:
            raise HTTPException(401, "Denied")

    def remember(owner, robot_id, kind, summary):
        if state.admit:
            state.receipts.append((owner, robot_id, kind, summary))
        return state.admit

    head.status = status
    head.aux_status = aux_status
    fleet = SimpleNamespace(heads={"robot-01": head}, robot=lambda _: None)
    settings = SimpleNamespace(mode="simulation", robots=[
        SimpleNamespace(id="robot-01", name="Pet", motion_enabled=False),
    ])
    app = FastAPI()
    register_robot_status_routes(
        app, settings, authorize=authorize, coordinator=lambda: fleet,
        requested_tool_context=lambda request, rid: "turn",
        remember_tool_context=remember, current_tool_context=lambda *args: None,
    )
    return app, state, payload, fleet


def test_registration_inventory_status_and_authorization(routes):
    app, state, _, _ = routes
    state.admit = True
    with TestClient(app) as client:
        assert client.get("/v1/robots").json() == {
            "mode": "simulation", "physical_acceptance_pass": False,
            "robots": [{"id": "robot-01", "name": "Pet", "motion_enabled": False}],
        }
        status = client.get("/v1/robots/robot-01/status").json()
        assert status["health"] == {
            "head": "simulated", "body": "simulated", "room_station": "disabled",
            "state": "reported", "physical_acceptance_pass": False,
        }
        assert state.receipts == [(
            "turn", "robot-01", "robot_status", "backend=test, armed=False, safety_fault=none",
        )]
        state.authorized = False
        for path in ("/v1/robots", "/v1/robots/robot-01/status", "/v1/robots/robot-01/aux"):
            assert client.get(path).status_code == 401
    assert len(state.receipts) == 1


def test_aux_rejected_receipt_does_not_retire_boot_or_consume_combined_sample(routes):
    app, state, payload, _ = routes
    url = "/v1/robots/robot-01/aux"
    with TestClient(app) as client:
        assert client.get(url).json() == payload
        assert state.receipts == []
        state.admit = True
        assert client.get(url).status_code == 200
        assert len(state.receipts) == 1
        assert state.receipts[0][3] == (
            "SHT41 local temp_centi=2312, humidity_centi=4420, seq=12, age_ms=1; "
            "BMP280 local pressure_pa=101325, seq=21, age_ms=1; raw local probe, not calibrated"
        )
        state.admit = False
        payload["force"]["boot_id"] = payload["proximity"]["boot_id"] = 8
        assert client.get(url).status_code == 200
        state.admit = True
        payload["force"]["boot_id"] = payload["proximity"]["boot_id"] = 7
        payload["climate"]["seq"] += 1
        assert client.get(url).status_code == 200
        assert len(state.receipts) == 2
        assert "SHT41" in state.receipts[-1][3] and "BMP280" not in state.receipts[-1][3]


def test_aux_power_validation_precedes_receipt_and_preserves_error(routes):
    app, state, payload, _ = routes
    state.admit = True
    payload["power"] = {"monitor_fault": "math_overflow", "monitor_valid": True}
    with TestClient(app) as client:
        url = "/v1/robots/robot-01/aux"
        bad = client.get(url)
        assert bad.status_code == 503
        assert bad.json() == {"error": "Invalid INA226 monitor fault provenance"}
        assert state.receipts == []
        payload["power"]["monitor_valid"] = False
        good = client.get(url)
        assert good.status_code == 200
        assert good.json()["power"]["monitor_warning"] == (
            "Last INA226 conversion reported math overflow; current unavailable."
        )
        assert len(state.receipts) == 1


@pytest.mark.parametrize("route,method,error", [
    ("status", "status", "Head status robot identity mismatch"),
    ("aux", "aux_status", "Auxiliary telemetry robot identity mismatch"),
])
def test_wrong_identity_never_enters_receipt(routes, route, method, error):
    app, state, _, fleet = routes
    state.admit = True

    async def wrong():
        return {"robot_id": "robot-02"}

    setattr(fleet.heads["robot-01"], method, wrong)
    with TestClient(app) as client, pytest.raises(HeadError, match=error):
        client.get(f"/v1/robots/robot-01/{route}")
    assert state.receipts == []


def test_aux_receipt_cursor_caps_retired_boots_and_rejects_replay(routes):
    app, state, payload, _ = routes
    state.admit = True
    with TestClient(app) as client:
        url = "/v1/robots/robot-01/aux"
        # Transition through 129 distinct boots (retiring boots 1..128).
        for boot in range(1, 130):
            payload["force"]["boot_id"] = payload["proximity"]["boot_id"] = boot
            payload["climate"]["seq"] = 1
            payload["bmp280"]["seq"] = 1
            assert client.get(url).status_code == 200
        assert len(state.receipts) == 129

        # Replaying any retired boot ID (e.g. boot 1 or boot 128) is ignored.
        for replayed in (1, 64, 128):
            payload["force"]["boot_id"] = payload["proximity"]["boot_id"] = replayed
            payload["climate"]["seq"] = 99
            assert client.get(url).status_code == 200
        assert len(state.receipts) == 129

        # Once 128 boots are retired, a 130th boot fails closed without growing the set.
        payload["force"]["boot_id"] = payload["proximity"]["boot_id"] = 130
        payload["climate"]["seq"] = 1
        assert client.get(url).status_code == 200
        assert len(state.receipts) == 129

        # Current active boot 129 still admits fresh advancing sequences.
        payload["force"]["boot_id"] = payload["proximity"]["boot_id"] = 129
        payload["climate"]["seq"] = 2
        assert client.get(url).status_code == 200
        assert len(state.receipts) == 130
