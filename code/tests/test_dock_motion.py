"""Dock motion remains operator permitted and disabled by default."""
import json
import time

import pytest
from desk_robot.controller import Coordinator, OperationError
from desk_robot.simulator import SimulatedHead, SimulationVision
from dock_detector_fixture import mock_dock_detector


class DockFrameFixture:
    """Host stand-in for a bound camera boot, sequence and stream generation."""

    async def snapshot_for_dock(self):
        return (await self.snapshot(), time.monotonic(), (1234, 1, 1), 1)

    async def dock_receipt_current(self, receipt):
        if not (
            isinstance(receipt, tuple) and len(receipt) == 4
            and receipt[2:] == ((1234, 1, 1), 1)
        ):
            raise ValueError("Fixture camera stream was replaced")


def make(settings):
    head = SimulatedHead("robot-01")
    return Coordinator(
        settings, {"robot-01": head, "robot-02": SimulatedHead("robot-02")},
        SimulationVision(),
    ), head


def test_dock_approach_refuses_unmeasured_hardware_and_default_config(settings):
    controller, head = make(settings)
    try:
        with pytest.raises(OperationError, match="qualification"):
            controller.dock("robot-01")
        assert head.commands == []
    finally:
        # Close is async and no tasks have been started here.
        pass


async def test_dock_does_not_consume_permit_without_measured_steering(settings, tmp_path):
    settings.mode = "hardware"
    robot = settings.robots[0]
    robot.dock_motion_qualified = True
    robot.dock_turn_sign = None
    robot.dock_forward_sign = 1
    dock = tmp_path / "dock.json"
    dock.write_text(json.dumps({
        "measured": True, "robot_id": "robot-01", "head_device_id": "xiaozhi-01", "fx": 410, "fy": 410, "cx": 320, "cy": 240,
        "tag_side_mm": 60, "marker_id": 1, "target_distance_mm": 200,
    }))
    robot.device_id = "xiaozhi-01"
    robot.dock_calibration = dock
    controller, head = make(settings)
    try:
        controller.permits["robot-01"] = 10**9
        with pytest.raises(OperationError, match="polarity"):
            controller.dock("robot-01")
        assert controller.permits["robot-01"] == 10**9
        assert head.commands == []
    finally:
        await controller.close()


@pytest.mark.parametrize("side_override", [
    {"valid_mask": 0},
    {"present_mask": 0},
    {"present_mask": True},
    {"present_mask": "7"},
    {"mm": [600, 600, 1301]},
    {"mm": [600, 600, -1]},
    {"mm": [600, True, 600]},
    {"age_ms": [10, 351, 10]},
])
async def test_dock_approach_rejects_turn_without_three_fresh_clear_ranges(
    settings, monkeypatch, side_override,
):
    from desk_robot.controller import Job
    from desk_robot.dock_vision import DockCameraCalibration, DockPose

    settings.mode = "hardware"

    class SensorHead(DockFrameFixture):
        def __init__(self):
            self.commands = []

        async def status(self):
            return {
                "robot_id": "robot-01",
                "armed": True,
                "safety": {"required": True, "ready": True, "fault": "none"},
                "ranges": {"present_mask": 31, "valid_mask": 31,
                           "mm": [50, 50, 50, 50, 650],
                           "age_ms": [5, 5, 5, 5, 5]},
                "imu": {"valid": True, "age_ms": 10},
                "touch": {"active": False},
                "side_ranges": {"present_mask": 7, "valid_mask": 7,
                                "age_ms": [10, 10, 10], "mm": [600, 600, 600],
                                **side_override},
            }

        async def snapshot(self):
            return b"simulated marker image"

        async def command(self, text):
            self.commands.append(text)

    head = SensorHead()
    controller = Coordinator(
        settings, {"robot-01": head}, SimulationVision(),
    )
    camera = DockCameraCalibration(
        fx=410, fy=410, cx=320, cy=240,
        tag_side_mm=60, marker_id=1,
        mount_lateral_offset_mm=0, mount_yaw_deg=0,
    )
    mock_dock_detector(
        monkeypatch,
        lambda jpeg, cal, *, captured_at: DockPose(
            80, 0, 500, 0.5, captured_at,
        ),
    )
    try:
        with pytest.raises(OperationError, match="side and rear"):
            await controller._dock_approach(
                Job("dock-unit", "robot-01", "dock_approach"),
                camera, 200, 1, 1,
            )
        assert head.commands == []
    finally:
        await controller.close()


async def test_dock_approach_moves_once_then_holds_before_contacts(
    settings, monkeypatch,
):
    from desk_robot.controller import Job
    from desk_robot.dock_vision import DockCameraCalibration, DockPose

    settings.mode = "hardware"

    class GuardedHead(DockFrameFixture):
        def __init__(self):
            self.commands = []

        async def status(self):
            return {
                "robot_id": "robot-01",
                "armed": True,
                "safety": {"required": True, "ready": True, "fault": "none"},
                "ranges": {"present_mask": 31, "valid_mask": 31,
                           "mm": [50, 50, 50, 50, 600],
                           "age_ms": [5, 5, 5, 5, 5]},
                "imu": {"valid": True, "age_ms": 10},
                "touch": {"active": False},
                "side_ranges": {"present_mask": 7, "valid_mask": 7, "age_ms": [10, 10, 10],
                                "mm": [600, 600, 600]},
            }

        async def snapshot(self):
            raise AssertionError("Dock motion used stale generic snapshot")

        async def snapshot_for_dock(self):
            import time
            return b"simulated marker image", time.monotonic(), (1234, 1, 1), 1

        async def command(self, text):
            self.commands.append(text)

    head = GuardedHead()
    controller = Coordinator(settings, {"robot-01": head}, SimulationVision())
    camera = DockCameraCalibration(
        fx=410, fy=410, cx=320, cy=240, tag_side_mm=60, marker_id=1,
        mount_lateral_offset_mm=0, mount_yaw_deg=0,
    )
    distances = iter((500, 150))
    mock_dock_detector(
        monkeypatch,
        lambda jpeg, cal, *, captured_at: DockPose(
            0, 0, next(distances), 0.5, captured_at,
        ),
    )
    try:
        result = await controller._dock_approach(
            Job("dock-unit", "robot-01", "dock_approach"),
            camera, 200, 1, 1,
        )
        assert result["phase"] == "hold"
        assert not result["charging_authorized"]
        assert not result["physical_acceptance_pass"]
        assert head.commands == ["drive 20 20 100", "stop"]
    finally:
        await controller.close()




async def test_dock_motion_refuses_unmeasured_lens_distortion_before_permit(
    settings, tmp_path,
):
    """A read-only zero distortion fallback never grants physical docking."""
    import time
    settings.mode = "hardware"
    robot = settings.robots[0]
    robot.motion_enabled = True
    robot.dock_motion_qualified = True
    robot.dock_turn_sign = 1
    robot.dock_forward_sign = 1
    path = tmp_path / "dock.json"
    path.write_text(json.dumps({
        "measured": True, "robot_id": "robot-01", "head_device_id": "xiaozhi-01", "fx": 410, "fy": 410, "cx": 320, "cy": 240,
        "tag_side_mm": 60, "marker_id": 1, "target_distance_mm": 200,
    }))
    robot.device_id = "xiaozhi-01"
    robot.dock_calibration = path
    controller, head = make(settings)
    try:
        controller.permits["robot-01"] = time.monotonic() + 10
        with pytest.raises(OperationError, match="measured camera lens distortion"):
            controller.dock("robot-01")
        assert controller.permits["robot-01"] > time.monotonic()
        assert not controller.jobs
        assert head.commands == []
    finally:
        await controller.close()



