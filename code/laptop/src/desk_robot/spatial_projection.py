"""Fixed Sense camera pixel-to-floor projection, guarded by measured geometry.

Reuses the existing DockCameraCalibration lens, PID, resolution and distortion
contract. A checkerboard result by itself lacks mount height, pitch and the
visible supported floor polygon. Synthetic tests do not qualify a real robot.
OpenCV undistortPoints is used only when measured distortion is nonzero.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .dock_vision import DockCameraCalibration, _finite_number
from .spatial_frames import rotate_xy


class ProjectionError(ValueError):
    """No validated ground intersection exists for this pixel."""


@dataclass(frozen=True)
class ProjectedFloorPoint:
    x_mm: float  # base_link +X forward
    y_mm: float  # base_link +Y left
    uncertainty_mm: float
    calibration_id: str
    frame: str = "base_link"


@dataclass(frozen=True)
class FloorProjectionCalibration:
    lens: DockCameraCalibration
    calibration_id: str
    camera_height_mm: float  # Installed optical center above the actual floor (Z up).
    camera_forward_offset_mm: float  # Signed base_link X: positive ahead of origin.
    pitch_down_deg: float  # Positive below horizontal, not tilt from vertical.
    valid_pixel_roi: tuple[int, int, int, int]  # left, top, right, bottom
    valid_forward_mm: tuple[float, float]
    valid_lateral_mm: tuple[float, float]
    uncertainty_mm: float
    measured: bool = False
    min_downward_ray: float = 0.15

    def __post_init__(self):
        if not isinstance(self.lens, DockCameraCalibration):
            raise ProjectionError("Existing dock lens calibration required")
        if (type(self.calibration_id) is not str or not self.calibration_id
                or len(self.calibration_id) > 96
                or not self.calibration_id.replace("_", "").replace("-", "").isalnum()):
            raise ProjectionError("Invalid calibration identity")
        for name, lo, hi in (
            ("camera_height_mm", 10, 500),
            ("camera_forward_offset_mm", -250, 250),
            ("pitch_down_deg", 1, 89),
            ("uncertainty_mm", 1, 500),
            ("min_downward_ray", 0.1, 0.95),
        ):
            value = getattr(self, name)
            if (not _finite_number(value)
                    or not lo <= value <= hi):
                raise ProjectionError(f"Invalid measured camera {name}")
        if (type(self.valid_pixel_roi) is not tuple or len(self.valid_pixel_roi) != 4
                or any(type(x) is not int for x in self.valid_pixel_roi)):
            raise ProjectionError("Invalid calibrated visible image ROI")
        if (self.lens.image_width_px is None or self.lens.image_height_px is None
                or self.lens.camera_sensor_pid not in ("OV3660", "OV5640")
                or self.lens.distortion_coeffs is None
                or self.lens.mount_lateral_offset_mm is None
                or self.lens.mount_yaw_deg is None):
            raise ProjectionError("Lens and measured mount geometry incomplete")
        left, top, right, bottom = self.valid_pixel_roi
        if not (0 <= left < right <= self.lens.image_width_px
                and 0 <= top < bottom <= self.lens.image_height_px):
            raise ProjectionError("Visible floor crop exceeds measured resolution")
        for bounds in (self.valid_forward_mm, self.valid_lateral_mm):
            if (type(bounds) is not tuple or len(bounds) != 2
                    or any(not _finite_number(v)
                           for v in bounds) or bounds[0] >= bounds[1]
                    or any(abs(v) > 5000 for v in bounds)):
                raise ProjectionError("Invalid bounded calibrated floor region")
        if type(self.measured) is not bool:
            raise ProjectionError("Physical calibration qualification must be boolean")

    def project(
        self, u: float, v: float, *, image_width: int, image_height: int,
        camera_sensor_pid: str,
    ) -> ProjectedFloorPoint:
        """Intersect one undistorted pixel ray with z=0 in base_link.

        This geometric point is never an occupancy or cliff clearance. Even a
        correct ground projection requires separate fresh floor evidence.
        """
        if self.measured is not True:
            raise ProjectionError("Actual measured camera geometry required")
        if (type(image_width) is not int or type(image_height) is not int
                or (image_width, image_height) !=
                (self.lens.image_width_px, self.lens.image_height_px)
                or type(camera_sensor_pid) is not str
                or camera_sensor_pid != self.lens.camera_sensor_pid):
            raise ProjectionError("Live camera PID or resolution mismatches intrinsics")
        if (not _finite_number(u) or not _finite_number(v)
                or not (self.valid_pixel_roi[0] <= u < self.valid_pixel_roi[2])
                or not (self.valid_pixel_roi[1] <= v < self.valid_pixel_roi[3])):
            raise ProjectionError("Pixel outside calibrated visible floor crop")
        if any(abs(d) > 0 for d in self.lens.distortion_coeffs):
            try:
                import cv2
                import numpy as np
            except ImportError as exc:
                raise ProjectionError("OpenCV vision extra required for lens undistortion") from exc
            matrix, coefficients = self.lens.opencv_parameters()
            mat = np.array(matrix, dtype=np.float64)
            distortion = np.array(coefficients, dtype=np.float64)
            try:
                points = cv2.undistortPoints(
                    np.array([[[u, v]]], dtype=np.float64), mat, distortion,
                )
                if (not isinstance(points, np.ndarray) or points.shape != (1, 1, 2)
                        or points.dtype.kind != "f" or not np.isfinite(points).all()):
                    raise ProjectionError("Invalid native lens undistortion result")
                right, down = (float(x) for x in points[0, 0])
                # OpenCV's default inverse is iterative and may return a
                # finite but inaccurate result. Reproject the ray with the
                # SAME lens before using it as a metric floor observation.
                projected, _ = cv2.projectPoints(
                    np.array([[right, down, 1.0]], dtype=np.float64),
                    np.zeros(3), np.zeros(3), mat, distortion,
                )
            except ProjectionError:
                raise
            except (cv2.error, TypeError, ValueError, OverflowError) as exc:
                raise ProjectionError("Native lens undistortion failed") from exc
            if (not isinstance(projected, np.ndarray) or projected.shape != (1, 1, 2)
                    or projected.dtype.kind != "f" or not np.isfinite(projected).all()
                    or math.hypot(float(projected[0, 0, 0]) - u,
                                  float(projected[0, 0, 1]) - v) > 0.5):
                raise ProjectionError("Lens undistortion round trip exceeds 0.5 pixels")
        else:
            right = (u - self.lens.cx) / self.lens.fx
            down = (v - self.lens.cy) / self.lens.fy
        pitch = math.radians(self.pitch_down_deg)
        ray_x = math.cos(pitch) - down * math.sin(pitch)
        ray_y = -right
        ray_z = -math.sin(pitch) - down * math.cos(pitch)
        # Require a strictly downward margin before distance amplification.
        ray_length = math.sqrt(ray_x * ray_x + ray_y * ray_y + ray_z * ray_z)
        if (not all(math.isfinite(x) for x in (ray_x, ray_y, ray_z, ray_length))
                or ray_length == 0
                or -ray_z / ray_length <= self.min_downward_ray):
            raise ProjectionError("Pixel ray grazes floor or points above horizon")
        distance_scale = self.camera_height_mm / -ray_z
        yaw = math.radians(self.lens.mount_yaw_deg)
        forward, left = rotate_xy(ray_x, ray_y, -yaw)
        x = self.camera_forward_offset_mm + distance_scale * forward
        y = -self.lens.mount_lateral_offset_mm + distance_scale * left
        if (not math.isfinite(x) or not math.isfinite(y)
                or not self.valid_forward_mm[0] <= x <= self.valid_forward_mm[1]
                or not self.valid_lateral_mm[0] <= y <= self.valid_lateral_mm[1]):
            raise ProjectionError("Ground intersection outside measured floor region")
        return ProjectedFloorPoint(x, y, self.uncertainty_mm, self.calibration_id)
