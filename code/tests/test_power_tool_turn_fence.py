"""An old Xiaozhi power reply cannot become a newer human turn's fact."""

from types import SimpleNamespace

import pytest
from desk_robot.api_readonly_context import register_readonly_context_routes
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.mark.parametrize(
    ("scenario", "expected_status"),
    [
        ("current", 200),
        ("interrupted", 409),
        ("reconnected", 409),
        ("missing_owner", 409),
        ("dashboard", 200),
    ],
)
def test_power_tool_requires_same_live_human_turn_after_wroom_read(
    settings, scenario, expected_status,
):
    settings.mode = "hardware"
    original = SimpleNamespace(_turn_epoch={"robot-01": 7})
    runtime = SimpleNamespace(
        multimodal=None if scenario == "missing_owner" else original,
    )
    receipts = []
    reads = []

    class Head:
        async def aux_status(self):
            reads.append(True)
            if scenario == "interrupted":
                original._turn_epoch["robot-01"] += 1
            elif scenario == "reconnected":
                # Same numeric turn on a different owner is NOT the same turn.
                runtime.multimodal = SimpleNamespace(_turn_epoch={"robot-01": 7})
            return {
                "robot_id": "robot-01",
                "power": {
                    "fuel_valid": True, "fuel_seq": 4,
                    "cell_mv": 3860, "soc_centi": 5300,
                },
            }

    coordinator = SimpleNamespace(
        robot=lambda robot_id: robot_id,
        heads={"robot-01": Head()},
    )

    def requested(request, robot_id):
        if request.headers.get("x-desk-robot-tool-receipt") != "1":
            return None
        visual = runtime.multimodal
        return (
            (visual, visual._turn_epoch[robot_id])
            if visual is not None else None
        )

    def remember(owner, robot_id, kind, summary):
        if owner is None:
            return False
        visual, generation = owner
        if visual._turn_epoch.get(robot_id) != generation:
            return False
        receipts.append((robot_id, kind, summary))
        return True

    app = FastAPI()
    app.state.runtime = runtime
    register_readonly_context_routes(
        app, settings, authorize=lambda: None,
        coordinator=lambda: coordinator,
        requested_tool_context=requested,
        remember_tool_context=remember,
        native_pet_speech_policy=lambda robot_id: {},
    )
    headers = (
        {} if scenario == "dashboard"
        else {"x-desk-robot-tool-receipt": "1"}
    )
    with TestClient(app) as client:
        response = client.get("/v1/pet/robot-01/power-status", headers=headers)

    assert response.status_code == expected_status
    assert len(reads) == (0 if scenario == "missing_owner" else 1)
    if expected_status == 409:
        assert "3860" not in response.text
        assert "5300" not in response.text
        assert receipts == []
    else:
        assert response.json()["reported_cell_mv"] == 3860
        assert response.json()["sample_freshness_verified"] is False
        assert len(receipts) == (0 if scenario == "dashboard" else 1)