async def test_dock_motion_needs_calibrated_camera_resolution_even_with_distortion(
    settings, tmp_path,
):
    """Matching physical XIAO JPEG mode is required before consuming a permit."""
    import time
    settings.mode = "hardware"
    robot = settings.robots[0]
    robot.motion_enabled = True
    robot.dock_motion_qualified = True
    robot.dock_turn_sign = 1
    robot.dock_forward_sign = 1
    path = tmp_path / "dock.json"
    path.write_text(json.dumps({
        "measured": True, "robot_id": "robot-01", "head_device_id": "xiaozhi-01", "fx": 410, "fy": 410, "cx": 320, "cy": 240,
        "tag_side_mm": 60, "marker_id": 1, "target_distance_mm": 200,
        "distortion_coeffs": [0.18, -0.07, 0.003, -0.002, 0.01],
    }))
    robot.device_id = "xiaozhi-01"
    robot.dock_calibration = path
    controller, head = make(settings)
    try:
        controller.permits["robot-01"] = time.monotonic() + 10
        with pytest.raises(OperationError, match="calibrated camera frame resolution"):
            controller.dock("robot-01")
        assert controller.permits["robot-01"] > time.monotonic()
        assert not controller.jobs
        assert head.commands == []
    finally:
        await controller.close()


async def test_dock_refuses_motion_without_measured_camera_mount_before_permit(
    settings, tmp_path,
):
    """Good checkerboard intrinsics do not prove the camera's chassis pose."""
    import time

    settings.mode = "hardware"
    robot = settings.robots[0]
    robot.motion_enabled = True
    robot.dock_motion_qualified = True
    robot.dock_turn_sign = 1
    robot.dock_forward_sign = 1
    path = tmp_path / "dock.json"
    path.write_text(json.dumps({
        "measured": True, "robot_id": "robot-01", "head_device_id": "xiaozhi-01", "fx": 410, "fy": 410, "cx": 320, "cy": 240,
        "tag_side_mm": 60, "marker_id": 1, "target_distance_mm": 200,
        "distortion_coeffs": [0.0, 0.0, 0.0, 0.0, 0.0],
        "image_width_px": 640, "image_height_px": 480,
    }))
    robot.device_id = "xiaozhi-01"
    robot.dock_calibration = path
    controller, head = make(settings)
    try:
        controller.permits["robot-01"] = time.monotonic() + 10
        with pytest.raises(OperationError, match="camera to chassis mounting"):
            controller.dock("robot-01")
        assert controller.permits["robot-01"] > time.monotonic()
        assert not controller.jobs and not head.commands
    finally:
        await controller.close()


@pytest.mark.parametrize(("lateral", "yaw"), [
    (40, 0),
    (-40, 0),
    (0, 5),
    (0, -5),
])
async def test_dock_refuses_chassis_turn_even_with_clear_side_ranges(
    settings, monkeypatch, lateral, yaw,
):
    from desk_robot.controller import Job
    from desk_robot.dock_vision import DockCameraCalibration, DockPose

    settings.mode = "hardware"

    class SafeHead(DockFrameFixture):
        def __init__(self):
            self.commands = []

        async def status(self):
            return {
                "robot_id": "robot-01",
                "armed": True,
                "safety": {"required": True, "ready": True, "fault": "none"},
                "ranges": {
                    "present_mask": 31, "valid_mask": 31,
                    "mm": [50, 50, 50, 50, 650],
                    "age_ms": [5, 5, 5, 5, 5],
                },
                "imu": {"valid": True, "age_ms": 10},
                "touch": {"active": False},
                "side_ranges": {
                    "present_mask": 7,
                    "valid_mask": 7, "age_ms": [10, 10, 10],
                    "mm": [600, 600, 600],
                    "motion_certified": False,
                },
            }

        async def snapshot(self):
            return b"synthetic tag image"

        async def command(self, text):
            self.commands.append(text)

    head = SafeHead()
    coordinator = Coordinator(
        settings, {"robot-01": head}, SimulationVision(),
    )
    camera = DockCameraCalibration(
        410, 410, 320, 240, 60, 1,
        mount_lateral_offset_mm=lateral, mount_yaw_deg=yaw,
    )
    z_values = iter((500, 150))
    mock_dock_detector(
        monkeypatch,
        lambda jpeg, calib, *, captured_at: DockPose(
            0, 0, next(z_values), 0.2, captured_at,
        ),
    )
    try:
        with pytest.raises(OperationError, match="side and rear clearance unqualified"):
            await coordinator._dock_approach(
                Job("mount-unit", "robot-01", "dock_approach"),
                camera, 200, 1, 1,
            )
        assert head.commands == []
    finally:
        await coordinator.close()



async def test_dock_approach_requires_operator_permit_after_qualification(settings, tmp_path):
    settings.mode = "hardware"
    settings.voice_vision_tools_enabled = True
    robot = settings.robots[0]
    robot.dock_motion_qualified = True
    robot.dock_turn_sign = 1
    robot.dock_forward_sign = 1
    path = tmp_path / "dock.json"
    path.write_text(json.dumps({
        "measured": True, "robot_id": "robot-01", "head_device_id": "xiaozhi-01", "fx": 410, "fy": 410, "cx": 320, "cy": 240,
        "tag_side_mm": 60, "marker_id": 1, "target_distance_mm": 200,
        "distortion_coeffs": [0.0, 0.0, 0.0, 0.0, 0.0],
        "image_width_px": 640, "image_height_px": 480,
        "mount_lateral_offset_mm": 0.0, "mount_yaw_deg": 0.0,
        "camera_sensor_pid": "OV5640",
    }))
    robot.device_id = "xiaozhi-01"
    robot.dock_calibration = path
    controller, head = make(settings)
    try:
        # One permission must not paper over another: missing assigned NEC
        # beacon remains a separate hard stop, even before operator permit.
        with pytest.raises(OperationError, match="assigned physical NEC beacon"):
            controller.dock("robot-01")
        robot.dock_beacon_id = 1
        settings.voice_vision_tools_enabled = False
        with pytest.raises(OperationError, match="camera consent"):
            controller.dock("robot-01")
        settings.voice_vision_tools_enabled = True
        with pytest.raises(OperationError, match="permit"):
            controller.dock("robot-01")
        assert head.commands == []
    finally:
        await controller.close()


async def test_dock_refuses_stale_pre_camera_safety_after_sensor_fault(
    settings, monkeypatch,
):
    """A good pre-camera WROOM reading cannot authorize a later drive."""
    from desk_robot.controller import Job
    from desk_robot.dock_vision import DockCameraCalibration, DockPose

    settings.mode = "hardware"

    class HeadWithMidframeFault(DockFrameFixture):
        def __init__(self):
            self.commands = []
            self.armed = True
            self.reads = 0

        async def status(self):
            self.reads += 1
            return {
                "robot_id": "robot-01",
                "armed": self.armed,
                "safety": {"required": True, "ready": self.armed,
                           "fault": "none" if self.armed else "missing_sample"},
                "ranges": {"present_mask": 31, "valid_mask": 31,
                           "mm": [50, 50, 50, 50, 610],
                           "age_ms": [5, 5, 5, 5, 5]},
                "imu": {"valid": True, "age_ms": 10},
                "touch": {"active": False},
                "side_ranges": {"present_mask": 7, "valid_mask": 7,
                                "age_ms": [10, 10, 10],
                                "mm": [600, 600, 600]},
            }

        async def snapshot(self):
            # Cliff or bumper fault occurred WHILE camera was receiving.
            self.armed = False
            return b"real-frame-shaped-placeholder"

        async def command(self, line):
            self.commands.append(line)

    head = HeadWithMidframeFault()
    controller = Coordinator(settings, {"robot-01": head}, SimulationVision())
    camera = DockCameraCalibration(
        410, 410, 320, 240, 60, 1,
        mount_lateral_offset_mm=0, mount_yaw_deg=0,
    )
    mock_dock_detector(
        monkeypatch,
        lambda jpeg, cal, *, captured_at: DockPose(
            0, 0, 500, 0.5, captured_at,
        ),
    )
    try:
        with pytest.raises(OperationError, match="body disarmed"):
            await controller._dock_approach(
                Job("dock-race", "robot-01", "dock_approach"),
                camera, 200, 1, 1,
            )
        assert head.reads == 2
        assert head.commands == []
    finally:
        await controller.close()


