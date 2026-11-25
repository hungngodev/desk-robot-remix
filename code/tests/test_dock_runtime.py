"""Dock observation must never gain motor/charging rights from JPEG geometry."""
import json
from types import SimpleNamespace

import pytest
from desk_robot import dock_runtime
from desk_robot.dock_vision import DockPose
from dock_detector_fixture import mock_dock_detector


class Head:
    def __init__(self):
        self.captures = 0
        self.commands = []
        self.sensor_pid = "OV5640"
        self.identity_checks = 0

    async def camera_identity(self):
        self.identity_checks += 1
        return self.sensor_pid

    async def snapshot(self):
        self.captures += 1
        return b"\xff\xd8\xff\xd9"

    async def command(self, command):
        self.commands.append(command)


async def test_absent_calibration_holds_without_camera_or_motors():
    head = Head()
    result = await dock_runtime.observe_actual_dock(
        head, SimpleNamespace(id="robot-01", dock_calibration=None)
    )
    assert result["phase"] == "hold"
    assert result["source"] == "not_calibrated"
    assert result["pose"] is None
    assert result["physical_acceptance_pass"] is False
    assert not result["motor_authorized"] and not result["charging_authorized"]
    assert not head.captures and not head.commands


@pytest.mark.parametrize("payload", [b"\xff\xfe", b"\xef\xbb\xbf{}"])
async def test_non_utf8_dock_calibration_fails_closed(tmp_path, payload):
    path = tmp_path / "dock.json"
    path.write_bytes(payload)
    head = Head()
    result = await dock_runtime.observe_actual_dock(
        head, SimpleNamespace(id="robot-01", dock_calibration=path)
    )
    assert result["phase"] == "hold"
    assert result["source"] == "not_calibrated"
    assert not result["motor_authorized"] and not result["charging_authorized"]
    assert result["physical_acceptance_pass"] is False
    assert not head.captures and not head.commands


def test_measured_distortion_survives_json_loader_and_invalid_values_fail_closed(tmp_path):
    path = tmp_path / "dock.json"
    payload = {
        "measured": True, "robot_id": "robot-01", "head_device_id": "xiaozhi-01", "fx": 410, "fy": 408, "cx": 320, "cy": 240,
        "tag_side_mm": 60, "marker_id": 12, "target_distance_mm": 120,
        "distortion_coeffs": [0.18, -0.07, 0.003, -0.002, 0.01],
        "image_width_px": 640, "image_height_px": 480,
        "mount_lateral_offset_mm": 22.0, "mount_yaw_deg": -2.0,
        "camera_sensor_pid": "OV5640",
    }
    path.write_text(json.dumps(payload))
    camera, target = dock_runtime.load_real_dock_calibration(path)
    assert camera.distortion_coeffs == tuple(payload["distortion_coeffs"])
    assert (camera.image_width_px, camera.image_height_px) == (640, 480)
    assert camera.mount_lateral_offset_mm == 22.0
    assert camera.mount_yaw_deg == -2.0
    assert camera.camera_sensor_pid == "OV5640"
    assert target == 120
    for invalid in ([0.1], [0.0, 0.0, True, 0.0], "invalid"):
        payload["distortion_coeffs"] = invalid
        path.write_text(json.dumps(payload))
        with pytest.raises(ValueError):
            dock_runtime.load_real_dock_calibration(path)



@pytest.mark.parametrize("pid", ["OV2640", "ov5640", "OV5640x", True, 0x3660])
def test_loader_rejects_unknown_or_ill_typed_camera_pid(tmp_path, pid):
    path = tmp_path / "dock.json"
    path.write_text(json.dumps({
        "measured": True, "robot_id": "robot-01", "head_device_id": "xiaozhi-01", "fx": 410, "fy": 408, "cx": 320, "cy": 240,
        "tag_side_mm": 60, "marker_id": 12, "target_distance_mm": 120,
        "camera_sensor_pid": pid,
    }))
    with pytest.raises(ValueError, match="unsupported camera PID"):
        dock_runtime.load_real_dock_calibration(path)



@pytest.mark.parametrize("invalid", [
    {"mount_lateral_offset_mm": None, "mount_yaw_deg": 0},
    {"mount_lateral_offset_mm": 0, "mount_yaw_deg": None},
    {"mount_lateral_offset_mm": True, "mount_yaw_deg": 0},
    {"mount_lateral_offset_mm": 0, "mount_yaw_deg": "sideways"},
    {"mount_lateral_offset_mm": 200, "mount_yaw_deg": 0},
])
async def test_invalid_mount_measurement_fails_before_dock_camera(
    tmp_path, invalid,
):
    base = {
        "measured": True, "robot_id": "robot-01", "head_device_id": "xiaozhi-01", "camera_sensor_pid": "OV5640", "fx": 410, "fy": 410,
        "cx": 320, "cy": 240,
        "tag_side_mm": 60, "marker_id": 12,
        "target_distance_mm": 120, **invalid,
    }
    file = tmp_path / "dock.json"
    file.write_text(json.dumps(base))
    head = Head()
    result = await dock_runtime.observe_actual_dock(
        head, SimpleNamespace(id="robot-01", dock_calibration=file),
    )
    assert result["phase"] == "hold"
    assert result["source"] == "not_calibrated"
    assert not result["motor_authorized"] and not result["charging_authorized"]
    assert head.captures == 0 and head.commands == []



