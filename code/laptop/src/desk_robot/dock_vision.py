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

    def __post_init__(self):
        for name in ("fx", "fy", "cx", "cy", "tag_side_mm"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{name} must be a measured finite number")
            if not math.isfinite(value):
                raise ValueError(f"{name} must be finite")
        if self.fx <= 0 or self.fy <= 0 or not 10 <= self.tag_side_mm <= 250:
            raise ValueError("Camera focal lengths and physical tag size are invalid")
        if self.cx < 0 or self.cy < 0:
            raise ValueError("Camera optical center must be nonnegative")
        if self.distortion_coeffs is not None:
            if (not isinstance(self.distortion_coeffs, tuple)
                    or len(self.distortion_coeffs) not in (4, 5, 8, 12, 14)
                    or any(type(v) not in (int, float) or not math.isfinite(v)
                           for v in self.distortion_coeffs)):
                raise ValueError("Invalid measured camera distortion coefficients")
        if type(self.marker_id) is not int or not 0 <= self.marker_id < 587:
            raise ValueError("AprilTag 36h11 marker ID out of range")


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
            if not math.isfinite(value):
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
            or any(type(v) not in (int, float) or not math.isfinite(v)
                   for v in (captured_at, max_reprojection_error_px))
            or not 0 < max_reprojection_error_px <= 10):
        raise ValueError("Invalid bounded camera frame or timing")
    try:
        import cv2
        import numpy as np
    except ImportError as exc:
        raise RuntimeError("Install the existing vision extra for OpenCV AprilTag") from exc
    frame = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    if frame is None or frame.size == 0:
        raise ValueError("Invalid JPEG frame")
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_APRILTAG_36h11)
    detector = cv2.aruco.ArucoDetector(dictionary)
    corners, ids, _rejected = detector.detectMarkers(frame)
    if ids is None:
        return None
    candidates = [i for i, marker in enumerate(ids.flatten())
                  if int(marker) == calibration.marker_id]
    if len(candidates) != 1:
        return None
    image_points = np.asarray(corners[candidates[0]], dtype=np.float64).reshape(4, 2)
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
    success, rvec, tvec = cv2.solvePnP(
        object_points, image_points, intrinsics, distortion,
        flags=cv2.SOLVEPNP_IPPE_SQUARE,
    )
    if not success:
        return None
    projected, _ = cv2.projectPoints(object_points, rvec, tvec,
                                     intrinsics, distortion)
    error = float(np.sqrt(np.mean(np.sum(
        (projected.reshape(4, 2) - image_points) ** 2, axis=1,
    ))))
    x_mm, y_mm, z_mm = [float(v) for v in tvec.reshape(3)]
    if (not all(math.isfinite(v) for v in (x_mm, y_mm, z_mm, error))
            or not 30 <= z_mm <= 2000 or error > max_reprojection_error_px):
        return None
    return DockPose(x_mm, y_mm, z_mm, error, captured_at)


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
           or not math.isfinite(v) for v in
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