async def test_dock_refuses_new_side_obstacle_after_camera_frame(
    settings, monkeypatch,
):
    from desk_robot.controller import Job
    from desk_robot.dock_vision import DockCameraCalibration, DockPose

    settings.mode = "hardware"

    class SideChangedHead(DockFrameFixture):
        def __init__(self):
            self.commands = []
            self.blocked = False

        async def status(self):
            return {
                "robot_id": "robot-01",
                "armed": True,
                "safety": {"required": True, "ready": True, "fault": "none"},
                "ranges": {"present_mask": 31, "valid_mask": 31,
                           "mm": [50, 50, 50, 50, 600],
                           "age_ms": [5, 5, 5, 5, 5]},
                "imu": {"valid": True, "age_ms": 10},
                "touch": {"active": False},
                "side_ranges": {
                    "present_mask": 7,
                    "valid_mask": 7 if not self.blocked else 0,
                    "age_ms": [10, 10, 10],
                    "mm": [600, 600, 600],
                },
            }

        async def snapshot(self):
            self.blocked = True
            return b"real-frame-shaped-placeholder"

        async def command(self, line):
            self.commands.append(line)

    head = SideChangedHead()
    controller = Coordinator(settings, {"robot-01": head}, SimulationVision())
    camera = DockCameraCalibration(
        410, 410, 320, 240, 60, 1,
        mount_lateral_offset_mm=0, mount_yaw_deg=0,
    )
    mock_dock_detector(
        monkeypatch,
        lambda jpeg, cal, *, captured_at: DockPose(
            80, 0, 500, 0.5, captured_at,
        ),
    )
    try:
        with pytest.raises(OperationError, match="side and rear"):
            await controller._dock_approach(
                Job("dock-side-race", "robot-01", "dock_approach"),
                camera, 200, 1, 1,
            )
        assert head.commands == []
    finally:
        await controller.close()



async def test_dock_slow_marker_inference_never_drives_from_expired_image(
    settings, monkeypatch,
):
    import asyncio
    import threading
    import time

    from desk_robot.controller import Job
    from desk_robot.dock_vision import DockCameraCalibration, DockPose

    settings.mode = "hardware"

    class CameraHead(DockFrameFixture):
        def __init__(self):
            self.commands = []

        async def status(self):
            return {
                "robot_id": "robot-01",
                "armed": True,
                "safety": {"required": True, "ready": True, "fault": "none"},
                "ranges": {"present_mask": 31, "valid_mask": 31,
                           "mm": [50, 50, 50, 50, 650],
                           "age_ms": [5, 5, 5, 5, 5]},
                "imu": {"valid": True, "age_ms": 10},
                "touch": {"active": False},
            }

        async def snapshot(self):
            return b"head-camera-jpeg-placeholder"

        async def command(self, line):
            self.commands.append(line)

    entered = threading.Event()

    def slow_detector(jpeg, camera, *, captured_at):
        entered.set()
        time.sleep(0.26)
        return DockPose(0, 0, 500, 0.5, captured_at)

    mock_dock_detector(monkeypatch, slow_detector)
    head = CameraHead()
    controller = Coordinator(settings, {"robot-01": head}, SimulationVision())
    camera = DockCameraCalibration(
        410, 410, 320, 240, 60, 1,
        mount_lateral_offset_mm=0, mount_yaw_deg=0,
    )
    try:
        task = asyncio.create_task(controller._dock_approach(
            Job("stale-tag", "robot-01", "dock_approach"),
            camera, 200, 1, 1,
        ))
        assert await asyncio.to_thread(entered.wait, 1)
        # The Mac event loop remains responsive while OpenCV-like work runs.
        await asyncio.wait_for(asyncio.sleep(0.01), timeout=0.08)
        assert not task.done()
        result = await asyncio.wait_for(task, timeout=2)
        assert result["phase"] == "hold"
        assert "stale" in result["reason"].lower()
        assert result["charging_authorized"] is False
        assert head.commands == []
    finally:
        await controller.close()



async def test_dock_marker_expires_while_waiting_for_second_body_status(
    settings, monkeypatch,
):
    import asyncio

    from desk_robot.controller import Job
    from desk_robot.dock_vision import DockCameraCalibration, DockPose

    settings.mode = "hardware"

    class SlowStatus(DockFrameFixture):
        def __init__(self):
            self.reads = 0
            self.commands = []

        async def status(self):
            self.reads += 1
            if self.reads == 2:
                # WROOM is healthy, but its response came after old image
                # geometry was already outside the 200 ms marker age policy.
                await asyncio.sleep(0.26)
            return {
                "robot_id": "robot-01",
                "armed": True,
                "safety": {"required": True, "ready": True, "fault": "none"},
                "ranges": {"present_mask": 31, "valid_mask": 31,
                           "mm": [50, 50, 50, 50, 700],
                           "age_ms": [5, 5, 5, 5, 5]},
                "imu": {"valid": True, "age_ms": 10},
                "touch": {"active": False},
            }

        async def snapshot(self):
            return b"marker-frame"

        async def command(self, command):
            self.commands.append(command)

    head = SlowStatus()
    controller = Coordinator(settings, {"robot-01": head}, SimulationVision())
    calibration = DockCameraCalibration(
        410, 410, 320, 240, 60, 1,
        mount_lateral_offset_mm=0, mount_yaw_deg=0,
    )
    mock_dock_detector(
        monkeypatch,
        lambda image, camera, *, captured_at: DockPose(
            0, 0, 500, 0.5, captured_at
        ),
    )
    try:
        result = await controller._dock_approach(
            Job("stale-after-status", "robot-01", "dock_approach"),
            calibration, 200, 1, 1,
        )
        assert head.reads == 2
        assert result["phase"] == "hold"
        assert "stale" in result["reason"].lower()
        assert not result["charging_authorized"]
        assert head.commands == []
    finally:
        await controller.close()


async def test_dock_approach_refuses_parallel_native_detector_ownership(settings, monkeypatch):
    """A diagnostic AprilTag worker and physical dock motion share one slot."""
    from desk_robot import dock_runtime
    from desk_robot.controller import Job
    from desk_robot.dock_vision import DockCameraCalibration

    settings.mode = "hardware"

    class HealthyHead(DockFrameFixture):
        def __init__(self):
            self.commands = []
            self.captures = 0

        async def status(self):
            return {
                "robot_id": "robot-01",
                "armed": True,
                "safety": {"required": True, "ready": True, "fault": "none"},
                "ranges": {"present_mask": 31, "valid_mask": 31,
                           "mm": [50, 50, 50, 50, 600],
                           "age_ms": [5, 5, 5, 5, 5]},
                "imu": {"valid": True, "age_ms": 10},
                "touch": {"active": False},
            }

        async def snapshot(self):
            self.captures += 1
            return b"real-head-fixture-not-decoded-when-busy"

        async def command(self, command):
            self.commands.append(command)

    head = HealthyHead()
    controller = Coordinator(settings, {"robot-01": head}, SimulationVision())
    camera = DockCameraCalibration(
        410, 410, 320, 240, 60, 1,
        mount_lateral_offset_mm=0, mount_yaw_deg=0,
    )
    monkeypatch.setattr(dock_runtime._DETECTOR_POOL, "_active", object())
    try:
        with pytest.raises(dock_runtime.DockDetectorBusy):
            await controller._dock_approach(
                Job("busy-detector", "robot-01", "dock_approach"),
                camera, 200, 1, 1,
            )
        assert head.captures == 1
        assert head.commands == []  # no speculative movement or charge
    finally:
        await controller.close()


