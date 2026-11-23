"""Authenticated Mac pose inspection never promotes odometry into motion authority."""

from types import SimpleNamespace

import pytest
from desk_robot.api_robot_status import register_robot_status_routes
from desk_robot.spatial_pose import PoseReceipt
from desk_robot.transport import HeadError
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient


def sample(robot_id="robot-01"):
    return PoseReceipt(
        robot_id=robot_id, head_boot=72, body_boot=42, origin=3,
        seq=101, sample_us=15_050_000, x_mm=121, y_mm=-20,
        yaw_mrad=158, quality="valid", received_at=39.25,
    )


class FakeHead:
    def __init__(self, reading):
        self.reading = reading
        self.pose_fence = SimpleNamespace(needs_reanchor=True)
        self.calls = 0

    async def pose_status(self):
        self.calls += 1
        if isinstance(self.reading, Exception):
            raise self.reading
        return self.reading() if callable(self.reading) else self.reading


def make_client(head, *, mode="hardware", epoch=None):
    epoch = epoch if epoch is not None else {"current": 1}
    app = FastAPI()

    def authorize(request: Request):
        if request.headers.get("authorization") != "Bearer local-secret":
            raise HTTPException(401, "Private token required")

    class Coordinator:
        heads = {"robot-01": head}

        def robot(self, robot_id):
            if robot_id != "robot-01":
                raise HTTPException(404, "Unknown robot")
            return SimpleNamespace(id=robot_id)

    def current_tool_context(owner, robot_id, message):
        assert robot_id == "robot-01"
        if owner != epoch["current"]:
            raise HTTPException(409, message)

    register_robot_status_routes(
        app, SimpleNamespace(mode=mode, robots=[]),
        authorize=authorize, coordinator=Coordinator,
        requested_tool_context=lambda request, robot_id: epoch["current"],
        remember_tool_context=lambda *args: pytest.fail(
            "Pose observations must not create spoken facts"
        ),
        current_tool_context=current_tool_context,
    )
    app.add_exception_handler(
        HeadError, lambda request, exc: JSONResponse(
            status_code=503, content={"error": str(exc)}
        ),
    )
    return TestClient(app)


def test_pose_read_is_authenticated_and_never_authorizes_motion():
    head = FakeHead(sample())
    client = make_client(head)
    path = "/v1/robots/robot-01/pose"
    assert client.get(path).status_code == 401
    assert client.post(path, headers={"Authorization": "Bearer local-secret"}).status_code == 405
    result = client.get(path, headers={"Authorization": "Bearer local-secret"})
    assert result.status_code == 200
    data = result.json()
    assert (data["robot_id"], data["head_boot"], data["body_boot"], data["origin"]) == (
        "robot-01", 72, 42, 3
    )
    assert (data["seq"], data["sample_us"], data["x_mm"], data["y_mm"],
            data["yaw_mrad"], data["received_at_s"]) == (
        101, 15_050_000, 121, -20, 158, 39.25
    )
    assert data["quality"] == "valid"
    assert data["needs_reanchor"] is True
    assert data["motor_authorized"] is False
    assert data["physical_qualified"] is False
    assert head.calls == 1
    assert client.get(
        "/v1/robots/robot-02/pose",
        headers={"Authorization": "Bearer local-secret"},
    ).status_code == 404


@pytest.mark.parametrize("mode,head", [
    ("simulation", FakeHead(sample())),
    ("hardware", object()),
])
def test_pose_missing_or_simulated_adapter_is_explicitly_unavailable(mode, head):
    response = make_client(head, mode=mode).get(
        "/v1/robots/robot-01/pose",
        headers={"Authorization": "Bearer local-secret"},
    )
    assert response.status_code == 200
    assert response.json()["available"] is False
    assert response.json()["motor_authorized"] is False


@pytest.mark.parametrize("reading", [sample("robot-02"), {"robot_id": "robot-01"}])
def test_pose_rejects_foreign_or_untyped_receipts(reading):
    response = make_client(FakeHead(reading)).get(
        "/v1/robots/robot-01/pose",
        headers={"Authorization": "Bearer local-secret"},
    )
    assert response.status_code == 503
    assert response.json()["error"] == "Pose receipt robot identity or type mismatch"


def test_pose_transport_failure_never_fabricates_coordinates():
    response = make_client(FakeHead(HeadError("legacy pose unsupported"))).get(
        "/v1/robots/robot-01/pose",
        headers={"Authorization": "Bearer local-secret"},
    )
    assert response.status_code == 503
    assert "x_mm" not in response.json()


def test_live_voice_tool_superseded_during_pose_read_returns_conflict():
    epoch = {"current": 1}

    def supersede():
        epoch["current"] = 2
        return sample()

    response = make_client(FakeHead(supersede), epoch=epoch).get(
        "/v1/robots/robot-01/pose",
        headers={
            "Authorization": "Bearer local-secret",
            "X-Desk-Robot-Tool-Receipt": "1",
        },
    )
    assert response.status_code == 409
    assert "x_mm" not in response.json()
