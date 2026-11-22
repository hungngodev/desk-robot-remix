"""Dock motion remains operator permitted and disabled by default."""
import json
import time

import pytest
from desk_robot.controller import Coordinator, OperationError
from desk_robot.simulator import SimulatedHead, SimulationVision


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
        "measured": True, "fx": 410, "fy": 410, "cx": 320, "cy": 240,
        "tag_side_mm": 60, "marker_id": 1, "target_distance_mm": 200,
    }))
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
    monkeypatch.setattr(
        "desk_robot.dock_runtime.detect_apriltag",
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
    monkeypatch.setattr(
        "desk_robot.dock_runtime.detect_apriltag",
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
        "measured": True, "fx": 410, "fy": 410, "cx": 320, "cy": 240,
        "tag_side_mm": 60, "marker_id": 1, "target_distance_mm": 200,
    }))
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
        "measured": True, "fx": 410, "fy": 410, "cx": 320, "cy": 240,
        "tag_side_mm": 60, "marker_id": 1, "target_distance_mm": 200,
        "distortion_coeffs": [0.18, -0.07, 0.003, -0.002, 0.01],
    }))
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
        "measured": True, "fx": 410, "fy": 410, "cx": 320, "cy": 240,
        "tag_side_mm": 60, "marker_id": 1, "target_distance_mm": 200,
        "distortion_coeffs": [0.0, 0.0, 0.0, 0.0, 0.0],
        "image_width_px": 640, "image_height_px": 480,
    }))
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


@pytest.mark.parametrize(("lateral", "yaw", "expected_drive"), [
    (40, 0, "drive 20 -20 100"),
    (-40, 0, "drive -20 20 100"),
    (0, 5, "drive 20 -20 100"),
    (0, -5, "drive -20 20 100"),
])
async def test_dock_turns_by_chassis_not_lens_axis(
    settings, monkeypatch, lateral, yaw, expected_drive,
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
    monkeypatch.setattr(
        "desk_robot.dock_runtime.detect_apriltag",
        lambda jpeg, calib, *, captured_at: DockPose(
            0, 0, next(z_values), 0.2, captured_at,
        ),
    )
    try:
        result = await coordinator._dock_approach(
            Job("mount-unit", "robot-01", "dock_approach"),
            camera, 200, 1, 1,
        )
        assert result["phase"] == "hold"
        assert not result["charging_authorized"]
        assert head.commands == [expected_drive, "stop"]
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
        "measured": True, "fx": 410, "fy": 410, "cx": 320, "cy": 240,
        "tag_side_mm": 60, "marker_id": 1, "target_distance_mm": 200,
        "distortion_coeffs": [0.0, 0.0, 0.0, 0.0, 0.0],
        "image_width_px": 640, "image_height_px": 480,
        "mount_lateral_offset_mm": 0.0, "mount_yaw_deg": 0.0,
        "camera_sensor_pid": "OV5640",
    }))
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
    monkeypatch.setattr(
        "desk_robot.dock_runtime.detect_apriltag",
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
    monkeypatch.setattr(
        "desk_robot.dock_runtime.detect_apriltag",
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

    monkeypatch.setattr("desk_robot.dock_runtime.detect_apriltag", slow_detector)
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
    monkeypatch.setattr(
        "desk_robot.dock_runtime.detect_apriltag",
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


async def test_dock_approach_refuses_parallel_native_detector_ownership(settings):
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
    assert dock_runtime._DETECTOR_SLOT.acquire(blocking=False)
    try:
        with pytest.raises(dock_runtime.DockDetectorBusy):
            await controller._dock_approach(
                Job("busy-detector", "robot-01", "dock_approach"),
                camera, 200, 1, 1,
            )
        assert head.captures == 1
        assert head.commands == []  # no speculative movement or charge
    finally:
        dock_runtime._DETECTOR_SLOT.release()
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
    monkeypatch.setattr(
        "desk_robot.dock_runtime.detect_apriltag",
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

    async def healthy(*args, **kwargs):
        return None

    monkeypatch.setattr(controller, "_assert_armed_health", healthy)
    camera = DockCameraCalibration(
        410, 410, 320, 240, 60, 1,
        camera_sensor_pid="OV5640",
    )
    try:
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

    monkeypatch.setattr("desk_robot.dock_runtime.detect_apriltag", forbidden)
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
