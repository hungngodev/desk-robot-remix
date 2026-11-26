"""Real camera docking observation without a motor or charger permission."""
from __future__ import annotations

import json
import math
import time
from typing import Callable

from .dock_process import DetectorPool, DockDetectorBusy
from .dock_timing import DOCK_OBSERVATION_MAX_AGE_S, dock_age_is_fresh, dock_time_remaining
from .dock_vision import DockCameraCalibration, DockPose, assess_dock
from .operations import bounded_head_reply as _bounded_head_reply

# Shared by all five robots and both read-only and guarded dock paths.
_DETECTOR_POOL = DetectorPool()


def _unique_calibration_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """No last-key-wins ambiguity in measured or device-bound dock geometry."""
    fields: dict[str, object] = {}
    for key, value in pairs:
        if key in fields:
            raise ValueError("Repeated dock calibration JSON field: " + key)
        fields[key] = value
    return fields


def _reject_calibration_json_constant(token: str) -> None:
    raise ValueError("Nonfinite dock calibration JSON constant: " + token)


def load_real_dock_calibration(
    path, *, robot_id: str | None = None, head_device_id: str | None = None,
) -> tuple[DockCameraCalibration, float]:
    if path is None:
        raise ValueError("No dock calibration configured")
    data = json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=_unique_calibration_object,
        parse_constant=_reject_calibration_json_constant,
    )
    if (not isinstance(data, dict) or type(data.get("schema_version")) is not int
            or data["schema_version"] != 1):
        raise ValueError("Unsupported or missing dock camera schema_version")
    if data.get("measured") is not True:
        raise ValueError("Dock camera geometry is not physically measured")
    # A camera model, PID and frame size cannot establish the robot that
    # physically produced these checkerboard and mount measurements.
    if robot_id is not None and (
        type(robot_id) is not str or not robot_id
        or data.get("robot_id") != robot_id
        or type(data.get("head_device_id")) is not str
        or not data["head_device_id"]
    ):
        raise ValueError("Dock calibration robot/head identity missing or mismatched")
    if head_device_id is not None and (
        type(head_device_id) is not str or not head_device_id
        or data.get("head_device_id") != head_device_id
    ):
        raise ValueError("Dock calibration head device identity missing or mismatched")
    props = ("fx", "fy", "cx", "cy", "tag_side_mm", "marker_id")
    if any(key not in data for key in props):
        raise ValueError("Dock calibration lacks measured camera parameters")
    calibration = DockCameraCalibration(
        **{key: data[key] for key in props},
        distortion_coeffs=(
            tuple(data["distortion_coeffs"])
            if isinstance(data.get("distortion_coeffs"), list)
            else data.get("distortion_coeffs")
        ),
        image_width_px=data.get("image_width_px"),
        image_height_px=data.get("image_height_px"),
        camera_sensor_pid=data.get("camera_sensor_pid"),
        robot_id=data.get("robot_id"),
        head_device_id=data.get("head_device_id"),
        mount_lateral_offset_mm=data.get("mount_lateral_offset_mm"),
        mount_yaw_deg=data.get("mount_yaw_deg"),
    )
    target = data.get("target_distance_mm")
    if type(target) not in (float, int) or not 50 <= target <= 500 or not math.isfinite(target):
        raise ValueError("Dock stopping distance is not calibrated")
    return calibration, float(target)


def _hold(robot_id: str, *, reason: str, source: str) -> dict:
    """Return a non-authorizing diagnostic for failed dock observation."""
    return {
        "robot_id": robot_id, "phase": "hold", "reason": reason,
        "source": source, "pose": None,
        "motor_authorized": False, "charging_authorized": False,
        "physical_acceptance_pass": False,
    }


async def prewarm_detector_pool() -> None:
    """Warm native dependencies before acquiring a camera receipt."""
    await _DETECTOR_POOL.prewarm()