async def test_dock_rejects_foreign_body_identity_after_camera_before_turn(
    settings, monkeypatch,
):
    """A replaced body response cannot authorize another robot's motors."""
    from desk_robot.controller import Job
    from desk_robot.dock_vision import DockCameraCalibration, DockPose

    settings.mode = "hardware"

    class SwappedBody(DockFrameFixture):
        def __init__(self):
            self.reads = 0
            self.commands = []

        async def status(self):
            self.reads += 1
            return {
                "robot_id": "robot-01" if self.reads == 1 else "robot-02",
                "armed": True,
                "safety": {"required": True, "ready": True, "fault": "none"},
                "ranges": {
                    "present_mask": 31, "valid_mask": 31,
                    "mm": [50, 50, 50, 50, 650],
                    "age_ms": [5] * 5,
                },
                "imu": {"valid": True, "age_ms": 10},
                "touch": {"active": False},
                "side_ranges": {
                    "present_mask": 7,
                    "valid_mask": 7,
                    "age_ms": [5] * 3,
                    "mm": [600] * 3,
                },
            }

        async def snapshot(self):
            return b"synthetic tag image"

        async def command(self, command):
            self.commands.append(command)

    head = SwappedBody()
    camera = DockCameraCalibration(
        fx=410, fy=410, cx=320, cy=240,
        tag_side_mm=60, marker_id=1,
        mount_lateral_offset_mm=0, mount_yaw_deg=0,
    )
    mock_dock_detector(
        monkeypatch,
        lambda jpeg, calibration, *, captured_at: DockPose(
            80, 0, 500, 0.5, captured_at,
        ),
    )
    coordinator = Coordinator(settings, {"robot-01": head}, SimulationVision())
    try:
        with pytest.raises(OperationError, match="body identity mismatch"):
            await coordinator._dock_approach(
                Job("dock-identity", "robot-01", "dock_approach"),
                camera, 200, 1, 1,
            )
        assert head.reads == 2
        assert head.commands == []
    finally:
        await coordinator.close()



async def test_unidentified_or_wrong_sensor_cannot_steer_real_dock(
    settings, monkeypatch,
):
    """A camera profile string cannot bypass live ESP32 sensor identity."""
    from desk_robot.controller import Job
    from desk_robot.dock_vision import DockCameraCalibration
    from desk_robot.simulator import SimulatedHead

    settings.mode = "hardware"
    legacy = SimulatedHead("robot-01")
    controller = Coordinator(settings, {"robot-01": legacy}, SimulationVision())

    # Replay raw WROOM status through the real Coordinator health checks.
    # Do not stub the entire physical safety admission boundary.
    body = {
        "robot_id": "robot-01", "armed": True,
        "safety": {"required": True, "ready": True, "fault": "none"},
        "ranges": {
            "present_mask": 31, "valid_mask": 31,
            "mm": [50, 50, 50, 50, 600], "age_ms": [5] * 5,
        },
        "imu": {"valid": True, "age_ms": 10},
        "touch": {"active": False},
    }
    legacy.replay_body_status({**body, "robot_id": "robot-02"})
    camera = DockCameraCalibration(
        410, 410, 320, 240, 60, 1,
        camera_sensor_pid="OV5640",
    )
    try:
        with pytest.raises(OperationError, match="body identity mismatch"):
            await controller._dock_approach(
                Job("foreign-body", "robot-01", "dock_approach"),
                camera, 200, 1, 1,
            )
        assert legacy.commands == []
        legacy.replay_body_status(body)
        # A compatibility snapshot is never an authenticated stream receipt.
        # Reject it before even consulting the calibration's sensor label.
        with pytest.raises(OperationError, match="authenticated live camera stream receipt"):
            await controller._dock_approach(
                Job("camera-legacy", "robot-01", "dock_approach"),
                camera, 200, 1, 1,
            )
        assert legacy.commands == []

        class AuthenticatedSensorHead(DockFrameFixture, SimulatedHead):
            pass

        head = AuthenticatedSensorHead("robot-01")
        head.replay_body_status(body)
        controller.heads["robot-01"] = head
        # With a valid immutable boot/frame receipt, missing or wrong live
        # PID must still be rejected before any motor command is possible.
        with pytest.raises(OperationError, match="live sensor identity unavailable"):
            await controller._dock_approach(
                Job("camera-missing-pid", "robot-01", "dock_approach"),
                camera, 200, 1, 1,
            )
        assert head.commands == []

        async def wrong_sensor(receipt):
            assert len(receipt) == 4
            return "OV3660"

        monkeypatch.setattr(head, "camera_identity", wrong_sensor, raising=False)
        with pytest.raises(OperationError, match="sensor PID differs"):
            await controller._dock_approach(
                Job("camera-wrong-pid", "robot-01", "dock_approach"),
                camera, 200, 1, 1,
            )
        assert head.commands == []
    finally:
        await controller.close()


async def test_dock_approach_rejects_expired_stream_receipt_before_detector_or_drive(
    settings, monkeypatch,
):
    import time

    from desk_robot.controller import Job
    from desk_robot.dock_vision import DockCameraCalibration

    settings.mode = "hardware"

    class StaleHead(DockFrameFixture):
        def __init__(self):
            self.commands = []

        async def status(self):
            return {
                "robot_id": "robot-01", "armed": True,
                "safety": {"required": True, "ready": True, "fault": "none"},
                "ranges": {"present_mask": 31, "valid_mask": 31,
                           "mm": [50, 50, 50, 50, 600],
                           "age_ms": [5, 5, 5, 5, 5]},
                "imu": {"valid": True, "age_ms": 10},
                "touch": {"active": False},
            }

        async def snapshot(self):
            raise AssertionError("Unexpected generic camera request")

        async def snapshot_for_dock(self):
            return b"synthetic image", time.monotonic() - 0.3, (1234, 1, 1), 1

        async def command(self, command):
            self.commands.append(command)

    def forbidden(*args, **kwargs):
        raise AssertionError("Stale dock frame entered native detector")

    mock_dock_detector(monkeypatch, forbidden)
    head = StaleHead()
    controller = Coordinator(settings, {"robot-01": head}, SimulationVision())
    camera = DockCameraCalibration(
        410, 410, 320, 240, 60, 1,
        mount_lateral_offset_mm=0, mount_yaw_deg=0,
    )
    try:
        with pytest.raises(OperationError, match="Stale or invalid dock camera receipt"):
            await controller._dock_approach(
                Job("expired-frame", "robot-01", "dock_approach"),
                camera, 200, 1, 1,
            )
        assert head.commands == []
    finally:
        await controller.close()


