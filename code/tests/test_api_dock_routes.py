"""Keep dock route roles and runtime admission intact across router extraction."""
from types import SimpleNamespace

import pytest
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
    settings = SimpleNamespace(
        mode="simulation", voice_vision_tools_enabled=False, camera_consent_generation=0,
    )
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


@pytest.mark.parametrize(("source", "status"), [
    ("not_calibrated", 200),
    ("head_snapshot_failed", 200),
    ("head_snapshot_invalid", 200),
    ("camera_identity_unavailable", 200),
    ("camera_identity_mismatch", 200),
    ("apriltag_detector_busy", 200),
    ("apriltag_detection_failed", 200),
    ("dock_mount_geometry_invalid", 200),
    ("camera_consent_revoked", 403),
])
def test_dock_observe_failure_contract(monkeypatch, source, status):
    robot = SimpleNamespace(id="robot-01")
    head = object()
    diagnostic = {
        "robot_id": robot.id, "phase": "hold", "source": source,
        "reason": "observation failed", "pose": None,
        "motor_authorized": False, "charging_authorized": False,
        "physical_acceptance_pass": False,
    }

    async def observe(actual_head, actual_robot, *, consent_valid):
        assert actual_head is head
        assert actual_robot is robot
        assert consent_valid()
        return diagnostic

    monkeypatch.setattr("desk_robot.api_dock_routes.observe_actual_dock", observe)
    settings = SimpleNamespace(
        mode="hardware", voice_vision_tools_enabled=True,
        camera_consent_generation=1, register_camera_revocation=lambda _: None,
    )
    coord = SimpleNamespace(robot=lambda _: robot, heads={robot.id: head})
    app = FastAPI()
    register_dock_routes(app, settings, authorize=lambda: None, operator=lambda: None,
                         coordinator=lambda: coord)
    with TestClient(app) as client:
        response = client.get(f"/v1/robots/{robot.id}/dock/observe")
    assert response.status_code == status
    if status == 200:
        assert response.json() == diagnostic
    else:
        assert response.json() == {"detail": "Camera consent revoked during dock observation"}


def test_dock_observe_rejects_consent_cycle_during_admission(monkeypatch):
    robot = SimpleNamespace(id="robot-01")
    head = object()
    calls = []

    class CyclingSettings:
        camera_consent_generation = 1
        switched = False

        @property
        def voice_vision_tools_enabled(self):
            if not self.switched:
                # Simulate an operator revoking and restoring consent between
                # the original grant and permission reads on separate threads.
                self.switched = True
                self.camera_consent_generation += 1
            return True

        def register_camera_revocation(self, _listener):
            pass

    async def observe(actual_head, actual_robot, *, consent_valid):
        calls.append((actual_head, actual_robot))
        assert consent_valid()
        return {"source": "not_calibrated"}

    monkeypatch.setattr("desk_robot.api_dock_routes.observe_actual_dock", observe)
    settings = CyclingSettings()
    coord = SimpleNamespace(robot=lambda _: robot, heads={robot.id: head})
    app = FastAPI()
    register_dock_routes(app, settings, authorize=lambda: None, operator=lambda: None,
                         coordinator=lambda: coord)
    url = f"/v1/robots/{robot.id}/dock/observe"
    with TestClient(app) as client:
        response = client.get(url)
        assert response.status_code == 409
        assert calls == []
        # A genuinely new request may use the new grant.
        assert client.get(url).status_code == 200
    assert calls == [(head, robot)]
