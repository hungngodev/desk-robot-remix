"""Fit a REVIEW-REQUIRED docking camera candidate from real XIAO checkerboard JPEGs.

Reuse OpenCV chessboard detection and calibrateCamera. This tool has NO
camera transport, live microphone, motor or charging access. Calibration is
not physically approved just because OpenCV returns low reprojection error.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


def fit_corners(
    views: list, image_size: tuple[int, int], *,
    columns: int, rows: int, square_mm: float,
    tag_side_mm: float, marker_id: int, target_distance_mm: float,
) -> dict:
    """Calibrate from detected independent board corners, not a guessed FOV."""
    import cv2
    import numpy as np

    width, height = image_size
    if (type(width) is not int or type(height) is not int
            or not 80 <= width <= 2048 or not 80 <= height <= 1536
            or type(columns) is not int or type(rows) is not int
            or not 4 <= columns <= 20 or not 4 <= rows <= 20
            or type(marker_id) is not int or not 0 <= marker_id < 587
            or any(type(x) not in (int, float) or not math.isfinite(x)
                   for x in (square_mm, tag_side_mm, target_distance_mm))
            or not 2 <= square_mm <= 100
            or not 10 <= tag_side_mm <= 250
            or not 50 <= target_distance_mm <= 500
            or len(views) < 12):
        raise ValueError("Need 12+ independent real views and measured board/dock geometry")
    object_grid = np.zeros((rows * columns, 3), dtype=np.float32)
    object_grid[:, :2] = (
        np.mgrid[0:columns, 0:rows].T.reshape(-1, 2) * square_mm
    )
    image_points = []
    centers = []
    board_areas = []
    for corners in views:
        points = np.asarray(corners, dtype=np.float32)
        if (points.shape not in ((rows * columns, 1, 2), (rows * columns, 2))
                or not np.isfinite(points).all()
                or not ((points[..., 0] >= 0) & (points[..., 0] < width)).all()
                or not ((points[..., 1] >= 0) & (points[..., 1] < height)).all()):
            raise ValueError("Invalid or cropped checkerboard corners")
        points = points.reshape(-1, 1, 2)
        image_points.append(points)
        flat = points.reshape(-1, 2)
        centers.append(flat.mean(axis=0))
        board_areas.append(float(np.ptp(flat[:, 0]) * np.ptp(flat[:, 1])))
    centers = np.stack(centers)
    if (float(np.ptp(centers[:, 0])) < width * 0.10
            or float(np.ptp(centers[:, 1])) < height * 0.10):
        raise ValueError("Checkerboard views do not cover enough of the real sensor")
    if min(board_areas) <= 1 or max(board_areas) / min(board_areas) < 1.15:
        raise ValueError("Checkerboard views need varied distance and board scale")
    rms, camera, dist, _, _, intrinsic_std, _, _ = cv2.calibrateCameraExtended(
        [object_grid] * len(image_points), image_points, (width, height),
        None, None,
    )
    # Low pixel reprojection error alone can conceal unobservable focal
    # length or lens distortion. OpenCV estimates their uncertainty using
    # the same detected corners; reject an underconstrained candidate.
    sigma = intrinsic_std.reshape(-1)
    if (len(sigma) < 9 or not np.isfinite(sigma).all()
            or sigma[0] > .03 * camera[0, 0]
            or sigma[1] > .03 * camera[1, 1]
            or sigma[2] > .04 * width or sigma[3] > .04 * height
            or sigma[4] > .15 or sigma[5] > .4
            or sigma[6] > .03 or sigma[7] > .03 or sigma[8] > .5):
        raise ValueError("Camera parameter uncertainty exceeds conservative fit limit")
    fx, fy = float(camera[0, 0]), float(camera[1, 1])
    cx, cy = float(camera[0, 2]), float(camera[1, 2])
    distortion = tuple(float(v) for v in dist.reshape(-1))
    if (not math.isfinite(rms) or rms > 1.5
            or not all(math.isfinite(x) for x in (fx, fy, cx, cy, *distortion))
            or not width * .1 <= fx <= width * 10
            or not height * .1 <= fy <= height * 10
            or not 0 <= cx <= width or not 0 <= cy <= height
            or len(distortion) not in (4, 5, 8, 12, 14)):
        raise ValueError("Untrustworthy camera intrinsics or excessive reprojection error")
    return {
        "measured": False,  # Operator must inspect actual mounting and images.
        "fx": fx, "fy": fy, "cx": cx, "cy": cy,
        "distortion_coeffs": list(distortion),
        "image_width_px": width, "image_height_px": height,
        "tag_side_mm": tag_side_mm, "marker_id": marker_id,
        "target_distance_mm": target_distance_mm,
        # Checkerboard intrinsics cannot measure where the camera sits on
        # the robot. These must be physically measured and explicitly set
        # after assembly; absent values prohibit dock motor qualification.
        "mount_lateral_offset_mm": None,
        "mount_yaw_deg": None,
        "checkerboard_square_mm": square_mm,
        "checkerboard_views": len(views),
        "reprojection_rms_px": round(float(rms), 4),
        "physical_acceptance_pass": False,
        "motor_authorized": False, "charging_authorized": False,
        "requires_real_head_mount_review": True,
    }


def calibrate_images(folder: Path, *, columns: int, rows: int,
                     square_mm: float, tag_side_mm: float,
                     marker_id: int, target_distance_mm: float,
                     camera_sensor_pid: str, robot_id: str | None = None,
                     head_device_id: str | None = None) -> dict:
    """Require original same-mode JPEGs with many real board placements."""
    # Seeed has shipped both OV3660 and OV5640 Sense cameras. A candidate
    # produced without a recorded physical sensor identity cannot be reused
    # across the two modules even at identical JPEG dimensions.
    if camera_sensor_pid not in ("OV3660", "OV5640"):
        raise ValueError("Record actual XIAO camera sensor PID: OV3660 or OV5640")
    for field_name, value in (
        ("robot_id", robot_id), ("head_device_id", head_device_id),
    ):
        if value is not None and (
            type(value) is not str or not value.strip()
            or value.strip() != value or len(value) > 160
        ):
            raise ValueError(f"Record actual {field_name} for dock calibration")
    import cv2
    import numpy as np

    files = sorted(p for p in folder.iterdir()
                   if p.is_file() and p.suffix.lower() in (".jpg", ".jpeg"))
    if len(files) < 12:
        raise ValueError("Provide at least 12 original checkerboard JPEGs")
    views = []
    size = None
    for path in files:
        blob = path.read_bytes()
        if (not 100 <= len(blob) <= 3_000_000
                or not blob.startswith(b"\xff\xd8")
                or not blob.endswith(b"\xff\xd9")):
            raise ValueError("Invalid or oversized original JPEG: " + path.name)
        gray = cv2.imdecode(np.frombuffer(blob, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
        if gray is None:
            raise ValueError("Undecodable source JPEG: " + path.name)
        current = (gray.shape[1], gray.shape[0])
        if size is not None and current != size:
            raise ValueError("XIAO camera resolution changed across views")
        size = current
        found, corners = cv2.findChessboardCorners(
            gray, (columns, rows),
            flags=cv2.CALIB_CB_ADAPTIVE_THRESH | cv2.CALIB_CB_NORMALIZE_IMAGE,
        )
        if found:
            refined = cv2.cornerSubPix(
                gray, corners, (7, 7), (-1, -1),
                (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_MAX_ITER, 30, 0.01),
            )
            views.append(refined)
    candidate = fit_corners(
        views, size, columns=columns, rows=rows, square_mm=square_mm,
        tag_side_mm=tag_side_mm, marker_id=marker_id,
        target_distance_mm=target_distance_mm,
    )
    candidate["camera_sensor_pid"] = camera_sensor_pid
    candidate["robot_id"] = robot_id
    candidate["head_device_id"] = head_device_id
    # A replaced camera module needs a new measured per-pet checkerboard trial.
    # Operator-entered labels alone never prove physical module identity.
    # Caller supplied identity remains unverified until a live device PID
    # receipt is compared against it. No authority is granted by this string.
    candidate["camera_pid_runtime_verified"] = False
    candidate["input_jpegs"] = len(files)
    candidate["rejected_checkerboard_views"] = len(files) - len(views)
    return candidate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--images", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--robot-id", required=True,
                        help="Pet whose assembled camera was measured")
    parser.add_argument("--head-device-id", required=True,
                        help="Configured Xiaozhi identity of the mounted head")
    parser.add_argument("--columns", type=int, required=True,
                        help="Number of INNER checkerboard corners across")
    parser.add_argument("--rows", type=int, required=True,
                        help="Number of INNER checkerboard corners down")
    parser.add_argument("--square-mm", type=float, required=True)
    parser.add_argument("--tag-side-mm", type=float, required=True)
    parser.add_argument("--marker-id", type=int, required=True)
    parser.add_argument("--target-distance-mm", type=float, required=True)
    parser.add_argument(
        "--camera-sensor-pid", required=True, choices=("OV3660", "OV5640"),
        help="Record the actual XIAO camera PID from the physical module",
    )
    args = parser.parse_args()
    candidate = calibrate_images(
        args.images, columns=args.columns, rows=args.rows,
        square_mm=args.square_mm, tag_side_mm=args.tag_side_mm,
        marker_id=args.marker_id, target_distance_mm=args.target_distance_mm,
        camera_sensor_pid=args.camera_sensor_pid,
        robot_id=args.robot_id, head_device_id=args.head_device_id,
    )
    with args.output.open("x", encoding="utf-8") as file:
        json.dump(candidate, file, indent=2)
        file.write("\n")
    print(json.dumps(candidate, indent=2))


if __name__ == "__main__":
    main()