async def test_measured_marker_pose_does_not_energize_contact_or_drive(tmp_path, monkeypatch):
    path = tmp_path / "dock.json"
    path.write_text(json.dumps({
        "measured": True, "robot_id": "robot-01", "head_device_id": "xiaozhi-01", "camera_sensor_pid": "OV5640", "fx": 410, "fy": 408, "cx": 320, "cy": 240,
        "tag_side_mm": 60, "marker_id": 12, "target_distance_mm": 120,
    }))
    head = Head()

    def detector(image, calibration, *, captured_at):
        assert image.startswith(b"\xff\xd8") and calibration.marker_id == 12
        return DockPose(0, 0, 450, 0.5, captured_at)

    mock_dock_detector(monkeypatch, detector)
    result = await dock_runtime.observe_actual_dock(
        head, SimpleNamespace(id="robot-01", dock_calibration=path)
    )
    assert result["phase"] == "approach"
    assert result["pose"]["z_mm"] == 450
    assert result["motor_authorized"] is False
    assert result["charging_authorized"] is False
    assert result["physical_acceptance_pass"] is False
    assert head.captures == 1 and not head.commands
    assert head.identity_checks == 1


async def test_dock_diagnostic_rejects_missing_actual_sensor_pid(tmp_path):
    path = tmp_path / "dock.json"
    path.write_text(json.dumps({
        "measured": True, "robot_id": "robot-01", "head_device_id": "xiaozhi-01", "fx": 410, "fy": 408, "cx": 320, "cy": 240,
        "tag_side_mm": 60, "marker_id": 12, "target_distance_mm": 120,
    }))
    head = Head()
    result = await dock_runtime.observe_actual_dock(
        head, SimpleNamespace(id="robot-01", dock_calibration=path),
    )
    assert result["source"] == "not_calibrated"
    assert result["phase"] == "hold" and result["pose"] is None
    assert head.captures == head.identity_checks == 0
    assert not result["motor_authorized"] and not result["charging_authorized"]


async def test_dock_diagnostic_rejects_same_resolution_wrong_sensor(
    tmp_path, monkeypatch,
):
    path = tmp_path / "dock.json"
    path.write_text(json.dumps({
        "measured": True, "robot_id": "robot-01", "head_device_id": "xiaozhi-01", "camera_sensor_pid": "OV3660",
        "fx": 410, "fy": 408, "cx": 320, "cy": 240,
        "image_width_px": 640, "image_height_px": 480,
        "tag_side_mm": 60, "marker_id": 12, "target_distance_mm": 120,
    }))
    head = Head()  # Actual OV5640 despite equal JPEG dimensions.
    mock_dock_detector(
        monkeypatch,
        lambda *_args, **_kw: pytest.fail("Wrong sensor entered PnP"),
    )
    result = await dock_runtime.observe_actual_dock(
        head, SimpleNamespace(id="robot-01", dock_calibration=path),
    )
    assert result["source"] == "camera_identity_mismatch"
    assert result["pose"] is None and result["phase"] == "hold"
    assert head.captures == 1 and head.identity_checks == 1
    assert not result["motor_authorized"] and not result["charging_authorized"]


async def test_dock_diagnostic_refuses_identity_endpoint_absence(tmp_path):
    path = tmp_path / "dock.json"
    path.write_text(json.dumps({
        "measured": True, "robot_id": "robot-01", "head_device_id": "xiaozhi-01", "camera_sensor_pid": "OV5640",
        "fx": 410, "fy": 408, "cx": 320, "cy": 240,
        "tag_side_mm": 60, "marker_id": 12, "target_distance_mm": 120,
    }))

    class LegacyHead:
        async def snapshot(self):
            return b"\xff\xd8\xff\xd9"

    result = await dock_runtime.observe_actual_dock(
        LegacyHead(), SimpleNamespace(id="robot-01", dock_calibration=path),
    )
    assert result["source"] == "camera_identity_unavailable"
    assert result["pose"] is None and result["phase"] == "hold"
    assert not result["motor_authorized"] and not result["charging_authorized"]


@pytest.mark.parametrize("target", [10 ** 1000, -(10 ** 1000), float("inf"), float("nan"), True])
async def test_unrepresentable_dock_stop_target_holds_before_camera(tmp_path, target):
    # A malformed calibration must never raise OverflowError or start a
    # camera observation, and certainly cannot authorize docking motion.
    path = tmp_path / "dock.json"
    path.write_text(json.dumps({
        "measured": True, "robot_id": "robot-01", "head_device_id": "xiaozhi-01", "camera_sensor_pid": "OV5640", "fx": 410, "fy": 410, "cx": 320, "cy": 240,
        "tag_side_mm": 60, "marker_id": 12, "target_distance_mm": target,
    }))
    head = Head()
    result = await dock_runtime.observe_actual_dock(
        head, SimpleNamespace(id="robot-01", dock_calibration=path)
    )
    assert result["phase"] == "hold"
    assert result["source"] == "not_calibrated"
    assert not result["motor_authorized"] and not result["charging_authorized"]
    assert not result["physical_acceptance_pass"]
    assert head.captures == 0 and head.commands == []


@pytest.mark.parametrize("change", [
    {"measured": False}, {"fx": 0}, {"tag_side_mm": 500},
    {"target_distance_mm": 0},
])
async def test_fake_or_bad_dock_calibration_never_looks_or_drives(tmp_path, change):
    data = {
        "measured": True, "robot_id": "robot-01", "head_device_id": "xiaozhi-01", "camera_sensor_pid": "OV5640", "fx": 410, "fy": 410, "cx": 320, "cy": 240,
        "tag_side_mm": 60, "marker_id": 12, "target_distance_mm": 120,
    }
    data.update(change)
    path = tmp_path / "dock.json"
    path.write_text(json.dumps(data))
    head = Head()
    result = await dock_runtime.observe_actual_dock(
        head, SimpleNamespace(id="robot-01", dock_calibration=path)
    )
    assert result["phase"] == "hold"
    assert head.captures == 0 and not head.commands



