"""Dock visual pose disclosure requires the original operator camera grant."""

import asyncio
from types import SimpleNamespace

import pytest
from desk_robot import dock_runtime
from desk_robot.api import create_app
from fastapi.testclient import TestClient


@pytest.mark.parametrize(("grant_change", "status"), [
    ("off", 403), ("unchanged", 200), ("revoke", 403), ("regrant", 409),
])
def test_dock_observe_never_publishes_old_grant_pose(
    settings, tokens, monkeypatch, grant_change, status,
):
    settings.mode = "hardware"
    settings.voice_vision_tools_enabled = grant_change != "off"
    robot_id = settings.robots[0].id
    calls = []
    private_pose = {
        "robot_id": robot_id, "phase": "approach", "pose": {"x_mm": 17},
        "motor_authorized": False, "charging_authorized": False,
    }

    async def observe(head, robot, *, consent_valid=None):
        assert consent_valid is not None and consent_valid()
        calls.append(robot.id)
        if grant_change in {"revoke", "regrant"}:
            settings.voice_vision_tools_enabled = False
            if grant_change == "regrant":
                settings.voice_vision_tools_enabled = True
        return private_pose

    async def noop():
        pass

    monkeypatch.setattr("desk_robot.api_dock_routes.observe_actual_dock", observe)
    coordinator = SimpleNamespace(
        robot=lambda robot: settings.robot(robot),
        heads={robot_id: object()},
    )
    runtime = SimpleNamespace(
        coordinator=coordinator, start=noop, close=noop,
    )
    tool = {"Authorization": "Bearer " + tokens["DESK_ROBOT_TOOL_TOKEN"]}
    with TestClient(create_app(settings, runtime=runtime)) as client:
        response = client.get(
            f"/v1/robots/{robot_id}/dock/observe", headers=tool,
        )
    assert response.status_code == status
    assert calls == ([] if grant_change == "off" else [robot_id])
    if grant_change == "unchanged":
        assert response.json() == private_pose
    else:
        assert "pose" not in response.text
        assert "x_mm" not in response.text


@pytest.mark.parametrize("regrant", [False, True])
async def test_revoked_snapshot_does_not_reach_identity_or_detector(
    settings, monkeypatch, regrant,
):
    """Do not process a JPEG captured during a different permission grant."""
    settings.voice_vision_tools_enabled = True
    old_grant = settings.camera_consent_generation
    observed = []

    def grant_valid():
        return (settings.voice_vision_tools_enabled
                and settings.camera_consent_generation == old_grant)

    class Head:
        async def snapshot(self):
            settings.voice_vision_tools_enabled = False
            if regrant:
                settings.voice_vision_tools_enabled = True
            return b"\\xff\\xd8\\xff\\xd9"

        async def camera_identity(self):
            observed.append("identity")
            return "OV5640"

    monkeypatch.setattr(
        dock_runtime, "load_real_dock_calibration",
        lambda path, **owner: (SimpleNamespace(camera_sensor_pid="OV5640"), 200),
    )
    monkeypatch.setattr(
        dock_runtime, "detect_bounded",
        lambda *args, **kwargs: observed.append("detector"),
    )
    result = await dock_runtime.observe_actual_dock(
        Head(), SimpleNamespace(id="robot-01", dock_calibration=None),
        consent_valid=grant_valid,
    )
    assert result["phase"] == "hold"
    assert result["source"] == "camera_consent_revoked"
    assert result["pose"] is None
    assert observed == []


@pytest.mark.parametrize("regrant", [False, True])
@pytest.mark.parametrize("live_adapter", [False, True])
async def test_revocation_before_scheduled_capture_never_calls_head(
    settings, monkeypatch, regrant, live_adapter,
):
    settings.voice_vision_tools_enabled = True
    old_grant = settings.camera_consent_generation
    calls = []

    def grant_valid():
        return (settings.voice_vision_tools_enabled
                and settings.camera_consent_generation == old_grant)

    class Head:
        async def snapshot(self):
            calls.append("snapshot")
            return b"\xff\xd8\xff\xd9"

    class LiveHead(Head):
        async def snapshot_for_dock(self):
            calls.append("live")
            return b"\xff\xd8\xff\xd9"

    original = dock_runtime._bounded_head_reply

    async def revoke_before_dispatch(coro, **kwargs):
        settings.voice_vision_tools_enabled = False
        if regrant:
            settings.voice_vision_tools_enabled = True
        return await original(coro, **kwargs)

    monkeypatch.setattr(dock_runtime, "_bounded_head_reply", revoke_before_dispatch)
    monkeypatch.setattr(
        dock_runtime, "load_real_dock_calibration",
        lambda path, **owner: (SimpleNamespace(camera_sensor_pid="OV5640"), 200),
    )
    result = await dock_runtime.observe_actual_dock(
        LiveHead() if live_adapter else Head(),
        SimpleNamespace(id="robot-01", dock_calibration=None),
        consent_valid=grant_valid,
    )
    assert result["source"] == "camera_consent_revoked"
    assert result["pose"] is None
    assert calls == []


@pytest.mark.parametrize(("regrant", "status"), [(False, 403), (True, 409)])
def test_revoking_consent_cancels_running_observation(
    settings, tokens, monkeypatch, regrant, status,
):
    settings.mode = "hardware"
    settings.voice_vision_tools_enabled = True
    robot_id = settings.robots[0].id
    cancelled = []

    async def observe(head, robot, *, consent_valid=None):
        assert consent_valid is not None and consent_valid()
        settings.voice_vision_tools_enabled = False
        if regrant:
            settings.voice_vision_tools_enabled = True
        try:
            await asyncio.wait_for(asyncio.Event().wait(), timeout=0.5)
        except asyncio.CancelledError:
            cancelled.append(robot.id)
            raise

    async def noop():
        pass

    monkeypatch.setattr("desk_robot.api_dock_routes.observe_actual_dock", observe)
    coordinator = SimpleNamespace(
        robot=lambda robot: settings.robot(robot),
        heads={robot_id: object()},
    )
    runtime = SimpleNamespace(coordinator=coordinator, start=noop, close=noop)
    tool = {"Authorization": "Bearer " + tokens["DESK_ROBOT_TOOL_TOKEN"]}
    with TestClient(create_app(settings, runtime=runtime)) as client:
        response = client.get(f"/v1/robots/{robot_id}/dock/observe", headers=tool)
    assert response.status_code == status
    assert cancelled == [robot_id]
    assert "pose" not in response.text