async def test_second_pet_cannot_use_first_pet_dock_intrinsics_to_move(
    settings, tmp_path,
):
    settings.mode = "hardware"
    settings.voice_vision_tools_enabled = True
    first, second = settings.robots
    first.device_id, second.device_id = "xiaozhi-01", "xiaozhi-02"
    for robot in (first, second):
        robot.motion_enabled = True
        robot.dock_motion_qualified = True
        robot.dock_turn_sign = 1
        robot.dock_forward_sign = 1
        robot.dock_beacon_id = 1 if robot.id == first.id else 2
    path = tmp_path / "only-pet-one.json"
    path.write_text(json.dumps({
        "measured": True, "robot_id": "robot-01",
        "head_device_id": "xiaozhi-01", "camera_sensor_pid": "OV5640",
        "fx": 410, "fy": 410, "cx": 320, "cy": 240,
        "tag_side_mm": 60, "marker_id": 1, "target_distance_mm": 200,
        "distortion_coeffs": [0.0, 0.0, 0.0, 0.0, 0.0],
        "image_width_px": 640, "image_height_px": 480,
        "mount_lateral_offset_mm": 6.0, "mount_yaw_deg": 1.0,
    }))
    first.dock_calibration = second.dock_calibration = path
    coordinator, head = make(settings)
    other_head = coordinator.heads[second.id]
    try:
        with pytest.raises(OperationError, match="Dock calibration required:.*robot/head identity"):
            coordinator.dock(second.id)
        assert not coordinator.jobs
        assert not head.commands and not other_head.commands
        # A correctly bound record still requires a separate operator permit.
        with pytest.raises(OperationError, match="permit"):
            coordinator.dock(first.id)
        assert not coordinator.jobs
        assert not head.commands and not other_head.commands
    finally:
        await coordinator.close()


@pytest.mark.parametrize(
    "outcome", ["standoff", "contact", "beacon_loss", "ir_replay", "timeout",
                "marker_loss", "terminal_marker_loss", "pulse_budget", "receipt_denial",
                "queued_camera_expired", "queued_stream_replaced"],
)
async def test_public_dock_replay_stops_without_unqualified_recovery(
    settings, tmp_path, monkeypatch, outcome,
):
    """Host replay: qualified approach is distinct from contact and charge proof."""
    import asyncio
    from types import SimpleNamespace

    from desk_robot.dock_evidence import observe_dock_evidence
    from desk_robot.dock_ir import dock_beacon_code
    from desk_robot.dock_vision import DockPose

    marker_loss = outcome in {"marker_loss", "terminal_marker_loss"}
    settings.mode = "hardware"
    settings.voice_vision_tools_enabled = True
    settings.max_job_seconds = 2 if outcome == "timeout" else 20
    robot = settings.robots[0]
    robot.motion_enabled = True
    robot.motor_backend = "dc_pwm_guarded"
    robot.dock_motion_qualified = True
    robot.dock_turn_sign = robot.dock_forward_sign = 1
    robot.dock_beacon_id = 1
    robot.device_id = "xiaozhi-01"
    robot.dock_calibration = tmp_path / "replay-dock.json"
    robot.dock_calibration.write_text(json.dumps({
        "measured": True, "robot_id": robot.id, "head_device_id": robot.device_id,
        "camera_sensor_pid": "OV5640", "fx": 410, "fy": 410,
        "cx": 320, "cy": 240, "tag_side_mm": 60, "marker_id": 1,
        "target_distance_mm": 200, "distortion_coeffs": [0.0] * 5,
        "image_width_px": 640, "image_height_px": 480,
        "mount_lateral_offset_mm": 0.0, "mount_yaw_deg": 0.0,
    }))

    clock = time
    clock_now = [time.monotonic()]
    if outcome in {"queued_camera_expired", "queued_stream_replaced"}:
        # Advance only the dock consumers' clock, not asyncio's deadlines.
        # Expiry: camera age 210 ms, IR age 110 ms. Reconnect: no age advance.
        clock = SimpleNamespace(monotonic=lambda: clock_now[0], time=time.time)
        monkeypatch.setattr("desk_robot.controller.time", clock)
        monkeypatch.setattr("desk_robot.dock_runtime.time", clock)

    class ReplayHead:
        supports_dispatch_check = outcome in {"queued_camera_expired", "queued_stream_replaced"}

        def __init__(self):
            self.armed = False
            self.contacted = False
            self.commands = []
            self.frames = self.ir_reads = self.aux_reads = 0
            self.last_verified = None
            self.stream_generation = 1
            self.snapshot_cancelled = asyncio.Event()

        async def status(self):
            return {
                "robot_id": robot.id, "backend": robot.motor_backend,
                "armed": self.armed,
                "safety": {"required": True, "ready": True, "fault": "none"},
                "ranges": {"present_mask": 31, "valid_mask": 31,
                           "mm": [50, 50, 50, 50, 700], "age_ms": [5] * 5},
                "side_ranges": {"present_mask": 7, "valid_mask": 7,
                                "mm": [600] * 3, "age_ms": [5] * 3},
                "imu": {"family": 4, "valid": True, "age_ms": 5,
                        "acc": [0, 0, 16384], "gyro": [0] * 3},
                "touch": {"active": False},
            }

        async def snapshot(self):
            raise AssertionError("Dock used an unbound camera snapshot")

        async def snapshot_for_dock(self):
            self.frames += 1
            if outcome == "timeout" and self.frames == 3:
                try:
                    await asyncio.Event().wait()
                finally:
                    self.snapshot_cancelled.set()
            return b"synthetic marker", clock.monotonic(), (1234, self.frames, 1), 1

        async def camera_identity(self, receipt):
            await self.dock_receipt_current(receipt)
            if outcome == "queued_camera_expired":
                clock_now[0] += 0.10
            return "OV5640"

        async def dock_receipt_current(self, receipt):
            assert receipt[2:] == ((1234, self.frames, 1), 1)
            if outcome == "receipt_denial" and self.ir_reads:
                return False  # Negative adapter verdict, not an exception.
            self.last_verified = (self.frames, self.ir_reads)

        def dock_receipt_current_now(self, receipt):
            if receipt[3] != self.stream_generation:
                raise ValueError("Selected stream replaced")

        async def ir_status(self):
            self.ir_reads += 1
            matching = not (outcome == "beacon_loss" and self.ir_reads == 2)
            seq = 1 if outcome == "ir_replay" and self.ir_reads == 2 else self.ir_reads
            return {
                "robot_id": robot.id, "left_valid": matching,
                "right_valid": matching, "match": matching,
                "left_seq": seq, "right_seq": seq,
                "left_age_ms": 5, "right_age_ms": 5,
                "code": dock_beacon_code(1) if matching else 0,
                "motor_authorized": False, "charging_authorized": False,
                "physical_qualified": False,
            }

        async def command(self, command, *, dispatch_check=None):
            if dispatch_check is not None:
                # Model state changes while waiting for HttpHead's command locks.
                if outcome == "queued_stream_replaced":
                    self.stream_generation += 1
                else:
                    clock_now[0] += 0.11
                dispatch_check()
            self.commands.append(command)
            if command == "arm":
                self.armed = True
            elif command == "halt":
                self.armed = False
            elif command.startswith("drive "):
                assert self.armed
                if command == "drive 10 10 100":
                    # A new explicit operator permit, not automatic dock recovery.
                    assert marker_loss
                    return {"ok": True}
                assert self.ir_reads == sum(
                    c.startswith("drive ") for c in self.commands
                )
                assert self.last_verified == (self.frames, self.ir_reads)
                assert command == "drive 20 20 100"
                if outcome == "contact" and self.ir_reads == 2:
                    # Inject the local WROOM contact interlock verdict, not a
                    # simulated proof that the wheels actually reached a dock.
                    self.contacted = True
                    self.armed = False
            return {"ok": True}

        async def aux_status(self):
            self.aux_reads += 1
            return {
                "robot_id": robot.id,
                "pulse": {"present": False, "valid": False, "part_id": 0,
                          "red": 0, "ir": 0, "age_ms": 0, "bpm": None,
                          "medical": False},
                "angles": {"raw": [0] * 3, "present_mask": 0,
                           "valid_mask": 0, "magnet": [0] * 3},
                "force": {"adc": [0, 0], "jaw_seq": 0, "valid": False,
                          "calibrated": False, "boot_id": 17},
                "climate": {"temp_centi": 0, "rh_centi": 0, "valid": False},
                "power": {"cell_mv": 0, "soc_centi": 0, "bus_mv": 0,
                          "shunt_uv": 0, "fuel_valid": False,
                          "monitor_valid": False, "current_calibrated": False},
                "proximity": {"raw": 0, "valid": False, "gesture": 0,
                              "gesture_events": 0, "physically_qualified": False,
                              "boot_id": 17},
                "dock": {"present": True, "valid": True,
                         "left_seated": self.contacted,
                         "right_seated": self.contacted,
                         "input_good": self.contacted,
                         "charge_indicated": self.contacted,
                         "charging_verified": False,
                         "seq": self.aux_reads, "age_ms": 5},
            }

    head = ReplayHead()
    # 300 mm tag depth is exactly 100 mm before the calibrated 200 mm standoff.
    # The generous synthetic front range does not qualify physical seat approach.
    initial_depth = 300 if outcome == "terminal_marker_loss" else 500
    poses = iter(((0, initial_depth), (0, 450), (0, 150)))

    def detect(_jpeg, _camera, *, captured_at):
        if marker_loss and head.frames == 2:
            return None
        x, z = (0, 500) if outcome == "pulse_budget" else next(poses)
        return DockPose(x, 0, z, 0.5, captured_at)

    mock_dock_detector(monkeypatch, detect)
    coordinator = Coordinator(settings, {robot.id: head}, SimulationVision())
    try:
        await coordinator.operator_arm(robot.id)
        assert head.commands == []  # A permit alone does not arm the body.
        job = coordinator.dock(robot.id)
        await asyncio.wait_for(coordinator.tasks[job.id], timeout=10)
        commands = [c for c in head.commands if c != "keepalive"]
        expected = ["arm", "drive 20 20 100", "stop"]
        if outcome in {"receipt_denial", "queued_camera_expired", "queued_stream_replaced"}:
            expected = ["arm"]
            assert head.frames == head.ir_reads == 1
        elif outcome == "pulse_budget":
            expected = ["arm"] + ["drive 20 20 100", "stop"] * 16
            assert head.frames == head.ir_reads == 16
        elif marker_loss:
            assert head.frames == 2 and head.ir_reads == 1
        else:
            if outcome not in {"beacon_loss", "ir_replay"}:
                expected += ["drive 20 20 100", "stop"]
            assert head.ir_reads == 2
        assert commands == expected + ["halt"]
        assert not head.armed
        if outcome in {
            "standoff", "beacon_loss", "ir_replay", "marker_loss",
            "terminal_marker_loss", "pulse_budget",
            "queued_camera_expired",
        }:
            assert job.state == "succeeded"
            assert job.result["phase"] == "hold"
            assert not job.result["charging_authorized"]
            assert not job.result["physical_acceptance_pass"]
            reason = {
                "standoff": "contacts unverified",
                "beacon_loss": "not jointly visible",
                "ir_replay": "Assigned dock IR replay or stale conversion",
                "marker_loss": "IR-only/dead-reckoning fallback unqualified",
                "terminal_marker_loss": "IR-only/dead-reckoning fallback unqualified",
                "pulse_budget": "Maximum guarded approach pulses reached",
                "queued_camera_expired": "Dock camera receipt expired before guarded drive",
            }[outcome]
            assert reason in job.result["reason"]
        else:
            assert job.state == "failed"
            assert job.result is None
            if outcome == "contact":
                assert "body disarmed" in job.error
            elif outcome == "receipt_denial":
                assert "Dock JPEG source changed before drive" in job.error
            elif outcome == "queued_stream_replaced":
                assert "Dock JPEG source changed at guarded dispatch" in job.error
            else:
                assert job.error == "TimeoutError"
                await asyncio.wait_for(head.snapshot_cancelled.wait(), timeout=1)
        # The diagnostic is the existing read-only pin observer, after HALT.
        # Neither seat+PGOOD+CHG nor the approach result verifies charging.
        if outcome == "contact":
            report = await observe_dock_evidence(head, robot.id, gap=0.25)
            assert report["state"] == "charger_reports_active"
            assert report["stable_three_samples"]
            assert not report["physical_contact_verified"]
            assert not report["charging_verified"]
            assert not report["charging_authorized"]
            assert not report["motor_authorized"]
            assert head.aux_reads == 3
            assert [c for c in head.commands if c != "keepalive"] == commands
        # No automatic reverse, retry, or new arm after any terminal outcome.
        with pytest.raises(OperationError, match="permit"):
            coordinator.dock(robot.id)
        with pytest.raises(OperationError, match="permit"):
            coordinator.manual(robot.id, "drive 10 10 100")
        assert [c for c in head.commands if c != "keepalive"] == commands
        if marker_loss:
            # Recovery belongs to the operator only after the terminal HALT.
            # A new permit can admit manual movement; it does not restart dock.
            await coordinator.operator_arm(robot.id)
            manual = coordinator.manual(robot.id, "drive 10 10 100")
            await asyncio.wait_for(coordinator.tasks[manual.id], timeout=6)
            assert manual.state == "succeeded"
            assert not head.armed
            assert [c for c in head.commands if c != "keepalive"] == (
                commands + ["arm", "drive 10 10 100", "halt"]
            )
            assert head.frames == 2 and head.ir_reads == 1
    finally:
        await coordinator.close()


