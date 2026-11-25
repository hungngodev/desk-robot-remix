"""Read only first unit replay across Mac pose and a selected Sense JPEG.

Synthetic authenticated transport and already selected MJPEG frame metadata
exercise the real Mac consumer. This is not physical map or motor acceptance.
"""

import json
import time
from types import SimpleNamespace

import httpx
import pytest
from desk_robot import transport
from desk_robot.api import create_app
from desk_robot.config import RobotConfig, Settings
from desk_robot.runtime import Runtime
from desk_robot.spatial_bracket import BracketError, validate_stationary_bracket
from desk_robot.transport import HeadError, HttpHead
from fastapi.testclient import TestClient

JPEG = bytes.fromhex("ffd8696d616765ffd9")


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", (
    "body_reboot", "head_reboot", "head_reboot_body_clock_reset",
    "foreign_robot", "pose_replay",
))
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
            # A Sense reboot does not restart the WROOM source clock.
            return httpx.Response(200, json={
                **packet, "head_boot": 78,
                "seq": 3, "sample_us": 1_060_000,
            })
        if sequence == 3 and fault == "head_reboot_body_clock_reset":
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
        if fault == "head_reboot_body_clock_reset":
            # Invalid source clock cannot replace the last trusted body baseline.
            assert head.pose_fence.last is continuous
        elif fault == "head_reboot":
            assert head.pose_fence.last.head_boot == 78
            assert head.pose_fence.last.body_boot == 8

        # The next still-fresh live JPEG cannot restore retired body pose.
        head._stream_version = 2
        head._stream_received_at = time.monotonic()
        head._accept_camera_identity((77, 2, 20_000))
        newer_frame = await head.snapshot_for_dock()
        assert newer_frame[2:] == ((77, 2, 20_000), 1)
        assert head.pose_fence.current(time.monotonic()) is None
    assert calls == ["/api/pose"] * 3


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ("foreign_robot", "stale_body_sample", "stream_reconnect"))
async def test_stationary_camera_pose_bracket_recovers_with_new_receipts(
    settings, tokens, monkeypatch, fault,
):
    """Synthetic receipt timing only: no calibrated optical or body lag claim."""
    robot = settings.robots[0]
    now = 100.0
    response_at = now
    packet = {}
    calls = []
    monkeypatch.setattr(transport, "time", SimpleNamespace(monotonic=lambda: now))

    def handler(request):
        nonlocal now
        assert request.method == "GET" and request.url.path == "/api/pose"
        assert request.headers["Authorization"] == "Bearer " + tokens[robot.token_env]
        calls.append(request.url.path)
        now = response_at
        return httpx.Response(200, json=packet)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        head = HttpHead(robot, client)

        async def forbidden_command(_command):
            pytest.fail("Stationary receipt replay must not send a body command")

        head.command = forbidden_command

        async def read_pose(at, seq, **overrides):
            nonlocal now, response_at, packet
            now = at - 0.01
            response_at = at
            packet = {
                "robot_id": robot.id, "v": 1, "head_boot": 77,
                "body_boot": 8, "origin": 3, "seq": seq,
                "sample_us": round(1_000_000 + (at - 100) * 1_000_000),
                "x_mm": 25, "y_mm": -30, "yaw_mrad": 1000, "quality": "valid",
                **overrides,
            }
            return await head.pose_status()

        async def select_frame(at, seq, generation=1):
            nonlocal now
            now = at
            # Replay the already selected authenticated-stream fixture.
            head._stream_connected = True
            head._stream_generation = generation
            head._stream_latest = JPEG
            head._stream_received_at = at
            head._stream_version = seq
            head._accept_camera_identity((77, seq, seq * 10_000))
            receipt = await head.snapshot_for_dock()
            assert receipt == (JPEG, at, (77, seq, seq * 10_000), generation)
            return receipt

        def bracket(previous, selected, before, after):
            return validate_stationary_bracket(
                fence=head.pose_fence, before=before, after=after,
                previous_camera=previous[2], camera=selected[2],
                camera_received_at=selected[1],
                stream_generation_before=previous[3],
                stream_generation_after=selected[3],
                motion_epoch_before=4, motion_epoch_after=4,
                disarmed_before=True, disarmed_after=True,
                now=now, max_optical_lag_s=0.05, max_body_lag_s=0.05,
            )

        await read_pose(100.0, 1)
        assert head.pose_fence.current(now) is None
        previous = await select_frame(100.05, 1)
        before = await read_pose(100.1, 2)
        selected = await select_frame(100.2, 2)
        after = await read_pose(100.3, 3)
        accepted = bracket(previous, selected, before, after)
        assert accepted.robot_id == robot.id
        assert (accepted.body_boot, accepted.origin) == (8, 3)
        assert accepted.camera_identity == selected[2]
        assert (accepted.before_seq, accepted.after_seq) == (2, 3)
        assert (accepted.odom_base.x_mm, accepted.odom_base.y_mm) == (25, -30)
        assert accepted.odom_base.yaw_rad == pytest.approx(1.0)
        assert head.pose_fence.needs_reanchor is True

        generation = 1
        frame_seq = 3
        if fault == "stream_reconnect":
            generation = 2
            foreign_session = await select_frame(100.31, 3, generation)
            frame_seq = 4
            with pytest.raises(BracketError, match="stream generation"):
                bracket(selected, foreign_session, before, after)
        else:
            overrides = (
                {"robot_id": "foreign-pet"} if fault == "foreign_robot"
                else {"sample_us": 1_310_000}
            )
            with pytest.raises(HeadError, match=(
                "Pose robot identity" if fault == "foreign_robot"
                else "sample lags local receipt clock"
            )):
                await read_pose(100.7, 4, **overrides)
            assert head.pose_fence.current(now) is None
            with pytest.raises(BracketError, match="current"):
                bracket(previous, selected, before, after)

        # Recovery needs a new camera baseline and two new pose samples after
        # a rejected pose; no original bracket or map anchor may be reused.
        await read_pose(100.8, 5)
        if fault != "stream_reconnect":
            assert head.pose_fence.current(now) is None
        new_previous = await select_frame(100.85, frame_seq, generation)
        new_before = await read_pose(100.9, 6)
        new_selected = await select_frame(101.0, frame_seq + 1, generation)
        new_after = await read_pose(101.1, 7)
        recovered = bracket(new_previous, new_selected, new_before, new_after)
        assert recovered.robot_id == robot.id
        assert recovered.camera_identity == new_selected[2]
        assert recovered.stream_generation == generation
        assert (recovered.before_seq, recovered.after_seq) == (6, 7)
        assert recovered.odom_base == accepted.odom_base
        assert head.pose_fence.current(now) is new_after
        assert head.pose_fence.needs_reanchor is True

        with pytest.raises(BracketError, match="current"):
            bracket(previous, selected, before, after)
    assert calls == ["/api/pose"] * (6 if fault == "stream_reconnect" else 7)


