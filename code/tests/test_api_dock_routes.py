"""Keep dock route roles and runtime admission intact across router extraction."""
from types import SimpleNamespace

from desk_robot.api_dock_routes import register_dock_routes
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient


def test_dock_route_roles_and_lifecycle():
    app = FastAPI()
    calls = []

    async def authorize(authorization: str = Header(default="")):
        if authorization not in {"operator", "tool"}:
            raise HTTPException(401)

    async def operator(authorization: str = Header(default="")):
        if authorization != "operator":
            raise HTTPException(403)

    def dock(robot_id):
        calls.append(robot_id)
        return SimpleNamespace(data=lambda: {"state": "queued"})

    coord = SimpleNamespace(robot=lambda _: None, dock=dock)
    settings = SimpleNamespace(mode="simulation", voice_vision_tools_enabled=False)
    register_dock_routes(app, settings, authorize=authorize, operator=operator,
                         coordinator=lambda: coord)
    prefix = "/v1/robots/robot-01/dock"
    with TestClient(app) as client:
        for route in ("ir", "evidence", "observe"):
            assert client.get(f"{prefix}/{route}").status_code == 401
        tool = {"Authorization": "tool"}
        for route in ("ir", "evidence"):
            result = client.get(f"{prefix}/{route}", headers=tool)
            assert result.status_code == 200
            assert result.json()["motor_authorized"] is False
            assert result.json()["charging_authorized"] is False
        assert client.get(f"{prefix}/observe", headers=tool).status_code == 403
        assert client.post(f"{prefix}/approach", headers=tool).status_code == 403
        operator_headers = {"Authorization": "operator"}
        assert client.post(f"{prefix}/approach", headers=operator_headers).status_code == 503
        assert not calls
        app.state.runtime = SimpleNamespace()
        app.state.runtime_started = True
        response = client.post(f"{prefix}/approach", headers=operator_headers)
        assert response.status_code == 202
        assert response.json() == {"state": "queued"}
    assert calls == ["robot-01"]
