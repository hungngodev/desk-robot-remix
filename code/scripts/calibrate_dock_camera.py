"""Fit a REVIEW-REQUIRED docking camera candidate from real XIAO checkerboard JPEGs.

Reuse OpenCV chessboard detection and calibrateCamera. This tool has NO
camera transport, live microphone, motor or charging access. Calibration is
not physically approved just because OpenCV returns low reprojection error.
"""
from __future__ import annotations

import argparse
import errno
import io
import json
import math
import os
import secrets
import stat
from pathlib import Path
from types import ModuleType


def _require_cv2() -> ModuleType:
    """Load optional OpenCV only when actual image processing is needed."""
    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError(
            "Install the existing vision extra for OpenCV dock camera calibration"
        ) from exc
    return cv2


def _validate_measured_board_geometry(
    *,
    columns: int,
    rows: int,
    square_mm: float,
    tag_side_mm: float,
    marker_id: int,
    target_distance_mm: float,
) -> None:
    """Validate checkerboard pattern and dock target geometry before CV work."""
    if (
        type(columns) is not int
        or type(rows) is not int
        or not 4 <= columns <= 20
        or not 4 <= rows <= 20
        or type(marker_id) is not int
        or not 0 <= marker_id < 587
        or any(
            type(x) not in (int, float)
            for x in (square_mm, tag_side_mm, target_distance_mm)
        )
        or not 2 <= square_mm <= 100
        or not 10 <= tag_side_mm <= 250
        or not 50 <= target_distance_mm <= 500
    ):
        raise ValueError("Need 12+ independent real views and measured board/dock geometry")


def fit_corners(
    views: list, image_size: tuple[int, int], *,
    columns: int, rows: int, square_mm: float,
    tag_side_mm: float, marker_id: int, target_distance_mm: float,
) -> dict:
    """Calibrate from detected independent board corners, not a guessed FOV."""
    width, height = image_size
    if (type(width) is not int or type(height) is not int
            or not 80 <= width <= 2048 or not 80 <= height <= 1536
            or len(views) < 12):
        raise ValueError("Need 12+ independent real views and measured board/dock geometry")
    _validate_measured_board_geometry(
        columns=columns, rows=rows, square_mm=square_mm,
        tag_side_mm=tag_side_mm, marker_id=marker_id,
        target_distance_mm=target_distance_mm,
    )
    import numpy as np

    cv2 = _require_cv2()
    object_grid = np.zeros((rows * columns, 3), dtype=np.float32)
    object_grid[:, :2] = (
        np.mgrid[0:columns, 0:rows].T.reshape(-1, 2) * square_mm
    )
    image_points = []
    checkerboard_grids = []
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
        checkerboard_grids.append(flat.reshape(rows, columns, 2))
        centers.append(flat.mean(axis=0))
        board_areas.append(float(np.ptp(flat[:, 0]) * np.ptp(flat[:, 1])))
    centers = np.stack(centers)
    if (float(np.ptp(centers[:, 0])) < width * 0.10
            or float(np.ptp(centers[:, 1])) < height * 0.10):
        raise ValueError("Checkerboard views do not cover enough of the real sensor")
    if min(board_areas) <= 1 or max(board_areas) / min(board_areas) < 1.15:
        raise ValueError("Checkerboard views need varied distance and board scale")

    # A wide aggregate center/scale range can still be manufactured by
    # repeating only a few real placements. Require every accepted view to
    # be observably distinct. Compare all four row/column orderings because
    # OpenCV may reverse an otherwise identical board's corner ordering.
    min_view_separation_px = max(3.0, 0.01 * math.hypot(width, height))
    for index, grid in enumerate(checkerboard_grids):
        for previous in checkerboard_grids[:index]:
            previous_orders = (
                previous,
                previous[::-1, :, :],
                previous[:, ::-1, :],
                previous[::-1, ::-1, :],
            )
            separation_px = min(
                float(np.sqrt(np.mean(np.sum((grid - order) ** 2, axis=2))))
                for order in previous_orders
            )
            if separation_px < min_view_separation_px:
                raise ValueError(
                    "Checkerboard views include repeated or near-duplicate placements"
                )

    rms, camera, dist, rvecs, tvecs, intrinsic_std, _, per_view_errors = (
        cv2.calibrateCameraExtended(
            [object_grid] * len(image_points), image_points, (width, height),
            None, None,
        )
    )
    # OpenCV also reports RMS for each view. A badly fitted placement can
    # hide inside a small pooled RMS when many other views fit well.
    # Apply the same existing pixel budget to every accepted view.
    view_rms = np.asarray(per_view_errors).reshape(-1)
    if (len(view_rms) != len(image_points) or not np.isfinite(view_rms).all()
            or (view_rms < 0).any() or (view_rms > 1.5).any()):
        raise ValueError("Excessive or invalid checkerboard per-view reprojection error")
    # Low pixel reprojection error alone can conceal unobservable focal
    # length or lens distortion. OpenCV estimates their uncertainty using
    # the same detected corners; reject an underconstrained candidate.
    sigma = intrinsic_std.reshape(-1)
    if (len(sigma) < 9 or not np.isfinite(sigma).all() or (sigma < 0).any()
            or sigma[0] > .03 * camera[0, 0]
            or sigma[1] > .03 * camera[1, 1]
            or sigma[2] > .04 * width or sigma[3] > .04 * height
            or sigma[4] > .15 or sigma[5] > .4
            or sigma[6] > .03 or sigma[7] > .03 or sigma[8] > .5):
        raise ValueError("Camera parameter uncertainty exceeds conservative fit limit")
    fx, fy = float(camera[0, 0]), float(camera[1, 1])
    cx, cy = float(camera[0, 2]), float(camera[1, 2])
    distortion = tuple(float(v) for v in dist.reshape(-1))
    if (not math.isfinite(rms) or not 0 <= rms <= 1.5
            or not all(math.isfinite(x) for x in (fx, fy, cx, cy, *distortion))
            or not width * .1 <= fx <= width * 10
            or not height * .1 <= fy <= height * 10
            or not 0 <= cx < width or not 0 <= cy < height
            or len(distortion) not in (4, 5, 8, 12, 14)):
        raise ValueError("Untrustworthy camera intrinsics or excessive reprojection error")
    # Per-view RMS still dilutes an individual bad checkerboard corner.
    # Reproject every accepted observation with the fitted extrinsics and
    # enforce the same 3 px absolute corner ceiling used for live AprilTags.
    if len(rvecs) != len(image_points) or len(tvecs) != len(image_points):
        raise ValueError("Incomplete checkerboard extrinsics")
    for observed, rvec, tvec in zip(image_points, rvecs, tvecs, strict=True):
        projected, _ = cv2.projectPoints(object_grid, rvec, tvec, camera, dist)
        if projected.shape != observed.shape or not np.isfinite(projected).all():
            raise ValueError("Invalid checkerboard corner reprojection")
        residual = projected.astype(np.float64) - observed
        errors = np.hypot(residual[..., 0], residual[..., 1])
        if not np.isfinite(errors).all() or np.any(errors > 3.0):
            raise ValueError("Excessive checkerboard corner reprojection error")
    return {
        "schema_version": 1,
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
        "mount_forward_offset_mm": None,
        "checkerboard_square_mm": square_mm,
        "checkerboard_views": len(views),
        "reprojection_rms_px": round(float(rms), 4),
        "worst_view_reprojection_rms_px": round(float(view_rms.max()), 4),
        "physical_acceptance_pass": False,
        "motor_authorized": False, "charging_authorized": False,
        "requires_real_head_mount_review": True,
    }