async def close_detector_pool() -> None:
    """Replace the owner only after every subprocess is confirmed reaped."""
    global _DETECTOR_POOL
    previous = _DETECTOR_POOL
    await previous.close()
    if _DETECTOR_POOL is previous:
        _DETECTOR_POOL = DetectorPool()


async def detect_bounded(jpeg: bytes, calibration: DockCameraCalibration, *,
                         captured_at: float) -> DockPose | None:
    """One isolated detector for diagnostics and permitted approach."""
    return await _DETECTOR_POOL.detect(jpeg, calibration, captured_at=captured_at)


def unpack_dock_frame(observation) -> tuple[bytes, float]:
    """Keep authenticated JPEG paired with its original Mac receipt clock.

    Legacy simulation heads return bare JPEG bytes. Real HttpHead returns an
    immutable (JPEG, received_at) pair from its camera condition lock.
    """
    now = time.monotonic()
    if isinstance(observation, bytes):
        return observation, now
    if (not isinstance(observation, tuple) or len(observation) not in (2, 4)
            or not isinstance(observation[0], bytes)
            or type(observation[1]) not in (int, float)):
        raise ValueError("Invalid or stale dock camera receipt")
    try:
        received_at = float(observation[1])
    except OverflowError as exc:
        # Python accepts arbitrarily large integers; math.isfinite(int)
        # itself raises OverflowError before our diagnostic HOLD can run.
        raise ValueError("Invalid or stale dock camera receipt") from exc
    if (not math.isfinite(received_at)
            or not dock_age_is_fresh(now - received_at, DOCK_OBSERVATION_MAX_AGE_S)):
        raise ValueError("Invalid or stale dock camera receipt")
    if len(observation) == 4:
        identity, generation = observation[2:]
        if (not isinstance(identity, tuple) or len(identity) != 3
                or any(type(n) is not int for n in identity)
                or not 0 <= identity[0] <= 0xffffffff
                or not 1 <= identity[1] <= 0xffffffff
                # Sense esp_timer_get_time() is signed int64 microseconds.
                # Match HttpHead.dock_receipt_current before any detector work.
                or not 1 <= identity[2] <= (1 << 63) - 1
                or type(generation) is not int or generation < 1):
            raise ValueError("Invalid or stale dock camera receipt")
    return observation[0], received_at


async def verify_selected_dock_frame(head, observation) -> None:
    """Reject stream replacement after an awaited dock vision or body call."""
    if isinstance(observation, tuple) and len(observation) == 4:
        verify = getattr(head, "dock_receipt_current", None)
        if not callable(verify):
            raise ValueError("Dock frame source verifier absent")
        # The verifier may wait on the live stream lock or an alternate
        # adapter. Its deadline is the original frame's remaining lifetime,
        # not a new timeout that would extend stale camera evidence.

        _, received_at = unpack_dock_frame(observation)
        remaining = dock_time_remaining(time.monotonic() - received_at)
        if remaining <= 0:
            raise ValueError("Invalid or stale dock camera receipt")
        verdict = await _bounded_head_reply(
            verify(observation), seconds=remaining,
            timeout_message="Dock frame source verification timed out",
        )
        # HttpHead has an exception-based, None-on-success contract. A
        # false or otherwise unexpected verdict must never authorize motion.
        if verdict is not None:
            raise ValueError("Dock frame source verification denied")
        # Even an apparently successful reply can arrive after the receipt
        # expired (for example while the event loop was busy).
        unpack_dock_frame(observation)


