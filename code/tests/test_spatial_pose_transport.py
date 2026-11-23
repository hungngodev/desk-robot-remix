import httpx
import pytest

from desk_robot.transport import HeadError, HttpHead


async def test_authenticated_pose_reader_tracks_identity_and_replay(settings, tokens):
    robot = settings.robots[0]
    calls = 0

    def handler(request):
        nonlocal calls
        assert request.method == "GET"
        assert request.url.path == "/api/pose"
        assert request.headers["Authorization"].startswith("Bearer ")
        calls += 1
        seq = min(calls, 2)
        return httpx.Response(200, json={
            "robot_id": robot.id, "v": 1, "body_boot": 7, "origin": 1,
            "seq": seq, "sample_us": 1_000_000 + 100_000 * seq,
            "x_mm": 30, "y_mm": 0, "yaw_mrad": 1000, "quality": "valid",
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        head = HttpHead(robot, client)
        first = await head.pose_status()
        second = await head.pose_status()
        assert first.seq == 1 and second.seq == 2
        assert second.yaw_rad == 1.0
        assert second.robot_id == robot.id
        assert head.pose_fence.needs_reanchor
        with pytest.raises(HeadError, match="Pose sequence"):
            await head.pose_status()
        assert head.pose_fence.current(second.received_at) is None
        assert calls == 3


async def test_old_head_missing_pose_does_not_disable_normal_status(settings, tokens):
    robot = settings.robots[0]

    def handler(request):
        if request.url.path == "/api/pose":
            return httpx.Response(404)
        assert request.url.path == "/api/status"
        return httpx.Response(200, json={"robot_id": robot.id, "armed": False})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        head = HttpHead(robot, client)
        with pytest.raises(HeadError):
            await head.pose_status()
        assert head.pose_fence.blocked_reason == "pose_transport_unavailable"
        assert (await head.status())["robot_id"] == robot.id