def test_legacy_pose_normal_runtime_startup_and_restart(tmp_path, tokens, monkeypatch):
    """Exercise the real lifespan with only head HTTP replaced, not Runtime.start."""
    robot = RobotConfig(id="robot-01", name="Legacy", token_env="DESK_ROBOT_HEAD_01_TOKEN")
    settings = Settings(mode="hardware", robots=[robot], memory_dir=tmp_path / "memory")
    auth = {"Authorization": "Bearer " + tokens["DESK_ROBOT_API_TOKEN"]}
    base = f"/v1/robots/{robot.id}"
    calls = []
    offline = False

    def handler(request):
        assert request.headers["Authorization"] == "Bearer " + tokens[robot.token_env]
        calls.append((request.method, request.url.path))
        if request.url.path == "/api/pose":
            if offline:
                raise httpx.ConnectError("Legacy head disconnected", request=request)
            return httpx.Response(501)
        if request.url.path == "/api/status":
            return httpx.Response(200, json={"robot_id": robot.id, "armed": False})
        assert request.url.path == "/api/command" and request.method == "POST"
        assert json.loads(request.content) == {"command": "halt"}
        return httpx.Response(200, json={
            "robot_id": robot.id, "ok": True, "reply": "OK halt",
        })

    original_client = httpx.AsyncClient

    def mock_client(**kwargs):
        return original_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", mock_client)
    runtimes = []
    # Start with empty private storage, then reconstruct all runtime owners.
    for _ in range(2):
        offline = False
        app = create_app(settings)
        with TestClient(app) as client:
            runtime = app.state.runtime
            assert isinstance(runtime, Runtime)
            runtimes.append(runtime)
            head = runtime.coordinator.heads[robot.id]
            assert isinstance(head, HttpHead)
            assert client.get(base + "/pose", headers=auth).status_code == 501
            assert head.pose_fence.current(time.monotonic()) is None
            assert head.pose_fence.needs_reanchor
            status = client.get(base + "/status", headers=auth)
            assert status.status_code == 200
            assert status.json()["armed"] is False
            grid = client.get(base + "/spatial/grid", headers=auth)
            assert grid.status_code == 200
            for field in ("anchored", "navigation_authorized", "motor_authorized",
                          "charging_authorized", "physical_acceptance_pass"):
                assert grid.json()[field] is False
            assert client.post(
                base + "/navigate", headers=auth, json={"goal": [1, 1]},
            ).status_code == 409
            offline = True
            assert client.get(base + "/pose", headers=auth).status_code == 503
            assert head.pose_fence.current(time.monotonic()) is None
            offline = False
            assert client.get(base + "/status", headers=auth).status_code == 200
        assert runtime.client.is_closed
    assert runtimes[0] is not runtimes[1]
    assert calls == [
        ("GET", "/api/pose"), ("GET", "/api/status"), ("GET", "/api/pose"),
        ("GET", "/api/status"), ("POST", "/api/command"),
    ] * 2
