"""Motion from live camera evidence must retain its original consent grant."""

import time
from types import SimpleNamespace

import pytest
from desk_robot.controller import Coordinator, Job, OperationError
from desk_robot.simulator import SimulatedHead, SimulationVision


def make_controller(settings):
    head = SimulatedHead("robot-01")
    return Coordinator(settings, {"robot-01": head}, SimulationVision()), head


@pytest.mark.parametrize("regrant", [False, True])
def test_camera_motion_grant_rejects_revocation(settings, regrant):
    settings.mode = "hardware"
    settings.voice_vision_tools_enabled = True
    controller, _ = make_controller(settings)
    grant = controller._camera_motion_grant()
    controller._require_camera_motion_grant(grant)
    settings.voice_vision_tools_enabled = False
    if regrant:
        settings.voice_vision_tools_enabled = True
    with pytest.raises(OperationError, match="Camera consent revoked"):
        controller._require_camera_motion_grant(grant)


@pytest.mark.parametrize("regrant", [False, True])
async def test_dock_camera_revoked_during_snapshot_never_drives(settings, regrant):
    settings.mode = "hardware"
    settings.voice_vision_tools_enabled = True
    controller, head = make_controller(settings)
    grant = controller._camera_motion_grant()

    async def healthy(*args, **kwargs):
        return {}

    async def changing_snapshot():
        settings.voice_vision_tools_enabled = False
        if regrant:
            settings.voice_vision_tools_enabled = True
        return b"camera-frame", time.monotonic()

    controller._assert_armed_health = healthy
    head.snapshot_for_dock = changing_snapshot
    camera = SimpleNamespace(camera_sensor_pid=None)
    try:
        with pytest.raises(OperationError, match="Camera consent revoked"):
            await controller._dock_approach(
                Job("dock-consent", "robot-01", "dock_approach"),
                camera, 200, 1, 1, camera_grant=grant,
            )
        assert head.commands == []
    finally:
        await controller.close()


@pytest.mark.parametrize("regrant", [False, True])
async def test_pickup_revocation_during_observe_never_grasps(settings, regrant):
    settings.mode = "hardware"
    settings.voice_vision_tools_enabled = True
    controller, head = make_controller(settings)
    grant = controller._camera_motion_grant()
    await head.command("arm")
    head.commands.clear()
    controller.multimodal = SimpleNamespace(
        stream_owns_camera=lambda robot_id: True,
        status=lambda robot_id: {"camera_stream_connected": True},
    )

    async def healthy(*args, **kwargs):
        return {}

    async def observe(*args, **kwargs):
        settings.voice_vision_tools_enabled = False
        if regrant:
            settings.voice_vision_tools_enabled = True
        return SimpleNamespace(center=(0, 0)), time.monotonic()

    controller._assert_armed_health = healthy
    controller._observe = observe
    calibration = SimpleNamespace(
        grip_open=70, lift_down=80, servo_settle_seconds=0,
        ground=lambda center: (0, 0), within=lambda position: True,
        grip_ground_mm=(0, 0), alignment_tolerance_mm=1,
    )
    try:
        with pytest.raises(OperationError, match="Camera consent revoked"):
            await controller._pickup(
                Job("pickup-consent", "robot-01", "pickup"),
                "key", calibration, camera_grant=grant,
            )
        assert head.commands == ["grip 70", "lift 80"]
    finally:
        await controller.close()