async def test_slow_apriltag_diagnostic_holds_stale_pose_without_any_motion(
    tmp_path, monkeypatch,
):
    import time
    calibration = tmp_path / "dock.json"
    calibration.write_text(json.dumps({
        "measured": True, "robot_id": "robot-01", "head_device_id": "xiaozhi-01", "camera_sensor_pid": "OV5640", "fx": 410, "fy": 410, "cx": 320, "cy": 240,
        "tag_side_mm": 60, "marker_id": 12, "target_distance_mm": 120,
    }))
    head = Head()

    def slow_detector(image, camera, *, captured_at):
        time.sleep(0.25)
        return DockPose(0, 0, 450, 0.5, captured_at)

    mock_dock_detector(monkeypatch, slow_detector)
    result = await dock_runtime.observe_actual_dock(
        head, SimpleNamespace(id="robot-01", dock_calibration=calibration)
    )
    assert result["phase"] == "hold"
    assert "stale" in result["reason"].lower()
    assert result["motor_authorized"] is False
    assert result["charging_authorized"] is False
    assert head.captures == 1 and head.commands == []


@pytest.mark.parametrize("failure", [
    OSError("camera disconnected"), TimeoutError(),
    RuntimeError("invalid camera stream state"), ValueError("malformed camera frame"),
])
async def test_snapshot_failure_holds_without_motion(tmp_path, monkeypatch, failure):
    path = tmp_path / "dock.json"
    path.write_text(json.dumps({
        "measured": True, "robot_id": "robot-01", "head_device_id": "xiaozhi-01", "camera_sensor_pid": "OV5640", "fx": 410, "fy": 410, "cx": 320, "cy": 240,
        "tag_side_mm": 60, "marker_id": 12, "target_distance_mm": 120,
    }))
    head = Head()

    async def failed_snapshot():
        raise failure

    monkeypatch.setattr(head, "snapshot", failed_snapshot)
    result = await dock_runtime.observe_actual_dock(
        head, SimpleNamespace(id="robot-01", dock_calibration=path)
    )
    assert result["phase"] == "hold"
    assert result["source"] == "head_snapshot_failed"
    assert result["pose"] is None
    assert result["motor_authorized"] is False
    assert result["charging_authorized"] is False
    assert result["physical_acceptance_pass"] is False
    assert head.commands == []


@pytest.mark.parametrize("failure", [
    RuntimeError("decoder failed"), TimeoutError(),
    Exception("native OpenCV detector failure"),
])
async def test_detector_failure_holds_without_motion(tmp_path, monkeypatch, failure):
    path = tmp_path / "dock.json"
    path.write_text(json.dumps({
        "measured": True, "robot_id": "robot-01", "head_device_id": "xiaozhi-01", "camera_sensor_pid": "OV5640", "fx": 410, "fy": 410, "cx": 320, "cy": 240,
        "tag_side_mm": 60, "marker_id": 12, "target_distance_mm": 120,
    }))
    head = Head()

    def failed_detector(*args, **kwargs):
        raise failure

    mock_dock_detector(monkeypatch, failed_detector)
    result = await dock_runtime.observe_actual_dock(
        head, SimpleNamespace(id="robot-01", dock_calibration=path)
    )
    assert result["phase"] == "hold"
    assert result["source"] == "apriltag_detection_failed"
    assert result["pose"] is None
    assert result["motor_authorized"] is False
    assert result["charging_authorized"] is False
    assert result["physical_acceptance_pass"] is False
    assert head.commands == []



@pytest.mark.parametrize("malformed_pose", [
    {"x_mm": 0, "z_mm": 450},
    (0, 0, 450),
    object(),
    "approach",
])
async def test_corrupt_native_pose_result_fails_closed(tmp_path, monkeypatch, malformed_pose):
    """A native adapter contract violation cannot escape or authorize contact."""
    path = tmp_path / "dock.json"
    path.write_text(json.dumps({
        "measured": True, "robot_id": "robot-01", "head_device_id": "xiaozhi-01", "camera_sensor_pid": "OV5640", "fx": 410, "fy": 410, "cx": 320, "cy": 240,
        "tag_side_mm": 60, "marker_id": 12, "target_distance_mm": 120,
    }))
    head = Head()
    mock_dock_detector(
        monkeypatch,
        lambda *args, **kwargs: malformed_pose,
    )
    result = await dock_runtime.observe_actual_dock(
        head, SimpleNamespace(id="robot-01", dock_calibration=path),
    )
    assert result["phase"] == "hold"
    assert result["source"] == "apriltag_detection_failed"
    assert result["pose"] is None
    assert result["motor_authorized"] is False
    assert result["charging_authorized"] is False
    assert result["physical_acceptance_pass"] is False
    assert head.captures == 1 and head.commands == []

