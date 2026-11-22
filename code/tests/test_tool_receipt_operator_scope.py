"""Only the dedicated Xiaozhi tool token can mark spoken tool receipts."""

from types import SimpleNamespace

from desk_robot.api import create_app
from desk_robot.multimodal import CameraFrameHub
from fastapi.testclient import TestClient


def test_operator_marker_cannot_promote_dashboard_read_to_voice_tool(
    settings, tokens,
):
    settings.mode = "hardware"
    robot_id = settings.robots[0].id
    hub = CameraFrameHub([robot.id for robot in settings.robots])
    visual = SimpleNamespace(
        _turn_epoch={robot.id: 3 for robot in settings.robots},
        hub=hub,
    )

    class Head:
        async def status(self):
            return {
                "robot_id": robot_id,
                "backend": "reported_head",
                "armed": False,
                "safety": {"fault": "none"},
            }

    async def noop():
        pass

    runtime = SimpleNamespace(
        coordinator=SimpleNamespace(
            robot=lambda rid: settings.robot(rid),
            heads={robot_id: Head()},
        ),
        multimodal=visual,
        start=noop,
        close=noop,
    )
    app = create_app(settings, runtime=runtime)
    operator = {
        "Authorization": "Bearer " + tokens["DESK_ROBOT_API_TOKEN"],
    }
    tool = {
        "Authorization": "Bearer " + tokens["DESK_ROBOT_TOOL_TOKEN"],
        "X-Desk-Robot-Tool-Receipt": "1",
    }
    url = f"/v1/robots/{robot_id}/status"
    with TestClient(app) as client:
        dashboard = client.get(url, headers=operator)
        assert dashboard.status_code == 200
        assert dashboard.json()["robot_id"] == robot_id
        assert not hub.tool_history[robot_id]

        forged = client.get(
            url, headers={**operator, "X-Desk-Robot-Tool-Receipt": "1"},
        )
        assert forged.status_code == 409
        assert not hub.tool_history[robot_id]

        legitimate = client.get(url, headers=tool)
        assert legitimate.status_code == 200
        assert len(hub.tool_history[robot_id]) == 1
        assert hub.tool_history[robot_id][0][0] == "robot_status"
