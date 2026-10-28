import json

import httpx
import pytest
from desk_robot.calibration import Calibration
from desk_robot.transport import HeadError, HttpHead, validate_command


@pytest.mark.parametrize(
    "command",
    [
        "drive 41 0 100",
        "drive 0 0 251",
        "drive 0 0 nan",
        "drive 0 0 100\narm",
        "grip 121",
        "lift 59",
        "stop extra",
        "arm ",
        "drive 0  0 100",
    ],
)
def test_invalid_commands_rejected(command):
    with pytest.raises(ValueError):
        validate_command(command)


@pytest.mark.parametrize(
    "reply,identity",
    [
        ("OK drive", "robot-01"),
        ("OK drive left=21 right=20 ms=100", "robot-01"),
        ("OK drive left=20 right=20 ms=100", "robot-02"),
    ],
)
async def test_ack_must_match_command_and_robot(settings, tokens, reply, identity):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"ok": True, "reply": reply, "robot_id": identity})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        head = HttpHead(settings.robots[0], client)
        with pytest.raises(HeadError):
            await head.command("drive 20 20 100")
        assert len(calls) == 1


def test_calibration_rejects_examples_and_degenerate_geometry(settings):
    path = settings.robots[0].calibration
    c = Calibration.load(path)
    assert c.ground((100, 100)) == pytest.approx((100, 100))
    data = json.loads(path.read_text())
    data["measured"] = False
    with pytest.raises(ValueError, match="unmeasured"):
        Calibration.model_validate(data).verify_ready()
    data["pixel_points"] = [[0, 0], [10, 0], [20, 0], [30, 0]]
    with pytest.raises(ValueError, match="collinear"):
        Calibration.model_validate(data)


def test_nonfinite_calibration_rejected(settings):
    data = json.loads(settings.robots[0].calibration.read_text())
    data["grip_ground_mm"] = [float("nan"), 100]
    with pytest.raises(ValueError):
        Calibration.model_validate(data)