async def test_real_snapshot_deadline_cancels_stalled_capture_without_motion(tmp_path):
    """A real deadline, not an injected TimeoutError, must fail closed."""
    import asyncio

    path = tmp_path / "dock.json"
    path.write_text(json.dumps({
        "measured": True, "robot_id": "robot-01", "head_device_id": "xiaozhi-01", "camera_sensor_pid": "OV5640", "fx": 410, "fy": 410, "cx": 320, "cy": 240,
        "tag_side_mm": 60, "marker_id": 12, "target_distance_mm": 120,
    }))
    head = Head()
    entered = asyncio.Event()
    cancelled = asyncio.Event()

    async def stalled_snapshot():
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    head.snapshot = stalled_snapshot
    result = await asyncio.wait_for(
        dock_runtime.observe_actual_dock(
            head, SimpleNamespace(id="robot-01", dock_calibration=path)
        ), timeout=4.0
    )
    assert entered.is_set()
    assert result["phase"] == "hold"
    assert result["source"] == "head_snapshot_failed"
    assert result["pose"] is None
    assert not result["motor_authorized"] and not result["charging_authorized"]
    assert not result["physical_acceptance_pass"]
    assert head.commands == []
    # The hold is immediate; cooperative cancellation cleanup may finish
    # shortly afterward, especially with a macOS event-loop scheduler.
    await asyncio.wait_for(cancelled.wait(), timeout=1.0)


@pytest.mark.parametrize("payload", [
    b"", b"not jpeg", b"\\xff\\xd8truncated", b"\\xff\\xd8" + b"x" * (512 * 1024) + b"\\xff\\xd9",
    b"\xff\xd8" + b"x" * 512000 + b"\xff\xd9",  # Within old 512 KiB limit, above native bound.
    "not bytes",
])
async def test_invalid_dock_snapshot_never_starts_native_detector(tmp_path, monkeypatch, payload):
    path = tmp_path / "dock.json"
    path.write_text(json.dumps({
        "measured": True, "robot_id": "robot-01", "head_device_id": "xiaozhi-01", "camera_sensor_pid": "OV5640", "fx": 410, "fy": 408, "cx": 320, "cy": 240,
        "tag_side_mm": 60, "marker_id": 12, "target_distance_mm": 120,
    }))
    head = Head()

    async def snapshot():
        return payload

    def detector(*args, **kwargs):
        pytest.fail("Malformed camera data reached native AprilTag detector")

    monkeypatch.setattr(head, "snapshot", snapshot)
    mock_dock_detector(monkeypatch, detector)
    result = await dock_runtime.observe_actual_dock(
        head, SimpleNamespace(id="robot-01", dock_calibration=path)
    )
    assert result["phase"] == "hold"
    assert result["source"] == "head_snapshot_invalid"
    assert result["pose"] is None
    assert not result["motor_authorized"] and not result["charging_authorized"]
    assert not result["physical_acceptance_pass"] and not head.commands


async def test_dock_diagnostic_uncooperative_camera_returns_hold(
    tmp_path, monkeypatch,
):
    """Cancellation ignoring JPEG source must not hold dock diagnostics open."""
    import asyncio
    from types import SimpleNamespace

    import desk_robot.dock_runtime as runtime
    from desk_robot.operations import _bounded_head_reply as real_bounded

    # Tighten only this diagnostic's deadline in the test while exercising
    # the same real bounded helper used by physical motion safety.
    async def tiny_deadline(coro, *, seconds, timeout_message):
        return await real_bounded(coro, seconds=0.04,
                                  timeout_message=timeout_message)
    monkeypatch.setattr(runtime, "_bounded_head_reply", tiny_deadline)

    entered = asyncio.Event()
    release = asyncio.Event()

    class StuckHead:
        def __init__(self):
            self.commands = []

        async def snapshot(self):
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                await release.wait()
                return b"\\xff\\xd8late\\xff\\xd9"

    calibration = tmp_path / "dock.json"
    calibration.write_text('''{
        "measured": true, "robot_id": "robot-01", "head_device_id": "xiaozhi-01", "camera_sensor_pid": "OV5640", "fx": 410, "fy": 410,
        "cx": 320, "cy": 240, "tag_side_mm": 60,
        "marker_id": 1, "target_distance_mm": 200
    }''')
    head = StuckHead()
    try:
        result = await asyncio.wait_for(runtime.observe_actual_dock(
            head, SimpleNamespace(id="robot-01", dock_calibration=calibration),
        ), timeout=0.5)
        assert entered.is_set()
        assert result["phase"] == "hold"
        assert result["source"] == "head_snapshot_failed"
        assert result["charging_authorized"] is False
        assert head.commands == []
    finally:
        release.set()
        await asyncio.sleep(0)


async def test_dock_diagnostic_uses_measured_chassis_offset_not_centered_lens(
    tmp_path, monkeypatch,
):
    """A tag centered in the JPEG may be off center of the actual tracks."""
    calibration = tmp_path / "dock.json"
    calibration.write_text(json.dumps({
        "measured": True, "robot_id": "robot-01", "head_device_id": "xiaozhi-01", "camera_sensor_pid": "OV5640", "fx": 410, "fy": 410,
        "cx": 320, "cy": 240, "tag_side_mm": 60,
        "marker_id": 12, "target_distance_mm": 120,
        "mount_lateral_offset_mm": 40.0,
        "mount_yaw_deg": 0.0,
    }))
    mock_dock_detector(
        monkeypatch,
        lambda jpeg, camera, *, captured_at: DockPose(
            0, 0, 450, 0.5, captured_at,
        ),
    )
    head = Head()
    result = await dock_runtime.observe_actual_dock(
        head, SimpleNamespace(id="robot-01", dock_calibration=calibration)
    )
    assert result["phase"] == "align"
    assert result["pose"]["x_mm"] == 0
    assert result["pose"]["chassis_lateral_mm"] == 40
    assert not result["motor_authorized"] and not result["charging_authorized"]
    assert not result["physical_acceptance_pass"]
    assert not head.commands


