"""Dock-marker perception adapter using OpenCV's established AprilTag dictionary.

This module performs calibrated geometric observation only. It never starts a
Coordinator job, arms the body, selects an actuator command, or tells a charging
controller to energize contacts. The robot's existing WROOM cliff/bumper/lease
path remains the sole movement authority.

Reuse: OpenCV's ArUco detector and SOLVEPNP_IPPE_SQUARE implementation.
https://docs.opencv.org/4.x/d5/dae/tutorial_aruco_detection.html
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .vision import _check_camera_jpeg


def _finite_number(value: object) -> bool:
    """Reject huge integers without leaking float conversion OverflowError."""
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


@dataclass(frozen=True)
class DockCameraCalibration:
    """Real measured camera intrinsics and physical marker side length."""

    fx: float
    fy: float
    cx: float
    cy: float
    tag_side_mm: float
    marker_id: int
    distortion_coeffs: tuple[float, ...] | None = None
    image_width_px: int | None = None
    image_height_px: int | None = None
    # Camera PID is calibration provenance, not a self-attested motor permit.
    camera_sensor_pid: str | None = None
    # Measured camera lens offset relative to the chassis centerline, right
    # positive, and horizontal yaw pointing right relative to chassis forward.
    # Image intrinsics alone cannot establish either mounting dimension.
    mount_lateral_offset_mm: float | None = None
    mount_yaw_deg: float | None = None
    # Append rather than shifting existing positional mount parameters.
    # Recorded builder provenance, not cryptographic camera attestation.
    robot_id: str | None = None
    head_device_id: str | None = None

    def __post_init__(self):
        for name in ("fx", "fy", "cx", "cy", "tag_side_mm"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{name} must be a measured finite number")
            if not _finite_number(value):
                raise ValueError(f"{name} must be finite")
        if self.fx <= 0 or self.fy <= 0 or not 10 <= self.tag_side_mm <= 250:
            raise ValueError("Camera focal lengths and physical tag size are invalid")
        if self.cx < 0 or self.cy < 0:
            raise ValueError("Camera optical center must be nonnegative")
        if ((self.image_width_px is None) !=
                (self.image_height_px is None)):
            raise ValueError("Dock calibration must specify both image dimensions")
        if self.image_width_px is not None and (
            type(self.image_width_px) is not int
            or type(self.image_height_px) is not int
            or not 80 <= self.image_width_px <= 2048
            or not 80 <= self.image_height_px <= 1536
        ):
            raise ValueError("Invalid measured dock camera image resolution")
        if self.image_width_px is not None and (
            self.cx >= self.image_width_px or self.cy >= self.image_height_px
        ):
            raise ValueError("Dock optical center lies outside measured image")
        # Match calibrate_dock_camera.fit_corners: loaded measured intrinsics
        # must not bypass the fitter's resolution-relative focal envelope.
        if self.image_width_px is not None and (
            not self.image_width_px * .1 <= self.fx <= self.image_width_px * 10
            or not self.image_height_px * .1 <= self.fy <= self.image_height_px * 10
        ):
            raise ValueError("Dock camera focal lengths outside measured resolution envelope")
        if self.camera_sensor_pid is not None and self.camera_sensor_pid not in (
            "OV3660", "OV5640"
        ):
            raise ValueError("Dock camera calibration names unsupported camera PID")
        for field_name in ("robot_id", "head_device_id"):
            value = getattr(self, field_name)
            if value is not None and (
                type(value) is not str or not value.strip()
                or value.strip() != value or len(value) > 160
            ):
                raise ValueError(f"Invalid dock calibration {field_name}")
        if self.distortion_coeffs is not None:
            if (not isinstance(self.distortion_coeffs, tuple)
                    or len(self.distortion_coeffs) not in (4, 5, 8, 12, 14)
                    or any(type(v) not in (int, float) or not _finite_number(v)
                           for v in self.distortion_coeffs)):
                raise ValueError("Invalid measured camera distortion coefficients")
        if type(self.marker_id) is not int or not 0 <= self.marker_id < 587:
            raise ValueError("AprilTag 36h11 marker ID out of range")
        # A measured offset and yaw are a pair. Never silently treat the
        # missing side of a mount calibration as a perfect centerline.
        if ((self.mount_lateral_offset_mm is None)
                != (self.mount_yaw_deg is None)):
            raise ValueError("Camera mount lateral offset and yaw must both be measured")
        if self.mount_lateral_offset_mm is not None:
            if (type(self.mount_lateral_offset_mm) not in (int, float)
                    or type(self.mount_yaw_deg) not in (int, float)
                    or not _finite_number(self.mount_lateral_offset_mm)
                    or not _finite_number(self.mount_yaw_deg)
                    or not -100 <= self.mount_lateral_offset_mm <= 100
                    or not -20 <= self.mount_yaw_deg <= 20):
                raise ValueError("Camera mount offset or yaw outside measured limits")

    def chassis_lateral_mm(self, pose: DockPose) -> float:
        """Transform the AprilTag camera x/z into the drive centerline.

        A pose is a camera observation, not a chassis alignment. The
        operator must first measure the lens position and yaw on the actual
        assembled frame before this geometry may steer wheels.
        """
        if self.mount_lateral_offset_mm is None or self.mount_yaw_deg is None:
            raise ValueError("Dock chassis camera mounting geometry unmeasured")
        yaw = math.radians(self.mount_yaw_deg)
        lateral = (self.mount_lateral_offset_mm
                   + pose.x_mm * math.cos(yaw) + pose.z_mm * math.sin(yaw))
        # Individually finite native pose values can overflow when transformed.
        # Never pass an infinite chassis offset into a docking alignment gate.
        if not math.isfinite(lateral):
            raise ValueError("Dock chassis lateral transform is not finite")
        return lateral


@dataclass(frozen=True)
class DockPose:
    """Camera-relative tag location, not a robot position measurement."""

    x_mm: float
    y_mm: float
    z_mm: float
    reprojection_error_px: float
    captured_at: float

    def __post_init__(self):
        for value in (self.x_mm, self.y_mm, self.z_mm,
                      self.reprojection_error_px, self.captured_at):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError("Dock pose contains nonnumeric values")
            if not _finite_number(value):
                raise ValueError("Dock pose must be finite")
        if self.z_mm <= 0 or self.reprojection_error_px < 0:
            raise ValueError("Dock pose must be physically meaningful")


def detect_apriltag(
    jpeg: bytes,
    calibration: DockCameraCalibration,
    *,
    captured_at: float,
    max_reprojection_error_px: float = 3.0,
) -> DockPose | None:
    """Use OpenCV AprilTag 36h11 + square PnP, never a guessed distance.

    Requires explicit calibration from the actual XIAO Sense camera. No
    detector is loaded for any other command or on startup. Returns None if a
    valid marker pose is unavailable or untrusted. The original image is not
    written to disk and no motors are touched.
    """
    if (not isinstance(jpeg, bytes) or not 0 < len(jpeg) <= 512000
            or any(type(v) not in (int, float) or not _finite_number(v)
                   for v in (captured_at, max_reprojection_error_px))
            or not 0 < max_reprojection_error_px <= 10):
        raise ValueError("Invalid bounded camera frame or timing")
    # imdecode accepts other image formats and allocates the decoded raster.
    # Reuse the camera header gate before invoking the native decoder.
    try:
        encoded_size = _check_camera_jpeg(jpeg, max_bytes=512000)
    except (OSError, ValueError) as exc:
        raise ValueError("Invalid JPEG frame") from exc
    if (calibration.image_width_px is not None
            and encoded_size != (calibration.image_width_px, calibration.image_height_px)):
        raise ValueError("Dock JPEG resolution differs from measured intrinsics")
    try:
        import cv2
        import numpy as np
    except ImportError as exc:
        raise RuntimeError("Install the existing vision extra for OpenCV AprilTag") from exc
    try:
        # Intrinsics describe the encoded sensor coordinates, not EXIF display
        # orientation. A 180-degree rotation even preserves image dimensions.
        frame = cv2.imdecode(
            np.frombuffer(jpeg, dtype=np.uint8),
            cv2.IMREAD_GRAYSCALE | cv2.IMREAD_IGNORE_ORIENTATION,
        )
    except cv2.error:
        return None  # A native decoder failure is not a trusted dock observation
    if (frame is None or not isinstance(frame, np.ndarray)
            or frame.ndim != 2 or frame.dtype != np.uint8 or frame.size == 0
            or frame.shape[0] < 1 or frame.shape[1] < 1):
        raise ValueError("Invalid JPEG frame")
    # OpenCV intrinsics and distortion belong to one exact capture mode.
    # Camera mode changes invalidate pose geometry, not just image quality.
    if (frame.shape[1], frame.shape[0]) != encoded_size:
        raise ValueError("Dock JPEG resolution differs from encoded image")
    try:
        dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_APRILTAG_36h11)
        detector = cv2.aruco.ArucoDetector(dictionary)
        corners, ids, _rejected = detector.detectMarkers(frame)
    except (cv2.error, TypeError, ValueError):
        return None  # Malformed native detector result is not a dock observation
    if ids is None:
        return None
    # A native detector may return IDs alongside missing or malformed corners.
    # Validate the container before calling len() or indexing a marker.
    if not isinstance(corners, (list, tuple)):
        return None
    # Native detector IDs must be a one-column integer array matching corners.
    # Never truncate floats, accept booleans, or index with a corrupt ID list.
    if (not isinstance(ids, np.ndarray) or ids.ndim != 2
            or ids.shape != (len(corners), 1)
            or ids.dtype.kind not in ("i", "u")):
        return None
    candidates = [i for i, marker in enumerate(ids[:, 0])
                  if marker == calibration.marker_id]
    if len(candidates) != 1:
        return None
    # A detector can return corrupt or off-frame corners. Never feed them to
    # native PnP or treat the resulting pose as an approach observation.
    # Native detectors may return a corrupt corner count or nonnumeric shape.
    # Reject it before reshape or solvePnP; neither is a motion authority.
    try:
        raw_points = np.asarray(corners[candidates[0]], dtype=np.float64)
    except (IndexError, TypeError, ValueError, OverflowError):
        return None
    if raw_points.size != 8 or raw_points.shape not in ((1, 4, 2), (4, 2)):
        return None
    image_points = raw_points.reshape(4, 2)
    if (not np.isfinite(image_points).all()
            or np.any(image_points[:, 0] < 0)
            or np.any(image_points[:, 0] >= frame.shape[1])
            or np.any(image_points[:, 1] < 0)
            or np.any(image_points[:, 1] >= frame.shape[0])):
        return None
    # Four in-frame corners can still describe a collapsed or crossed square.
    # Reject subpixel/degenerate quads before native PnP can fit an unstable
    # pose with deceptively small reprojection error.
    edges = np.roll(image_points, -1, axis=0) - image_points
    if np.any(np.sum(edges * edges, axis=1) < 4.0):
        return None
    x, y = image_points[:, 0], image_points[:, 1]
    signed_twice_area = np.sum(x * np.roll(y, -1) - y * np.roll(x, -1))
    if not np.isfinite(signed_twice_area) or abs(signed_twice_area) < 32.0:
        return None
    # Area alone does not reject asymmetric bowties or concave quads.
    # ArucoDetector returns clockwise corners in image coordinates (y down).
    turns = (edges[:, 0] * np.roll(edges[:, 1], -1)
             - edges[:, 1] * np.roll(edges[:, 0], -1))
    if (not np.isfinite(turns).all()
            or not np.all(turns > 0)):
        return None
    side = calibration.tag_side_mm / 2
    object_points = np.array([
        [-side, side, 0], [side, side, 0],
        [side, -side, 0], [-side, -side, 0],
    ], dtype=np.float64)
    intrinsics = np.array([
        [calibration.fx, 0, calibration.cx],
        [0, calibration.fy, calibration.cy],
        [0, 0, 1],
    ], dtype=np.float64)
    # Legacy unqualified observations retain zero distortion; measured optics
    # can be supplied without introducing a second detector or motion owner.
    distortion = np.asarray(
        calibration.distortion_coeffs if calibration.distortion_coeffs is not None
        else (0.0,) * 5, dtype=np.float64,
    ).reshape(-1, 1)
    # OpenCV #30402: IPPE's rotation-vector conversion can return a flipped
    # high-error pose for a front-facing planar tag near 180 degrees. Retry
    # once with OpenCV's planar iterative solver only when the reprojection
    # is untrustworthy. A reliable but out-of-envelope pose must stay rejected.
    for method in (cv2.SOLVEPNP_IPPE_SQUARE, cv2.SOLVEPNP_ITERATIVE):
        try:
            success, rvec, tvec = cv2.solvePnP(
                object_points, image_points, intrinsics, distortion, flags=method,
            )
            if not success:
                return None
            projected, _ = cv2.projectPoints(object_points, rvec, tvec,
                                             intrinsics, distortion)
            normal = cv2.Rodrigues(rvec)[0][:, 2]
            projected = np.asarray(projected, dtype=np.float64).reshape(4, 2)
            translation = np.asarray(tvec, dtype=np.float64).reshape(3)
        except (cv2.error, ValueError, TypeError, IndexError, OverflowError):
            return None  # Native pose failure cannot authorize contact approach
        # A pooled RMS can hide one bad corner (5 px / sqrt(4) = 2.5 px).
        # Every corner must satisfy the budget; retain RMS in the pose receipt.
        residual = projected - image_points
        corner_errors = np.hypot(residual[:, 0], residual[:, 1])
        if (not np.isfinite(corner_errors).all()
                or np.any(corner_errors > max_reprojection_error_px)):
            continue
        error = float(np.sqrt(np.mean(corner_errors ** 2)))
        # The physical printed face must point toward the camera. A good
        # reprojection is not permission to relax the existing angle gate.
        if (normal.shape != (3,) or not np.isfinite(normal).all()
                or normal[2] > -math.cos(math.radians(45))):
            return None
        x_mm, y_mm, z_mm = [float(v) for v in translation]
        if (not all(_finite_number(v) for v in (x_mm, y_mm, z_mm))
                or not 30 <= z_mm <= 2000):
            return None
        # Optical-axis tilt alone misses grazing views of off-center tags.
        # Compare the printed-face normal with the actual ray to the lens.
        incidence = -float(normal @ (translation / math.hypot(x_mm, y_mm, z_mm)))
        if not math.isfinite(incidence) or incidence < math.cos(math.radians(45)):
            return None
        return DockPose(x_mm, y_mm, z_mm, error, captured_at)
    return None


@dataclass(frozen=True)
class DockAssessment:
    """An operator-readable analysis, explicitly NOT a drive command."""

    phase: str
    reason: str
    motor_authorized: bool = False
    charging_authorized: bool = False


def assess_dock(
    pose: DockPose | None, *,
    now: float,
    target_distance_mm: float,
    max_age_seconds: float = 0.20,
    lateral_tolerance_mm: float = 15.0,
) -> DockAssessment:
    """Plan only; never infer docking contact from an AprilTag image.

    Distance to final contacts, clearance, bumper transition and real charger
    sensing all require their own qualified gates. Even a good pose can only
    recommend an alignment phase, not issue a WROOM motor permit.
    """
    if any(isinstance(v, bool) or not isinstance(v, (int, float))
           or not _finite_number(v) for v in
           (now, target_distance_mm, max_age_seconds, lateral_tolerance_mm)):
        raise ValueError("Invalid dock assessment parameters")
    if not 50 <= target_distance_mm <= 500 or not 0 < max_age_seconds <= 1:
        raise ValueError("Dock approach calibration outside bounds")
    if not 2 <= lateral_tolerance_mm <= 100:
        raise ValueError("Dock lateral tolerance outside bounds")
    if pose is None:
        return DockAssessment("hold", "No identified, calibrated target")
    age = now - pose.captured_at
    if not 0 <= age <= max_age_seconds:
        return DockAssessment("hold", "Marker observation stale or from the future")
    if pose.reprojection_error_px > 3:
        return DockAssessment("hold", "Marker geometry untrusted")
    if pose.z_mm <= target_distance_mm:
        return DockAssessment("hold", "Approach limit reached; physical contacts unverified")
    if abs(pose.x_mm) > lateral_tolerance_mm:
        return DockAssessment(
            "align", "Marker offset requires separately qualified swept turn"
        )
    return DockAssessment(
        "approach", "Marker centered; require full floor and bumper guard"
    )