def _original_camera_jpegs(folder: Path) -> list[tuple[str, bytes]]:
    """Read bounded original JPEGs from one pinned, no-follow directory."""
    absolute = folder.absolute()
    if ".." in absolute.parts:
        raise ValueError("Checkerboard capture directory must not traverse parents")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    folder_fd = os.open(absolute.anchor, flags)
    try:
        for part in absolute.parts[1:]:
            child_fd = os.open(part, flags, dir_fd=folder_fd)
            os.close(folder_fd)
            folder_fd = child_fd
        names = sorted(
            name for name in os.listdir(folder_fd)
            if Path(name).suffix.lower() in (".jpg", ".jpeg")
        )
        if len(names) < 12:
            raise ValueError("Provide at least 12 original checkerboard JPEGs")
        originals = []
        for name in names:
            try:
                image_fd = os.open(
                    name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                    dir_fd=folder_fd,
                )
            except OSError as exc:
                if exc.errno in (errno.ELOOP, errno.ENOENT):
                    raise ValueError(
                        "Original checkerboard JPEG must not be a symlink or vanish"
                    ) from exc
                raise
            with os.fdopen(image_fd, "rb") as image:
                if not stat.S_ISREG(os.fstat(image.fileno()).st_mode):
                    raise ValueError("Original checkerboard JPEG must be a regular file")
                # Limit reads before handing camera bytes to native OpenCV.
                originals.append((name, image.read(3_000_001)))
        return originals
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.ENOTDIR):
            raise ValueError(
                "Checkerboard capture directory must not use symlinks"
            ) from exc
        raise
    finally:
        os.close(folder_fd)


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
    _validate_measured_board_geometry(
        columns=columns, rows=rows, square_mm=square_mm,
        tag_side_mm=tag_side_mm, marker_id=marker_id,
        target_distance_mm=target_distance_mm,
    )
    # An original on-head capture must be a regular file below the chosen
    # capture folder. Path.is_file() and read_bytes() otherwise follow a
    # symlink and can silently import an unrelated JPEG as measured evidence.
    # Check the entire lexical directory chain, not only the final folder.
    if any(part.is_symlink() for part in (folder, *folder.parents)):
        raise ValueError("Checkerboard capture directory must not use symlinks")
    # Preload the original bytes through held descriptors before native
    # decoding; a swapped file or parent must not replace checked evidence.
    files = _original_camera_jpegs(folder)

    import numpy as np
    from PIL import Image

    cv2 = _require_cv2()
    views = []
    size = None
    for filename, blob in files:
        if (not 100 <= len(blob) <= 3_000_000
                or not blob.startswith(b"\xff\xd8")
                or not blob.endswith(b"\xff\xd9")):
            raise ValueError("Invalid or oversized original JPEG: " + filename)
        # JPEG byte size alone does not bound decoded pixel allocation.
        # Preserve the sensor's encoded pixel coordinate system, not EXIF
        # display rotations that OpenCV may apply automatically.
        try:
            with Image.open(io.BytesIO(blob)) as header:
                encoded_size = header.size
                if (header.format != "JPEG" or not 80 <= encoded_size[0] <= 2048
                        or not 80 <= encoded_size[1] <= 1536):
                    raise ValueError("Unsupported XIAO checkerboard JPEG dimensions: " + filename)
                if header.getexif().get(274, 1) != 1:
                    raise ValueError("Noncanonical checkerboard JPEG orientation: " + filename)
        except (OSError, Image.DecompressionBombError) as exc:
            raise ValueError("Invalid original JPEG header: " + filename) from exc
        gray = cv2.imdecode(np.frombuffer(blob, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
        if gray is None:
            raise ValueError("Undecodable source JPEG: " + filename)
        current = (gray.shape[1], gray.shape[0])
        if current != encoded_size:
            raise ValueError("Decoded checkerboard dimensions differ from JPEG header")
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



def _publish_candidate(folder_fd: int, name: str, contents: str) -> None:
    """Publish a complete, synced candidate without replacing prior evidence."""
    temporary = f".dock-candidate-{secrets.token_hex(16)}.tmp"
    fd = os.open(
        temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600, dir_fd=folder_fd,
    )
    try:
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as output:
                fd = -1
                output.write(contents)
                output.flush()
                os.fsync(output.fileno())
        finally:
            if fd >= 0:
                os.close(fd)
        # Unlike replace(), link() refuses to overwrite existing evidence.
        # Both names are anchored to the same verified directory descriptor.
        os.link(
            temporary, name, src_dir_fd=folder_fd, dst_dir_fd=folder_fd,
            follow_symlinks=False,
        )
    finally:
        os.unlink(temporary, dir_fd=folder_fd)
    os.fsync(folder_fd)


def write_private_dock_candidate(target: Path, candidate: dict) -> None:
    """Write a review-only intrinsics candidate to one private local file.

    Directory handles anchor the actual destination: an operator-controlled
    symlink or a path containing '..' must not redirect checkerboard evidence.
    No existing calibration is modified or granted motor/charge authority.
    """
    if (".." in target.parts or not isinstance(candidate, dict)
            or type(candidate.get("schema_version")) is not int
            or candidate["schema_version"] != 1
            or any(candidate.get(key) is not False for key in (
                "measured", "physical_acceptance_pass",
                "motor_authorized", "charging_authorized",
            ))):
        raise ValueError(
            "Dock camera candidate requires schema_version 1, unapproved provenance and safe path"
        )
    # Verify JSON entirely before opening a filesystem target, so a rejected
    # NaN or non-JSON input cannot leave an incomplete safety evidence file.
    contents = json.dumps(candidate, indent=2, allow_nan=False) + "\n"
    absolute = target.absolute()
    folder_fd = os.open(absolute.anchor, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in absolute.parts[1:-1]:
            entry = os.stat(part, dir_fd=folder_fd, follow_symlinks=False)
            if stat.S_ISLNK(entry.st_mode):
                current = os.fstat(folder_fd)
                # macOS /var and similar immutable root aliases are allowed;
                # user-owned or writable aliases are not measurement roots.
                if (entry.st_uid != 0 or current.st_uid != 0
                        or stat.S_IMODE(current.st_mode) & 0o022):
                    raise ValueError("Unsafe dock camera candidate parent symlink")
            elif not stat.S_ISDIR(entry.st_mode):
                raise ValueError("Dock candidate parent is not a directory")
            flags = os.O_RDONLY | os.O_DIRECTORY
            if not stat.S_ISLNK(entry.st_mode):
                flags |= os.O_NOFOLLOW
            next_fd = os.open(part, flags, dir_fd=folder_fd)
            os.close(folder_fd)
            folder_fd = next_fd
        directory = os.fstat(folder_fd)
        if (directory.st_uid != os.geteuid()
                or stat.S_IMODE(directory.st_mode) & 0o022):
            raise ValueError("Dock candidate parent must be owned and private to writers")
        _publish_candidate(folder_fd, absolute.name, contents)
    finally:
        os.close(folder_fd)


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
    try:
        candidate = calibrate_images(
            args.images, columns=args.columns, rows=args.rows,
            square_mm=args.square_mm, tag_side_mm=args.tag_side_mm,
            marker_id=args.marker_id, target_distance_mm=args.target_distance_mm,
            camera_sensor_pid=args.camera_sensor_pid,
            robot_id=args.robot_id, head_device_id=args.head_device_id,
        )
        write_private_dock_candidate(args.output, candidate)
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(candidate, indent=2))


if __name__ == "__main__":
    main()
