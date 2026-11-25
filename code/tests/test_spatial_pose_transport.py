import asyncio
from types import SimpleNamespace

import httpx
import pytest
from desk_robot import transport
from desk_robot.transport import HeadError, HttpHead, PoseUnsupported


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
        with pytest.raises(PoseUnsupported):
            await head.pose_status()
        assert head.pose_fence.blocked_reason == "pose_unsupported"
        assert (await head.status())["robot_id"] == robot.id


@pytest.mark.asyncio
async def test_slow_pose_http_receipts_cannot_establish_freshness(settings, tokens, monkeypatch):
    robot = settings.robots[0]
    now = 100.0
    sequence = 0
    delays = iter((0.6, 0.6, 0.01, 0.01))
    monkeypatch.setattr(transport, "time", SimpleNamespace(monotonic=lambda: now))

    def handler(request):
        nonlocal now, sequence
        sequence += 1
        assert request.method == "GET" and request.url.path == "/api/pose"
        packet = {
            "robot_id": robot.id, "v": 1, "head_boot": 12, "body_boot": 9,
            "origin": 3, "seq": sequence, "sample_us": round(now * 1_000_000),
            "x_mm": 0, "y_mm": 0, "yaw_mrad": 0, "quality": "valid",
        }
        now += next(delays)
        return httpx.Response(200, json=packet)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        head = HttpHead(robot, client)
        for _ in range(2):
            with pytest.raises(HeadError, match="request age"):
                await head.pose_status()
            assert head.pose_fence.current(now) is None
            assert head.pose_fence.blocked_reason == "pose_transport_delayed"
        await head.pose_status()
        assert head.pose_fence.current(now) is None
        receipt = await head.pose_status()
        assert receipt.request_started_at == pytest.approx(now - 0.01)
        assert receipt.received_at == now
        assert head.pose_fence.current(now) == receipt
        assert head.pose_fence.current(now + 0.245) is None


@pytest.mark.asyncio
async def test_pose_http_age_excludes_wait_for_transport_lock(settings, tokens, monkeypatch):
    robot = settings.robots[0]
    now = 100.0
    monkeypatch.setattr(transport, "time", SimpleNamespace(monotonic=lambda: now))

    def handler(request):
        nonlocal now
        assert request.url.path == "/api/pose"
        now += 0.01
        return httpx.Response(200, json={
            "robot_id": robot.id, "v": 1, "head_boot": 12, "body_boot": 9,
            "origin": 3, "seq": 1, "sample_us": 100_000,
            "x_mm": 0, "y_mm": 0, "yaw_mrad": 0, "quality": "valid",
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        head = HttpHead(robot, client)
        async with head.lock:
            pending = asyncio.create_task(head.pose_status())
            await asyncio.sleep(0)
            now += 0.6
        receipt = await pending
        assert receipt.request_started_at == pytest.approx(100.6)
        assert receipt.received_at == pytest.approx(100.61)
        assert head.pose_fence.current(now) is None
