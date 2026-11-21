"""Native HTTP camera egress is bound to the admitted permission generation."""
import time
from types import SimpleNamespace

import pytest
from desk_robot.api import create_app
from fastapi.testclient import TestClient


class Runtime:
    def __init__(self, settings, camera):
        self.coordinator = SimpleNamespace(robot=lambda rid: settings.robot(rid))
        self.multimodal = camera

    async def start(self):
        pass

    async def close(self):
        pass


@pytest.mark.parametrize("regrant", [False, True])
def test_native_snapshot_cannot_return_media_from_revoked_grant(
    settings, tokens, regrant,
):
    settings.mode = "hardware"
    settings.voice_vision_tools_enabled = True
    source = b"real-camera-jpeg"

    class Camera:
        async def capture(self, robot_id, *, source):
            assert source == "speech"
            if regrant:
                settings.voice_vision_tools_enabled = False
                settings.voice_vision_tools_enabled = True
            return SimpleNamespace(jpeg=b"real-camera-jpeg", received_at=time.monotonic())

    robot = settings.robots[0].id
    url = f"/v1/pet/{robot}/omni-frame"
    headers = {"Authorization": "Bearer " + tokens["DESK_ROBOT_TOOL_TOKEN"]}
    with TestClient(create_app(settings, runtime=Runtime(settings, Camera()))) as client:
        response = client.get(url, headers=headers)
    assert response.status_code == (403 if regrant else 200)
    if regrant:
        assert source not in response.content
    else:
        assert response.content == source


@pytest.mark.parametrize("regrant", [False, True])
def test_native_push_drops_old_grant_jpeg_after_socket_await(
    settings, tokens, monkeypatch, regrant,
):
    from starlette.requests import Request

    settings.mode = "hardware"
    settings.voice_vision_tools_enabled = True
    source = b"real-camera-jpeg"

    class Camera:
        async def native_live_frames(self, robot_id):
            yield SimpleNamespace(
                jpeg=source, received_at=time.monotonic(),
                motion_fraction=0.1, source="proactive",
            )

    async def socket_check(_request):
        if regrant:
            settings.voice_vision_tools_enabled = False
            settings.voice_vision_tools_enabled = True
        return False

    monkeypatch.setattr(Request, "is_disconnected", socket_check)
    robot = settings.robots[0].id
    url = f"/v1/pet/{robot}/omni-stream"
    headers = {"Authorization": "Bearer " + tokens["DESK_ROBOT_TOOL_TOKEN"]}
    with TestClient(create_app(settings, runtime=Runtime(settings, Camera()))) as client:
        response = client.get(url, headers=headers)
    assert response.status_code == 200
    if regrant:
        assert response.content == b""
    else:
        assert b"jpeg_base64" in response.content
