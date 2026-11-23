"""Read only first unit replay across Mac pose and a selected Sense JPEG.

Synthetic authenticated transport and already selected MJPEG frame metadata
exercise the real Mac consumer. This is not physical map or motor acceptance.
"""

import time

import httpx
import pytest
from desk_robot.transport import HeadError, HttpHead

JPEG = bytes.fromhex("ffd8696d616765ffd9")


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ("body_reboot", "head_reboot", "foreign_robot", "pose_replay"))
async def test_fresh_camera_frame_never_rescues_invalid_body_origin(
    settings, tokens, fault,
):
    robot = settings.robots[0]
    packet = {
        "robot_id": robot.id, "v": 1, "head_boot": 77,
        "body_boot": 8, "origin": 3,
        "sample_us": 1_000_000, "x_mm": 0, "y_mm": 0,
        "yaw_mrad": 0, "quality": "valid",
    }
    calls = []

    def handler(request):
        assert request.method == "GET" and request.url.path == "/api/pose"
        assert request.headers["Authorization"] == "Bearer " + tokens[robot.token_env]
        calls.append(request.url.path)
        sequence = len(calls)
        if sequence == 3 and fault == "body_reboot":
            return httpx.Response(200, json={
                **packet, "body_boot": 9, "origin": 1,
                "seq": 1, "sample_us": 10_000,
            })
        if sequence == 3 and fault == "head_reboot":
            return httpx.Response(200, json={
                **packet, "head_boot": 78,
                "seq": 1, "sample_us": 10_000,
            })
        if sequence == 3 and fault == "foreign_robot":
            return httpx.Response(200, json={
                **packet, "robot_id": "foreign-pet", "seq": 3,
                "sample_us": 1_060_000,
            })
        return httpx.Response(200, json={
            **packet, "seq": min(sequence, 2),
            "sample_us": 1_000_000 + 20_000 * min(sequence, 2),
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        head = HttpHead(robot, client)

        async def forbidden_command(_command):
            pytest.fail("Reading pose or JPEG must not send a body command")

        head.command = forbidden_command
        baseline = await head.pose_status()
        assert head.pose_fence.current(baseline.received_at) is None
        continuous = await head.pose_status()
        assert head.pose_fence.current(continuous.received_at) == continuous
        assert head.pose_fence.needs_reanchor is True

        # The frame is a selected, fresh, authenticated-stream fixture.
        # A JPEG is not a second independent pose or a metric map anchor.
        head._stream_connected = True
        head._stream_generation = 1
        head._stream_latest = JPEG
        head._stream_received_at = time.monotonic()
        head._stream_version = 1
        head._accept_camera_identity((77, 1, 10_000))
        frame = await head.snapshot_for_dock()
        assert frame[0] == JPEG
        assert frame[2:] == ((77, 1, 10_000), 1)
        assert head.pose_fence.needs_reanchor is True

        with pytest.raises(HeadError, match=(
            "re-anchor" if fault in ("body_reboot", "head_reboot")
            else "Pose robot identity" if fault == "foreign_robot"
            else "Pose sequence"
        )):
            await head.pose_status()
        assert head.pose_fence.current(time.monotonic()) is None
        assert head.pose_fence.needs_reanchor is True

        # The next still-fresh live JPEG cannot restore retired body pose.
        head._stream_version = 2
        head._stream_received_at = time.monotonic()
        head._accept_camera_identity((77, 2, 20_000))
        newer_frame = await head.snapshot_for_dock()
        assert newer_frame[2:] == ((77, 2, 20_000), 1)
        assert head.pose_fence.current(time.monotonic()) is None
    assert calls == ["/api/pose"] * 3