@pytest.mark.parametrize("initial_low,deferred_fault", [
    (True, None), (False, None), (False, "recovered"), (False, "stale"),
    (False, "expired"), (False, "consent_replaced"),
])
async def test_autonomous_low_battery_dock_and_charge_inhibition_lifecycle(
    settings, tmp_path, monkeypatch, initial_low, deferred_fault,
):
    """Qualified low-battery auto-dock covers initial/crossing low, voice deferral, and dock inhibition."""
    import asyncio

    from desk_robot.dock_ir import dock_beacon_code
    from desk_robot.dock_vision import DockPose
    from desk_robot.runtime import Runtime

    settings.memory_dir = tmp_path / "memory"
    settings.trials_file = tmp_path / "trials.jsonl"
    robot = settings.robots[0]
    robot.device_id = "xiaozhi-01"
    robot.motor_backend = "stepper_28byj48"
    robot.motion_enabled = True
    robot.exploration_qualified = True
    robot.dock_motion_qualified = True
    robot.dock_beacon_id = 1
    robot.dock_turn_sign = 1
    robot.dock_forward_sign = 1
    robot.battery_low_percent = 20

    calib = tmp_path / "dock_cal.json"
    calib.write_text(json.dumps({
        "measured": True,
        "robot_id": robot.id,
        "head_device_id": "xiaozhi-01",
        "camera_sensor_pid": "OV5640",
        "fx": 410,
        "fy": 410,
        "cx": 320,
        "cy": 240,
        "distortion_coeffs": [0.1, -0.05, 0.0, 0.0, 0.0],
        "image_width_px": 640,
        "image_height_px": 480,
        "mount_lateral_offset_mm": 0.0,
        "mount_yaw_deg": 0.0,
        "tag_side_mm": 60,
        "marker_id": 1,
        "target_distance_mm": 200,
    }))
    robot.dock_calibration = calib

    class LowBatteryDockHead(DockFrameFixture):
        def __init__(self):
            self.commands = []
            self.armed = False
            self.frames = 0
            self.ir_reads = 0
            self.sensor_pid = "OV5640"
            self.fuel_soc = 1800
            self.fuel_age = 10

        async def status(self):
            return {
                "robot_id": robot.id,
                "backend": "stepper_28byj48",
                "armed": self.armed,
                "watchdog_ms": 500,
                "safety": {"required": True, "ready": True, "fault": "none"},
                "ranges": {
                    "present_mask": 31,
                    "valid_mask": 31,
                    "mm": [50, 50, 50, 50, 600],
                    "age_ms": [5, 5, 5, 5, 5],
                },
                "imu": {
                    "family": 1,
                    "valid": True,
                    "age_ms": 10,
                    "acc": [0, 0, 16384],
                    "gyro": [0, 0, 0],
                },
                "touch": {"active": False},
                "side_ranges": {
                    "present_mask": 7,
                    "valid_mask": 7,
                    "age_ms": [10, 10, 10],
                    "mm": [600, 600, 600],
                },
                "power": {
                    "cell_mv": 3650,
                    "soc_centi": self.fuel_soc,
                    "fuel_valid": True,
                    "fuel_seq": 50,
                    "fuel_age_ms": self.fuel_age,
                },
            }

        async def snapshot(self):
            raise AssertionError("Autonomous dock used stale snapshot")

        async def snapshot_for_dock(self):
            self.frames += 1
            return (b"\xff\xd8" + b"\x00" * 20 + b"\xff\xd9", time.monotonic(), (1234, 1, 1), 1)

        async def camera_identity(self, _obs=None):
            return self.sensor_pid

        async def ir_status(self):
            self.ir_reads += 1
            return {
                "robot_id": robot.id,
                "left_valid": True,
                "right_valid": True,
                "match": True,
                "left_seq": self.ir_reads,
                "right_seq": self.ir_reads,
                "left_age_ms": 5,
                "right_age_ms": 5,
                "code": dock_beacon_code(1),
                "motor_authorized": False,
                "charging_authorized": False,
                "physical_qualified": False,
            }

        async def command(self, cmd):
            self.commands.append(cmd)
            if cmd == "arm":
                self.armed = True
            elif cmd == "halt":
                self.armed = False

    def aux_packet(
        soc: int,
        fuel_seq: int,
        *,
        dock_seq: int | None = None,
        seated: bool = False,
    ) -> dict:
        pkt = {
            "robot_id": robot.id,
            "pulse": {
                "present": False,
                "valid": False,
                "part_id": 0,
                "red": 0,
                "ir": 0,
                "age_ms": 0,
                "seq": 1,
                "bpm": None,
                "medical": False,
            },
            "angles": {"raw": [0, 0, 0], "present_mask": 0, "valid_mask": 0, "magnet": [0, 0, 0]},
            "force": {"adc": [100, 100], "jaw_seq": 1, "valid": False, "calibrated": False, "boot_id": 7},
            "climate": {"temp_centi": 2200, "rh_centi": 5000, "valid": False},
            "power": {
                "cell_mv": 3650,
                "soc_centi": soc,
                "bus_mv": 5100,
                "shunt_uv": 5,
                "fuel_valid": True,
                "fuel_seq": fuel_seq,
                "fuel_age_ms": 10,
                "monitor_valid": True,
                "current_calibrated": False,
            },
            "proximity": {
                "raw": 0,
                "valid": False,
                "gesture": 0,
                "gesture_events": 0,
                "physically_qualified": False,
                "boot_id": 7,
            },
        }
        if dock_seq is not None:
            pkt["dock"] = {
                "present": True,
                "valid": True,
                "left_seated": seated,
                "right_seated": seated,
                "input_good": seated,
                "charge_indicated": seated,
                "charging_verified": False,
                "seq": dock_seq,
                "age_ms": 5,
            }
        return pkt

    poses = iter(((0, 450), (0, 150)))
    mock_dock_detector(
        monkeypatch,
        lambda _jpeg, _cal, *, captured_at: DockPose(0, 0, next(poses)[1], 0.5, captured_at),
    )

    head = LowBatteryDockHead()
    rt = Runtime(settings)
    rt.coordinator.heads[robot.id] = head
    rt.pet.heads[robot.id] = head
    rt.conversation.speaker.interrupt = lambda _robot: asyncio.sleep(0)
    settings.mode = "hardware"
    settings.voice_vision_tools_enabled = True
    rt.pet.set_voice_monitor_ready(True)
    rt.coordinator.set_voice_state(monitor_enforced=True, monitor_ready=True)
    state = rt.pet.states[robot.id]
    state.enabled = True
    state.generation = 1
    try:
        # Fail-closed default: autonomous_low_battery_dock_enabled=False performs no motion.
        assert robot.autonomous_low_battery_dock_enabled is False
        baseline_samples = (1800, 1800, 1800, 1800) if initial_low else (5000, 1800, 1800, 1800)
        for seq, soc in enumerate(baseline_samples, start=1):
            await rt.pet._observe_aux(robot.id, 1, aux_packet(soc, seq))
        assert rt.coordinator.jobs == {}
        assert head.commands == []

        # Enable qualified autonomous low-battery dock and reset to test fresh episode.
        robot.autonomous_low_battery_dock_enabled = True
        state.last_battery_low = None
        state.last_fuel_seq = None
        state.low_fuel_streak = 0
        state.recovered_fuel_streak = 0
        state.low_battery_memory_recorded = False
        state.low_battery_dock_episode_attempted = False

        # For crossing_low, defer behind live human voice first, then dispatch on speech_end.
        if not initial_low:
            rt.coordinator.set_voice_state(active_robots=frozenset({robot.id}), monitor_ready=True)
        next_samples = (1800, 1800, 1800, 1800) if initial_low else (5000, 1800, 1800, 1800)
        for seq, soc in enumerate(next_samples, start=10):
            await rt.pet._observe_aux(robot.id, 1, aux_packet(soc, seq))

        if not initial_low:
            assert rt.coordinator.jobs == {}
            assert head.commands == []
            if deferred_fault == "recovered":
                head.fuel_soc = 3500
            elif deferred_fault == "stale":
                head.fuel_age = 500
            elif deferred_fault == "expired":
                pending = rt.coordinator._deferred_autonomous_dock
                initial, _, grant = pending[robot.id]
                pending[robot.id] = (initial, time.monotonic() - 1, grant)
            elif deferred_fault == "consent_replaced":
                settings.voice_vision_tools_enabled = False
                settings.voice_vision_tools_enabled = True
            rt.coordinator.set_voice_state(active_robots=frozenset(), monitor_ready=True)
            dispatched = await rt.coordinator.dispatch_next_deferred()
            if deferred_fault:
                assert dispatched is None
                assert rt.coordinator.jobs == {}
                assert head.commands == []
                assert robot.id not in rt.coordinator.permits
                return
            assert dispatched is not None and dispatched.kind == "dock_approach"

        assert len(rt.coordinator.jobs) == 1
        dock_job = next(iter(rt.coordinator.jobs.values()))
        await asyncio.wait_for(rt.coordinator.tasks[dock_job.id], timeout=6)
        assert dock_job.state == "succeeded"
        assert dock_job.result["phase"] == "hold"
        assert dock_job.result["charging_authorized"] is False
        assert any(cmd.startswith("drive 20 20") for cmd in head.commands)
        assert head.armed is False

        # A fresh pet session (including a Mac restart) loses the volatile flags.
        # The already consumed autonomous attempt must nevertheless remain denied.
        state.last_battery_low = None
        state.last_fuel_seq = None
        state.low_fuel_streak = state.recovered_fuel_streak = 0
        state.low_battery_dock_episode_attempted = False
        for seq in range(14, 18):
            await rt.pet._observe_aux(robot.id, 1, aux_packet(1800, seq))
        assert len(rt.coordinator.jobs) == 1

        # Additional sustained low samples within same episode must not re-dock.
        await rt.pet._observe_aux(robot.id, 1, aux_packet(1800, 20))
        await rt.pet._observe_aux(robot.id, 1, aux_packet(1800, 21))
        assert len(rt.coordinator.jobs) == 1

        # Seated/charger-indicated dock flags inhibit exploration/pickup without proving charge.
        await rt.pet._observe_aux(robot.id, 1, aux_packet(1800, 22, dock_seq=1, seated=True))
        pet_status = rt.pet.status(robot.id)
        assert pet_status["dock_seated"] is True
        assert pet_status["dock_input_good"] is True
        assert pet_status["dock_charge_indicated"] is True
        assert pet_status["dock_motion_inhibited"] is True
        assert pet_status["charging_verified"] is False
        assert rt.coordinator.dock_inhibited(robot.id) is True

        with pytest.raises(OperationError, match="seated or powered on dock"):
            rt.coordinator.explore(robot.id)

        # Recovering and dropping low again while still seated on dock stays inhibited.
        for seq, soc in ((23, 3500), (24, 3500), (25, 1800), (26, 1800), (27, 1800)):
            await rt.pet._observe_aux(robot.id, 1, aux_packet(soc, seq, dock_seq=seq - 20, seated=True))
        assert len(rt.coordinator.jobs) == 1

        # Losing optional telemetry and receiving an old all-open packet
        # cannot release the Mac motion interlock.
        await rt.pet._observe_aux(robot.id, 1, aux_packet(1800, 28))
        assert rt.pet.status(robot.id)["dock_seated"] is None
        assert rt.coordinator.dock_inhibited(robot.id)
        await rt.pet._observe_aux(robot.id, 1, aux_packet(1800, 29, dock_seq=7))
        assert rt.coordinator.dock_inhibited(robot.id)
        for seq in (8, 9, 10):
            await rt.pet._observe_aux(robot.id, 1, aux_packet(1800, seq + 22, dock_seq=seq))
            assert rt.coordinator.dock_inhibited(robot.id) is (seq < 10)
        assert not rt.pet.status(robot.id)["charging_verified"]
        assert len(rt.coordinator.jobs) == 1
    finally:
        state.enabled = False
        await rt.close()


