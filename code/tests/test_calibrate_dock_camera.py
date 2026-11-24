"""Offline OpenCV docking calibration must require diverse measured images."""
import importlib.util
import sys
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
    assert candidate["worst_view_reprojection_rms_px"] < .02
    assert abs(candidate["fx"] - 510) < 4
    assert abs(candidate["fy"] - 512) < 4
    assert candidate["image_width_px"] == 640
    assert candidate["image_height_px"] == 480
    assert len(candidate["distortion_coeffs"]) == 5




def test_rejects_one_bad_view_hidden_by_low_pooled_rms():
    """Actual OpenCV fit with one poor frame and well-constrained intrinsics."""
    cv2 = pytest.importorskip("cv2")
    rng = np.random.default_rng(123)
    board = np.zeros((54, 3), dtype=np.float32)
    board[:, :2] = np.mgrid[:9, :6].T.reshape(-1, 2) * 10
    camera = np.array([[510., 0, 321.], [0, 512., 239.], [0, 0, 1.]])
    distortion = np.array([.09, -.04, .001, -.002, .008])
    views = []
    for _ in range(200):
        rotation = rng.uniform(-.6, .6, 3)
        translation = np.array([
            rng.uniform(-140, 90), rng.uniform(-90, 60), rng.uniform(170, 330),
        ])
        corners, _ = cv2.projectPoints(board, rotation, translation, camera, distortion)
        if ((corners[..., 0] > 10).all() and (corners[..., 0] < 630).all()
                and (corners[..., 1] > 10).all() and (corners[..., 1] < 470).all()):
            views.append(corners)
            if len(views) == 40:
                break
    assert len(views) == 40
    views[-1] += rng.normal(0, 1.8, views[-1].shape).astype(np.float32)
    with pytest.raises(ValueError, match="per-view reprojection error"):
        fit(views)


@pytest.mark.parametrize("bad_error", [float("nan"), -0.1])
def test_rejects_invalid_native_per_view_error(monkeypatch, bad_error):
    cv2 = pytest.importorskip("cv2")
    original = cv2.calibrateCameraExtended

    def invalid_error(*args, **kwargs):
        data = list(original(*args, **kwargs))
        data[7] = data[7].copy()
        data[7][0, 0] = bad_error
        return tuple(data)

    monkeypatch.setattr(cv2, "calibrateCameraExtended", invalid_error)
    with pytest.raises(ValueError, match="per-view reprojection error"):
        fit(projected_views(cv2))


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
def test_known_camera_pid_passes_identity_check_but_not_image_gate(tmp_path, pid, monkeypatch):
    # Prove the original-image gate works on a dev-only install, even in CI
    # where the real calibration tests have already imported OpenCV.
    monkeypatch.setitem(sys.modules, "cv2", None)
    with pytest.raises(ValueError, match="12 original checkerboard"):
        fitter().calibrate_images(
            tmp_path, columns=9, rows=6, square_mm=10,
            tag_side_mm=60, marker_id=2, target_distance_mm=200,
            camera_sensor_pid=pid,
        )


def test_missing_opencv_is_actionable_after_original_image_gate(tmp_path, monkeypatch):
    from PIL import Image

    for index in range(12):
        Image.new("L", (640, 480), color=index).save(tmp_path / f"{index:02}.jpg")
    monkeypatch.setitem(sys.modules, "cv2", None)
    with pytest.raises(RuntimeError, match="vision extra for OpenCV") as error:
        fitter().calibrate_images(
            tmp_path, columns=9, rows=6, square_mm=10,
            tag_side_mm=60, marker_id=2, target_distance_mm=200,
            camera_sensor_pid="OV5640",
        )
    assert isinstance(error.value.__cause__, ImportError)


def test_missing_opencv_does_not_mask_corner_geometry_preflight(monkeypatch):
    monkeypatch.setitem(sys.modules, "cv2", None)
    with pytest.raises(ValueError, match="12"):
        fit([])
    with pytest.raises(RuntimeError, match="vision extra for OpenCV") as error:
        fit([np.zeros((54, 2)) for _ in range(12)])
    assert isinstance(error.value.__cause__, ImportError)


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


def unapproved_dock_candidate():
    return {
        "robot_id": "robot-01", "camera_sensor_pid": "OV5640",
        "measured": False, "physical_acceptance_pass": False,
        "motor_authorized": False, "charging_authorized": False,
    }


def test_private_dock_candidate_is_exclusive_0600_even_with_public_umask(tmp_path):
    import json
    import os
    import stat

    target = tmp_path / "intrinsics.json"
    camera = fitter()
    original = unapproved_dock_candidate()
    previous_umask = os.umask(0)
    try:
        camera.write_private_dock_candidate(target, original)
    finally:
        os.umask(previous_umask)
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert json.loads(target.read_text(encoding="utf-8")) == original
    with pytest.raises(FileExistsError):
        camera.write_private_dock_candidate(target, unapproved_dock_candidate())
    assert json.loads(target.read_text(encoding="utf-8")) == original


def test_private_dock_candidate_refuses_symlink_to_existing_evidence(tmp_path):
    original = tmp_path / "reviewed.json"
    original.write_text("DO NOT MODIFY", encoding="utf-8")
    target = tmp_path / "linked.json"
    target.symlink_to(original)
    with pytest.raises(OSError):
        fitter().write_private_dock_candidate(target, unapproved_dock_candidate())
    assert original.read_text(encoding="utf-8") == "DO NOT MODIFY"


def test_private_dock_candidate_rejects_unsafe_parent_alias_and_traversal(tmp_path):
    real = tmp_path / "camera"
    real.mkdir(mode=0o700)
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)
    camera = fitter()
    with pytest.raises(ValueError, match="symlink"):
        camera.write_private_dock_candidate(
            alias / "intrinsics.json", unapproved_dock_candidate(),
        )
    with pytest.raises(ValueError, match="safe path"):
        camera.write_private_dock_candidate(
            tmp_path / "missing" / ".." / "camera" / "intrinsics.json",
            unapproved_dock_candidate(),
        )
    assert not (real / "intrinsics.json").exists()


def test_private_dock_candidate_rejects_writable_parent(tmp_path):
    import os

    folder = tmp_path / "public"
    folder.mkdir(mode=0o700)
    os.chmod(folder, 0o777)
    target = folder / "intrinsics.json"
    with pytest.raises(ValueError, match="private to writers"):
        fitter().write_private_dock_candidate(target, unapproved_dock_candidate())
    assert not target.exists()


@pytest.mark.parametrize("override", [
    {"measured": True},
    {"physical_acceptance_pass": True},
    {"motor_authorized": True},
    {"charging_authorized": True},
    {"fx": float("nan")},
])
def test_private_dock_candidate_never_publishes_approved_or_nonfinite_fields(
    tmp_path, override,
):
    candidate = unapproved_dock_candidate()
    candidate.update(override)
    target = tmp_path / "intrinsics.json"
    with pytest.raises(ValueError):
        fitter().write_private_dock_candidate(target, candidate)
    assert not target.exists()