async def observe_actual_dock(
    head, robot, *, consent_valid: Callable[[], bool] | None = None,
) -> dict:
    """Real head JPEG in, real marker pose out. No movement is possible here.

    Time is captured at Mac JPEG receipt, not falsely claimed camera exposure.
    No drive, servo, arm or charge tools are imported or called. An optional
    API-grant callback prevents further visual processing after revocation.
    """
    def consent_denied() -> bool:
        return consent_valid is not None and not consent_valid()

    if consent_denied():
        return _hold(
            robot.id, reason="Camera consent revoked",
            source="camera_consent_revoked",
        )
    try:
        calib, target = load_real_dock_calibration(
            robot.dock_calibration, robot_id=robot.id,
            head_device_id=getattr(robot, "device_id", None),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        return _hold(robot.id, reason=f"Dock calibration required: {exc}", source="not_calibrated")
    # A camera model change invalidates checkerboard intrinsics even when
    # two sensors return equal-size JPEGs. A real numeric pose requires the
    # sensor PID actually measured for this dock calibration.
    if calib.camera_sensor_pid not in ("OV3660", "OV5640"):
        return _hold(
            robot.id, reason="Dock calibration needs actual camera sensor PID",
            source="not_calibrated",
        )
    if consent_denied():
        return _hold(robot.id, reason="Camera consent revoked",
                     source="camera_consent_revoked")
    try:
        # The native AprilTag slot must not be occupied by an alternate
        # head snapshot that suppresses coroutine cancellation indefinitely.
        # Read-only dock diagnostics should see the same current MJPEG
        # receipt as a guarded approach, not a near-one-second-old frame.
        async def capture_current_dock_frame():
            # The bounded reply starts in a child task on a later loop turn.
            if consent_denied():
                raise PermissionError("Camera consent revoked")
            capture_dock = getattr(head, "snapshot_for_dock", head.snapshot)
            return await capture_dock()

        observation = await _bounded_head_reply(
            capture_current_dock_frame(), seconds=3.0,
            timeout_message="Dock diagnostic camera snapshot timeout",
        )
    except (OSError, ConnectionError, TimeoutError, RuntimeError, ValueError) as exc:
        if consent_denied():
            return _hold(robot.id, reason="Camera consent revoked",
                         source="camera_consent_revoked")
        return _hold(
            robot.id, reason=f"Dock camera unavailable: {type(exc).__name__}",
            source="head_snapshot_failed",
        )
    if consent_denied():
        return _hold(robot.id, reason="Camera consent revoked",
                     source="camera_consent_revoked")
    try:
        jpeg, received_at = unpack_dock_frame(observation)
    except ValueError:
        return _hold(robot.id, reason="Invalid or stale dock camera receipt",
                     source="head_snapshot_invalid")
    # Reject malformed or oversized snapshots before occupying the sole native
    # AprilTag worker. Match the native detector's 512000-byte bound.
    if (not isinstance(jpeg, bytes) or len(jpeg) < 4 or len(jpeg) > 512000
            or not jpeg.startswith(b"\xff\xd8") or not jpeg.endswith(b"\xff\xd9")):
        return _hold(robot.id, reason="Invalid dock JPEG", source="head_snapshot_invalid")
    # Compare live Espressif PID with the just-accepted JPEG boot identity.
    # HttpHead.camera_identity rejects a different or retired Sense boot;
    # a saved calibration field alone cannot establish physical provenance.
    read_identity = getattr(head, "camera_identity", None)
    if not callable(read_identity):
        return _hold(
            robot.id, reason="Dock camera live sensor identity unavailable",
            source="camera_identity_unavailable",
        )
    remaining = dock_time_remaining(time.monotonic() - received_at)
    if remaining <= 0:
        return _hold(
            robot.id, reason="Dock camera receipt expired before identity check",
            source="head_snapshot_invalid",
        )
    try:
        observed_pid = await _bounded_head_reply(
            (read_identity(observation) if isinstance(observation, tuple)
             and len(observation) == 4 else read_identity()), seconds=remaining,
            timeout_message="Dock camera live sensor identity timeout",
        )
    except Exception as exc:
        # Cancellation propagates; asyncio.CancelledError is BaseException.
        return _hold(
            robot.id,
            reason=f"Dock camera live identity unavailable: {type(exc).__name__}",
            source="camera_identity_unavailable",
        )
    if consent_denied():
        return _hold(robot.id, reason="Camera consent revoked",
                     source="camera_consent_revoked")
    if observed_pid != calib.camera_sensor_pid:
        return _hold(
            robot.id, reason="Dock camera sensor PID differs from calibration",
            source="camera_identity_mismatch",
        )
    # Identity may be slow; never refresh the original JPEG receipt clock.
    if time.monotonic() - received_at > DOCK_OBSERVATION_MAX_AGE_S:
        return _hold(
            robot.id, reason="Dock camera receipt expired during identity check",
            source="head_snapshot_invalid",
        )
    if consent_denied():
        return _hold(robot.id, reason="Camera consent revoked",
                     source="camera_consent_revoked")
    try:
        pose = await detect_bounded(jpeg, calib, captured_at=received_at)
    except DockDetectorBusy as exc:
        return _hold(
            robot.id, reason=str(exc),
            source="apriltag_detector_busy",
        )
    except TimeoutError:
        return _hold(
            robot.id, reason="Stale dock camera receipt: AprilTag deadline expired",
            source="apriltag_detection_failed",
        )
    except Exception as exc:
        # Malformed IPC and native decoder failures never grant rights.
        # Do not catch BaseException: cancellation must still propagate.
        return _hold(
            robot.id,
            reason=f"Dock marker detection unavailable: {type(exc).__name__}",
            source="apriltag_detection_failed",
        )
    if consent_denied():
        return _hold(robot.id, reason="Camera consent revoked",
                     source="camera_consent_revoked")
    # The native detector can finish after a same-PID stream reconnect.
    try:
        await verify_selected_dock_frame(head, observation)
    except Exception as exc:
        return _hold(
            robot.id, reason=f"Dock frame source changed: {type(exc).__name__}",
            source="head_snapshot_invalid",
        )
    if consent_denied():
        return _hold(robot.id, reason="Camera consent revoked",
                     source="camera_consent_revoked")
    # A corrupted native adapter result must not escape as a plausible dock
    # phase or crash the observer after the detector worker has completed.
    if pose is not None and not isinstance(pose, DockPose):
        return _hold(
            robot.id, reason="Dock marker detector returned invalid pose",
            source="apriltag_detection_failed",
        )
    # Receipt timestamp is not the end of OpenCV computation. A slow or
    # stalled detector cannot authorize a now-stale dock observation.
    # Report alignment relative to the TRACK CENTERLINE when the camera's
    # measured mount offset exists. A centered lens view is not necessarily
    # a centered dock approach. Preserve raw camera coordinates separately.
    assessed_pose = pose
    chassis_lateral = None
    if pose is not None and calib.mount_lateral_offset_mm is not None:
        try:
            chassis_lateral = calib.chassis_lateral_mm(pose)
            assessed_pose = DockPose(
                chassis_lateral, pose.y_mm, pose.z_mm,
                pose.reprojection_error_px, pose.captured_at,
            )
        except ValueError:
            return _hold(
                robot.id, reason="Invalid measured camera to chassis transform",
                source="dock_mount_geometry_invalid",
            )
    assessment = assess_dock(
        assessed_pose, now=time.monotonic(), target_distance_mm=target
    )
    if consent_denied():
        return _hold(robot.id, reason="Camera consent revoked",
                     source="camera_consent_revoked")
    return {
        "robot_id": robot.id, "phase": assessment.phase,
        "reason": assessment.reason,
        "source": "head_jpeg_observed_on_mac_receipt",
        "pose": (
            {
                "x_mm": pose.x_mm, "y_mm": pose.y_mm, "z_mm": pose.z_mm,
                "reprojection_error_px": pose.reprojection_error_px,
                "chassis_lateral_mm": chassis_lateral,
            } if pose is not None else None
        ),
        "motor_authorized": False,
        "charging_authorized": False,
        "physical_acceptance_pass": False,
    }