async def test_seated_robot_cannot_start_dock_approach_or_consume_permit(settings):
    from desk_robot.controller import Job

    controller, head = make(settings)
    controller.permits["robot-01"] = time.monotonic() + 10
    controller.set_dock_charge_inhibition("robot-01", True)
    try:
        with pytest.raises(OperationError, match="seated or powered"):
            controller.dock("robot-01")
        with pytest.raises(OperationError, match="seated or powered"):
            await controller._dock_approach(
                Job("seated", "robot-01", "dock_approach"), None, 200, 1, 1,
            )
        assert controller.permits["robot-01"] > time.monotonic()
        assert not controller.jobs
        assert head.commands == []
    finally:
        await controller.close()


async def test_contact_inhibition_cancels_only_own_active_dock_approach(settings):
    import asyncio

    from desk_robot.controller import Job

    controller, _head = make(settings)
    job = Job("approach", "robot-01", "dock_approach")
    task = asyncio.create_task(asyncio.Event().wait())
    controller.jobs[job.id] = job
    controller.tasks[job.id] = task
    controller._fleet_motion_owner = job.id
    try:
        controller.set_dock_charge_inhibition("robot-02", True)
        assert not task.cancelling()
        controller.set_dock_charge_inhibition("robot-01", True)
        assert task.cancelling()
        assert job.error == "Stopped: robot seated or powered on dock"
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        controller.jobs.pop(job.id)
        controller.tasks.pop(job.id)
        controller._fleet_motion_owner = None
        await controller.close()