async def test_dock_diagnostic_keeps_raw_camera_only_when_mount_unmeasured(
    tmp_path, monkeypatch,
):
    """Provisional camera geometry is not secretly a chassis measurement."""
    calibration = tmp_path / "dock.json"
    calibration.write_text(json.dumps({
        "measured": True, "robot_id": "robot-01", "head_device_id": "xiaozhi-01", "camera_sensor_pid": "OV5640", "fx": 410, "fy": 410,
        "cx": 320, "cy": 240, "tag_side_mm": 60,
        "marker_id": 12, "target_distance_mm": 120,
    }))
    mock_dock_detector(
        monkeypatch,
        lambda jpeg, camera, *, captured_at: DockPose(
            0, 0, 450, 0.5, captured_at,
        ),
    )
    result = await dock_runtime.observe_actual_dock(
        Head(), SimpleNamespace(id="robot-01", dock_calibration=calibration)
    )
    assert result["pose"]["chassis_lateral_mm"] is None
    assert not result["motor_authorized"] and not result["charging_authorized"]


async def test_dock_diagnostic_uses_strict_live_frame_receipt_if_available(
    tmp_path, monkeypatch,
):
    """Dock diagnostics never choose the generic snapshot when a strict one exists."""
    calibration = tmp_path / "dock.json"
    calibration.write_text(json.dumps({
        "measured": True, "robot_id": "robot-01", "head_device_id": "xiaozhi-01", "camera_sensor_pid": "OV5640", "fx": 410, "fy": 410, "cx": 320, "cy": 240,
        "tag_side_mm": 60, "marker_id": 12, "target_distance_mm": 120,
    }))

    class StrictHead(Head):
        async def snapshot(self):
            raise AssertionError("Generic camera snapshot used for docking")

        async def snapshot_for_dock(self):
            import time
            self.captures += 1
            return b"\xff\xd8\xff\xd9", time.monotonic()

    mock_dock_detector(
        monkeypatch,
        lambda jpeg, camera, *, captured_at: DockPose(
            0, 0, 450, 0.5, captured_at,
        ),
    )
    head = StrictHead()
    result = await dock_runtime.observe_actual_dock(
        head, SimpleNamespace(id="robot-01", dock_calibration=calibration),
    )
    assert result["phase"] == "approach"
    assert head.captures == 1
    assert head.commands == []
    assert not result["motor_authorized"]
    assert not result["charging_authorized"]


async def test_stale_mac_receipt_does_not_enter_dock_detector(tmp_path, monkeypatch):
    import time

    calibration = tmp_path / "dock.json"
    calibration.write_text(json.dumps({
        "measured": True, "robot_id": "robot-01", "head_device_id": "xiaozhi-01", "camera_sensor_pid": "OV5640", "fx": 410, "fy": 410, "cx": 320, "cy": 240,
        "tag_side_mm": 60, "marker_id": 12, "target_distance_mm": 120,
    }))

    class StaleHead(Head):
        async def snapshot_for_dock(self):
            return b"\xff\xd8\xff\xd9", time.monotonic() - 0.30

    def detector(*args, **kwargs):
        raise AssertionError("Stale observation entered native detector")

    mock_dock_detector(monkeypatch, detector)
    result = await dock_runtime.observe_actual_dock(
        StaleHead(), SimpleNamespace(id="robot-01", dock_calibration=calibration)
    )
    assert result["phase"] == "hold"
    assert result["source"] == "head_snapshot_invalid"
    assert not result["motor_authorized"] and not result["charging_authorized"]


@pytest.mark.parametrize("bad_receipt", [
    (b"\xff\xd8\xff\xd9", float("nan")),
    (b"\xff\xd8\xff\xd9", float("inf")),
    (b"\xff\xd8\xff\xd9", True),
    (b"\xff\xd8\xff\xd9", -1.0),
    (b"\xff\xd8\xff\xd9", "recent"),
    (b"\xff\xd8\xff\xd9",),
    ("not jpeg", 1.0),
])
def test_invalid_dock_receipt_types_are_not_pose_evidence(bad_receipt):
    with pytest.raises(ValueError, match="Invalid or stale dock camera receipt"):
        dock_runtime.unpack_dock_frame(bad_receipt)


@pytest.mark.parametrize("timestamp", [10**1000, -(10**1000)])
@pytest.mark.parametrize("receipt_shape", [2, 4])
def test_unrepresentable_dock_receipt_time_is_rejected(timestamp, receipt_shape):
    receipt = (b"\xff\xd8\xff\xd9", timestamp)
    if receipt_shape == 4:
        receipt += ((1, 1, 1), 1)
    with pytest.raises(ValueError, match="Invalid or stale dock camera receipt"):
        dock_runtime.unpack_dock_frame(receipt)


@pytest.mark.parametrize("timestamp", [10**1000, -(10**1000)])
async def test_unrepresentable_dock_receipt_holds_before_identity_or_detector(
    tmp_path, monkeypatch, timestamp,
):
    calibration = tmp_path / "dock.json"
    calibration.write_text(json.dumps({
        "measured": True, "robot_id": "robot-01",
        "head_device_id": "xiaozhi-01", "camera_sensor_pid": "OV5640",
        "fx": 410, "fy": 410, "cx": 320, "cy": 240,
        "tag_side_mm": 60, "marker_id": 12, "target_distance_mm": 120,
    }))

    class ExtremeReceiptHead(Head):
        async def snapshot_for_dock(self):
            self.captures += 1
            return b"\xff\xd8\xff\xd9", timestamp

    head = ExtremeReceiptHead()
    mock_dock_detector(
        monkeypatch,
        lambda *_args, **_kwargs: pytest.fail("Bad receipt entered native detector"),
    )
    result = await dock_runtime.observe_actual_dock(
        head, SimpleNamespace(id="robot-01", dock_calibration=calibration),
    )
    assert result["source"] == "head_snapshot_invalid"
    assert result["phase"] == "hold" and result["pose"] is None
    assert result["physical_acceptance_pass"] is False
    assert not result["motor_authorized"] and not result["charging_authorized"]
    assert head.captures == 1 and head.identity_checks == 0
    assert head.commands == []


