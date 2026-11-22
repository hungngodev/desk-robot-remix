"""Offline OpenCV docking calibration must require diverse measured images."""
import importlib.util
from pathlib import Path

import numpy as np
import pytest

SOURCE = Path(__file__).resolve().parents[1] / "scripts/calibrate_dock_camera.py"


def fitter():
    spec = importlib.util.spec_from_file_location("desk_dock_calibration", SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def projected_views(cv2, count=24):
    columns, rows = 9, 6
    board = np.zeros((rows * columns, 3), dtype=np.float32)
    board[:, :2] = np.mgrid[:columns, :rows].T.reshape(-1, 2) * 10
    intrinsics = np.array([
        [510.0, 0, 321.0], [0, 512.0, 239.0], [0, 0, 1],
    ])
    distortion = np.array([0.09, -0.04, 0.001, -0.002, 0.008])
    views = []
    for index in range(count):
        rotation = np.array([
            .08 + .04 * (index % 4),
            -.12 + .05 * (index % 6),
            .02 * (index % 3),
        ])
        translation = np.array([
            -95 + 42 * (index % 6),
            -80 + 40 * (index // 6),
            320 + 25 * (index % 4),
        ], dtype=float)
        points, _ = cv2.projectPoints(
            board, rotation, translation, intrinsics, distortion,
        )
        views.append(points)
    return views


def fit(views):
    return fitter().fit_corners(
        views, (640, 480), columns=9, rows=6, square_mm=10,
        tag_side_mm=60, marker_id=2, target_distance_mm=200,
    )


def test_opencv_recovers_synthetic_distorted_camera_but_cannot_approve_dock():
    cv2 = pytest.importorskip("cv2")
    candidate = fit(projected_views(cv2))
    assert candidate["measured"] is False
    assert candidate["requires_real_head_mount_review"] is True
    assert candidate["mount_lateral_offset_mm"] is None
    assert candidate["mount_yaw_deg"] is None
    assert candidate["physical_acceptance_pass"] is False
    assert candidate["motor_authorized"] is False
    assert candidate["charging_authorized"] is False
    assert candidate["checkerboard_views"] == 24
    assert candidate["reprojection_rms_px"] < .02
    assert abs(candidate["fx"] - 510) < 4
    assert abs(candidate["fy"] - 512) < 4
    assert candidate["image_width_px"] == 640
    assert candidate["image_height_px"] == 480
    assert len(candidate["distortion_coeffs"]) == 5




def test_rejects_low_rms_with_unreliable_lens_parameter_uncertainty(monkeypatch):
    """A tiny residual is insufficient proof of observable distortion."""
    cv2 = pytest.importorskip("cv2")
    original = cv2.calibrateCameraExtended

    def weak_lens_fit(*args, **kwargs):
        data = list(original(*args, **kwargs))
        uncertainty = data[5].copy()
        uncertainty[8, 0] = 0.9  # wildly unconstrained radial k3
        data[5] = uncertainty
        return tuple(data)

    monkeypatch.setattr(cv2, "calibrateCameraExtended", weak_lens_fit)
    with pytest.raises(ValueError, match="parameter uncertainty"):
        fit(projected_views(cv2))


def test_fitter_refuses_fewer_than_twelve_checkerboard_views():
    cv2 = pytest.importorskip("cv2")
    with pytest.raises(ValueError, match="12"):
        fit(projected_views(cv2)[:11])


def test_fitter_refuses_repeated_position_and_scale():
    cv2 = pytest.importorskip("cv2")
    original = projected_views(cv2)[0]
    with pytest.raises(ValueError, match="cover"):
        fit([original.copy() for _ in range(20)])


def test_fitter_refuses_repeated_distinct_pose_subset():
    cv2 = pytest.importorskip("cv2")
    views = projected_views(cv2)
    base = [views[index] for index in (0, 5, 18, 23)]
    repeated = [view.copy() for view in base for _ in range(3)]
    with pytest.raises(ValueError, match="near-duplicate placements"):
        fit(repeated)


def test_fitter_refuses_near_duplicate_pose_subset():
    cv2 = pytest.importorskip("cv2")
    views = projected_views(cv2)
    base = [views[index] for index in (0, 5, 18, 23)]
    repeated = []
    for view in base:
        for offset_px in (0.0, 2.0, 4.0):
            shifted = view.copy()
            shifted[..., 0] += offset_px
            shifted[..., 1] += offset_px / 2
            repeated.append(shifted)
    with pytest.raises(ValueError, match="near-duplicate placements"):
        fit(repeated)


def test_fitter_accepts_twelve_geometrically_distinct_projected_views():
    cv2 = pytest.importorskip("cv2")
    candidate = fit(projected_views(cv2, count=12))
    assert candidate["checkerboard_views"] == 12
    assert candidate["measured"] is False
    assert candidate["physical_acceptance_pass"] is False
    assert candidate["motor_authorized"] is False


def test_fitter_refuses_cropped_or_wrong_shape_corners():
    cv2 = pytest.importorskip("cv2")
    with pytest.raises(ValueError, match="cropped"):
        fit(projected_views(cv2)[:-1] + [np.zeros((20, 2))])


def test_fitter_rejects_impossible_geometry_without_physical_permission():
    cv2 = pytest.importorskip("cv2")
    frames = projected_views(cv2)
    with pytest.raises(ValueError):
        fitter().fit_corners(
            frames, (640, 480), columns=9, rows=6, square_mm=0,
            tag_side_mm=60, marker_id=2, target_distance_mm=200,
        )


def test_camera_calibration_rejects_mixed_jpeg_modes(tmp_path):
    cv2 = pytest.importorskip("cv2")
    for index in range(12):
        shape = (240, 320) if index == 11 else (480, 640)
        ok, jpeg = cv2.imencode(".jpg", np.zeros(shape, dtype=np.uint8))
        assert ok
        (tmp_path / f"{index:02}.jpg").write_bytes(jpeg.tobytes())
    with pytest.raises(ValueError, match="resolution changed"):
        fitter().calibrate_images(
            tmp_path, columns=9, rows=6, square_mm=10,
            tag_side_mm=60, marker_id=2, target_distance_mm=200,
            camera_sensor_pid="OV5640",
        )


@pytest.mark.parametrize("pid", [None, "", "OV2640", "OV5640b", "ov3660", 0x5640])
def test_calibration_rejects_unknown_or_unrecorded_camera_identity(tmp_path, pid):
    # Identity validation must happen before any image or CV2 operation.
    with pytest.raises(ValueError, match="actual XIAO camera sensor PID"):
        fitter().calibrate_images(
            tmp_path, columns=9, rows=6, square_mm=10,
            tag_side_mm=60, marker_id=2, target_distance_mm=200,
            camera_sensor_pid=pid,
        )


@pytest.mark.parametrize("pid", ["OV3660", "OV5640"])
def test_known_camera_pid_passes_identity_check_but_not_image_gate(tmp_path, pid):
    with pytest.raises(ValueError, match="12 original checkerboard"):
        fitter().calibrate_images(
            tmp_path, columns=9, rows=6, square_mm=10,
            tag_side_mm=60, marker_id=2, target_distance_mm=200,
            camera_sensor_pid=pid,
        )


@pytest.mark.parametrize(
    ("robot_id", "head_id"),
    [(0, "xiaozhi-01"), ("robot-01", ""), (" robot-01 ", "xiaozhi-01"),
     ("robot-01", "  "), ("robot-01", None)],
)
def test_operator_recorded_calibration_identity_validation_before_cv2(
    tmp_path, robot_id, head_id,
):
    with pytest.raises(ValueError, match="Record actual"):
        fitter().calibrate_images(
            tmp_path, columns=9, rows=6, square_mm=10,
            tag_side_mm=60, marker_id=2, target_distance_mm=200,
            camera_sensor_pid="OV5640", robot_id=robot_id,
            head_device_id=head_id if head_id is not None else "",
        )


@pytest.mark.parametrize("kind", ["linked_image", "linked_folder", "linked_ancestor"])
def test_original_checkerboard_sources_reject_symlink_aliases(tmp_path, kind):
    """A copied or linked unrelated JPEG is not an original head capture."""
    actual = tmp_path / "capture"
    actual.mkdir()
    image_root = actual
    if kind == "linked_image":
        external = tmp_path / "unrelated.jpg"
        external.write_bytes(b"\\xff\\xd8" + b"x" * 128 + b"\\xff\\xd9")
        for index in range(12):
            (actual / f"{index:02}.jpg").symlink_to(external)
    elif kind == "linked_folder":
        image_root = tmp_path / "shortcut"
        image_root.symlink_to(actual, target_is_directory=True)
    else:
        ancestor = tmp_path / "real_parent"
        ancestor.mkdir()
        link = tmp_path / "linked_parent"
        link.symlink_to(ancestor, target_is_directory=True)
        image_root = link / "photos"
        image_root.mkdir()
    # Preflight must reject the alias before file decoding, and without
    # needing an installed OpenCV runtime or enabling motor/charge authority.
    with pytest.raises(ValueError, match="symlink"):
        fitter().calibrate_images(
            image_root, columns=9, rows=6, square_mm=10,
            tag_side_mm=60, marker_id=2, target_distance_mm=200,
            camera_sensor_pid="OV5640",
            robot_id="robot-01", head_device_id="xiaozhi-01",
        )


def test_checkerboard_photo_swap_to_symlink_during_read_is_rejected(
    tmp_path, monkeypatch,
):
    """A successful path precheck cannot authorize later swapped evidence."""
    cv2 = pytest.importorskip("cv2")
    images = tmp_path / "capture"
    images.mkdir()
    ok, encoded = cv2.imencode(
        ".jpg", np.zeros((480, 640), dtype=np.uint8)
    )
    assert ok
    for index in range(12):
        (images / f"{index:02d}.jpg").write_bytes(encoded.tobytes())
    outside = tmp_path / "outside.jpg"
    outside.write_bytes(encoded.tobytes())
    target = images / "01.jpg"
    module = fitter()
    original_open = module.os.open
    switched = False

    def substitute_before_second_image_open(path, flags, *args, **kwargs):
        nonlocal switched
        if path == "01.jpg" and not switched:
            switched = True
            target.unlink()
            target.symlink_to(outside)
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(module.os, "open", substitute_before_second_image_open)
    with pytest.raises(ValueError, match="symlink"):
        module.calibrate_images(
            images, columns=9, rows=6, square_mm=10,
            tag_side_mm=60, marker_id=2, target_distance_mm=200,
            camera_sensor_pid="OV5640",
            robot_id="robot-01", head_device_id="xiaozhi-01",
        )
    assert switched
    assert target.is_symlink()