def test_autonomous_dock_retry_budget_survives_reopen_and_boot_change(tmp_path):
    from desk_robot.memory import MemoryStore

    def reopen():
        return MemoryStore(tmp_path, ["robot-01", "robot-02"])

    first = reopen()
    assert first.dock_retry_transition("robot-01", 17, 100, recovered=False)
    assert first.dock_retry_transition("robot-02", 17, 100, recovered=False)
    second = reopen()
    assert not second.dock_retry_transition("robot-01", 17, 101, recovered=False)
    assert not second.dock_retry_transition("robot-01", 18, 1, recovered=False)
    assert not second.dock_retry_transition(
        "robot-01", 17, 103, recovered=True, previous_fuel_seq=102,
    )
    assert not second.dock_retry_transition(
        "robot-01", 18, 2, recovered=True, previous_fuel_seq=1,
    )
    assert second.dock_retry_transition(
        "robot-01", 18, 3, recovered=True, previous_fuel_seq=2,
    )
    third = reopen()
    assert not third.dock_retry_transition("robot-01", 18, 3, recovered=False)
    assert third.dock_retry_transition("robot-01", 18, 4, recovered=False)
    assert not third.dock_retry_transition("robot-02", 17, 101, recovered=False)


def test_autonomous_dock_retry_budget_reserves_only_once_concurrently(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    from desk_robot.memory import MemoryStore

    store = MemoryStore(tmp_path, ["robot-01"])

    def reserve(seq):
        return store.dock_retry_transition("robot-01", 1, seq, recovered=False)

    with ThreadPoolExecutor(max_workers=5) as pool:
        assert sum(pool.map(reserve, range(1, 6))) == 1


@pytest.mark.parametrize("boot,seq,previous", [
    (True, 2, 1), (1, 2, 2), (1, 2, 3), (1, 2, None), (1, 2, True),
])
def test_autonomous_dock_retry_rejects_malformed_recovery(tmp_path, boot, seq, previous):
    from desk_robot.memory import MemoryStore

    store = MemoryStore(tmp_path, ["robot-01"])
    assert store.dock_retry_transition("robot-01", 1, 1, recovered=False)
    with pytest.raises(ValueError):
        store.dock_retry_transition(
            "robot-01", boot, seq, recovered=True, previous_fuel_seq=previous,
        )
    assert not store.dock_retry_transition("robot-01", 1, 2, recovered=False)


@pytest.mark.parametrize("changes,elapsed", [
    ({"fuel_valid": False}, 0), ({"fuel_seq": 0}, 0), ({"fuel_seq": True}, 0),
    ({"fuel_age_ms": 499}, 1), ({"fuel_age_ms": 10**1000}, 0.5),
    ({"soc_centi": 2001}, 0), ({"soc_centi": True}, 0), ({}, float("nan")),
])
def test_auto_dock_fuel_preflight_rejects_stale_or_recovered_evidence(changes, elapsed):
    from desk_robot.controller import _require_fresh_auto_dock_fuel

    power = {"fuel_valid": True, "fuel_seq": 7, "fuel_age_ms": 10, "soc_centi": 1800}
    _require_fresh_auto_dock_fuel(power, max_soc_centi=2000, elapsed_ms=0)
    with pytest.raises(OperationError, match="fresh low battery"):
        _require_fresh_auto_dock_fuel(
            power | changes, max_soc_centi=2000, elapsed_ms=elapsed,
        )

async def test_dock_reverse_polarity_refused_before_permit_or_head_io(settings):
    settings.mode = "hardware"
    robot = settings.robots[0]
    robot.motion_enabled = True
    robot.dock_motion_qualified = True
    robot.dock_turn_sign = 1
    robot.dock_forward_sign = -1
    controller, head = make(settings)
    try:
        controller.permits[robot.id] = time.monotonic() + 10
        permit = controller.permits[robot.id]
        with pytest.raises(OperationError, match="reverse direction clearance"):
            controller.dock(robot.id)
        assert controller.permits[robot.id] == permit
        assert not controller.jobs
        assert head.commands == []
    finally:
        await controller.close()


@pytest.mark.parametrize("forward_sign", [-1, 0])
async def test_dock_internal_reverse_rejected_before_head_io(settings, forward_sign):
    from desk_robot.controller import Job

    settings.mode = "hardware"
    controller, head = make(settings)
    try:
        with pytest.raises(OperationError, match="reverse direction clearance"):
            await controller._dock_approach(
                Job("dock-reverse", "robot-01", "dock_approach"),
                None, 200, 1, forward_sign,
            )
        assert head.commands == []
    finally:
        await controller.close()