def test_original_dock_receipt_time_is_not_replaced_after_waiting():
    import time

    from desk_robot.dock_vision import assess_dock

    received = time.monotonic() - 0.15
    jpeg, stamp = dock_runtime.unpack_dock_frame(
        (b"\xff\xd8\xff\xd9", received)
    )
    assert jpeg.startswith(b"\xff\xd8")
    assert stamp == received
    # A second delayed stage must assess the ORIGINAL receipt, not a
    # fabricated new pose timestamp after native detector completion.
    pose = DockPose(0, 0, 450, 0.5, stamp)
    result = assess_dock(
        pose, now=received + 0.25, target_distance_mm=120
    )
    assert result.phase == "hold"
    assert "stale" in result.reason.lower()


async def test_dock_detector_delay_expires_original_receipt_without_motion(
    tmp_path, monkeypatch,
):
    import time

    calibration = tmp_path / "dock.json"
    calibration.write_text(json.dumps({
        "measured": True, "robot_id": "robot-01", "head_device_id": "xiaozhi-01", "camera_sensor_pid": "OV5640", "fx": 410, "fy": 410, "cx": 320, "cy": 240,
        "tag_side_mm": 60, "marker_id": 12, "target_distance_mm": 120,
    }))

    class DelayedFrame(Head):
        async def snapshot_for_dock(self):
            return b"\xff\xd8\xff\xd9", time.monotonic() - 0.15

    def slow_detector(jpeg, cal, *, captured_at):
        time.sleep(0.08)
        return DockPose(0, 0, 450, 0.5, captured_at)

    mock_dock_detector(monkeypatch, slow_detector)
    head = DelayedFrame()
    result = await dock_runtime.observe_actual_dock(
        head, SimpleNamespace(id="robot-01", dock_calibration=calibration)
    )
    assert result["phase"] == "hold"
    assert "stale" in result["reason"].lower()
    assert not result["motor_authorized"] and not result["charging_authorized"]
    assert head.commands == []



@pytest.mark.parametrize(
    ("changed", "expected_error"),
    [
        ({"robot_id": "robot-02"}, "robot/head identity"),
        ({"head_device_id": "xiaozhi-02"}, "head device identity"),
        ({"robot_id": None}, "robot/head identity"),
        ({"head_device_id": None}, "robot/head identity"),
    ],
)
async def test_measured_dock_calibration_is_bound_to_pet_and_head_before_camera(
    tmp_path, changed, expected_error,
):
    payload = {
        "measured": True, "robot_id": "robot-01",
        "head_device_id": "xiaozhi-01",
        "fx": 410, "fy": 410, "cx": 320, "cy": 240,
        "tag_side_mm": 60, "marker_id": 1,
        "target_distance_mm": 200, "camera_sensor_pid": "OV5640",
        "mount_lateral_offset_mm": 6, "mount_yaw_deg": 1,
    }
    path = tmp_path / "pet-one-calibration.json"
    payload.update(changed)
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match=expected_error):
        dock_runtime.load_real_dock_calibration(
            path, robot_id="robot-01", head_device_id="xiaozhi-01",
        )
    head = Head()
    observed = await dock_runtime.observe_actual_dock(
        head, SimpleNamespace(
            id="robot-01", device_id="xiaozhi-01", dock_calibration=path,
        ),
    )
    assert observed["source"] == "not_calibrated"
    assert observed["pose"] is None
    assert head.captures == 0 and head.commands == []


async def test_matching_pet_camera_calibration_keeps_source_identity(tmp_path):
    payload = {
        "measured": True, "robot_id": "robot-01",
        "head_device_id": "xiaozhi-01",
        "fx": 410, "fy": 410, "cx": 320, "cy": 240,
        "tag_side_mm": 60, "marker_id": 1,
        "target_distance_mm": 200, "camera_sensor_pid": "OV5640",
        "mount_lateral_offset_mm": 6, "mount_yaw_deg": 1,
    }
    path = tmp_path / "pet-one-calibration.json"
    path.write_text(json.dumps(payload))
    camera, target = dock_runtime.load_real_dock_calibration(
        path, robot_id="robot-01", head_device_id="xiaozhi-01",
    )
    assert target == 200
    assert camera.robot_id == "robot-01"
    assert camera.head_device_id == "xiaozhi-01"
    with pytest.raises(ValueError, match="robot/head identity"):
        dock_runtime.load_real_dock_calibration(
            path, robot_id="robot-02", head_device_id="xiaozhi-02",
        )

