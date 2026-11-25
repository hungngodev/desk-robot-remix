"""Mac lifecycle health is not a physical robot or USB connectivity receipt."""
from types import SimpleNamespace

from desk_robot.api import create_app
from fastapi.testclient import TestClient


def test_health_registered_before_runtime_start_and_reports_explicit_simulation(
    settings, tokens,
):
    calls = []

    async def start():
        assert any(route.path == "/v1/health" for route in app.routes)
        assert app.state.runtime_started is False
        calls.append("start")

    async def close():
        assert app.state.runtime_started is False
        calls.append("close")

    runtime = SimpleNamespace(start=start, close=close, _closed=False)
    app = create_app(settings, runtime=runtime)
    operator = {"Authorization": "Bearer " + tokens["DESK_ROBOT_API_TOKEN"]}
    tool = {"Authorization": "Bearer " + tokens["DESK_ROBOT_TOOL_TOKEN"]}
    with TestClient(app) as client:
        assert calls == ["start"]
        assert client.get("/v1/health").status_code == 401
        assert client.get("/v1/health", headers=tool).status_code == 403
        response = client.get("/v1/health", headers=operator)
        assert response.status_code == 200
        assert response.json() == {
            "mode": "simulation",
            "runtime_ready": True,
            "physical_acceptance_pass": False,
            "warnings": [{"code": "simulation_mode"}],
        }
        runtime._closed = True
        response = client.get("/v1/health", headers=operator)
        assert response.status_code == 503
        assert response.json()["runtime_ready"] is False
        assert {"code": "runtime_unavailable"} in response.json()["warnings"]
    assert calls == ["start", "close"]


def test_health_does_not_turn_missing_room_usb_into_simulation(settings, tokens):
    settings.mode = "hardware"
    settings.room_station_enabled = True

    async def noop():
        pass

    runtime = SimpleNamespace(
        start=noop, close=noop, _closed=False,
        room_feed=SimpleNamespace(last_error="SerialException"),
    )
    operator = {"Authorization": "Bearer " + tokens["DESK_ROBOT_API_TOKEN"]}
    with TestClient(create_app(settings, runtime=runtime)) as client:
        response = client.get("/v1/health", headers=operator)
        assert response.status_code == 200
        assert response.json() == {
            "mode": "hardware",
            "runtime_ready": True,
            "physical_acceptance_pass": False,
            "warnings": [
                {"code": "hardware_connectivity_not_verified_by_health"},
                {"code": "room_usb_unavailable"},
            ],
        }
        runtime.room_feed.last_error = None
        response = client.get("/v1/health", headers=operator)
        assert {"code": "room_usb_unavailable"} not in response.json()["warnings"]
        runtime._fatal_service_error = RuntimeError("service stopped")
        response = client.get("/v1/health", headers=operator)
        assert response.status_code == 503
        assert response.json()["runtime_ready"] is False
