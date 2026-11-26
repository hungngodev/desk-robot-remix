"""Original Sense camera boot must stay bound to every dock JPEG."""
import asyncio
import json
import time
from types import SimpleNamespace

import httpx
import pytest
from desk_robot.controller import Coordinator, Job
from desk_robot.dock_runtime import observe_actual_dock, unpack_dock_frame
from desk_robot.dock_vision import DockCameraCalibration
from desk_robot.transport import HeadError, HttpHead

JPEG = bytes.fromhex("ffd8696d616765ffd9")


def make_head():
    head = HttpHead(SimpleNamespace(id="robot-01", head_url="http://unused.invalid",
                                    token_env="DUMMY_DOCK_TOKEN"), client=None)
    head._stream_connected = True
    head._stream_generation = 1
    head._stream_latest = JPEG
    head._stream_received_at = time.monotonic()
    head._stream_version = 1
    head._last_camera = (100, 1, 1000)
    return head


async def replace_boot(head, boot=101):
    async with head._stream_condition:
        head._stream_generation += 1
        head._last_camera = (boot, 1, 2000)
        head._stream_latest = JPEG
        head._stream_received_at = time.monotonic()
        head._stream_version += 1
        head._stream_condition.notify_all()


def pid_receipt(boot):
    return httpx.Response(200, json={"robot_id": "robot-01",
        "camera_sensor_pid": "OV5640", "camera_pid_raw": 0x5640, "boot": boot})


@pytest.mark.asyncio
async def test_uninterrupted_frame_identity_is_bound_to_its_own_boot():
    head = make_head()
    receipt = await head.snapshot_for_dock()
    assert len(receipt) == 4
    assert receipt[2:] == ((100, 1, 1000), 1)
    assert unpack_dock_frame(receipt) == receipt[:2]
    async def request(*args, **kwargs):
        return pid_receipt(100)
    head._request = request
    assert await head.camera_identity(receipt) == "OV5640"
    await head.dock_receipt_current(receipt)


@pytest.mark.asyncio
@pytest.mark.parametrize("new_boot", [100, 101])
async def test_identity_request_rejects_reconnected_stream_even_with_same_pid(new_boot):
    head = make_head()
    receipt = await head.snapshot_for_dock()
    entered, released = asyncio.Event(), asyncio.Event()
    async def request(*args, **kwargs):
        entered.set()
        await released.wait()
        return pid_receipt(new_boot)
    head._request = request
    task = asyncio.create_task(head.camera_identity(receipt))
    await asyncio.wait_for(entered.wait(), 1)
    await replace_boot(head, new_boot)
    released.set()
    with pytest.raises(HeadError, match="Dock JPEG boot changed"):
        await asyncio.wait_for(task, 1)
    with pytest.raises(HeadError):
        await head.dock_receipt_current(receipt)


@pytest.mark.asyncio
async def test_read_only_pose_holds_instead_of_decoding_retired_boot(tmp_path, monkeypatch):
    calibration = tmp_path / "dock.json"
    calibration.write_text(json.dumps({"schema_version": 1,
        "measured": True, "robot_id": "robot-01", "head_device_id": "xiaozhi-01", "camera_sensor_pid": "OV5640",
        "fx": 410, "fy": 410, "cx": 320, "cy": 240, "tag_side_mm": 60,
        "marker_id": 12, "target_distance_mm": 120}))
    head = make_head()
    entered, released = asyncio.Event(), asyncio.Event()
    async def request(*args, **kwargs):
        entered.set()
        await released.wait()
        return pid_receipt(101)
    async def forbidden(*args, **kwargs):
        pytest.fail("Old JPEG must never reach the native AprilTag detector")
    head._request = request
    monkeypatch.setattr("desk_robot.dock_runtime.detect_bounded", forbidden)
    task = asyncio.create_task(observe_actual_dock(
        head, SimpleNamespace(id="robot-01", dock_calibration=calibration)))
    await asyncio.wait_for(entered.wait(), 1)
    await replace_boot(head)
    released.set()
    outcome = await asyncio.wait_for(task, 1)
    assert outcome["phase"] == "hold" and outcome["pose"] is None
    assert outcome["source"] == "camera_identity_unavailable"
    assert not outcome["motor_authorized"] and not outcome["charging_authorized"]


@pytest.mark.asyncio
async def test_guarded_dock_reconnect_never_dispatches_motor_pulse():
    head = make_head()
    entered, released = asyncio.Event(), asyncio.Event()
    commands = []
    async def request(*args, **kwargs):
        entered.set()
        await released.wait()
        return pid_receipt(101)
    async def command(value):
        commands.append(value)
        raise AssertionError("Stale dock frame dispatched drive")
    async def healthy(*args, **kwargs):
        return {}
    head._request = request
    head.command = command
    controller = object.__new__(Coordinator)
    controller.settings = SimpleNamespace(mode="hardware")
    controller.heads = {"robot-01": head}
    controller.robot = lambda _id: SimpleNamespace(dock_beacon_id=1)
    controller._assert_armed_health = healthy
    camera = DockCameraCalibration(410, 410, 320, 240, 60, 12,
                                   camera_sensor_pid="OV5640")
    task = asyncio.create_task(controller._dock_approach(
        Job("boot-race", "robot-01", "dock_approach"), camera, 200, 1, 1))
    await asyncio.wait_for(entered.wait(), 1)
    await replace_boot(head)
    released.set()
    with pytest.raises(HeadError, match="Dock JPEG boot changed"):
        await asyncio.wait_for(task, 1)
    assert commands == []


@pytest.mark.parametrize("identity,epoch", [
    ((100, 1, 1000), True), ((100, 1, 1000), 0),
    (("100", 1, 1000), 1), ((100, 1, 1000, 2), 1),
])
def test_invalid_source_metadata_never_becomes_dock_pose(identity, epoch):
    with pytest.raises(ValueError, match="Invalid or stale dock camera receipt"):
        unpack_dock_frame((JPEG, time.monotonic(), identity, epoch))


@pytest.mark.asyncio
@pytest.mark.parametrize("new_boot", [100, 101])
@pytest.mark.parametrize("lock_name", ["lock", "command_lock"])
async def test_dispatch_rejects_replaced_stream_inside_command_queue(
    new_boot, lock_name, monkeypatch,
):
    head = make_head()
    receipt = await head.snapshot_for_dock()
    # Keep the original receipt fresh: this tests generation, not expiration.
    monkeypatch.setattr(
        "desk_robot.transport.time",
        SimpleNamespace(monotonic=lambda: receipt[1] + 0.01),
    )
    posts = []

    async def request(*args, **kwargs):
        posts.append((args, kwargs))
        raise AssertionError("Retired camera receipt reached POST")

    head._request = request
    lock = getattr(head, lock_name)
    async with lock:
        task = asyncio.create_task(head.command(
            "drive 20 20 100",
            dispatch_check=lambda: head.dock_receipt_current_now(receipt),
        ))
        await asyncio.sleep(0)
        await replace_boot(head, new_boot)
    with pytest.raises(HeadError, match="Dock JPEG boot changed"):
        await asyncio.wait_for(task, 1)
    assert posts == []