@pytest.mark.parametrize("key,early_value", [
    ("measured", False),
    ("robot_id", "robot-02"),
    ("head_device_id", "xiaozhi-other"),
    ("marker_id", 13),
    ("fx", 0),
    ("camera_sensor_pid", "OV3660"),
])
async def test_ambiguous_dock_calibration_fields_fail_closed_before_camera(
    tmp_path, key, early_value,
):
    """A second apparently valid JSON field cannot conceal contradictory data."""
    record = {
        "measured": True, "robot_id": "robot-01",
        "head_device_id": "xiaozhi-01", "camera_sensor_pid": "OV5640",
        "fx": 410, "fy": 408, "cx": 320, "cy": 240,
        "tag_side_mm": 60, "marker_id": 12,
        "target_distance_mm": 120,
    }
    expected = json.dumps(record)
    field = f'"{key}": {json.dumps(record[key])}'
    assert expected.count(field) == 1
    ambiguous = expected.replace(
        field, f'"{key}": {json.dumps(early_value)}, {field}',
    )
    path = tmp_path / "contradictory_dock_calibration.json"
    path.write_text(ambiguous, encoding="utf-8")
    with pytest.raises(ValueError, match="Repeated dock calibration JSON field"):
        dock_runtime.load_real_dock_calibration(
            path, robot_id="robot-01", head_device_id="xiaozhi-01",
        )
    head = Head()
    result = await dock_runtime.observe_actual_dock(
        head, SimpleNamespace(
            id="robot-01", device_id="xiaozhi-01", dock_calibration=path,
        ),
    )
    assert result["phase"] == "hold"
    assert result["source"] == "not_calibrated"
    assert result["physical_acceptance_pass"] is False
    assert not result["motor_authorized"] and not result["charging_authorized"]
    assert head.captures == head.identity_checks == 0
    assert not head.commands


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_dock_calibration_json_rejects_nonstandard_numeric_constants(
    tmp_path, constant,
):
    record = {
        "measured": True, "robot_id": "robot-01",
        "head_device_id": "xiaozhi-01", "camera_sensor_pid": "OV5640",
        "fx": 410, "fy": 408, "cx": 320, "cy": 240,
        "tag_side_mm": 60, "marker_id": 12,
        "target_distance_mm": 120,
    }
    value = json.dumps(record)
    assert value.count('"fx": 410') == 1
    path = tmp_path / "nonfinite_calibration.json"
    path.write_text(value.replace('"fx": 410', f'"fx": {constant}'))
    with pytest.raises(ValueError, match="Nonfinite dock calibration JSON constant"):
        dock_runtime.load_real_dock_calibration(path)


@pytest.mark.parametrize("complete_us", [0, -1, 1 << 63, 10**100])
def test_dock_receipt_rejects_non_int64_camera_completion_clock(complete_us):
    received_at = dock_runtime.time.monotonic()
    with pytest.raises(ValueError, match="Invalid or stale dock camera receipt"):
        dock_runtime.unpack_dock_frame(
            (b"\xff\xd8\xff\xd9", received_at, (1, 1, complete_us), 1)
        )


def test_dock_receipt_accepts_signed_int64_camera_completion_limit():
    received_at = dock_runtime.time.monotonic()
    receipt = (
        b"\xff\xd8\xff\xd9", received_at, (1, 1, (1 << 63) - 1), 1
    )
    assert dock_runtime.unpack_dock_frame(receipt) == (receipt[0], received_at)


async def test_selected_dock_frame_verification_rejects_expired_receipt_before_call():
    class Verifier:
        async def dock_receipt_current(self, receipt):
            pytest.fail("Expired receipt entered stream verifier")

    receipt = (
        b"\xff\xd8\xff\xd9", dock_runtime.time.monotonic() - 1.0,
        (1, 1, 1), 1,
    )
    with pytest.raises(ValueError, match="Invalid or stale dock camera receipt"):
        await dock_runtime.verify_selected_dock_frame(Verifier(), receipt)


async def test_selected_dock_frame_verification_is_bounded_even_if_cancel_ignored():
    import asyncio

    entered = asyncio.Event()
    cancelled = asyncio.Event()
    release = asyncio.Event()
    finished = asyncio.Event()

    class Verifier:
        async def dock_receipt_current(self, receipt):
            entered.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                cancelled.set()
                await release.wait()
            finally:
                finished.set()

    receipt = (
        b"\xff\xd8\xff\xd9", dock_runtime.time.monotonic(),
        (1, 1, 1), 1,
    )
    try:
        with pytest.raises(TimeoutError, match="Dock frame source verification timed out"):
            await asyncio.wait_for(
                dock_runtime.verify_selected_dock_frame(Verifier(), receipt),
                timeout=1.0,
            )
        assert entered.is_set()
        await asyncio.wait_for(cancelled.wait(), timeout=1.0)
        assert not finished.is_set()
    finally:
        release.set()
        if entered.is_set():
            await asyncio.wait_for(finished.wait(), timeout=1.0)

@pytest.mark.parametrize("strict_receipt", [False, True])
async def test_dock_identity_lookup_expires_with_original_frame(
    tmp_path, monkeypatch, strict_receipt,
):
    """A stalled PID lookup cannot extend the original camera evidence lifetime."""
    import asyncio
    import time

    calibration = tmp_path / "dock.json"
    calibration.write_text(json.dumps({
        "measured": True, "robot_id": "robot-01",
        "head_device_id": "xiaozhi-01", "camera_sensor_pid": "OV5640",
        "fx": 410, "fy": 410, "cx": 320, "cy": 240,
        "tag_side_mm": 60, "marker_id": 12, "target_distance_mm": 120,
    }))
    entered = asyncio.Event()
    cancelled = asyncio.Event()
    release = asyncio.Event()
    finished = asyncio.Event()
    head = Head()

    async def strict_snapshot():
        head.captures += 1
        return b"\xff\xd8\xff\xd9", time.monotonic(), (1, 1, 1), 1

    async def stuck_identity(*args):
        assert bool(args) is strict_receipt
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            await release.wait()
            return "OV5640"
        finally:
            finished.set()

    if strict_receipt:
        monkeypatch.setattr(head, "snapshot_for_dock", strict_snapshot, raising=False)
    monkeypatch.setattr(head, "camera_identity", stuck_identity)
    mock_dock_detector(
        monkeypatch,
        lambda *args, **kwargs: pytest.fail("Expired receipt reached native detector"),
    )
    try:
        result = await asyncio.wait_for(dock_runtime.observe_actual_dock(
            head, SimpleNamespace(id="robot-01", dock_calibration=calibration),
        ), timeout=1.0)
        assert entered.is_set()
        assert result["phase"] == "hold" and result["pose"] is None
        assert result["source"] == "camera_identity_unavailable"
        assert not result["motor_authorized"] and not result["charging_authorized"]
        assert not result["physical_acceptance_pass"]
        assert head.captures == 1 and not head.commands
        await asyncio.wait_for(cancelled.wait(), timeout=1.0)
        assert not finished.is_set()
    finally:
        release.set()
        if entered.is_set():
            await asyncio.wait_for(finished.wait(), timeout=1.0)


