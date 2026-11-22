"""Canonical Xiaozhi tool HTTP replies keep exact Mac voice turn ownership."""

from types import SimpleNamespace

import pytest
from desk_robot.api_robot_status import register_robot_status_routes
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.mark.parametrize("endpoint", ("status", "aux"))
@pytest.mark.parametrize(
    ("scenario", "expected"),
    (
        ("current", 200),
        ("interrupted", 409),
        ("reconnected", 409),
        ("missing_owner", 409),
        ("dashboard", 200),
    ),
)
def test_delayed_head_telemetry_rejects_superseded_voice_turn(
    settings, endpoint, scenario, expected,
):
    settings.mode = "hardware"
    current = SimpleNamespace(_turn_epoch={"robot-01": 12})
    runtime = SimpleNamespace(
        multimodal=None if scenario == "missing_owner" else current,
    )
    calls = []
    receipts = []

    def maybe_supersede():
        if scenario == "interrupted":
            current._turn_epoch["robot-01"] += 1
        elif scenario == "reconnected":
            # An old head and a new one may share the same numeric epoch.
            runtime.multimodal = SimpleNamespace(_turn_epoch={"robot-01": 12})

    class Head:
        async def status(self):
            calls.append("status")
            maybe_supersede()
            return {
                "robot_id": "robot-01", "backend": "live",
                "armed": False, "safety": {"fault": "old_fault"},
            }

        async def aux_status(self):
            calls.append("aux")
            maybe_supersede()
            return {
                "robot_id": "robot-01",
                "force": {"boot_id": 5},
                "proximity": {"boot_id": 5},
                "climate": {
                    "valid": True, "seq": 15, "age_ms": 20,
                    "temp_centi": 2077, "rh_centi": 4200,
                },
            }

    def requested(request, robot_id):
        if request.headers.get("x-desk-robot-tool-receipt") != "1":
            return None
        visual = runtime.multimodal
        return (visual, visual._turn_epoch[robot_id]) if visual else None

    def remember(owner, robot_id, kind, summary):
        if owner is None:
            return False
        visual, generation = owner
        if visual._turn_epoch.get(robot_id) != generation:
            return False
        receipts.append((robot_id, kind, summary))
        return True

    fleet = SimpleNamespace(
        robot=lambda robot_id: robot_id,
        heads={"robot-01": Head()},
    )
    app = FastAPI()
    app.state.runtime = runtime
    register_robot_status_routes(
        app, settings, authorize=lambda: None,
        coordinator=lambda: fleet,
        requested_tool_context=requested,
        remember_tool_context=remember,
    )
    headers = (
        {} if scenario == "dashboard"
        else {"x-desk-robot-tool-receipt": "1"}
    )
    with TestClient(app) as client:
        response = client.get(f"/v1/robots/robot-01/{endpoint}", headers=headers)

    assert response.status_code == expected
    assert len(calls) == (0 if scenario == "missing_owner" else 1)
    if expected == 409:
        assert "old_fault" not in response.text
        assert "2077" not in response.text
        assert not receipts
    else:
        assert response.json()["robot_id"] == "robot-01"
        assert len(receipts) == (1 if scenario == "current" else 0)
