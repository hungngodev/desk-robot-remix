"""Dock observation must never gain motor/charging rights from JPEG geometry."""
import json
from types import SimpleNamespace

import pytest
from desk_robot import dock_runtime
from desk_robot.dock_vision import DockPose


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

    monkeypatch.setattr(dock_runtime, "detect_apriltag", detector)
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
    monkeypatch.setattr(
        dock_runtime, "detect_apriltag",
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

    monkeypatch.setattr(dock_runtime, "detect_apriltag", slow_detector)
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

    monkeypatch.setattr(dock_runtime, "detect_apriltag", failed_detector)
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
    monkeypatch.setattr(
        dock_runtime, "detect_apriltag",
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

async def test_detector_timeout_does_not_queue_another_native_worker(tmp_path, monkeypatch):
    import asyncio
    import threading

    path = tmp_path / "dock.json"
    path.write_text(json.dumps({
        "measured": True, "robot_id": "robot-01", "head_device_id": "xiaozhi-01", "camera_sensor_pid": "OV5640", "fx": 410, "fy": 410, "cx": 320, "cy": 240,
        "tag_side_mm": 60, "marker_id": 12, "target_distance_mm": 120,
    }))
    robot = SimpleNamespace(id="robot-01", dock_calibration=path)
    started = threading.Event()
    release = threading.Event()
    calls = []

    def blocked_detector(image, calibration, *, captured_at):
        calls.append(captured_at)
        started.set()
        release.wait(timeout=10)
        return DockPose(0, 0, 450, 0.5, captured_at)

    monkeypatch.setattr(dock_runtime, "detect_apriltag", blocked_detector)
    try:
        first = asyncio.create_task(dock_runtime.observe_actual_dock(Head(), robot))
        await asyncio.wait_for(asyncio.to_thread(started.wait), timeout=1)
        second = await dock_runtime.observe_actual_dock(Head(), robot)
        assert second["phase"] == "hold"
        assert second["source"] == "apriltag_detector_busy"
        assert second["motor_authorized"] is False
        assert second["charging_authorized"] is False
        assert len(calls) == 1

        timed_out = await asyncio.wait_for(first, timeout=4)
        assert timed_out["source"] == "apriltag_detection_failed"
        still_busy = await dock_runtime.observe_actual_dock(Head(), robot)
        assert still_busy["source"] == "apriltag_detector_busy"
        assert len(calls) == 1
    finally:
        release.set()

    # The worker releases the slot after it really exits, not at timeout.
    for _ in range(100):
        if dock_runtime._DETECTOR_SLOT.acquire(blocking=False):
            dock_runtime._DETECTOR_SLOT.release()
            break
        await asyncio.sleep(0.01)
    else:
        pytest.fail("Detector worker did not release its slot")
    recovered = await dock_runtime.observe_actual_dock(Head(), robot)
    assert recovered["motor_authorized"] is False
    assert recovered["charging_authorized"] is False
    assert len(calls) == 2


async def test_cancel_before_detector_dispatch_releases_slot(tmp_path, monkeypatch):
    """A queued native future must release its slot if dispatch is cancelled."""
    import asyncio
    from concurrent.futures import Future

    path = tmp_path / "dock.json"
    path.write_text(json.dumps({
        "measured": True, "robot_id": "robot-01", "head_device_id": "xiaozhi-01", "camera_sensor_pid": "OV5640", "fx": 410, "fy": 410, "cx": 320, "cy": 240,
        "tag_side_mm": 60, "marker_id": 12, "target_distance_mm": 120,
    }))
    robot = SimpleNamespace(id="robot-01", dock_calibration=path)
    queued = Future()
    submitted = asyncio.Event()
    real_submit = dock_runtime._DETECTOR_POOL.submit

    def not_dispatched_yet(*args, **kwargs):
        submitted.set()
        return queued

    monkeypatch.setattr(dock_runtime._DETECTOR_POOL, "submit", not_dispatched_yet)
    observer = asyncio.create_task(dock_runtime.observe_actual_dock(Head(), robot))
    try:
        await asyncio.wait_for(submitted.wait(), timeout=1)
        observer.cancel()
        with pytest.raises(asyncio.CancelledError):
            await observer
        busy = await dock_runtime.observe_actual_dock(Head(), robot)
        assert busy["source"] == "apriltag_detector_busy"
        assert not busy["motor_authorized"] and not busy["charging_authorized"]
    finally:
        # Model executor cancellation *before* a worker has started.
        assert queued.cancel()
        monkeypatch.setattr(dock_runtime._DETECTOR_POOL, "submit", real_submit)

    for _ in range(100):
        if dock_runtime._DETECTOR_SLOT.acquire(blocking=False):
            dock_runtime._DETECTOR_SLOT.release()
            break
        await asyncio.sleep(0.01)
    else:
        pytest.fail("Cancelled native future leaked the detector slot")

    def detector(image, calibration, *, captured_at):
        return DockPose(0, 0, 450, 0.5, captured_at)

    monkeypatch.setattr(dock_runtime, "detect_apriltag", detector)
    recovered = await dock_runtime.observe_actual_dock(Head(), robot)
    assert recovered["source"] == "head_jpeg_observed_on_mac_receipt"
    assert not recovered["motor_authorized"] and not recovered["charging_authorized"]


async def test_cancel_after_native_detector_starts_keeps_slot(tmp_path, monkeypatch):
    """Cancellation of the observer must not release a running native worker."""
    import asyncio
    import threading

    path = tmp_path / "dock.json"
    path.write_text(json.dumps({
        "measured": True, "robot_id": "robot-01", "head_device_id": "xiaozhi-01", "camera_sensor_pid": "OV5640", "fx": 410, "fy": 410, "cx": 320, "cy": 240,
        "tag_side_mm": 60, "marker_id": 12, "target_distance_mm": 120,
    }))
    robot = SimpleNamespace(id="robot-01", dock_calibration=path)
    started = threading.Event()
    release = threading.Event()
    calls = []

    def blocked_detector(image, calibration, *, captured_at):
        calls.append(captured_at)
        started.set()
        if not release.wait(timeout=5):
            raise TimeoutError("Test worker release never arrived")
        return DockPose(0, 0, 450, 0.5, captured_at)

    monkeypatch.setattr(dock_runtime, "detect_apriltag", blocked_detector)
    observer = asyncio.create_task(dock_runtime.observe_actual_dock(Head(), robot))
    try:
        assert await asyncio.wait_for(asyncio.to_thread(started.wait, 1), timeout=2)
        observer.cancel()
        with pytest.raises(asyncio.CancelledError):
            await observer

        busy = await dock_runtime.observe_actual_dock(Head(), robot)
        assert busy["source"] == "apriltag_detector_busy"
        assert busy["phase"] == "hold"
        assert not busy["motor_authorized"] and not busy["charging_authorized"]
        assert not busy["physical_acceptance_pass"]
        assert len(calls) == 1
    finally:
        release.set()
        if not observer.done():
            observer.cancel()
            await asyncio.gather(observer, return_exceptions=True)

    for _ in range(100):
        if dock_runtime._DETECTOR_SLOT.acquire(blocking=False):
            dock_runtime._DETECTOR_SLOT.release()
            break
        await asyncio.sleep(0.01)
    else:
        pytest.fail("Native detector did not release slot after worker completion")

    recovered = await dock_runtime.observe_actual_dock(Head(), robot)
    assert recovered["source"] == "head_jpeg_observed_on_mac_receipt"
    assert not recovered["motor_authorized"] and not recovered["charging_authorized"]
    assert not recovered["physical_acceptance_pass"]
    assert len(calls) == 2



async def test_cancel_asyncio_future_while_native_detector_runs_still_holds_slot(
    tmp_path, monkeypatch,
):
    """Cancelling the asyncio wrapper cannot make active C work seem finished."""
    import asyncio
    import threading

    path = tmp_path / "dock.json"
    path.write_text(json.dumps({
        "measured": True, "robot_id": "robot-01", "head_device_id": "xiaozhi-01", "camera_sensor_pid": "OV5640", "fx": 410, "fy": 410, "cx": 320, "cy": 240,
        "tag_side_mm": 60, "marker_id": 12, "target_distance_mm": 120,
    }))
    robot = SimpleNamespace(id="robot-01", dock_calibration=path)
    started, release = threading.Event(), threading.Event()
    wrappers = []
    calls = []
    original_wrap = asyncio.wrap_future

    def tracked_wrap(native_future, *args, **kwargs):
        wrapper = original_wrap(native_future, *args, **kwargs)
        wrappers.append(wrapper)
        return wrapper

    def blocked_detector(image, calibration, *, captured_at):
        calls.append(captured_at)
        started.set()
        if not release.wait(timeout=5):
            raise TimeoutError("Detector test release was not signalled")
        return DockPose(0, 0, 450, 0.5, captured_at)

    monkeypatch.setattr(dock_runtime.asyncio, "wrap_future", tracked_wrap)
    monkeypatch.setattr(dock_runtime, "detect_apriltag", blocked_detector)
    observer = asyncio.create_task(dock_runtime.observe_actual_dock(Head(), robot))
    try:
        assert await asyncio.wait_for(asyncio.to_thread(started.wait, 1), timeout=2)
        assert wrappers
        # Simulate the event loop cancelling its adapter task at shutdown.
        wrappers[0].cancel()
        with pytest.raises(asyncio.CancelledError):
            await observer
        busy = await dock_runtime.observe_actual_dock(Head(), robot)
        assert busy["source"] == "apriltag_detector_busy"
        assert busy["phase"] == "hold"
        assert not busy["motor_authorized"] and not busy["charging_authorized"]
        assert len(calls) == 1
    finally:
        release.set()
        if not observer.done():
            observer.cancel()
            await asyncio.gather(observer, return_exceptions=True)

    for _ in range(100):
        if dock_runtime._DETECTOR_SLOT.acquire(blocking=False):
            dock_runtime._DETECTOR_SLOT.release()
            break
        await asyncio.sleep(0.01)
    else:
        pytest.fail("Completed native detector never released its slot")
    recovered = await dock_runtime.observe_actual_dock(Head(), robot)
    assert recovered["source"] == "head_jpeg_observed_on_mac_receipt"
    assert len(calls) == 2
    assert not recovered["motor_authorized"] and not recovered["charging_authorized"]


@pytest.mark.parametrize("failure", [RuntimeError("Executor unavailable"), ValueError("Bad executor submission")])
async def test_detector_executor_submission_failure_releases_slot(tmp_path, monkeypatch, failure):
    """A rejected native job must not permanently block subsequent observations."""
    import asyncio

    path = tmp_path / "dock.json"
    path.write_text(json.dumps({
        "measured": True, "robot_id": "robot-01", "head_device_id": "xiaozhi-01", "camera_sensor_pid": "OV5640", "fx": 410, "fy": 410, "cx": 320, "cy": 240,
        "tag_side_mm": 60, "marker_id": 12, "target_distance_mm": 120,
    }))
    robot = SimpleNamespace(id="robot-01", dock_calibration=path)
    original_submit = dock_runtime._DETECTOR_POOL.submit

    def rejected_submit(*args, **kwargs):
        raise failure

    monkeypatch.setattr(dock_runtime._DETECTOR_POOL, "submit", rejected_submit)
    first_head = Head()
    failed = await dock_runtime.observe_actual_dock(first_head, robot)
    assert failed["phase"] == "hold"
    assert failed["source"] == "apriltag_detection_failed"
    assert failed["pose"] is None
    assert not failed["motor_authorized"] and not failed["charging_authorized"]
    assert failed["physical_acceptance_pass"] is False
    assert first_head.commands == []

    monkeypatch.setattr(dock_runtime._DETECTOR_POOL, "submit", original_submit)
    monkeypatch.setattr(
        dock_runtime, "detect_apriltag",
        lambda image, calibration, *, captured_at:
            DockPose(0, 0, 450, 0.5, captured_at),
    )
    recovered = await asyncio.wait_for(
        dock_runtime.observe_actual_dock(Head(), robot), timeout=3
    )
    assert recovered["source"] == "head_jpeg_observed_on_mac_receipt"
    assert not recovered["motor_authorized"] and not recovered["charging_authorized"]
    assert recovered["physical_acceptance_pass"] is False


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
    monkeypatch.setattr(dock_runtime, "detect_apriltag", detector)
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
    from desk_robot.controller import _bounded_head_reply as real_bounded

    # Tighten only this diagnostic's deadline in the test while exercising
    # the same real bounded helper used by physical motion safety.
    async def tiny_deadline(coro, *, seconds, timeout_message):
        return await real_bounded(coro, seconds=0.04,
                                  timeout_message=timeout_message)
    monkeypatch.setattr("desk_robot.controller._bounded_head_reply", tiny_deadline)

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
    monkeypatch.setattr(
        dock_runtime, "detect_apriltag",
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
    monkeypatch.setattr(
        dock_runtime, "detect_apriltag",
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

    monkeypatch.setattr(
        dock_runtime, "detect_apriltag",
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

    monkeypatch.setattr(dock_runtime, "detect_apriltag", detector)
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
    monkeypatch.setattr(
        dock_runtime, "detect_apriltag",
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

    monkeypatch.setattr(dock_runtime, "detect_apriltag", slow_detector)
    head = DelayedFrame()
    result = await dock_runtime.observe_actual_dock(
        head, SimpleNamespace(id="robot-01", dock_calibration=calibration)
    )
    assert result["phase"] == "hold"
    assert "stale" in result["reason"].lower()
    assert not result["motor_authorized"] and not result["charging_authorized"]
    assert head.commands == []



async def test_close_native_detector_retires_idle_pool_before_new_runtime(
    monkeypatch,
):
    """A normal Runtime restart gets a new single native worker, not a leak."""
    from types import SimpleNamespace

    old = dock_runtime._DETECTOR_POOL
    monkeypatch.setattr(
        dock_runtime, "detect_apriltag",
        lambda jpeg, calibration, *, captured_at: DockPose(
            0, 0, 400, 0.5, captured_at,
        ),
    )
    await dock_runtime.close_detector_pool()
    assert dock_runtime._DETECTOR_POOL is not old
    with pytest.raises(RuntimeError):
        old.submit(lambda: None)
    result = await dock_runtime.detect_bounded(
        b"fake-frame", SimpleNamespace(), captured_at=1.0,
    )
    assert result.z_mm == 400
    await dock_runtime.close_detector_pool()


async def test_close_native_detector_refuses_restart_until_process_reset(
    monkeypatch,
):
    """One hung native C worker cannot be replaced by a second unsafe pool."""
    import asyncio
    import threading
    from types import SimpleNamespace

    entered, release = threading.Event(), threading.Event()

    def blocked(jpeg, calibration, *, captured_at):
        entered.set()
        release.wait(timeout=5)
        return DockPose(0, 0, 450, 0.5, captured_at)

    monkeypatch.setattr(dock_runtime, "detect_apriltag", blocked)
    # Restore the global latched fault after this test; production never
    # clears it except via restart of the Mac process.
    monkeypatch.setattr(dock_runtime, "_DETECTOR_RESTART_REQUIRED", False)
    monkeypatch.setattr(dock_runtime, "_DETECTOR_SHUTTING_DOWN", False)
    current_pool = dock_runtime._DETECTOR_POOL
    pending = asyncio.create_task(dock_runtime.detect_bounded(
        b"frame", SimpleNamespace(), captured_at=1.0,
    ))
    try:
        assert await asyncio.to_thread(entered.wait, 1.0)
        with pytest.raises(RuntimeError, match="restart Mac process"):
            await dock_runtime.close_detector_pool()
        assert dock_runtime._DETECTOR_RESTART_REQUIRED is True
        assert dock_runtime._DETECTOR_POOL is current_pool
        with pytest.raises(dock_runtime.DockDetectorBusy, match="restart Mac process"):
            await dock_runtime.detect_bounded(
                b"new frame", SimpleNamespace(), captured_at=2.0,
            )
    finally:
        release.set()
        await asyncio.wait_for(pending, timeout=2.0)
    assert dock_runtime._DETECTOR_RESTART_REQUIRED is True
    with pytest.raises(RuntimeError, match="restart Mac process"):
        await dock_runtime.close_detector_pool()


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