async def test_frozen_observer_reaps_worker_and_recovers_without_replaying_jpeg(
    tmp_path, monkeypatch,
):
    import os
    import signal
    import sys
    import time

    from desk_robot.dock_process import DetectorPool

    worker = """
import json, sys
print("ready", flush=True)
for line in sys.stdin:
    request = json.loads(line)
    pose = dict(x_mm=0, y_mm=0, z_mm=450, reprojection_error_px=0.5,
                captured_at=request["captured_at"])
    print(json.dumps(dict(id=request["id"], pose=pose)), flush=True)
"""
    pool = DetectorPool((sys.executable, "-u", "-c", worker))
    monkeypatch.setattr(dock_runtime, "_DETECTOR_POOL", pool)
    calibration = tmp_path / "dock.json"
    calibration.write_text(json.dumps({
        "measured": True, "robot_id": "robot-01", "head_device_id": "xiaozhi-01",
        "camera_sensor_pid": "OV5640", "fx": 410, "fy": 410, "cx": 320, "cy": 240,
        "tag_side_mm": 60, "marker_id": 12, "target_distance_mm": 120,
    }))
    robot = SimpleNamespace(id="robot-01", dock_calibration=calibration)
    head = Head()
    try:
        await dock_runtime.prewarm_detector_pool()
        assert len(pool._ready) == 2
        frozen, spare = pool._ready
        os.kill(frozen.pid, signal.SIGSTOP)
        started = time.monotonic()
        first = await dock_runtime.observe_actual_dock(head, robot)
        assert first["phase"] == "hold" and first["pose"] is None
        assert first["source"] == "apriltag_detection_failed"
        assert frozen.returncode == -signal.SIGKILL
        second = await dock_runtime.observe_actual_dock(head, robot)
        assert second["phase"] == "approach"
        assert second["pose"]["z_mm"] == 450
        assert pool._ready[0] is spare and head.captures == 2
        assert time.monotonic() - started < 0.5
        for result in (first, second):
            assert not result["motor_authorized"] and not result["charging_authorized"]
            assert not result["physical_acceptance_pass"]
        assert not head.commands
    finally:
        await dock_runtime.close_detector_pool()
    assert not pool._owned
    assert dock_runtime._DETECTOR_POOL is not pool


@pytest.mark.parametrize("verdict", [False, True, 0, {}, {"ok": False}, "stale"])
async def test_selected_dock_frame_rejects_unexpected_verifier_result(verdict):
    class Verifier:
        async def dock_receipt_current(self, receipt):
            return verdict

    receipt = (b"\xff\xd8\xff\xd9", dock_runtime.time.monotonic(), (1, 1, 1), 1)
    with pytest.raises(ValueError, match="Dock frame source verification denied"):
        await dock_runtime.verify_selected_dock_frame(Verifier(), receipt)


async def test_selected_dock_frame_accepts_none_return_from_exception_based_verifier():
    class Verifier:
        async def dock_receipt_current(self, receipt):
            assert receipt[2:] == ((1, 1, 1), 1)

    receipt = (b"\xff\xd8\xff\xd9", dock_runtime.time.monotonic(), (1, 1, 1), 1)
    await dock_runtime.verify_selected_dock_frame(Verifier(), receipt)


@pytest.mark.parametrize("completed_at,expired", [(100.19, False), (100.21, True)])
async def test_selected_dock_frame_preserves_original_deadline(
    monkeypatch, completed_at, expired,
):
    """Successful verification cannot renew the JPEG receipt lifetime."""
    now = 100.15
    monkeypatch.setattr(dock_runtime, "time", SimpleNamespace(monotonic=lambda: now))
    receipt = (b"\xff\xd8\xff\xd9", 100.0, (1, 1, 1), 1)
    real_bounded = dock_runtime._bounded_head_reply
    budgets = []
    verified = []

    async def record_budget(coro, *, seconds, timeout_message):
        budgets.append(seconds)
        return await real_bounded(coro, seconds=seconds, timeout_message=timeout_message)

    class Verifier:
        async def dock_receipt_current(self, observation):
            nonlocal now
            verified.append(observation)
            now = completed_at

    monkeypatch.setattr(dock_runtime, "_bounded_head_reply", record_budget)
    if expired:
        with pytest.raises(ValueError, match="Invalid or stale dock camera receipt"):
            await dock_runtime.verify_selected_dock_frame(Verifier(), receipt)
    else:
        await dock_runtime.verify_selected_dock_frame(Verifier(), receipt)
    assert budgets == [pytest.approx(0.05)]
    assert verified == [receipt]
